"""代理通知（応答が無い受付のエスカレーション）。

訪問先担当者に「代理通知先(別の担当者)」と待機秒数が設定されている受付が、その秒数を過ぎても
未応答(`state` が received/notified のまま)なら、代理担当者の通知先へ1段だけ転送する。

**タイマーではなく定期スイープで実装している。** 受付ごとに `asyncio.sleep` する方式だと
Render の再デプロイ/再起動で待機中のタスクが消え、代理通知が黙って出なくなる（安全網の機能が
一番必要なときに効かない）。スイープなら再起動後も未処理ぶんを拾い直せる。対象は `staff_notification_routes` との JOIN で
「代理通知が設定された担当者宛」に限定する（そうしないと代理設定の無い未応答ログに LIMIT の枠を
食い潰され、本来送るべき受付が永久に選ばれなくなる）。

冪等性は `reception_logs.escalated_at` で担保する。**送信前に「まだ未応答・未エスカレーション」を
条件にした UPDATE で確定・commit** してから送る。条件付きにしているのは、対象を読んでから送るまでの
await の間にスタッフが応答を commit しうるため（単一ワーカーでもリクエストは並行する）。更新件数が
0 なら誰かが先に確定させたということなので送らない。

この順序は意図的に **at-most-once** である。commit と送信の間でプロセスが落ちるとその1件は送られない
（Render 再デプロイ等）。逆にすると送信成功後に commit が失敗した場合、次のスイープで代理通知を送り直し、
15秒ごとに鳴り続けうる。通知は全経路 best-effort なので、鳴りすぎるより取りこぼす側に倒す。

前提: 本番は uvicorn `--workers 1`（Dockerfile）＝単一プロセス。複数ワーカー化する場合は
このループが各ワーカーで走らないよう、担当プロセスを決めるかロックを入れること。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_, func, select, update

from app.database import AsyncSessionLocal
from app.models.reception import ReceptionLog
from app.models.staff_route import StaffNotificationRoute
from app.services import events as event_bus
from app.services import reception_notify, staff_routing
from app.services.timeutil import to_naive_utc, utcnow_naive

logger = logging.getLogger(__name__)

# スイープ間隔。最短の待機秒(MIN_ESCALATE_SEC=30)に対して十分細かく、
# かつ設定しているテナントが無ければクエリ1本で終わる程度に軽い。
SWEEP_INTERVAL_SEC = 15.0
# これより古い未応答ログは拾わない（放置された受付を後から蒸し返さないため）。
LOOKBACK_HOURS = 24
# 1回のスイープで処理する上限（異常時に一気に送らないための歯止め）。
# 対象は JOIN で「代理通知が設定された担当者宛の未応答ログ」に限定済みなので、
# この枠が無関係なログで埋まることはない。
MAX_PER_SWEEP = 50

# 「まだ誰も応答していない」とみなす state。accepted/phone/declined は確定、
# completed/cancelled は終了済みなので代理通知しない。
PENDING_STATES = ("received", "notified")

# 誰かの応答を待つ受付ではないので代理通知しない。配達の呼び出し(delivery)は担当者が紐づかず、
# 置き配(dropoff)は state="completed" で記録されるため実際には拾われないが、
# データ補正や将来の変更で紛れ込まないよう明示的に除外しておく。
EXCLUDED_METHODS = ("delivery", "dropoff")


async def sweep_once() -> int:
    """期限切れの未応答受付を探して代理通知を送る。送った件数を返す。"""
    sent = 0
    async with AsyncSessionLocal() as db:
        now = utcnow_naive()
        # 代理通知が設定されている担当者宛の受付だけを取り出す。
        # **ここで絞らないと LIMIT の枠を食い潰される**: 代理設定の無い担当者宛や担当者未選択の
        # 未応答ログは `escalated_at` が永久に NULL のままなので（来客に直接応対して誰も
        # 受付/電話/お断り を押さない受付はそのまま残る）、毎周期そちらが先に50件埋めてしまい、
        # 本来送るべき受付が永久に選ばれなくなる。ルートとの JOIN で対象自体を限定する。
        result = await db.execute(
            select(ReceptionLog)
            .join(
                StaffNotificationRoute,
                and_(
                    StaffNotificationRoute.tenant_id == ReceptionLog.tenant_id,
                    # 既存データには前後空白付きの担当者名が残りうるので trim して突き合わせる。
                    # ルート側(`staff_name`)は保存時に必ず strip 済み。新規受付も入口で strip する
                    # ようにしたが、過去分を拾えないと代理通知だけ静かに落ちるため両方で担保する。
                    StaffNotificationRoute.staff_name == func.trim(ReceptionLog.staff),
                    StaffNotificationRoute.fallback_staff_name.is_not(None),
                    StaffNotificationRoute.fallback_staff_name != "",
                    StaffNotificationRoute.escalate_after_sec > 0,
                ),
            )
            .where(
                ReceptionLog.state.in_(PENDING_STATES),
                ReceptionLog.escalated_at.is_(None),
                ReceptionLog.method.notin_(EXCLUDED_METHODS),
                # cutoff は naive-UTC で渡す。SQLAlchemy はモデルの型(DateTime, timezone=False)から
                # `$1::TIMESTAMP WITHOUT TIME ZONE` にキャストするため、aware を渡すと asyncpg 側で壊れる。
                ReceptionLog.created_at >= now - timedelta(hours=LOOKBACK_HOURS),
            )
            .order_by(ReceptionLog.created_at)
            .limit(MAX_PER_SWEEP)
        )
        logs = result.scalars().all()

        for log in logs:
            plan = await staff_routing.escalation_plan(db, log.tenant_id, log.staff)
            if plan is None:
                continue
            created = to_naive_utc(log.created_at)
            if created is None or (now - created).total_seconds() < plan.after_sec:
                continue

            # 先に「送った」を確定させる＝送信中の例外や次のスイープで二重送信しない。
            # 条件付き UPDATE にして、読み取り後に応答が確定した受付へは送らない。
            result = await db.execute(
                update(ReceptionLog)
                .where(
                    ReceptionLog.id == log.id,
                    ReceptionLog.tenant_id == log.tenant_id,
                    ReceptionLog.state.in_(PENDING_STATES),
                    ReceptionLog.escalated_at.is_(None),
                )
                .values(escalated_at=now)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            if result.rowcount != 1:
                continue  # 別経路(通知ボタン/管理画面/Slack)で先に応答が確定した
            await db.refresh(log)

            await reception_notify.notify_reception(
                db, log.tenant_id, log, stage=reception_notify.FALLBACK
            )
            # 管理画面(SSE)に「代理通知済み」バッジを即反映させる。
            event_bus.publish(log.tenant_id, {"type": "reception"})
            sent += 1
    return sent


async def run_escalation_loop() -> None:
    """アプリのライフサイクルに紐づく常駐ループ（`main.lifespan` が起動・停止する）。"""
    logger.info("reception escalation sweeper started (interval=%.0fs)", SWEEP_INTERVAL_SEC)
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SEC)
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 1回のスイープが失敗してもループは止めない（次の周期で拾い直す）。
            logger.warning("reception escalation sweep failed", exc_info=False)
