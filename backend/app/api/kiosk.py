"""Public kiosk endpoints — authenticated by device token, not JWT.

The device token is stored in the kiosk's localStorage and sent via
the X-Kiosk-Token header. It identifies both the device and the tenant.
"""
import zoneinfo
from datetime import datetime, timezone

_JST = zoneinfo.ZoneInfo("Asia/Tokyo")

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.content import Media, Playlist, PlaylistItem, Schedule
from app.models.reception import ReceptionLog
from app.models.notification import NotificationSetting, PushSubscription
from app.services.slack import send_slack_notification
from app.services.storage import generate_presigned_get_url
from app.services.crypto import decrypt_dict
from app.services.webpush import send_push
from app.config import settings

router = APIRouter(prefix="/kiosk", tags=["kiosk"])
_limiter = Limiter(key_func=get_remote_address)

_ALLOWED_METHODS = {"form", "qr"}
_PIN_FAIL_MSG = "PINが無効または期限切れです"


class PinVerifyRequest(BaseModel):
    pin_code: str


@router.post("/verify-pin")
@_limiter.limit("10/minute")
async def verify_pin(request: Request, body: PinVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a one-time PIN for the device token. PIN expires in 15 min and is single-use."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(select(Device).where(Device.pin_code == body.pin_code))
    device = result.scalar_one_or_none()

    if device is None or device.pin_used or device.pin_expires_at is None or device.pin_expires_at < now:
        raise HTTPException(status_code=401, detail=_PIN_FAIL_MSG)

    # Invalidate PIN immediately
    device.pin_used = True
    device.pin_code = None
    await db.commit()

    return {"device_token": device.token, "device_name": device.name}


async def get_kiosk_device(
    x_kiosk_token: str = Header(alias="X-Kiosk-Token"),
    db: AsyncSession = Depends(get_db),
) -> tuple[Tenant, Device]:
    result = await db.execute(select(Device).where(Device.token == x_kiosk_token))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")

    device.last_seen_at = datetime.now(_JST).replace(tzinfo=None)
    await db.commit()

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == device.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")

    return tenant, device


@router.get("/schedule")
async def kiosk_schedule(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device), db: AsyncSession = Depends(get_db)):
    """Return the current scheduled playlist with embedded media data."""
    tenant, _ = ctx
    now = datetime.now(_JST)
    day = now.weekday()
    time_str = now.strftime("%H:%M")

    result = await db.execute(
        select(Schedule).where(
            Schedule.tenant_id == tenant.id,
            (Schedule.day_of_week == day) | (Schedule.day_of_week == -1),
            Schedule.start_time <= time_str,
            Schedule.end_time > time_str,
        )
    )
    schedule = result.scalars().first()
    if schedule is None:
        return {"playlist": None}

    pl_result = await db.execute(select(Playlist).where(Playlist.id == schedule.playlist_id))
    pl = pl_result.scalar_one_or_none()
    if pl is None:
        return {"playlist": None}

    items_result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == pl.id)
        .order_by(PlaylistItem.display_order)
    )
    items = items_result.scalars().all()

    if not items:
        return {"playlist": {"id": pl.id, "name": pl.name, "items": []}}

    media_ids = [i.media_id for i in items]
    media_result = await db.execute(
        select(Media).where(Media.id.in_(media_ids), Media.tenant_id == tenant.id)
    )
    media_map = {m.id: m for m in media_result.scalars()}

    storage_base = settings.storage_public_url.rstrip("/") + "/"

    def _media_url(url: str) -> str:
        if url.startswith(storage_base):
            return generate_presigned_get_url(url.removeprefix(storage_base), expires_in=3600)
        return url

    return {
        "playlist": {
            "id": pl.id,
            "name": pl.name,
            "items": [
                {
                    "id": i.id,
                    "media_id": i.media_id,
                    "display_order": i.display_order,
                    "duration_sec": i.duration_sec,
                    "media": (
                        {
                            "id": m.id,
                            "url": _media_url(m.url),
                            "mime_type": m.mime_type,
                            "filename": m.filename,
                        }
                        if (m := media_map.get(i.media_id))
                        else None
                    ),
                }
                for i in items
            ],
        }
    }


