import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.middleware.tenant import require_roles
from app.models.notification import NotificationSetting, PushSubscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth import create_slack_state_token, verify_slack_state_token
from app.services.crypto import encrypt_dict, decrypt_dict
from app.services.slack import SlackNotifier, SlackOAuthError, SlackApiError
from app.services.webpush import send_push
from app.config import settings
import httpx

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Reception test-notification text (作業指示 §5). Kept distinct from the delivery test.
_SLACK_TEST_MESSAGE = ":bell: mokuture のSlack通知テストです\n\nこのチャンネルに受付通知が送信されます。"


class SlackConfig(BaseModel):
    webhook_url: str


class ChatworkConfig(BaseModel):
    api_token: str
    room_id: str


class WebhookConfig(BaseModel):
    webhook_url: str


class PushDeliveryConfig(BaseModel):
    enabled: bool = True


@router.get("/settings")
async def get_settings(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationSetting).where(NotificationSetting.tenant_id == user.tenant_id))
    settings_list = result.scalars().all()
    out = {}
    for s in settings_list:
        try:
            config = decrypt_dict(s.config_json) if s.config_json and s.config_json != "{}" else {}
        except Exception:
            config = {}
        # Mask sensitive values in response (covers base + *_delivery variants).
        # Webhook URL must never be shown in the admin panel — replace with a
        # content-free marker that still reads as truthy ("設定済") for the UI.
        # Bot Token must never leave the server at all — drop it entirely.
        if s.type.startswith("slack"):
            if config.get("webhook_url"):
                config["webhook_url"] = "***"
            config.pop("bot_access_token", None)  # never expose the bot token
            config.pop("bot_token", None)         # legacy field name, just in case
        if s.type.startswith("chatwork") and "api_token" in config:
            config["api_token"] = "***"
        out[s.type] = config
    return out


# NOTE: 受付用 Slack (type="slack") は OAuth 連携（/slack/oauth/url → /slack/callback）
# のみで設定する。Webhook URL を手入力/上書きする PUT /settings/slack は廃止した
# （顧客に Webhook URL を触らせない方針・OAuth バイパス防止）。配達用 slack_delivery は
# 従来どおり手入力（下記）。


@router.put("/settings/chatwork")
async def update_chatwork(
    body: ChatworkConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "chatwork", {"api_token": body.api_token, "room_id": body.room_id}, db)
    return {"ok": True}


@router.put("/settings/webhook")
async def update_webhook(
    body: WebhookConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "webhook", {"webhook_url": body.webhook_url}, db)
    return {"ok": True}


# ── Delivery-specific notification destinations (荷物の配達/呼び出し) ──────────────
# Same config shape as the base types; falls back to the base destination in kiosk
# call-staff when unset (see app.api.kiosk).

@router.put("/settings/slack_delivery")
async def update_slack_delivery(
    body: SlackConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "slack_delivery", {"webhook_url": body.webhook_url}, db)
    return {"ok": True}


@router.put("/settings/chatwork_delivery")
async def update_chatwork_delivery(
    body: ChatworkConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "chatwork_delivery", {"api_token": body.api_token, "room_id": body.room_id}, db)
    return {"ok": True}


@router.put("/settings/webhook_delivery")
async def update_webhook_delivery(
    body: WebhookConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "webhook_delivery", {"webhook_url": body.webhook_url}, db)
    return {"ok": True}


