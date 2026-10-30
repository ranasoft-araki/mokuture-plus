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
from app.services import chatwork as chatwork_service
from app.services import notification_channels
from app.services import notification_health
from app.services.slack import SlackNotifier, SlackOAuthError, SlackApiError
from app.services.webpush import send_push
from app.config import settings
import httpx

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Reception test-notification text (作業指示 §5). Kept distinct from the delivery test.
_SLACK_TEST_MESSAGE = ":bell: mokuture のSlack通知テストです\n\nこのチャンネルに受付通知が送信されます。"


class ChatworkConfig(BaseModel):
    """Chatwork の接続設定。

    **空欄は「変更しない」**。API トークンはレスポンスで `***` にマスクしていて画面に
    戻らないため、入力欄は常に空で表示される。素直に受け取って上書きすると、ルーム ID
    だけ直したいときに**トークンが空で潰れ、Chatwork 通知が丸ごと止まる**（担当者ごとの
    ルームも道連れになる）。秘密情報を伏せている以上、部分更新を既定にするしかない。
    """

    api_token: str = ""
    room_id: str = ""


class WebhookConfig(BaseModel):
    webhook_url: str


class PushDeliveryConfig(BaseModel):
    enabled: bool = True


class ChannelEnabledConfig(BaseModel):
    enabled: bool = True


@router.get("/settings")
async def get_settings(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationSetting).where(NotificationSetting.tenant_id == user.tenant_id))
    settings_list = result.scalars().all()
    out = {}
    for s in settings_list:
        if s.type.startswith("notification_health_"):
            continue
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


@router.get("/health")
async def get_notification_health(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Failures visible in the admin UI plus whether any usable channel exists."""
    rows = (await db.execute(select(NotificationSetting).where(
        NotificationSetting.tenant_id == user.tenant_id,
        NotificationSetting.type.in_(("slack", "chatwork")),
    ))).scalars().all()
    configs: dict[str, dict] = {}
    for row in rows:
        try:
            configs[row.type] = decrypt_dict(row.config_json)
        except Exception:
            configs[row.type] = {}
    slack = configs.get("slack", {})
    chatwork = configs.get("chatwork", {})
    push_count = len((await db.execute(select(PushSubscription.id).where(
        PushSubscription.tenant_id == user.tenant_id,
    ))).scalars().all())
    enabled = {
        channel: await notification_channels.is_enabled(db, user.tenant_id, channel)
        for channel in notification_channels.CHANNELS
    }
    configured = {
        "slack": bool(
            slack.get("webhook_url")
            or (slack.get("bot_access_token") and slack.get("channel_id"))
        ),
        "chatwork": bool(chatwork.get("api_token")),
        "push": push_count > 0,
    }
    issues = await notification_health.get_issues(db, user.tenant_id)
    return {
        "issues": issues,
        "issue_count": len(issues),
        "configured": configured,
        "enabled": enabled,
        "no_active_channel": not any(
            configured[channel] and enabled[channel] for channel in notification_channels.CHANNELS
        ),
    }


# NOTE: 受付用 Slack (type="slack") は OAuth 連携（/slack/oauth/url → /slack/callback）
# のみで設定する。Webhook URL を手入力/上書きする PUT /settings/slack は廃止した
# （顧客に Webhook URL を触らせない方針・OAuth バイパス防止）。配達用 slack_delivery も
# 手入力のPUTは廃止し、POST /slack/channel に target="slack_delivery" を渡して
# 共通連携のチャンネルだけを上書きする方式にした（下記「Delivery-specific」節）。


@router.put("/settings/chatwork")
async def update_chatwork(
    body: ChatworkConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    # ルームは任意: トークンだけで「連携済」にできる（担当者ごとのルーム指定・
    # テスト送信はトークンさえあれば使える）。ルームを設定すると、配達の呼び出しと、
    # 担当者別の宛先が無い（または共通宛先も使う）受付通知の宛先になる。
    await _upsert_chatwork(user.tenant_id, "chatwork", body, db)
    await notification_health.clear(user.tenant_id, "chatwork")
    return {"ok": True}


class ChatworkRoomLookup(BaseModel):
    """ルーム一覧の取得元トークン。空なら共通の `chatwork` 設定の保存済みトークンを使う。

    `api_token` を渡せるのは、まだ保存していない(入力中の)トークンでもルーム一覧を
    見てから保存できるようにするため（Slack の OAuth 後チャンネル選択と同じ体験）。
    値は保存しない。
    """

    api_token: str = ""


@router.post("/chatwork/rooms")
async def chatwork_rooms(
    body: ChatworkRoomLookup,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """管理画面のルーム選択用。トークンさえあれば保存前でも一覧を取れる。"""
    token = (body.api_token or "").strip()
    if not token:
        token = await chatwork_service.load_api_token(db, user.tenant_id)
    if not token:
        raise HTTPException(status_code=400, detail="Chatworkが未連携です。APIトークンを入力してください。")
    try:
        rooms = await chatwork_service.list_rooms(token)
    except chatwork_service.ChatworkApiError:
        raise HTTPException(status_code=502, detail="ルーム一覧の取得に失敗しました。APIトークンを確認してください。")
    return {"rooms": rooms}


@router.put("/settings/webhook")
async def update_webhook(
    body: WebhookConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "webhook", {"webhook_url": body.webhook_url}, db)
    return {"ok": True}


# ── Delivery-specific notification destinations (荷物の配達/呼び出し) ──────────────
# Webhook: same config shape as the base type; falls back to the base destination in
# kiosk call-staff when unset (see app.api.kiosk). Slack/Chatwork no longer have their
# own "連携設定"(接続) here — they reuse the shared Slack bot / Chatwork token and only
# let delivery override the channel/room (Slack: POST /slack/channel with
# target="slack_delivery"; Chatwork: the common card's room is shared by reception and delivery,
# see CLAUDE.md「Chatwork の接続設定」)。2026-10-24: 通常の通知先と配達の通知先で
# それぞれ別にSlack/Chatworkへ連携させていたのを統合した(無駄な二重連携の解消)。

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


@router.put("/settings/channel-enabled/{channel}")
async def update_channel_enabled(
    channel: str,
    body: ChannelEnabledConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Enable/disable shared notifications without deleting integration settings."""
    if channel not in notification_channels.CHANNELS:
        raise HTTPException(status_code=422, detail="invalid notification channel")
    await _upsert_setting(
        user.tenant_id,
        notification_channels.setting_type(channel),
        {"enabled": bool(body.enabled)},
        db,
    )
    if not body.enabled:
        await notification_health.clear(user.tenant_id, channel)
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


async def _load_setting_config(tenant_id: str, type_: str, db: AsyncSession) -> dict | None:
    """1種類ぶんの通知設定を復号して返す。行が無い/空/壊れているなら None。"""
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.tenant_id == tenant_id, NotificationSetting.type == type_)
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return None
    try:
        return decrypt_dict(setting.config_json)
    except Exception:
        return None


