"""Meeting room management API — admin JWT required."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.room import MeetingRoom
from app.models.user import User

router = APIRouter(prefix="/meeting-rooms", tags=["meeting-rooms"])


class MeetingRoomResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    location: Optional[str] = None
    capacity: Optional[int] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: datetime


class MeetingRoomCreate(BaseModel):
    name: str
    location: Optional[str] = None
    capacity: Optional[int] = None
    color: Optional[str] = None
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class MeetingRoomUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    capacity: Optional[int] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


def _out(room: MeetingRoom) -> MeetingRoomResponse:
    return MeetingRoomResponse(
        id=room.id,
        tenant_id=room.tenant_id,
        name=room.name,
        location=room.location,
        capacity=room.capacity,
        color=room.color,
        description=room.description,
        is_active=room.is_active,
        created_at=room.created_at,
    )


async def _get_room(room_id: str, tenant_id: str, db: AsyncSession) -> MeetingRoom:
    result = await db.execute(
        select(MeetingRoom).where(
            MeetingRoom.id == room_id,
            MeetingRoom.tenant_id == tenant_id,
        )
    )
    room = result.scalar_one_or_none()
    if room is None:
        raise HTTPException(status_code=404, detail="Meeting room not found")
    return room


@router.get("", response_model=list[MeetingRoomResponse])
async def list_rooms(
    active_only: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(MeetingRoom).where(MeetingRoom.tenant_id == user.tenant_id).order_by(MeetingRoom.name)
    if active_only:
        stmt = stmt.where(MeetingRoom.is_active.is_(True))
    result = await db.execute(stmt)
    return [_out(room) for room in result.scalars().all()]


@router.post("", status_code=201, response_model=MeetingRoomResponse)
async def create_room(
    body: MeetingRoomCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = MeetingRoom(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        location=body.location,
        capacity=body.capacity,
        color=body.color,
        description=body.description,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return _out(room)


@router.patch("/{room_id}", response_model=MeetingRoomResponse)
async def update_room(
    room_id: str,
    body: MeetingRoomUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room(room_id, user.tenant_id, db)

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be empty")
        room.name = name
    if body.location is not None:
        room.location = body.location
    if body.capacity is not None:
        room.capacity = body.capacity
    if body.color is not None:
        room.color = body.color
    if body.description is not None:
        room.description = body.description
    if body.is_active is not None:
        room.is_active = body.is_active

    await db.commit()
    await db.refresh(room)
    return _out(room)


@router.delete("/{room_id}", status_code=204)
async def delete_room(
    room_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room(room_id, user.tenant_id, db)
    await db.delete(room)
    await db.commit()
