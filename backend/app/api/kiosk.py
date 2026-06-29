"""Public kiosk endpoints — authenticated by device token, not JWT.

The device token is stored in the kiosk's localStorage and sent via
the X-Kiosk-Token header. It identifies both the device and the tenant.
"""
import hashlib
import os
import re
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

_JST = zoneinfo.ZoneInfo("Asia/Tokyo")

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.device import Device, Locker
from app.models.tenant import Tenant
from app.models.content import Media, Playlist, PlaylistItem, Schedule
from app.models.reception import ReceptionLog
from app.models.notification import NotificationSetting, PushSubscription
from app.models.visitor_appointment import VisitorAppointment
from app.models.room import MeetingRoom
from app.services.slack import send_slack_notification
from app.services.storage import generate_presigned_get_url
from app.services.crypto import decrypt_dict
from app.services.webpush import send_push
from app.services.auth import hash_password, verify_password
from app.config import settings

_PIN_RE = re.compile(r"^\d{4}$")

router = APIRouter(prefix="/kiosk", tags=["kiosk"])
_limiter = Limiter(key_func=get_remote_address)

_ALLOWED_METHODS = {"form", "qr", "appointment"}
_PIN_FAIL_MSG = "PINが無効または期限切れです"

# ── OTA bundle ────────────────────────────────────────────────────────────────
# Env var override; default resolves to <repo>/kiosk_agent relative to this file.
_KIOSK_AGENT_DIR = Path(
    os.environ.get("KIOSK_BUNDLE_DIR", str(Path(__file__).parents[3] / "kiosk_agent"))
)

# Files distributed via OTA (relative to kiosk_agent root); order is stable for hashing.
BUNDLE_FILES = [
    "static/kiosk.html",
    "main.py",
    "updater.py",
    "gpio.py",
    "sync.py",
    "state.py",
    "config.py",
]
_FORCE_WINDOW_SEC = 7200  # force flag stays active for 2 hours after trigger


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _bundle_version() -> str:
    parts = []
    for rel in BUNDLE_FILES:
        p = _KIOSK_AGENT_DIR / rel
        if p.exists():
            parts.append(f"{rel}:{_file_sha(p)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


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


@router.post("/heartbeat", status_code=200)
async def kiosk_heartbeat(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device)):
    """軽量生存確認。get_kiosk_device が last_seen_at を更新するためここでの追加処理不要。"""
    return {"ok": True}


@router.get("/schedule")
async def kiosk_schedule(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device), db: AsyncSession = Depends(get_db)):
    """Return the current scheduled playlist with embedded media data."""
    tenant, device = ctx

    # Return suspension status immediately — kiosk handles UI
    if tenant.is_suspended:
        return {"suspended": True, "message": "このテナントは現在停止中です", "playlist": None, "force_update_at": None}

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
    force_update_at = device.force_update_at.isoformat() if device.force_update_at else None

    if schedule is None:
        return {"playlist": None, "force_update_at": force_update_at}

    pl_result = await db.execute(select(Playlist).where(Playlist.id == schedule.playlist_id))
    pl = pl_result.scalar_one_or_none()
    if pl is None:
        return {"playlist": None, "force_update_at": force_update_at}

    items_result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == pl.id)
        .order_by(PlaylistItem.display_order)
    )
    items = items_result.scalars().all()

    if not items:
        return {"playlist": {"id": pl.id, "name": pl.name, "items": []}, "force_update_at": force_update_at}

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
            "transition_type": pl.transition_type,
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
        },
        "force_update_at": force_update_at,
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
    appointment_id: str | None = None

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


