"""受付通知のファンアウト（Slack / Chatwork / Web Push / Webhook / メール）。

キオスク受付(`api/kiosk.kiosk_reception`)と管理画面からの手動受付(`api/reception.create_reception`)
の**両方がここを通る**。以前は両ファイルに `_notify_slack` / `_notify_push` がほぼ同じ形で重複して
おり、宛先ロジックを担当者別に拡張するとズレる一方だったので1か所に集約した。

宛先は `services/staff_routing.py` が決める:
  - 通常(`stage="primary"`)   … 訪問先担当者の個別宛先 ＋（許可されていれば）テナント共通の通知先
  - 代理(`stage="fallback"`)  … 応答が無いまま時間切れ。代理担当者の宛先へ1段だけ転送

どのチャネルも best-effort（失敗しても受付自体は成立済み）。秘密情報(Bot Token / Webhook URL)は
ログに一切出さない。
"""
from __future__ import annotations

import logging
import re
from html import escape

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.notification import NotificationSetting, PushSubscription
from app.models.reception import ReceptionLog
from app.models.tenant import Tenant
from app.services import analytics as analytics_service
from app.services import analytics_link
from app.services import chatwork
from app.services import email as email_service
from app.services import staff_routing
from app.services.crypto import decrypt_dict
from app.services.honorific import with_honorific
from app.services.slack import SlackNotifier
from app.services.staff_routing import Destinations
from app.services.timeutil import format_jst, iso_z
from app.services.webpush import send_push

logger = logging.getLogger(__name__)

PRIMARY = "primary"
FALLBACK = "fallback"

_HTTP_TIMEOUT = 5.0


# ── 通知本体 ───────────────────────────────────────────────────────────────────

async def notify_reception(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, *, stage: str = PRIMARY
) -> None:
    """受付通知を全チャネルへ送る。`stage="fallback"` は代理通知（応答が無いとき）。

    代理通知で送り先が決まらない（代理担当者が未設定）場合は何もしない。
    """
    if stage == FALLBACK:
        dest = await staff_routing.resolve_fallback(db, tenant_id, log.staff)
        if dest is None:
            return
    else:
        dest = await staff_routing.resolve_primary(db, tenant_id, log.staff)

    escalated_from = (log.staff or "").strip() if stage == FALLBACK else ""

    # 各チャネルは True=1件以上成功 / False=全滅 / None=未設定(送らなかった) を返す。
    results = {
        "slack": await _notify_slack(db, tenant_id, log, dest, escalated_from),
        "chatwork": await _notify_chatwork(db, tenant_id, log, dest, escalated_from),
        "push": await _notify_push(db, tenant_id, log, dest, escalated_from),
        "webhook": await _notify_webhook(db, tenant_id, log, dest, escalated_from),
        "email": await _notify_email(db, tenant_id, log, dest, escalated_from),
    }
    await _record_analytics(tenant_id, log, results, stage)


async def _record_analytics(
    tenant_id: str, log: ReceptionLog, results: dict[str, bool | None], stage: str
) -> None:
    """通知の成否を匿名セッションへ記録する（分析ログ・best-effort）。

    受付ログIDから匿名セッションを引けるのは `analytics_link` の**プロセス内 TTL マップ**だけで、
    永続化はしない（ANALYTICS.md §2）。引けなければ静かに何もしない＝通知も受付も止めない。
    担当者名・チャンネル名・宛先は一切渡さず、経路の固定語（slack/push/webhook/email）だけを載せる。
    """
    try:
        ref = analytics_link.lookup(log.id)
        if ref is None:
            return
        if stage == FALLBACK:
            await analytics_service.record_backend_event(
                ref, "notification_retried", result="succeeded" if any(results.values()) else "failed"
            )
            return
        attempted = {k: v for k, v in results.items() if v is not None}
        if not attempted:
            return
        for channel, ok in attempted.items():
            await analytics_service.record_backend_event(
                ref,
                "notification_succeeded" if ok else "notification_failed",
                result="succeeded" if ok else "failed",
                element_id=channel,
            )
    except Exception:
        logger.warning("analytics: reception notification result not recorded (tenant=%s)", tenant_id)


async def fire_reception_notifications(
    tenant_id: str, log: ReceptionLog, *, stage: str = PRIMARY
) -> None:
    """`BackgroundTasks` から呼ぶ版。レスポンス送出後に新しいDBセッションで送る。

    inline で await すると通知の往復ぶんキオスク(agent)の応答待ちが延び、10秒プロキシ
    タイムアウトを超えて「リモートAPIに接続できません」を招く（Slack chat.postMessage は
    未参加chの join+retry で最大 ~30s、Web Push は死んだ購読を逐次送信）。
    `log` は呼び出し元で commit 済み（`AsyncSessionLocal` は `expire_on_commit=False` なので
    列値は失効せず、別セッションの本関数からも安全に読める）。
    """
    try:
        async with AsyncSessionLocal() as db:
            await notify_reception(db, tenant_id, log, stage=stage)
    except Exception:
        logger.warning("reception notification failed (tenant=%s, reception=%s)", tenant_id, log.id)