async def _run_test_slack_delivery(tenant_id: str, db: AsyncSession) -> dict:
    """配達（荷物の配達の呼び出し）専用のSlackテスト送信。

    共通の Slack 連携(Bot Token) + 配達専用のチャンネル上書き(あれば)を合成して送る
    （`SlackNotifier.resolve_delivery_config`。kiosk.py の実送信と同じ解決）。"""
    base = await _load_setting_config(tenant_id, "slack", db)
    override = await _load_setting_config(tenant_id, "slack_delivery", db)
    config = SlackNotifier.resolve_delivery_config(base, override)
    if not config.get("bot_access_token") and not config.get("webhook_url"):
        raise HTTPException(status_code=400, detail="Slackが未連携です。上の「Slack」で連携してください。")
    if config.get("bot_access_token") and not config.get("channel_id"):
        raise HTTPException(status_code=400, detail="通知先チャンネルが選択されていません。チャンネルを選択してください。")
    ok = await SlackNotifier.send_to_config(
        config,
        ":package: mokuture の配達通知テストです\n\nこのチャンネルに配達の呼び出し・置き配が通知されます。",
    )
    return {"ok": ok}


async def _run_test_chatwork(tenant_id: str, type_: str, db: AsyncSession) -> dict:
    setting = await _get_setting_or_404(tenant_id, type_, "Chatwork", db)
    config = decrypt_dict(setting.config_json)
    api_token = config.get("api_token", "")
    room_id = config.get("room_id", "")
    if not api_token:
        raise HTTPException(status_code=400, detail="Chatwork API token missing")
    if not room_id:
        # ルーム未設定＝トークンだけの「連携済」状態。実際にメッセージは送れないので、
        # トークンが有効かどうかの確認に留める（GET /v2/me）。
        info = await chatwork_service.verify_token(api_token)
        if info is None:
            raise HTTPException(status_code=400, detail="Chatwork API トークンが無効です")
        return {"ok": True, "checked": "token"}
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
    private_key = settings.vapid_private_key
    if not private_key:
        raise HTTPException(status_code=400, detail="プッシュ通知が使えない状態です。運営にお問い合わせください。")

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
    return await _run_test_slack_delivery(user.tenant_id, db)


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