@router.put("/settings/push_delivery")
async def update_push_delivery(
    body: PushDeliveryConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle Web Push for delivery staff-calls. Push always targets the tenant's
    registered devices (shared with reception); this only enables/disables it for
    the 配達の呼び出し flow. Default = enabled (see app.api.kiosk.call-staff)."""
    await _upsert_setting(user.tenant_id, "push_delivery", {"enabled": bool(body.enabled)}, db)
    return {"ok": True}


async def _get_setting_or_404(tenant_id: str, type_: str, label: str, db: AsyncSession) -> NotificationSetting:
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.tenant_id == tenant_id, NotificationSetting.type == type_)
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail=f"{label} not configured")
    return setting


async def _run_test_slack(
    tenant_id: str, type_: str, db: AsyncSession, message: str = _SLACK_TEST_MESSAGE
) -> dict:
    setting = await _get_setting_or_404(tenant_id, type_, "Slack", db)
    config = decrypt_dict(setting.config_json)
    # Bot Token link connected but no channel chosen yet → clear, actionable error.
    if config.get("bot_access_token") and not config.get("channel_id"):
        raise HTTPException(status_code=400, detail="通知先チャンネルが選択されていません。チャンネルを選択してください。")
    ok = await SlackNotifier.send_to_config(config, message)
    return {"ok": ok}


async def _run_test_chatwork(tenant_id: str, type_: str, db: AsyncSession) -> dict:
    setting = await _get_setting_or_404(tenant_id, type_, "Chatwork", db)
    config = decrypt_dict(setting.config_json)
    api_token = config.get("api_token", "")
    room_id = config.get("room_id", "")
    if not api_token or not room_id:
        raise HTTPException(status_code=400, detail="Chatwork API token or room ID missing")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": "mokuture+ テスト通知"},
            )
        ok = res.status_code == 200
    except Exception:
        ok = False
    return {"ok": ok}


async def _run_test_push_delivery(tenant_id: str, db: AsyncSession) -> dict:
    """Send a delivery-flavored test push to every device registered for this tenant.

    Push shares the tenant's device subscriptions with reception, so there is no
    separate destination — this simply confirms the 配達の呼び出し push works."""
    vapid_result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "vapid",
        )
    )
    vapid_setting = vapid_result.scalar_one_or_none()
    private_key = ""
    if vapid_setting and vapid_setting.config_json and vapid_setting.config_json != "{}":
        try:
            private_key = decrypt_dict(vapid_setting.config_json).get("private_key", "")
        except Exception:
            private_key = ""
    if not private_key:
        private_key = settings.vapid_private_key
    if not private_key:
        raise HTTPException(status_code=400, detail="プッシュ通知が未設定です。「プッシュ通知」で VAPID 鍵を生成してください。")

    subs_result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == tenant_id)
    )
    subs = subs_result.scalars().all()
    if not subs:
        raise HTTPException(status_code=404, detail="通知先の端末が登録されていません。「プッシュ通知」で端末を登録してください。")

    sent = 0
    errors: list[str] = []
    for s in subs:
        ok, err = await send_push(
            endpoint=s.endpoint,
            p256dh=s.p256dh,
            auth=s.auth_key,
            title="配達の呼び出し（テスト）",
            body="配達の呼び出し通知のテストです。この端末で受信できています。",
            url="/",
            private_key=private_key,
            subject=settings.vapid_subject,
        )
        if ok:
            sent += 1
        elif err:
            errors.append(err)

    if sent == 0 and errors:
        raise HTTPException(status_code=500, detail=f"プッシュ送信失敗: {errors[0]}")
    return {"ok": sent > 0, "sent": sent, "total": len(subs)}


async def _run_test_webhook(tenant_id: str, type_: str, db: AsyncSession) -> dict:
    setting = await _get_setting_or_404(tenant_id, type_, "Webhook", db)
    config = decrypt_dict(setting.config_json)
    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL missing")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(
                webhook_url,
                json={
                    "event": "test",
                    "message": "mokuture+ テスト通知",
                    "tenant_id": tenant_id,
                },
            )
        ok = res.status_code < 400
    except Exception:
        ok = False
    return {"ok": ok}


@router.post("/test/slack")
async def test_slack(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_slack(user.tenant_id, "slack", db)


@router.post("/test/chatwork")
async def test_chatwork(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_chatwork(user.tenant_id, "chatwork", db)


@router.post("/test/webhook")
async def test_webhook(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_webhook(user.tenant_id, "webhook", db)


@router.post("/test/slack_delivery")
async def test_slack_delivery(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_slack(
        user.tenant_id, "slack_delivery", db,
        message=":package: mokuture の配達通知テストです\n\nこのチャンネルに配達の呼び出し・置き配が通知されます。",
    )


@router.post("/test/chatwork_delivery")
async def test_chatwork_delivery(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_chatwork(user.tenant_id, "chatwork_delivery", db)


@router.post("/test/webhook_delivery")
async def test_webhook_delivery(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_webhook(user.tenant_id, "webhook_delivery", db)


@router.post("/test/push_delivery")
async def test_push_delivery(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    return await _run_test_push_delivery(user.tenant_id, db)


async def _upsert_setting(tenant_id: str, type_: str, config: dict, db: AsyncSession) -> None:
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.tenant_id == tenant_id, NotificationSetting.type == type_)
    )
    setting = result.scalar_one_or_none()
    encrypted = encrypt_dict(config)
    if setting:
        setting.config_json = encrypted
    else:
        db.add(NotificationSetting(tenant_id=tenant_id, type=type_, config_json=encrypted))
    await db.commit()


# ── Slack OAuth (Bot Token + chat.postMessage) ─────────────────────────────────
# Lets a tenant admin connect Slack by pressing "Slackに追加" (OAuth), then choosing a
# channel in the admin UI (conversations.list). The bot token is stored in the same
# NotificationSetting row (type="slack") the reception notifier reads, so no schema
# change is needed and 受付通知 keeps working. The bot token is never returned to the
# client nor logged. See CLAUDE.md「Slack OAuth 連携」.


def _slack_redirect(slug: str | None, status: str) -> RedirectResponse:
    """Redirect the browser back to the admin notify page (or login if the tenant
    could not be resolved) with a ?slack=<status> flag the UI reads on mount."""
    base = settings.public_web_url.rstrip("/")
    target = f"{base}/{slug}/admin/notify?slack={status}" if slug else f"{base}/login?slack={status}"
    return RedirectResponse(target, status_code=302)


@router.get("/slack")
async def slack_status(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Connection status for the admin UI. Never includes the Webhook URL / bot token."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == user.tenant_id,
            NotificationSetting.type == "slack",
        )
    )
    setting = result.scalar_one_or_none()
    config: dict = {}
    if setting and setting.config_json and setting.config_json != "{}":
        try:
            config = decrypt_dict(setting.config_json)
        except Exception:
            config = {}
    return {"enabled": SlackNotifier.enabled(), **SlackNotifier.public_config(config)}


@router.get("/slack/oauth/url")
async def slack_oauth_url(user: User = Depends(require_roles("admin", "superadmin"))):
    """Return the Slack authorize URL for the SPA to navigate to. The signed `state`
    binds the round-trip to this tenant (no server-side session needed).
    Returns {enabled: false} when SLACK_* env vars are unset (feature disabled)."""
    if not SlackNotifier.enabled():
        return {"enabled": False}
    state = create_slack_state_token(user.tenant_id)
    return {"enabled": True, "authorize_url": SlackNotifier.build_authorize_url(state)}


class ChannelSelect(BaseModel):
    channel_id: str


async def _load_slack_config(tenant_id: str, db: AsyncSession) -> dict | None:
    """Decrypted Slack config for a tenant, or None if not connected."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "slack",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return None
    try:
        return decrypt_dict(setting.config_json)
    except Exception:
        return None


@router.get("/slack/channels")
async def slack_channels(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """List Slack channels the bot can post to (公開: channels:read / 非公開: groups:read),
    for the admin's channel picker. Requires an OAuth-connected bot token."""
    if not SlackNotifier.enabled():
        raise HTTPException(status_code=404, detail="Slack integration disabled")
    config = await _load_slack_config(user.tenant_id, db)
    token = (config or {}).get("bot_access_token") or ""
    if not token:
        raise HTTPException(status_code=400, detail="Slackが未連携です")
    try:
        channels = await SlackNotifier.list_channels(token)
    except SlackApiError:
        raise HTTPException(status_code=502, detail="チャンネル一覧の取得に失敗しました。連携をやり直してください。")
    return {"channels": channels}


@router.post("/slack/channel")
async def slack_set_channel(
    body: ChannelSelect,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Set the notification channel. Joins the channel if it is public and the bot is
    not a member yet (conversations.join); private channels require a manual invite."""
    if not SlackNotifier.enabled():
        raise HTTPException(status_code=404, detail="Slack integration disabled")
    config = await _load_slack_config(user.tenant_id, db)
    token = (config or {}).get("bot_access_token") or ""
    if not token:
        raise HTTPException(status_code=400, detail="Slackが未連携です")
    channel_id = (body.channel_id or "").strip()
    if not channel_id:
        raise HTTPException(status_code=422, detail="channel_id is required")
    try:
        info = await SlackNotifier.get_channel_info(token, channel_id)
    except SlackApiError:
        raise HTTPException(status_code=400, detail="チャンネル情報の取得に失敗しました。")
    if not info["is_private"] and not info["is_member"]:
        await SlackNotifier.join_channel(token, channel_id)  # best-effort
    display = ("#" if not info["is_private"] else "") + (info["name"] or channel_id)
    config["channel_id"] = channel_id
    config["channel_name"] = display
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _upsert_setting(user.tenant_id, "slack", config, db)
    return {"ok": True, "channel_name": display}


@router.post("/slack/disconnect")
async def slack_disconnect(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the tenant's Slack link. The stored bot token is dropped and no longer used.
    (Slack-side app removal / token revocation is out of scope for Phase 1.)"""
    await db.execute(
        delete(NotificationSetting).where(
            NotificationSetting.tenant_id == user.tenant_id,
            NotificationSetting.type == "slack",
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/slack/callback")
async def slack_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """OAuth redirect target (SLACK_REDIRECT_URI). Unauthenticated — Slack redirects the
    browser here, so the tenant is identified solely by the signed `state`."""
    if not SlackNotifier.enabled():
        raise HTTPException(status_code=404, detail="Slack integration disabled")

    # Resolve the tenant from the signed state first, so every outcome (success, denied,
    # error) can redirect back to the correct admin page. A bad/expired state is untrusted.
    tenant_id: str | None = None
    if state:
        try:
            tenant_id = verify_slack_state_token(state)
        except JWTError:
            tenant_id = None

    slug: str | None = None
    if tenant_id:
        res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = res.scalar_one_or_none()
        if tenant is not None:
            slug = tenant.slug

    if tenant_id is None or slug is None:
        # Invalid state or unknown tenant → do not modify anything.
        return _slack_redirect(None, "error")

    if error or not code:
        # User cancelled on Slack's consent screen (or no code returned).
        return _slack_redirect(slug, "denied")

    try:
        config = await SlackNotifier.exchange_code(code)
    except SlackOAuthError:
        # Do not log — the exception may reference the exchange. Redirect with a flag.
        return _slack_redirect(slug, "error")

    # Overwrite any existing Slack link (再連携 = 上書き, 作業指示 §3).
    await _upsert_setting(tenant_id, "slack", config, db)
    return _slack_redirect(slug, "connected")


def _verify_slack_signature(raw: bytes, timestamp: str, signature: str) -> bool:
    """Slack の署名検証(v0)。`v0:{ts}:{raw}` を signing secret で HMAC-SHA256 し比較。
    5分より古いリクエストはリプレイ防止で拒否。"""
    secret = settings.slack_signing_secret
    if not secret or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return False
    base = b"v0:" + timestamp.encode() + b":" + raw
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


_DECISION_JP = {"accepted": "受付", "phone": "電話", "declined": "お断り"}


async def _post_slack_response_url(url: str, body: dict) -> None:
    """response_url へメッセージ更新をbest-effort送信(30分/5回有効)。失敗しても無視。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=body)
    except Exception:
        pass


@router.post("/slack/interactions")
async def slack_interactions(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Slack の受付通知ボタン(受付/電話/お断り)押下の受け口。未認証だが署名検証で真正性を担保。

    ボタンの value に載る署名トークン(create_decision_token)で受付ログ→テナントを特定し、
    _apply_decision(冪等)で state を更新。元メッセージを response_url 経由で「対応済み」に
    置き換える(ボタン除去)。Slack App の Interactivity Request URL に本エンドポイントを登録する。"""
    if not settings.slack_signing_secret:
        raise HTTPException(status_code=404, detail="Slack interactivity disabled")
    raw = await request.body()
    if not _verify_slack_signature(
        raw,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    ):
        raise HTTPException(status_code=401, detail="invalid signature")

    form = parse_qs(raw.decode("utf-8"))
    try:
        payload = json.loads(form.get("payload", ["{}"])[0])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="bad payload")

    actions = payload.get("actions") or []
    if not actions:
        return {}
    decision, _, token = (actions[0].get("value") or "").partition("|")

    # 遅延 import で循環参照を避ける（reception は auth/models のみ依存、notifications は未参照）。
    from app.api.reception import _apply_decision
    from app.services.auth import decode_token
    from app.models.reception import ReceptionLog

    try:
        tok = decode_token(token)
    except JWTError:
        return {"text": "リンクが無効か期限切れです。管理画面「受付ログ」から対応してください。"}
    if tok.get("type") != "decision":
        return {"text": "無効なトークンです。"}
    log_id = tok.get("sub")
    tenant_id = tok.get("tenant_id")
    res = await db.execute(select(ReceptionLog).where(ReceptionLog.id == log_id))
    log = res.scalar_one_or_none()
    if not log or log.tenant_id != tenant_id:
        return {"text": "対象の受付が見つかりません。"}

    state = await _apply_decision(db, log, decision)

    # 元メッセージを「対応済み」に置換（ボタン除去）。押した人も添える。response_url は30分/5回有効。
    label = _DECISION_JP.get(state, state)
    who = (payload.get("user") or {}).get("username") or (payload.get("user") or {}).get("name") or ""
    orig_text = (payload.get("message") or {}).get("text") or "来客の受付"
    ctx = f"✅ 対応済み：*{label}*" + (f"（{who}）" if who else "")
    updated = {
        "replace_original": True,
        "text": orig_text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": orig_text}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": ctx}]},
        ],
    }
    # Slack は3秒以内の応答を要求。response_url 更新は背後で送り、即200を返す。
    response_url = payload.get("response_url")
    if response_url:
        background.add_task(_post_slack_response_url, response_url, updated)
    return {}
