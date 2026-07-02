from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import require_roles
from app.models.notification import NotificationSetting, PushSubscription
from app.models.user import User
from app.services.crypto import encrypt_dict, decrypt_dict
from app.services.slack import send_slack_notification
from app.services.webpush import send_push
from app.config import settings
import httpx

router = APIRouter(prefix="/notifications", tags=["notifications"])


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
        # Mask sensitive values in response (covers base + *_delivery variants)
        if s.type.startswith("slack") and "webhook_url" in config:
            config["webhook_url"] = config["webhook_url"][:30] + "***"
        if s.type.startswith("chatwork") and "api_token" in config:
            config["api_token"] = "***"
        out[s.type] = config
    return out


@router.put("/settings/slack")
async def update_slack(
    body: SlackConfig,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    await _upsert_setting(user.tenant_id, "slack", {"webhook_url": body.webhook_url}, db)
    return {"ok": True}


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


async def _run_test_slack(tenant_id: str, type_: str, db: AsyncSession) -> dict:
    setting = await _get_setting_or_404(tenant_id, type_, "Slack", db)
    config = decrypt_dict(setting.config_json)
    ok = await send_slack_notification(config.get("webhook_url", ""), "mokuture+ テスト通知")
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
    return await _run_test_slack(user.tenant_id, "slack_delivery", db)


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