async def _upsert_chatwork(tenant_id: str, type_: str, body: "ChatworkConfig", db: AsyncSession) -> None:
    """Chatwork 設定を**部分更新**する。空欄の項目は現在値を残す。

    理由は `ChatworkConfig` の docstring を参照（トークンはマスクして返しているので、
    画面から素直に上書きすると片方だけ直したときに消える）。

    ルームは任意: トークンだけで「連携済」として保存できる（担当者ごとのルーム指定・
    テスト送信はトークンだけで使える）。ルームを設定すると、配達の呼び出しに加えて、
    担当者ごとの通知先が未設定または「共通の通知先にも送る」の受付にも使用する。
    """
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == type_,
        )
    )
    setting = result.scalar_one_or_none()
    current: dict = {}
    if setting is not None and setting.config_json and setting.config_json != "{}":
        try:
            current = decrypt_dict(setting.config_json)
        except Exception:
            current = {}

    api_token = (body.api_token or "").strip() or (current.get("api_token") or "").strip()
    room_id = (body.room_id or "").strip() or (current.get("room_id") or "").strip()
    if not api_token:
        raise HTTPException(status_code=422, detail="API トークンを入力してください")
    await _upsert_setting(tenant_id, type_, {"api_token": api_token, "room_id": room_id}, db)


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
    """通知先。チャンネルへ送るか、個人へDMするかのどちらか一方を指定する。

    `user_id` 指定時は `conversations.open` でDMを開いて得た channel_id を保存する
    （送信そのものは通常のチャンネルと同じ `chat.postMessage` なので追加スコープ不要。
    DMを開くときだけ `im:write` が要る）。`display_name` はDM相手の表示名（`users.list`
    で取得済みのものをそのまま渡す。無くても動く）。

    `target`: どちらの宛先を設定するか。既定 `"slack"` は受付通知の共通チャンネル
    （従来どおり、共通の Bot Token と一緒に保存する）。`"slack_delivery"` は**配達の呼び出し
    専用のチャンネル上書き**（Bot Token は共通連携を使い回し、ここには channel_id/channel_name
    だけを保存する。チャンネル・DM先を1つも指定しない呼び出しは「上書きを解除して受付と
    同じチャンネルに戻す」を意味する）。2026-10-24追記: 配達専用に別のSlack連携を結ばせない
    ための設計（無駄な二重連携の解消）。
    """

    channel_id: str = ""
    user_id: str = ""
    display_name: str = ""
    target: str = "slack"


async def _load_slack_config(tenant_id: str, db: AsyncSession) -> dict | None:
    """Decrypted Slack config for a tenant, or None if not connected."""
    return await _load_setting_config(tenant_id, "slack", db)


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


def _slack_scope_error(e: SlackApiError, fallback: str) -> HTTPException:
    """`missing_scope` は「連携し直せば直る」と分かる専用メッセージにする。

    `im:write`/`users:read` は DM対応(issue #1追記分)で後から足したスコープなので、
    それ以前に連携済みのテナントの Bot Token には付与されていない。"""
    if "missing_scope" in str(e):
        return HTTPException(
            status_code=400,
            detail="DM機能を使うには権限が足りません。「Slackに追加」でもう一度連携してください。",
        )
    return HTTPException(status_code=502, detail=fallback)