@router.get("/content-manifest")
async def kiosk_content_manifest(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device), db: AsyncSession = Depends(get_db)):
    """Return all scheduled-playlist media for local device caching."""
    tenant, _ = ctx

    sched_result = await db.execute(
        select(Schedule.playlist_id).where(
            Schedule.tenant_id == tenant.id,
            Schedule.playlist_id.isnot(None),
        ).distinct()
    )
    playlist_ids = [row[0] for row in sched_result.all()]
    if not playlist_ids:
        return {"items": []}

    items_result = await db.execute(
        select(PlaylistItem.media_id).where(
            PlaylistItem.playlist_id.in_(playlist_ids)
        ).distinct()
    )
    media_ids = [row[0] for row in items_result.all()]
    if not media_ids:
        return {"items": []}

    media_result = await db.execute(
        select(Media).where(Media.id.in_(media_ids), Media.tenant_id == tenant.id)
    )
    media_list = media_result.scalars().all()

    storage_base = settings.storage_public_url.rstrip("/") + "/"

    def _download_url(url: str) -> str:
        if url.startswith(storage_base):
            return generate_presigned_get_url(url.removeprefix(storage_base), expires_in=3600)
        return url

    return {
        "items": [
            {
                "id": m.id,
                "filename": m.filename,
                "mime_type": m.mime_type,
                "size_bytes": m.size_bytes,
                "url": _download_url(m.url),
            }
            for m in media_list
        ]
    }


class ReceptionCreate(BaseModel):
    visitor_name: str
    company: str | None = None
    purpose: str | None = None
    staff: str | None = None
    method: str = "form"

    @field_validator("visitor_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("visitor_name must not be empty")
        if len(v) > 255:
            raise ValueError("visitor_name too long (max 255 chars)")
        return v

    @field_validator("method")
    @classmethod
    def method_allowed(cls, v: str) -> str:
        if v not in _ALLOWED_METHODS:
            raise ValueError(f"method must be one of: {_ALLOWED_METHODS}")
        return v


@router.post("/reception", status_code=201)
async def kiosk_reception(
    body: ReceptionCreate,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Submit a reception form entry using device token authentication."""
    tenant, _ = ctx
    log = ReceptionLog(tenant_id=tenant.id, **body.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)

    await _notify_slack(tenant.id, log, db)
    await _notify_push(tenant.id, log, db)

    return {
        "id": log.id,
        "visitor_name": log.visitor_name,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }


async def _notify_slack(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "slack",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return
    try:
        config = decrypt_dict(setting.config_json)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            msg = (
                f"*新規受付* {log.visitor_name}様（{log.company or '—'}）\n"
                f"用件: {log.purpose or '—'}　担当: {log.staff or '—'}"
            )
            await send_slack_notification(webhook_url, msg)
    except Exception:
        pass


async def _notify_push(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    """Fire Web Push to all registered subscriptions for this tenant."""
    # Get VAPID keys (from per-tenant setting or global config)
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
            vapid_config = decrypt_dict(vapid_setting.config_json)
            private_key = vapid_config.get("private_key", "")
        except Exception:
            pass
    if not private_key:
        private_key = settings.vapid_private_key
    if not private_key:
        return

    subs_result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == tenant_id)
    )
    subs = subs_result.scalars().all()
    if not subs:
        return

    title = "来客のお知らせ"
    body = f"{log.visitor_name}様（{log.company or '—'}）が受付を完了しました。"
    if log.purpose:
        body += f" 用件：{log.purpose}"

    for sub in subs:
        await send_push(
            endpoint=sub.endpoint,
            p256dh=sub.p256dh,
            auth=sub.auth_key,
            title=title,
            body=body,
            url=f"/{tenant_id}/admin/reception",
            private_key=private_key,
            subject=settings.vapid_subject,
        )  # fire-and-forget: ignore (bool, str) return