# ── Slack ──────────────────────────────────────────────────────────────────────

async def _notify_slack(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> bool | None:
    """True=1件以上成功 / False=全滅 / None=宛先が無く送らなかった（分析ログの判定に使う）。"""
    default_config = await staff_routing.load_default_slack_config(db, tenant_id)
    targets = staff_routing.slack_send_configs(default_config, dest)
    if not targets:
        return None
    try:
        msg = SlackNotifier.build_reception_message(
            visitor_name=log.visitor_name,
            company=log.company,
            host_name=log.staff,
            when=log.created_at,
            department=log.department,
            escalated_from=escalated_from or None,
        )
    except Exception:
        logger.warning("Slack reception message build failed (tenant=%s, reception=%s)", tenant_id, log.id)
        return False

    any_ok = False
    for config, label in targets:
        # 署名シークレット設定時のみ、受付/電話/お断りの対応ボタン(Block Kit)を付ける。
        # Bot Token 経路のときだけ(webhook はインタラクション不可)。押下は署名トークンで検証。
        blocks = None
        if settings.slack_signing_secret and config.get("bot_access_token") and config.get("channel_id"):
            from app.api.reception import decision_actions  # 遅延 import で循環参照を避ける
            from app.services.auth import create_decision_token

            token = create_decision_token(log.id, tenant_id)
            blocks = SlackNotifier.build_reception_blocks(msg, decision_actions(log), token)
        try:
            ok = await SlackNotifier.send_to_config(config, msg, blocks=blocks)
        except Exception:
            ok = False
        any_ok = any_ok or bool(ok)
        if not ok:
            # 受付は失敗させない(best-effort)。Bot Token/Webhook URL は絶対に出さない。
            logger.warning(
                "Slack reception notification failed (tenant=%s, reception=%s, target=%s)",
                tenant_id, log.id, label,
            )
    return any_ok


# ── Web Push ───────────────────────────────────────────────────────────────────

async def vapid_private_key(db: AsyncSession, tenant_id: str) -> str:
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "vapid",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is not None and setting.config_json and setting.config_json != "{}":
        try:
            key = decrypt_dict(setting.config_json).get("private_key", "")
            if key:
                return key
        except Exception:
            pass
    return settings.vapid_private_key


async def push_targets(
    db: AsyncSession, tenant_id: str, dest: Destinations, escalated_from: str
) -> list[PushSubscription]:
    """この通知で実際にプッシュする購読を選ぶ。

    **担当者にプッシュ先ユーザーが設定されていれば、その人の端末だけに送る。**
    `include_default`(共通の通知先へも送る) が ON でも全員には広げない。Slack や
    Chatwork は「担当者のチャンネル＋共通チャンネル」と足し算に意味があるが、
    プッシュの「共通」はテナント内の全購読＝絞り込みの上位集合なので、足すと
    担当者ごとの指定が必ず無意味になる（既定が ON なので、そのままでは機能が死ぬ）。

    絞った結果が 0 件（指定した人がまだプッシュを許可していない／退職して購読ごと
    消えた）のときは、黙って誰にも届かないほうが危険なので `include_default` に
    従って全購読へ落とす。代理通知は誰も応答していない状態なので、絞れなければ
    `include_default` に関わらず全購読へ送る。
    """
    stmt = select(PushSubscription).where(PushSubscription.tenant_id == tenant_id)
    all_subs = list((await db.execute(stmt)).scalars().all())
    if not all_subs:
        return []

    if dest.push_user_ids:
        wanted = set(dest.push_user_ids)
        targeted = [s for s in all_subs if s.user_id and s.user_id in wanted]
        if targeted:
            return targeted

    # ここから先は「担当者ごとの指定が無い／効かなかった」場合。
    if dest.use_default or escalated_from:
        return all_subs
    return []


# ── Chatwork ───────────────────────────────────────────────────────────────────

async def _notify_chatwork(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> bool | None:
    """担当者ごとに設定された Chatwork ルームへ投稿する。

    API トークンはテナント共通のものを使い回し、担当者ごとに差し替えるのはルームだけ
    （Slack と同じ考え方）。**共通ルームへは送らない** — 理由は
    `staff_routing.chatwork_send_rooms()` を参照。

    戻り値は他チャネルと同じ契約: True=1件以上成功 / False=全滅 / None=未設定。
    """
    rooms = staff_routing.chatwork_send_rooms(dest)
    if not rooms:
        return None
    token = await chatwork.load_api_token(db, tenant_id)
    if not token:
        return None

    text = chatwork.build_reception_message(
        visitor_name=log.visitor_name,
        company=log.company,
        # 訪問先は「来訪者が選んだ担当者」を出す。代理通知でも本文の末尾で
        # 「『{元の担当者}』宛の受付に応答がありません」と続くので、ここを代理の人に
        # すると 1 通の中で辻褄が合わなくなる（Slack 側も log.staff を使っている）。
        host_name=log.staff,
        when=log.created_at,
        department=log.department,
        escalated_from=escalated_from or None,
    )
    any_ok = False
    for room_id, _label in rooms:
        any_ok = await chatwork.send_message(token, room_id, text) or any_ok
    return any_ok


# ── Web Push ───────────────────────────────────────────────────────────────────

async def _notify_push(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> bool | None:
    """Web Push を送る。

    購読(`push_subscriptions`)はブラウザ＝**ログインした管理ユーザー**に紐づく。担当者は
    `tenants.staff_list` のただの名前でアカウントを持たないため、担当者ごとのプッシュは
    「この担当者あては誰の端末へ」という結びつけ(`push_user_id`)で実現する。

      - 担当者にプッシュ先ユーザーが設定されている → そのユーザーの購読へ
      - 加えて「共通の通知先へも送る」が ON なら、テナント内の全購読へ
      - 代理通知は誰も応答していない状態なので、宛先が絞れないときは全購読へ送る
        （手元の端末に届くほうが安全側）

    同じ端末(endpoint)が二重に該当しても 1 回だけ送る。
    """
    # 「送る/送らない」の判定は push_targets() に集約してある（担当者ごとの絞り込みと
    # 共通購読へのフォールバックが絡むため、ここで先に弾くと両立しない）。
    private_key = await vapid_private_key(db, tenant_id)
    if not private_key:
        return None

    subs = await push_targets(db, tenant_id, dest, escalated_from)
    if not subs:
        return None

    if escalated_from:
        title = "受付に応答がありません"
        body = f"{with_honorific(log.visitor_name)}（{log.company or '—'}）が「{escalated_from}」宛にお待ちです。"
    else:
        title = "来客のお知らせ"
        body = f"{with_honorific(log.visitor_name)}（{log.company or '—'}）が受付を完了しました。"
    if log.department:
        body += f" 部署：{log.department}"
    if log.purpose:
        body += f" 用件：{log.purpose}"

    from app.api.reception import build_decision_push_extras  # 遅延 import で循環参照を避ける

    data, actions = build_decision_push_extras(tenant_id, log)
    any_ok = False
    for sub in subs:
        try:
            await send_push(
                endpoint=sub.endpoint,
                p256dh=sub.p256dh,
                auth=sub.auth_key,
                title=title,
                body=body,
                url=f"/{tenant_id}/admin/reception",
                private_key=private_key,
                subject=settings.vapid_subject,
                # 代理通知は元の通知を上書きせず別タグで並べる(見逃しを防ぐ)。
                tag=f"reception-{log.id}" + ("-esc" if escalated_from else ""),
                data=data,
                actions=actions,
            )
            any_ok = True
        except Exception:
            pass  # fire-and-forget: 死んだ購読で全体を止めない
    return any_ok


# ── Webhook ────────────────────────────────────────────────────────────────────

def build_webhook_payload(tenant_id: str, log: ReceptionLog, escalated_from: str) -> dict:
    payload = {
        "event": "reception",
        "tenant_id": tenant_id,
        "reception_id": log.id,
        "visitor_name": log.visitor_name,
        "company": log.company,
        "staff": log.staff,
        "department": log.department,
        "purpose": log.purpose,
        "method": log.method,
        "created_at": iso_z(log.created_at),
    }
    if escalated_from:
        payload["event"] = "reception_escalated"
        payload["escalated_from"] = escalated_from
    return payload


async def _post_webhook(url: str, payload: dict) -> bool:
    """送信できたら True。best-effort なので例外は握りつぶす（URL はログに出さない）。"""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        return resp.status_code < 400
    except Exception:
        return False


async def _notify_webhook(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> bool | None:
    urls: list[str] = [u for u in dest.webhooks if u]
    if dest.use_default:
        result = await db.execute(
            select(NotificationSetting).where(
                NotificationSetting.tenant_id == tenant_id,
                NotificationSetting.type == "webhook",
            )
        )
        setting = result.scalar_one_or_none()
        if setting is not None and setting.config_json and setting.config_json != "{}":
            try:
                default_url = (decrypt_dict(setting.config_json).get("webhook_url") or "").strip()
            except Exception:
                default_url = ""
            if default_url and default_url not in urls:
                urls.append(default_url)
    if not urls:
        return None
    payload = build_webhook_payload(tenant_id, log, escalated_from)
    any_ok = False
    for url in urls:
        any_ok = await _post_webhook(url, payload) or any_ok
    return any_ok


# ── メール ─────────────────────────────────────────────────────────────────────

def build_reception_email(
    tenant_name: str,
    brand_color: str,
    log: ReceptionLog,
    admin_url: str,
    escalated_from: str = "",
) -> tuple[str, str, str]:
    """(subject, text, html) を返す。担当者ごとのメール通知用。"""
    rows: list[tuple[str, str]] = []
    if (log.company or "").strip():
        rows.append(("会社名", log.company.strip()))
    rows.append(("お名前", with_honorific(log.visitor_name)))
    if (log.department or "").strip():
        rows.append(("訪問先部署", log.department.strip()))
    if (log.staff or "").strip():
        rows.append(("訪問先", log.staff.strip()))
    if (log.purpose or "").strip():
        rows.append(("ご用件", log.purpose.strip()))
    rows.append(("受付時刻", format_jst(log.created_at)))

    if escalated_from:
        heading = "受付に応答がありません（代理通知）"
        lead = f"「{escalated_from}」宛の受付に応答がありません。代わりに対応をお願いします。"
    else:
        heading = "来客がありました"
        lead = "受付にお客様がお待ちです。対応をお願いします。"
    subject = f"【{tenant_name}】{heading}"

    text = "\n".join(
        [lead, ""] + [f"{k}：{v}" for k, v in rows] + [
            "",
            f"受付ログ: {admin_url}",
            "",
            "※このメールは送信専用です。ご返信いただけません。",
            f"— {tenant_name} 受付システム",
        ]
    )

    # ユーザー入力(氏名・会社名・部署・用件・テナント名)は全て escape する。
    e_tenant = escape(tenant_name)
    e_lead = escape(lead)
    accent = brand_color if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", brand_color or "") else "#4a7c4e"
    detail_html = "".join(
        f'<tr>'
        f'<td style="padding:6px 14px 6px 0;color:#8a8478;font-size:13px;white-space:nowrap;vertical-align:top">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#2d2a24;font-size:14px;font-weight:600">{escape(v)}</td>'
        f'</tr>'
        for k, v in rows
    )
    html = f"""\
<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f1ea;font-family:'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif">
  <div style="max-width:520px;margin:0 auto;padding:28px 16px">
    <div style="background:#fffefb;border:1px solid #e7e3d9;border-radius:16px;overflow:hidden">
      <div style="height:6px;background:{accent}"></div>
      <div style="padding:28px 30px">
        <p style="margin:0 0 4px;font-size:12px;color:#a8a198;letter-spacing:.04em">{e_tenant}</p>
        <h1 style="margin:0 0 18px;font-size:20px;color:#1d1a15">{escape(heading)}</h1>
        <p style="margin:0 0 20px;font-size:14px;line-height:1.8;color:#4a463d">{e_lead}</p>
        <table style="width:100%;border-collapse:collapse;margin:0 0 22px">{detail_html}</table>
        <a href="{escape(admin_url, quote=True)}"
           style="display:inline-block;padding:11px 22px;background:{accent};color:#fff;font-size:14px;font-weight:600;text-decoration:none;border-radius:8px">受付ログを開く</a>
      </div>
      <div style="padding:14px 30px;background:#f7f5f0;border-top:1px solid #efece5">
        <p style="margin:0;font-size:11px;color:#a8a198;line-height:1.7">
          ※このメールは送信専用です。ご返信いただけません。<br>— {e_tenant} 受付システム
        </p>
      </div>
    </div>
  </div>
</body></html>"""
    return subject, text, html


async def _notify_email(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> bool | None:
    if not dest.emails or not settings.smtp_enabled:
        return None
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    tenant_name = tenant.name if tenant else settings.app_name
    brand_color = tenant.brand_color if tenant else "#4a7c4e"
    slug = tenant.slug if tenant else tenant_id
    admin_url = f"{settings.public_web_url.rstrip('/')}/{slug}/admin/reception?respond={log.id}"

    subject, text, html = build_reception_email(
        tenant_name, brand_color, log, admin_url, escalated_from
    )
    any_ok = False
    for addr in dest.emails:
        ok, err = await email_service.send_email(
            to=addr,
            subject=subject,
            html=html,
            text=text,
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_addr=settings.smtp_from or settings.smtp_username,
            from_name=settings.smtp_from_name or tenant_name,
            starttls=settings.smtp_starttls,
            use_ssl=settings.smtp_ssl,
        )
        any_ok = any_ok or bool(ok)
        if not ok:
            logger.warning(
                "reception email failed (tenant=%s, reception=%s): %s", tenant_id, log.id, err[:200]
            )
    return any_ok