@router.get("/appointment/{token}")
async def kiosk_get_appointment(
    token: str,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """QR トークンから来社予定を取得（デバイストークン認証）"""
    tenant, _ = ctx
    result = await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.token == token,
            VisitorAppointment.tenant_id == tenant.id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    meeting_room = None
    if appt.meeting_room_id:
        room_result = await db.execute(
            select(MeetingRoom).where(
                MeetingRoom.id == appt.meeting_room_id,
                MeetingRoom.tenant_id == tenant.id,
            )
        )
        room = room_result.scalar_one_or_none()
        if room is not None:
            meeting_room = {
                "name": room.name,
                "location": room.location,
                "map_image_url": room.map_image_url,
            }

    return {
        "id": appt.id,
        "visitor_name": appt.visitor_name,
        "company": appt.company,
        "purpose": appt.purpose,
        "staff": appt.staff,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "status": appt.status,
        "meeting_room": meeting_room,
    }


@router.post("/reception", status_code=201)
async def kiosk_reception(
    body: ReceptionCreate,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Submit a reception form entry using device token authentication."""
    tenant, _ = ctx
    log = ReceptionLog(
        tenant_id=tenant.id,
        visitor_name=body.visitor_name,
        company=body.company,
        purpose=body.purpose,
        staff=body.staff,
        method=body.method,
        appointment_id=body.appointment_id,
    )
    db.add(log)

    # チェックイン時に予約ステータスを更新
    if body.appointment_id:
        appt_result = await db.execute(
            select(VisitorAppointment).where(
                VisitorAppointment.id == body.appointment_id,
                VisitorAppointment.tenant_id == tenant.id,
            )
        )
        appt = appt_result.scalar_one_or_none()
        if appt:
            appt.status = "received"

    await db.commit()
    await db.refresh(log)

    await _notify_slack(tenant.id, log, db)
    await _notify_push(tenant.id, log, db)
    await _notify_webhook(tenant.id, log, db)

    return {
        "id": log.id,
        "visitor_name": log.visitor_name,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }


# ── Staff call (delivery) ──────────────────────────────────────────────────────

class CallStaffBody(BaseModel):
    message: str | None = None


@router.post("/call-staff")
async def kiosk_call_staff(
    body: CallStaffBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Notify staff that delivery is waiting (配達の呼び出し) over all configured channels.

    Best-effort across Slack / Web Push / Webhook / Chatwork — a failing channel
    must not fail the request.
    """
    tenant, _ = ctx
    message = (body.message or "").strip() or None

    title = "配達の呼び出し"
    text = f"🔔 配達の呼び出し\n受付端末から担当者が呼ばれています。{message or ''}"

    await _notify_slack_text(tenant.id, text, db)
    await _notify_push_text(tenant.id, title, text, tenant.id, db)
    await _notify_webhook_event(
        tenant.id,
        {
            "event": "call_staff",
            "tenant_id": tenant.id,
            "kind": "delivery",
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        db,
    )
    await _notify_chatwork_text(tenant.id, text, db)

    return {"ok": True}


# ── Lockers (device token auth) ────────────────────────────────────────────────

class LockerPinBody(BaseModel):
    pin: str


async def _get_kiosk_locker(locker_id: str, tenant_id: str, db: AsyncSession) -> Locker:
    result = await db.execute(
        select(Locker).where(Locker.id == locker_id, Locker.tenant_id == tenant_id)
    )
    locker = result.scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Locker not found")
    return locker


@router.get("/lockers")
async def kiosk_list_lockers(
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """List this tenant's lockers for the kiosk. Never exposes pin_hash."""
    tenant, _ = ctx
    result = await db.execute(
        select(Locker).where(Locker.tenant_id == tenant.id).order_by(Locker.door_number)
    )
    lockers = result.scalars().all()
    available = sum(1 for l in lockers if not l.occupied)
    return {
        "lockers": [
            {
                "id": l.id,
                "name": l.name or f"ロッカー {l.door_number}",
                "door_number": l.door_number,
                "occupied": bool(l.occupied),
                "has_pin": l.pin_hash is not None,
            }
            for l in lockers
        ],
        "available_count": available,
    }


@router.post("/lockers/{locker_id}/occupy")
async def kiosk_occupy_locker(
    locker_id: str,
    body: LockerPinBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Hold a locker with a 4-digit PIN."""
    tenant, _ = ctx
    if not _PIN_RE.match(body.pin or ""):
        raise HTTPException(status_code=422, detail="pin must be exactly 4 digits")
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)
    if locker.occupied:
        raise HTTPException(status_code=409, detail="already occupied")
    locker.pin_hash = hash_password(body.pin)
    locker.occupied = True
    locker.occupied_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.post("/lockers/{locker_id}/occupy-delivery")
async def kiosk_occupy_locker_delivery(
    locker_id: str,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Hold a locker for delivery drop-off (置き配) with NO PIN — auto-lock without passcode."""
    tenant, _ = ctx
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)
    if locker.occupied:
        raise HTTPException(status_code=409, detail="already occupied")
    locker.pin_hash = None
    locker.occupied = True
    locker.occupied_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.post("/lockers/{locker_id}/release")
async def kiosk_release_locker(
    locker_id: str,
    body: LockerPinBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Release a held locker by verifying its 4-digit PIN."""
    tenant, _ = ctx
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)
    if not locker.occupied:
        raise HTTPException(status_code=409, detail="not occupied")
    # No-pin hold (should not happen in Phase 2): allow release.
    if locker.pin_hash is None:
        locker.occupied = False
        locker.occupied_at = None
        await db.commit()
        return {"ok": True, "door_number": locker.door_number}
    if not verify_password(body.pin or "", locker.pin_hash):
        raise HTTPException(status_code=403, detail="invalid pin")
    locker.pin_hash = None
    locker.occupied = False
    locker.occupied_at = None
    await db.commit()
    return {"ok": True, "door_number": locker.door_number}


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


async def _send_webhook(url: str, data: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=data)
    except Exception:
        pass


async def _notify_webhook(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "webhook",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return
    try:
        config = decrypt_dict(setting.config_json)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            payload = {
                "event": "reception",
                "tenant_id": tenant_id,
                "visitor_name": log.visitor_name,
                "company": log.company,
                "staff": log.staff,
                "purpose": log.purpose,
                "method": log.method,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            await _send_webhook(webhook_url, payload)
    except Exception:
        pass


# ── Generic-message notify helpers (staff call etc.) ───────────────────────────

async def _notify_slack_text(tenant_id: str, text: str, db: AsyncSession) -> None:
    """Send a plain text message to the tenant's Slack webhook. Best-effort."""
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
            await send_slack_notification(webhook_url, text)
    except Exception:
        pass


async def _notify_push_text(
    tenant_id: str, title: str, body: str, url_tenant_id: str, db: AsyncSession
) -> None:
    """Fire Web Push with a plain title/body to all subscriptions. Best-effort."""
    try:
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

        for sub in subs:
            try:
                await send_push(
                    endpoint=sub.endpoint,
                    p256dh=sub.p256dh,
                    auth=sub.auth_key,
                    title=title,
                    body=body,
                    url=f"/{url_tenant_id}/admin/reception",
                    private_key=private_key,
                    subject=settings.vapid_subject,
                )
            except Exception:
                pass
    except Exception:
        pass


async def _notify_webhook_event(tenant_id: str, payload: dict, db: AsyncSession) -> None:
    """POST an arbitrary event payload to the tenant's webhook. Best-effort."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "webhook",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return
    try:
        config = decrypt_dict(setting.config_json)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            await _send_webhook(webhook_url, payload)
    except Exception:
        pass


async def _notify_chatwork_text(tenant_id: str, text: str, db: AsyncSession) -> None:
    """Post a message to the tenant's Chatwork room. Best-effort."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "chatwork",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return
    try:
        config = decrypt_dict(setting.config_json)
        api_token = config.get("api_token", "")
        room_id = config.get("room_id", "")
        if not api_token or not room_id:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": text},
            )
    except Exception:
        pass


# ── OTA bundle endpoints ───────────────────────────────────────────────────────

@router.get("/bundle/manifest")
async def kiosk_bundle_manifest(
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
):
    """Return current bundle version + per-file hashes. Device uses this to detect changes."""
    tenant, _ = ctx
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    force = False
    fat = getattr(tenant, "kiosk_force_update_at", None)
    if fat is not None:
        diff = (now - fat).total_seconds()
        force = 0 <= diff <= _FORCE_WINDOW_SEC

    files = []
    for rel in BUNDLE_FILES:
        p = _KIOSK_AGENT_DIR / rel
        if p.exists():
            files.append({"path": rel, "hash": _file_sha(p), "size": p.stat().st_size})

    return {"version": _bundle_version(), "files": files, "force": force}


@router.get("/bundle/file/{file_path:path}")
async def kiosk_bundle_file(
    file_path: str,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
):
    """Download a single bundle file. Path must be in BUNDLE_FILES whitelist."""
    if file_path not in BUNDLE_FILES:
        raise HTTPException(status_code=404, detail="Not in bundle")
    p = _KIOSK_AGENT_DIR / file_path
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p)
