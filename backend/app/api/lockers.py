"""Locker control API – manages state in DB; Phase 2: wire up GPIO bridge."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import get_current_user, require_roles
from app.models.device import Locker
from app.models.user import User

router = APIRouter(prefix="/lockers", tags=["lockers"])


class CreateLockerRequest(BaseModel):
    # New interface: name + gpio_pin
    name: Optional[str] = None
    gpio_pin: Optional[int] = None
    # Legacy interface: door_number + auto_relock_sec (kept for backwards compatibility)
    door_number: Optional[int] = None
    auto_relock_sec: int = 60


@router.get("")
async def list_lockers(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Locker).where(Locker.tenant_id == user.tenant_id).order_by(Locker.door_number))
    return [_locker_out(l) for l in result.scalars()]


@router.post("", status_code=201)
async def create_locker(
    body: CreateLockerRequest,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    # Support new (name, gpio_pin) and legacy (door_number) request formats
    gpio_pin = body.gpio_pin if body.gpio_pin is not None else (body.door_number or 0)
    door_number = gpio_pin  # door_number column stores the pin number
    auto_relock_sec = body.auto_relock_sec
    locker = Locker(
        tenant_id=user.tenant_id,
        door_number=door_number,
        auto_relock_sec=auto_relock_sec,
        state="closed",
    )
    db.add(locker)
    await db.commit()
    await db.refresh(locker)
    # Store name in a synthesized field for the response
    return _locker_out(locker, name=body.name)


@router.post("/{locker_id}/open")
async def open_locker(
    locker_id: str,
    user: User = Depends(require_roles("admin", "kiosk", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Open (unlock) a locker. In production this would trigger GPIO."""
    locker = await _get_locker(locker_id, user.tenant_id, db)
    locker.state = "open"
    locker.last_unlocked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": locker.id, "state": locker.state}


@router.post("/{locker_id}/close")
async def close_locker(
    locker_id: str,
    user: User = Depends(require_roles("admin", "kiosk", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Close (lock) a locker."""
    locker = await _get_locker(locker_id, user.tenant_id, db)
    locker.state = "closed"
    await db.commit()
    return {"id": locker.id, "state": locker.state}


@router.post("/{locker_id}/unlock")
async def unlock_locker(
    locker_id: str,
    user: User = Depends(require_roles("admin", "kiosk", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Legacy unlock endpoint – delegates to open."""
    locker = await _get_locker(locker_id, user.tenant_id, db)
    locker.state = "open"
    locker.last_unlocked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "state": "open", "auto_relock_sec": locker.auto_relock_sec}


@router.post("/{locker_id}/lock")
async def lock_locker(
    locker_id: str,
    user: User = Depends(require_roles("admin", "kiosk", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Legacy lock endpoint – delegates to close."""
    locker = await _get_locker(locker_id, user.tenant_id, db)
    locker.state = "closed"
    await db.commit()
    return {"ok": True, "state": "closed"}


@router.delete("/{locker_id}", status_code=204)
async def delete_locker(
    locker_id: str,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    locker = await _get_locker(locker_id, user.tenant_id, db)
    await db.delete(locker)
    await db.commit()


async def _get_locker(locker_id: str, tenant_id: str, db: AsyncSession) -> Locker:
    result = await db.execute(
        select(Locker).where(Locker.id == locker_id, Locker.tenant_id == tenant_id)
    )
    locker = result.scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Locker not found")
    return locker


def _locker_out(l: Locker, name: Optional[str] = None) -> dict:
    return {
        "id": l.id,
        "name": name or f"ロッカー {l.door_number}",
        "gpio_pin": l.door_number,
        "state": l.state if l.state in ("open", "closed") else ("open" if l.state == "unlocked" else "closed"),
        "tenant_id": l.tenant_id,
        # Legacy fields kept for backwards compatibility
        "door_number": l.door_number,
        "last_unlocked_at": l.last_unlocked_at.isoformat() if l.last_unlocked_at else None,
        "auto_relock_sec": l.auto_relock_sec,
    }
