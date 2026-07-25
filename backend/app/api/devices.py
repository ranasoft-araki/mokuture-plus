"""Admin API for kiosk device management (承認フロー)."""
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.device import Device
from app.models.content import Playlist
from app.models.user import User
from app.services.timeutil import iso_z

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceCreate(BaseModel):
    name: str
    location: str | None = None


class DeviceOut(BaseModel):
    id: str
    name: str
    location: str | None
    status: str
    last_seen_at: str | None
    created_at: str
    agent_version: str | None = None
    ip_address: str | None = None
    online_since: str | None = None
    current_playlist_name: str | None = None


@router.get("", response_model=list[DeviceOut])
async def list_devices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device).where(Device.tenant_id == user.tenant_id).order_by(Device.created_at.desc())
    )
    devices = list(result.scalars())
    # current_playlist_id → プレイリスト名を解決（削除済みプレイリストを指す場合は None）。
    pl_ids = {d.current_playlist_id for d in devices if d.current_playlist_id}
    pl_names: dict[str, str] = {}
    if pl_ids:
        pl_rows = await db.execute(
            select(Playlist.id, Playlist.name).where(
                Playlist.id.in_(pl_ids), Playlist.tenant_id == user.tenant_id
            )
        )
        pl_names = {pid: name for pid, name in pl_rows.all()}
    return [_out(d, pl_names.get(d.current_playlist_id)) for d in devices]


@router.post("", status_code=201)
async def create_device(
    body: DeviceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """管理者が端末を手動追加する（承認済み active として作成）。

    通常は端末側の自己登録（POST /kiosk/register → 承認）を使う。この経路は
    トークンを手動プロビジョニングする補助用途で、発行トークンを一度だけ返す。"""
    token = secrets.token_hex(32)  # 64-char hex, cryptographically secure
    device = Device(
        tenant_id=user.tenant_id,
        name=body.name,
        location=body.location,
        token=token,
        status="active",
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return {**_out(device), "token": token}


@router.post("/{device_id}/approve", response_model=DeviceOut)
async def approve_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """承認待ち端末を承認して起動可能（active）にする。"""
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.status = "active"
    await db.commit()
    await db.refresh(device)
    return _out(device)


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
    new_name: str | None = None
    if body.name is not None:
        new_name = body.name.strip()
        if len(new_name) < 1 or len(new_name) > 100:
            raise HTTPException(status_code=422, detail="端末名は1〜100文字で入力してください")
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.tenant_id == user.tenant_id)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if new_name is not None:
        device.name = new_name
    if body.location is not None or "location" in body.model_fields_set:
        device.location = body.location
    await db.commit()
    await db.refresh(device)
    return _out(device)


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


def _out(d: Device, playlist_name: str | None = None) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "location": d.location,
        "status": d.status or "active",
        "last_seen_at": iso_z(d.last_seen_at),
        "created_at": iso_z(d.created_at) or "",
        "agent_version": d.agent_version,
        "ip_address": d.ip_address,
        "online_since": iso_z(d.online_since),
        "current_playlist_name": playlist_name,
    }