@router.get("/slack/users")
async def slack_users(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """List workspace members for the DM picker (`users:read`). Requires an
    OAuth-connected bot token with the DM scopes (see `services.slack._SCOPE`)."""
    if not SlackNotifier.enabled():
        raise HTTPException(status_code=404, detail="Slack integration disabled")
    config = await _load_slack_config(user.tenant_id, db)
    token = (config or {}).get("bot_access_token") or ""
    if not token:
        raise HTTPException(status_code=400, detail="Slackが未連携です")
    try:
        users = await SlackNotifier.list_users(token)
    except SlackApiError as e:
        raise _slack_scope_error(e, "メンバー一覧の取得に失敗しました。連携をやり直してください。")
    return {"users": users}


async def _clear_stale_delivery_channel_override(tenant_id: str, db: AsyncSession) -> None:
    """配達専用のチャンネル上書き(`slack_delivery`)のうち、共通のBot連携に依存する
    **新形式**(channel_id だけを持つ)だけを消す。channel id はワークスペース固有なので、
    共通連携を解除・再連携した直後は別ワークスペースの channel id が残っていると送信が
    静かに失敗する。**旧形式**(自前の `webhook_url` を持つ)は共通連携と無関係に動くので
    残す。"""
    override = await _load_setting_config(tenant_id, "slack_delivery", db)
    if override is not None and not override.get("webhook_url"):
        await db.execute(
            delete(NotificationSetting).where(
                NotificationSetting.tenant_id == tenant_id,
                NotificationSetting.type == "slack_delivery",
            )
        )
        await db.commit()


@router.post("/slack/channel")
async def slack_set_channel(
    body: ChannelSelect,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Set the notification destination: a channel, or a DM to one person.

    Channels: joins the channel if it is public and the bot is not a member yet
    (conversations.join); private channels require a manual invite. DM: opens (or
    resumes) a 1:1 conversation via `conversations.open` and stores that channel id —
    sending afterward is the same `chat.postMessage` as any channel (CLAUDE.md参照)。

    `target="slack_delivery"`: 配達の呼び出し専用のチャンネル上書き。共通の Bot Token は
    使うが保存はしない(channel_id/channel_name だけ `slack_delivery` 行に保存。常に共通の
    連携を使い回す)。channel_id も user_id も指定しなければ上書きを解除し、以後は受付と
    同じ共通チャンネルに配達通知も届く。"""
    if not SlackNotifier.enabled():
        raise HTTPException(status_code=404, detail="Slack integration disabled")
    if body.target not in ("slack", "slack_delivery"):
        raise HTTPException(status_code=422, detail="invalid target")
    config = await _load_slack_config(user.tenant_id, db)
    token = (config or {}).get("bot_access_token") or ""
    if not token:
        raise HTTPException(status_code=400, detail="Slackが未連携です")

    user_id = (body.user_id or "").strip()
    channel_id = (body.channel_id or "").strip()
    if not channel_id and not user_id:
        if body.target == "slack_delivery":
            # 配達専用の上書きを解除 = 受付と同じ共通チャンネルに戻す。
            await db.execute(
                delete(NotificationSetting).where(
                    NotificationSetting.tenant_id == user.tenant_id,
                    NotificationSetting.type == "slack_delivery",
                )
            )
            await db.commit()
            return {"ok": True, "channel_name": ""}
        raise HTTPException(status_code=422, detail="channel_id or user_id is required")

    if user_id:
        try:
            dm_channel_id = await SlackNotifier.open_dm(token, user_id)
        except SlackApiError as e:
            raise _slack_scope_error(e, "DMの作成に失敗しました。")
        display = f"DM: {(body.display_name or '').strip() or user_id}"
        channel_id, channel_name = dm_channel_id, display
    else:
        try:
            info = await SlackNotifier.get_channel_info(token, channel_id)
        except SlackApiError:
            raise HTTPException(status_code=400, detail="チャンネル情報の取得に失敗しました。")
        if not info["is_private"] and not info["is_member"]:
            await SlackNotifier.join_channel(token, channel_id)  # best-effort
        channel_name = ("#" if not info["is_private"] else "") + (info["name"] or channel_id)
        channel_id = info["id"]

    now = datetime.now(timezone.utc).isoformat()
    if body.target == "slack_delivery":
        # Bot Token は複製しない(共通の連携を使い回す)。チャンネルだけ上書きで保存する。
        await _upsert_setting(
            user.tenant_id, "slack_delivery",
            {"channel_id": channel_id, "channel_name": channel_name, "updated_at": now},
            db,
        )
    else:
        config["channel_id"] = channel_id
        config["channel_name"] = channel_name
        config["updated_at"] = now
        await _upsert_setting(user.tenant_id, "slack", config, db)
    await notification_health.clear(user.tenant_id, "slack")
    return {"ok": True, "channel_name": channel_name}


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
    await _clear_stale_delivery_channel_override(user.tenant_id, db)
    await notification_health.clear(user.tenant_id, "slack")
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
    # 再連携は別ワークスペースの可能性がある。配達専用のチャンネル上書き(新形式)は
    # channel id がワークスペース固有なので、持ち越すと静かに送信失敗する。
    await _clear_stale_delivery_channel_override(tenant_id, db)
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

    slack_user = payload.get("user") or {}
    who = slack_user.get("real_name") or slack_user.get("username") or slack_user.get("name") or "Slack担当者"
    outcome = await _apply_decision(
        db, log, decision, actor_name=who, actor_user_id=slack_user.get("id"), via="slack"
    )
    if outcome.applied:
        background.add_task(reception_notify.fire_decision_notifications, log.tenant_id, log.id)

    # 元メッセージを「対応済み」に置換（ボタン除去）。押した人も添える。response_url は30分/5回有効。
    label = _DECISION_JP.get(outcome.state, outcome.state)
    who = outcome.decided_by_name
    orig_text = (payload.get("message") or {}).get("text") or "来客の受付"
    ctx = (
        "⌛ 対応時間切れです。キオスクは電話案内に切り替わりました。"
        if outcome.decision_expired
        else f"✅ 対応済み：*{label}*" + (f"（{who}）" if who else "")
    )
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
