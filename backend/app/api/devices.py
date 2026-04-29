"""Admin API for kiosk device token management."""
import random
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.device import Device
from app.models.user import User

router = APIRouter(prefix="/devices", tags=["devices"])

_PIN_EXPIRY_MINUTES = 15


class DeviceCreate(BaseModel):
    name: str
    location: str | None = None


class DeviceOut(BaseModel):
    id: str
    name: str
    location: str | None
    last_seen_at: str | None
    created_at: str


@router.get("", response_model=list[DeviceOut])
async def list_devices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device).where(Device.tenant_id == user.tenant_id).order_by(Device.created_at.desc())
    )
    return [_out(d) for d in result.scalars()]


@router.post("", status_code=201)
async def create_device(
    body: DeviceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = secrets.token_hex(32)  # 64-char hex, cryptographically secure
    pin = f"{random.SystemRandom().randint(0, 999999):06d}"
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=_PIN_EXPIRY_MINUTES)
    device = Device(
        tenant_id=user.tenant_id,
        name=body.name,
        location=body.location,
        token=token,
        pin_code=pin,
        pin_expires_at=expires,
        pin_used=False,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return {**_out(device), "token": token, "pin_code": pin, "pin_expires_minutes": _PIN_EXPIRY_MINUTES}


@router.post("/{device_id}/force-refresh")
async def force_refresh_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.force_update_at = datetime.utcnow()
    await db.commit()
    await db.refresh(device)
    return {"ok": True, "force_update_at": device.force_update_at.isoformat()}


class UpdateDeviceRequest(BaseModel):
    name: str | None = None
    location: str | None = None


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: str,
    body: UpdateDeviceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is not None and (len(body.name) < 3 or len(body.name) > 100):
        raise HTTPException(status_code=422, detail="name must be 3-100 characters")
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if body.name is not None:
        device.name = body.name
    if body.location is not None or "location" in body.model_fields_set:
        device.location = body.location
    await db.commit()
    await db.refresh(device)
    return _out(device)


@router.post("/{device_id}/pin")
async def regenerate_pin(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    pin = f"{random.SystemRandom().randint(0, 999999):06d}"
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=_PIN_EXPIRY_MINUTES)
    device.pin_code = pin
    device.pin_expires_at = expires
    device.pin_used = False
    await db.commit()
    return {"pin_code": pin, "expires_minutes": _PIN_EXPIRY_MINUTES}


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.delete(device)
    await db.commit()


def _out(d: Device) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "location": d.location,
        "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else "",
    }
