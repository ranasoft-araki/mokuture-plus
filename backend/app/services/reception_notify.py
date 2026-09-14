"""受付通知のファンアウト（Slack / Web Push / Webhook / メール）。

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

    await _notify_slack(db, tenant_id, log, dest, escalated_from)
    await _notify_push(db, tenant_id, log, dest, escalated_from)
    await _notify_webhook(db, tenant_id, log, dest, escalated_from)
    await _notify_email(db, tenant_id, log, dest, escalated_from)


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
) -> None:
    default_config = await staff_routing.load_default_slack_config(db, tenant_id)
    targets = staff_routing.slack_send_configs(default_config, dest)
    if not targets:
        return
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
        return

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
        if not ok:
            # 受付は失敗させない(best-effort)。Bot Token/Webhook URL は絶対に出さない。
            logger.warning(
                "Slack reception notification failed (tenant=%s, reception=%s, target=%s)",
                tenant_id, log.id, label,
            )


# ── Web Push ───────────────────────────────────────────────────────────────────

async def _vapid_private_key(db: AsyncSession, tenant_id: str) -> str:
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


async def _notify_push(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> None:
    """テナントに登録された全端末へ Web Push。

    プッシュは端末(購読)単位で担当者と結び付いていないため宛先の担当者別分割はできない。
    通常の受付では「テナント共通の通知先へも送る」設定に従い、代理通知では**必ず**送る
    （誰も応答していない状態なので、手元の端末へ届けるのが安全側）。
    """
    if not escalated_from and not dest.use_default:
        return
    private_key = await _vapid_private_key(db, tenant_id)
    if not private_key:
        return

    subs_result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == tenant_id)
    )
    subs = subs_result.scalars().all()
    if not subs:
        return

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
        except Exception:
            pass  # fire-and-forget: 死んだ購読で全体を止めない


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


async def _post_webhook(url: str, payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(url, json=payload)
    except Exception:
        pass  # best-effort。URL はログに出さない


async def _notify_webhook(
    db: AsyncSession, tenant_id: str, log: ReceptionLog, dest: Destinations, escalated_from: str
) -> None:
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
        return
    payload = build_webhook_payload(tenant_id, log, escalated_from)
    for url in urls:
        await _post_webhook(url, payload)


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
) -> None:
    if not dest.emails or not settings.smtp_enabled:
        return
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    tenant_name = tenant.name if tenant else settings.app_name
    brand_color = tenant.brand_color if tenant else "#4a7c4e"
    slug = tenant.slug if tenant else tenant_id
    admin_url = f"{settings.public_web_url.rstrip('/')}/{slug}/admin/reception?respond={log.id}"

    subject, text, html = build_reception_email(
        tenant_name, brand_color, log, admin_url, escalated_from
    )
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
        if not ok:
            logger.warning(
                "reception email failed (tenant=%s, reception=%s): %s", tenant_id, log.id, err[:200]
            )
