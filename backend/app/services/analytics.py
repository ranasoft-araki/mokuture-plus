"""分析ログの受信・集計・後始末。

設計は リポジトリ直下の `ANALYTICS.md`。要点だけ再掲する:

- 受け取れる項目は `app/schemas/analytics.py`（`extra="forbid"`）と
  `app/services/analytics_vocab.py`（固定語彙）で二重に絞る。自由入力欄は無い。
- `event_id` が主キー＝再送されても二重登録されない。
- 並べ替えは **受信順ではなく** `client_occurred_at` + `sequence_no`。
- 1件の不正で全体を落とさない（部分成功）。端末は accepted/duplicate/rejected を
  まとめて破棄してよい（reject されたものを送り続けないため）。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.analytics import DeviceEvent, DeviceMetric, ReceptionEvent, ReceptionSession
from app.models.device import Device
from app.models.tenant import Tenant
from app.schemas.analytics import DeviceEventIn, DeviceMetricIn, ReceptionEventIn
from app.services import analytics_vocab as V
from app.services.analytics_link import SessionRef
from app.services.timeutil import to_naive_utc, utcnow_naive

logger = logging.getLogger(__name__)

MAX_BATCH = 200
MAX_BODY_BYTES = 512 * 1024

# 端末時計が大きく狂っている場合の補正幅。Raspberry Pi は RTC を持たず、
# NTP 同期前は 1970 年などを指すことがある。この窓を外れた申告時刻は
# サーバ受信時刻で置き換える（並び順は sequence_no が保証するので失われない）。
_CLOCK_PAST_LIMIT = timedelta(days=30)
_CLOCK_FUTURE_LIMIT = timedelta(days=1)

# 未終了セッションの後始末
SWEEP_INTERVAL_SEC = 300
SWEEP_GRACE_SEC = 120  # idle_timeout に足す猶予
_DEFAULT_IDLE_TIMEOUT_SEC = 60


# ── 共通ヘルパ ────────────────────────────────────────────────────────────────

def _sane_time(client_dt: datetime | None, now: datetime) -> datetime:
    """端末申告時刻を naive-UTC にそろえ、明らかに狂っていればサーバ時刻で置き換える。"""
    dt = to_naive_utc(client_dt)
    if dt is None:
        return now
    if dt < now - _CLOCK_PAST_LIMIT or dt > now + _CLOCK_FUTURE_LIMIT:
        return now
    return dt


def _insert_ignore(db: AsyncSession, model, rows: list[dict]):
    """主キー衝突を無視する INSERT。PostgreSQL / SQLite の両方で使える。

    事前に SELECT で重複を除いているが、同じイベントが同時に2経路から届いた場合
    （ブラウザの再送とエージェントの再送が競合する等）に例外で全体を落とさないための保険。
    """
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:
        from sqlalchemy.dialects.sqlite import insert as _insert
    return db.execute(_insert(model).on_conflict_do_nothing(), rows)


def _reject(items: list[dict], ident: Any, reason: str) -> None:
    """reject は理由コードだけを載せる（本文・入力値をログにもレスポンスにも出さない）。"""
    items.append({"id": str(ident) if ident is not None else None, "reason": reason})


# ── 行動イベント ──────────────────────────────────────────────────────────────

def _validate_event_vocab(ev: ReceptionEventIn) -> str | None:
    if ev.event_name not in V.EVENT_NAMES:
        return "unknown_event_name"
    if ev.event_source not in V.EVENT_SOURCES:
        return "unknown_event_source"
    if ev.screen_id is not None and ev.screen_id not in V.SCREEN_IDS:
        return "unknown_screen_id"
    if ev.previous_screen_id is not None and ev.previous_screen_id not in V.SCREEN_IDS:
        return "unknown_previous_screen_id"
    if ev.field_id is not None and ev.field_id not in V.FIELD_IDS:
        return "unknown_field_id"
    if ev.error_code is not None and ev.error_code not in V.ERROR_CODES:
        return "unknown_error_code"
    if ev.input_method is not None and ev.input_method not in V.INPUT_METHODS:
        return "unknown_input_method"
    if ev.result is not None and ev.result not in V.RESULTS:
        return "unknown_result"
    if ev.question_id is not None:
        if ev.question_id not in V.QUESTION_IDS:
            return "unknown_question_id"
        if ev.answer_code is not None and ev.answer_code not in V.SURVEY_ANSWERS[ev.question_id]:
            return "unknown_answer_code"
    elif ev.answer_code is not None:
        return "answer_without_question"
    # element_id は ID なので語彙固定にできないが、表示文字列が紛れ込まないよう
    # 「英数字・ハイフン・アンダースコア・コロン」だけに限る（日本語＝ラベルは弾く）。
    if ev.element_id is not None and not _is_identifier(ev.element_id):
        return "element_id_not_identifier"
    return None


def _is_identifier(value: str) -> bool:
    if not value or len(value) > 64:
        return False
    return all(c.isascii() and (c.isalnum() or c in "-_:.") for c in value)


async def ingest_reception_events(
    db: AsyncSession,
    tenant: Tenant,
    device: Device | None,
    raw_items: Sequence[Any],
) -> dict:
    """行動イベントのバッチを取り込む。部分成功を返す。"""
    accepted: list[str] = []
    duplicate: list[str] = []
    rejected: list[dict] = []
    now = utcnow_naive()

    valid: list[ReceptionEventIn] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            _reject(rejected, None, "not_an_object")
            continue
        ident = raw.get("event_id")
        try:
            ev = ReceptionEventIn.model_validate(raw)
        except ValidationError:
            # 例外本文には値が載るのでログにもレスポンスにも出さない
            _reject(rejected, ident, "schema")
            continue
        reason = _validate_event_vocab(ev)
        if reason:
            _reject(rejected, ev.event_id, reason)
            continue
        if ev.event_id in seen:
            duplicate.append(ev.event_id)
            continue
        seen.add(ev.event_id)
        valid.append(ev)

    if not valid:
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    existing = set(
        (
            await db.execute(
                select(ReceptionEvent.event_id).where(ReceptionEvent.event_id.in_(list(seen)))
            )
        )
        .scalars()
        .all()
    )
    fresh = [ev for ev in valid if ev.event_id not in existing]
    duplicate.extend(ev.event_id for ev in valid if ev.event_id in existing)
    if not fresh:
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    site_id = tenant.id  # 拠点ID＝テナントID（ANALYTICS.md §5）
    device_id = device.id if device is not None else None
    rows = []
    for ev in fresh:
        rows.append(
            {
                "event_id": ev.event_id,
                "session_id": ev.session_id,
                # tenant/site/device は端末トークンから確定する（本文の申告値は使わない）
                "tenant_id": tenant.id,
                "site_id": site_id,
                "device_id": device_id,
                "sequence_no": ev.sequence_no,
                "client_occurred_at": _sane_time(ev.client_occurred_at, now),
                "client_tz_offset_min": ev.client_tz_offset_min,
                "server_received_at": now,
                "event_source": ev.event_source,
                "app_version": ev.app_version,
                "ui_version": ev.ui_version,
                "flow_version": ev.flow_version,
                "event_name": ev.event_name,
                "screen_id": ev.screen_id,
                "previous_screen_id": ev.previous_screen_id,
                "element_id": ev.element_id,
                "field_id": ev.field_id,
                "input_method": ev.input_method,
                "result": ev.result,
                "error_code": ev.error_code,
                "screen_dwell_ms": ev.screen_dwell_ms,
                "duration_ms": ev.duration_ms,
                "retry_count": ev.retry_count,
                "recovered": ev.recovered,
                "question_id": ev.question_id,
                "answer_code": ev.answer_code,
            }
        )

    await _insert_ignore(db, ReceptionEvent, rows)
    await _apply_to_sessions(db, tenant.id, site_id, device_id, rows, now)
    await db.commit()
    accepted.extend(r["event_id"] for r in rows)
    return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}


async def _apply_to_sessions(
    db: AsyncSession,
    tenant_id: str,
    site_id: str,
    device_id: str | None,
    rows: list[dict],
    now: datetime,
) -> None:
    """取り込んだイベントを `reception_sessions` へ反映する（集計の前計算）。

    セッション行は `session_started` が来ていなくても最初に見たイベントから作る
    （送信順が前後しても、また開始イベントを取りこぼしても行動は残す）。
    """
    by_session: dict[str, list[dict]] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)

    for session_id, evs in by_session.items():
        evs.sort(key=lambda r: (r["client_occurred_at"], r["sequence_no"]))
        sess = (
            await db.execute(select(ReceptionSession).where(ReceptionSession.id == session_id))
        ).scalar_one_or_none()
        first = evs[0]
        if sess is None:
            sess = ReceptionSession(
                id=session_id,
                tenant_id=tenant_id,
                site_id=site_id,
                device_id=device_id,
                started_at=first["client_occurred_at"],
                client_tz_offset_min=first.get("client_tz_offset_min"),
                app_version=first.get("app_version"),
                ui_version=first.get("ui_version"),
                flow_version=first.get("flow_version"),
                first_screen_id=first.get("screen_id"),
            )
            db.add(sess)

        for r in evs:
            name = r["event_name"]
            sess.event_count = (sess.event_count or 0) + 1
            if name == "session_started":
                # 開始イベントが後から届いた場合も開始時刻・入口を正とする
                sess.started_at = min(sess.started_at, r["client_occurred_at"])
                method = r.get("input_method")
                if method in V.ENTRY_METHODS:
                    sess.entry_method = method
                if r.get("screen_id"):
                    sess.first_screen_id = r["screen_id"]
            elif name == "screen_viewed":
                sess.screen_count = (sess.screen_count or 0) + 1
                if r.get("screen_id"):
                    sess.last_screen_id = r["screen_id"]
            elif name == "back_selected":
                sess.back_count = (sess.back_count or 0) + 1
            elif name == "notification_requested":
                sess.notified = True
            elif name == "staff_responded":
                sess.staff_response = r.get("result")
                sess.staff_response_ms = r.get("duration_ms")
            elif name == "feedback_submitted":
                qid = r.get("question_id")
                col = V.SURVEY_COLUMN.get(qid or "")
                if col and r.get("answer_code"):
                    setattr(sess, col, r["answer_code"])
            if V.is_error_event(name):
                sess.error_count = (sess.error_count or 0) + 1
            if r.get("app_version") and not sess.app_version:
                sess.app_version = r["app_version"]
            if r.get("ui_version") and not sess.ui_version:
                sess.ui_version = r["ui_version"]
            if r.get("flow_version") and not sess.flow_version:
                sess.flow_version = r["flow_version"]

            outcome = V.OUTCOME_BY_EVENT.get(name)
            if outcome and sess.outcome is None:
                # 終了は先着1件で確定（後から別の終了が来ても上書きしない）
                sess.outcome = outcome
                sess.ended_at = r["client_occurred_at"]

        if sess.started_at and sess.ended_at and sess.ended_at >= sess.started_at:
            sess.duration_ms = int((sess.ended_at - sess.started_at).total_seconds() * 1000)
        sess.updated_at = now


# ── 端末イベント / メトリクス ────────────────────────────────────────────────

async def ingest_device_events(
    db: AsyncSession, tenant: Tenant, device: Device, raw_items: Sequence[Any]
) -> dict:
    accepted: list[str] = []
    duplicate: list[str] = []
    rejected: list[dict] = []
    now = utcnow_naive()

    valid: list[DeviceEventIn] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            _reject(rejected, None, "not_an_object")
            continue
        ident = raw.get("id")
        try:
            it = DeviceEventIn.model_validate(raw)
        except ValidationError:
            _reject(rejected, ident, "schema")
            continue
        if it.event_name not in V.DEVICE_EVENT_NAMES:
            _reject(rejected, it.id, "unknown_event_name")
            continue
        if it.detail_code is not None and it.detail_code not in V.DEVICE_DETAIL_CODES:
            _reject(rejected, it.id, "unknown_detail_code")
            continue
        if it.id in seen:
            duplicate.append(it.id)
            continue
        seen.add(it.id)
        valid.append(it)

    if not valid:
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    existing = set(
        (await db.execute(select(DeviceEvent.id).where(DeviceEvent.id.in_(list(seen)))))
        .scalars()
        .all()
    )
    fresh = [it for it in valid if it.id not in existing]
    duplicate.extend(it.id for it in valid if it.id in existing)
    if not fresh:
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    rows = [
        {
            "id": it.id,
            "tenant_id": tenant.id,
            "site_id": tenant.id,
            "device_id": device.id,
            "sequence_no": it.sequence_no,
            "occurred_at": _sane_time(it.occurred_at, now),
            "received_at": now,
            "event_name": it.event_name,
            "detail_code": it.detail_code,
            "duration_ms": it.duration_ms,
            "count": it.count,
            "agent_version": it.agent_version,
            "ui_version": it.ui_version,
            "os_version": it.os_version,
            "uptime_sec": it.uptime_sec,
        }
        for it in fresh
    ]
    await _insert_ignore(db, DeviceEvent, rows)
    _mirror_device_versions(device, rows[-1])
    await db.commit()
    accepted.extend(r["id"] for r in rows)
    return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}


async def ingest_device_metrics(
    db: AsyncSession, tenant: Tenant, device: Device, raw_items: Sequence[Any]
) -> dict:
    accepted: list[str] = []
    duplicate: list[str] = []
    rejected: list[dict] = []
    now = utcnow_naive()

    valid: list[DeviceMetricIn] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            _reject(rejected, None, "not_an_object")
            continue
        ident = raw.get("id")
        try:
            it = DeviceMetricIn.model_validate(raw)
        except ValidationError:
            _reject(rejected, ident, "schema")
            continue
        if it.screen_id is not None and it.screen_id not in V.SCREEN_IDS:
            # 画面名は語彙固定。未知なら落として保存しない（スタッフ設定画面など）
            it.screen_id = None
        if it.id in seen:
            duplicate.append(it.id)
            continue
        seen.add(it.id)
        valid.append(it)

    if not valid:
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    existing = set(
        (await db.execute(select(DeviceMetric.id).where(DeviceMetric.id.in_(list(seen)))))
        .scalars()
        .all()
    )
    fresh = [it for it in valid if it.id not in existing]
    duplicate.extend(it.id for it in valid if it.id in existing)
    if not fresh:
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    rows = []
    for it in fresh:
        row = it.model_dump()
        row["measured_at"] = _sane_time(it.measured_at, now)
        row.update(
            {
                "tenant_id": tenant.id,
                "site_id": tenant.id,
                "device_id": device.id,
                "received_at": now,
            }
        )
        rows.append(row)
    await _insert_ignore(db, DeviceMetric, rows)
    _mirror_device_versions(device, rows[-1])
    await db.commit()
    accepted.extend(r["id"] for r in rows)
    return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}


def _mirror_device_versions(device: Device, row: dict) -> None:
    """端末の最新バージョン情報を devices テーブルへ写す（管理画面表示用）。"""
    agent_version = row.get("agent_version")
    if agent_version and agent_version != device.agent_version:
        device.agent_version = agent_version[:32]
    os_version = row.get("os_version")
    if os_version and os_version != getattr(device, "os_version", None):
        device.os_version = os_version[:64]
    ui_version = row.get("ui_version")
    if ui_version and ui_version != getattr(device, "ui_version", None):
        device.ui_version = ui_version[:32]
    if row.get("event_name") in ("device_boot", "device_restart"):
        device.last_boot_at = row.get("occurred_at")


# ── バックエンド発のイベント（通知の成否） ──────────────────────────────────

async def record_backend_event(
    ref: SessionRef,
    event_name: str,
    *,
    result: str | None = None,
    error_code: str | None = None,
    element_id: str | None = None,
    duration_ms: int | None = None,
    retry_count: int | None = None,
) -> None:
    """通知系イベントをサーバ側から1件書く（best-effort・失敗しても呼び出し元に影響しない）。

    `ref` は `analytics_link` のプロセス内 TTL マップから引いた匿名セッション参照。
    受付ログID・氏名・担当者名は一切渡ってこない。

    `sequence_no` は 0 固定（ブラウザの連番とは別系統）。時系列表示は
    `client_occurred_at` を主キーに並べるので混在しても順序は壊れない。
    """
    if event_name not in V.EVENT_NAMES:
        return
    now = utcnow_naive()
    try:
        async with AsyncSessionLocal() as db:
            await _insert_ignore(
                db,
                ReceptionEvent,
                [
                    {
                        "event_id": str(uuid.uuid4()),
                        "session_id": ref.session_id,
                        "tenant_id": ref.tenant_id,
                        "site_id": ref.site_id,
                        "device_id": ref.device_id,
                        "sequence_no": 0,
                        "client_occurred_at": now,
                        "client_tz_offset_min": None,
                        "server_received_at": now,
                        "event_source": "backend",
                        "app_version": ref.app_version,
                        "ui_version": ref.ui_version,
                        "flow_version": ref.flow_version,
                        "event_name": event_name,
                        "screen_id": None,
                        "previous_screen_id": None,
                        "element_id": element_id if element_id in V.NOTIFY_CHANNELS else None,
                        "field_id": None,
                        "input_method": None,
                        "result": result if result in V.RESULTS else None,
                        "error_code": error_code if error_code in V.ERROR_CODES else None,
                        "screen_dwell_ms": None,
                        "duration_ms": duration_ms,
                        "retry_count": retry_count,
                        "recovered": None,
                        "question_id": None,
                        "answer_code": None,
                    }
                ],
            )
            sess = (
                await db.execute(
                    select(ReceptionSession).where(ReceptionSession.id == ref.session_id)
                )
            ).scalar_one_or_none()
            if sess is not None:
                sess.event_count = (sess.event_count or 0) + 1
                sess.updated_at = now
            await db.commit()
    except Exception:
        # 分析ログの失敗は通知・受付を止めない。値・本文はログに出さない。
        logger.warning("analytics: failed to record backend event %s", event_name)


# ── 未終了セッションの後始末 ────────────────────────────────────────────────

async def sweep_stale_sessions(now: datetime | None = None) -> int:
    """終了イベントが来なかったセッションを畳む。畳んだ件数を返す。

    - 端末再起動/エージェント起動が最終イベント以降にある → `device_restarted`
    - ブラウザの異常終了(`app_crashed`)が記録されている → `app_error`
    - どちらでもない（単に連絡が途絶えた）→ `abandoned`
      （`timeout` はブラウザ自身が無操作タイマーで申告したときだけ使う）
    """
    # DB 日時列は naive-UTC 前提。aware な now を渡されても引き算で落ちないよう揃える
    # （本番 Neon は一部列が timestamptz で aware に読み戻る。既存の tz 罠と同じ対策）。
    now = to_naive_utc(now) or utcnow_naive()
    closed = 0
    async with AsyncSessionLocal() as db:
        # テナントごとの無操作タイムアウト（既存設定を流用）
        timeouts = {
            t_id: (sec or _DEFAULT_IDLE_TIMEOUT_SEC)
            for t_id, sec in (
                await db.execute(select(Tenant.id, Tenant.kiosk_idle_timeout_sec))
            ).all()
        }
        open_sessions = (
            (
                await db.execute(
                    select(ReceptionSession)
                    .where(ReceptionSession.outcome.is_(None))
                    .where(ReceptionSession.started_at < now - timedelta(seconds=60))
                    .order_by(ReceptionSession.started_at)
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
        for sess in open_sessions:
            last_at = (
                await db.execute(
                    select(ReceptionEvent.client_occurred_at)
                    .where(ReceptionEvent.session_id == sess.id)
                    .order_by(ReceptionEvent.client_occurred_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none() or sess.started_at
            last_at = to_naive_utc(last_at) or sess.started_at
            grace = timeouts.get(sess.tenant_id, _DEFAULT_IDLE_TIMEOUT_SEC) + SWEEP_GRACE_SEC
            if now - last_at < timedelta(seconds=grace):
                continue

            outcome = "abandoned"
            if sess.device_id:
                names = set(
                    (
                        await db.execute(
                            select(DeviceEvent.event_name)
                            .where(DeviceEvent.device_id == sess.device_id)
                            .where(DeviceEvent.occurred_at > last_at)
                            .where(DeviceEvent.occurred_at <= now)
                        )
                    )
                    .scalars()
                    .all()
                )
                if names & V.DEVICE_RESTART_EVENTS:
                    outcome = "device_restarted"
                elif "app_crashed" in names:
                    outcome = "app_error"

            sess.outcome = outcome
            sess.ended_at = last_at
            if sess.started_at and last_at >= sess.started_at:
                sess.duration_ms = int((last_at - sess.started_at).total_seconds() * 1000)
            sess.updated_at = now
            closed += 1
        if closed:
            await db.commit()
    return closed


async def run_analytics_sweeper_loop() -> None:
    """未終了セッションの定期スイープ。単一ワーカー前提（既存のエスカレーションと同じ）。"""
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SEC)
            await sweep_stale_sessions()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("analytics: session sweep failed")


# ── 集計ヘルパ ────────────────────────────────────────────────────────────────

def percentile(values: Iterable[float], pct: float) -> float | None:
    """線形補間なしの単純パーセンタイル（件数が少ないので十分）。"""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return float(data[0])
    k = (len(data) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(data) - 1)
    if lo == hi:
        return float(data[lo])
    return float(data[lo] + (data[hi] - data[lo]) * (k - lo))


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None
