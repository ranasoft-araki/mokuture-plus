from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import require_roles
from app.models.notification import NotificationSetting
from app.models.user import User
from app.services.crypto import encrypt_dict, decrypt_dict
from app.services.slack import send_slack_notification
import httpx

router = APIRouter(prefix="/notifications", tags=["notifications"])


class SlackConfig(BaseModel):
    webhook_url: str


class ChatworkConfig(BaseModel):
    api_token: str
    room_id: str


class WebhookConfig(BaseModel):
    webhook_url: str


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
        # Mask sensitive values in response
        if s.type == "slack" and "webhook_url" in config:
            config["webhook_url"] = config["webhook_url"][:30] + "***"
        if s.type == "chatwork" and "api_token" in config:
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


@router.post("/test/slack")
async def test_slack(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.tenant_id == user.tenant_id, NotificationSetting.type == "slack")
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Slack not configured")
    config = decrypt_dict(setting.config_json)
    ok = await send_slack_notification(config.get("webhook_url", ""), "mokuture+ テスト通知")
    return {"ok": ok}


@router.post("/test/chatwork")
async def test_chatwork(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.tenant_id == user.tenant_id, NotificationSetting.type == "chatwork")
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Chatwork not configured")
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


@router.post("/test/webhook")
async def test_webhook(user: User = Depends(require_roles("admin", "superadmin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.tenant_id == user.tenant_id, NotificationSetting.type == "webhook")
    )
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Webhook not configured")
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
                    "tenant_id": user.tenant_id,
                },
            )
        ok = res.status_code < 400
    except Exception:
        ok = False
    return {"ok": ok}


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
