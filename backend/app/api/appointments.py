"""Visitor appointment management — admin JWT required."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.room import MeetingRoom
from app.models.user import User
from app.models.visitor_appointment import VisitorAppointment

router = APIRouter(prefix="/appointments", tags=["appointments"])


class AppointmentCreate(BaseModel):
    visitor_name: str
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    meeting_room_id: Optional[str] = None
    scheduled_at: datetime
    notes: Optional[str] = None
    duration_minutes: Optional[int] = None

    @field_validator("visitor_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("visitor_name must not be empty")
        return v


class AppointmentUpdate(BaseModel):
    visitor_name: Optional[str] = None
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    meeting_room_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    duration_minutes: Optional[int] = None


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


class AppointmentResponse(BaseModel):
    id: str
    visitor_name: str
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    scheduled_at: str
    token: str
    status: str
    notes: Optional[str] = None
    meeting_room_id: Optional[str] = None
    meeting_room: Optional[MeetingRoomResponse] = None
    duration_minutes: Optional[int] = None
    created_at: Optional[str] = None


def _room_out(room: Optional[MeetingRoom]) -> Optional[dict]:
    if room is None:
        return None
    return {
        "id": room.id,
        "tenant_id": room.tenant_id,
        "name": room.name,
        "location": room.location,
        "capacity": room.capacity,
        "color": room.color,
        "description": room.description,
        "is_active": room.is_active,
        "created_at": room.created_at,
    }


def _out(appt: VisitorAppointment, room: Optional[MeetingRoom] = None) -> dict:
    return {
        "id": appt.id,
        "visitor_name": appt.visitor_name,
        "company": appt.company,
        "purpose": appt.purpose,
        "staff": appt.staff,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "token": appt.token,
        "status": appt.status,
        "notes": appt.notes,
        "meeting_room_id": appt.meeting_room_id,
        "meeting_room": _room_out(room),
        "duration_minutes": appt.duration_minutes,
        "created_at": appt.created_at.isoformat() if appt.created_at else None,
    }


async def _ensure_room_belongs_to_tenant(
    room_id: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> None:
    if room_id is None:
        return
    result = await db.execute(
        select(MeetingRoom.id).where(
            MeetingRoom.id == room_id,
            MeetingRoom.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Meeting room not found")


@router.get("", response_model=list[AppointmentResponse])
async def list_appointments(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(VisitorAppointment, MeetingRoom)
        .outerjoin(
            MeetingRoom,
            and_(
                VisitorAppointment.meeting_room_id == MeetingRoom.id,
                MeetingRoom.tenant_id == user.tenant_id,
            ),
        )
        .where(VisitorAppointment.tenant_id == user.tenant_id)
        .order_by(VisitorAppointment.scheduled_at)
    )
    if status:
        stmt = stmt.where(VisitorAppointment.status == status)
    if date_from:
        try:
            stmt = stmt.where(VisitorAppointment.scheduled_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(VisitorAppointment.scheduled_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    result = await db.execute(stmt)
    return [_out(appt, room) for appt, room in result.all()]


@router.post("", status_code=201, response_model=AppointmentResponse)
async def create_appointment(
    body: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scheduled_at = body.scheduled_at
    if scheduled_at.tzinfo is not None:
        scheduled_at = scheduled_at.replace(tzinfo=None)
    await _ensure_room_belongs_to_tenant(body.meeting_room_id, user.tenant_id, db)

    appt = VisitorAppointment(
        tenant_id=user.tenant_id,
        visitor_name=body.visitor_name.strip(),
        company=body.company,
        purpose=body.purpose,
        staff=body.staff,
        meeting_room_id=body.meeting_room_id,
        scheduled_at=scheduled_at,
        notes=body.notes,
        duration_minutes=body.duration_minutes,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    room = None
    if appt.meeting_room_id is not None:
        room_result = await db.execute(select(MeetingRoom).where(MeetingRoom.id == appt.meeting_room_id))
        room = room_result.scalar_one_or_none()
    return _out(appt, room)


@router.get("/{appt_id}", response_model=AppointmentResponse)
async def get_appointment(
    appt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitorAppointment, MeetingRoom)
        .outerjoin(
            MeetingRoom,
            and_(
                VisitorAppointment.meeting_room_id == MeetingRoom.id,
                MeetingRoom.tenant_id == user.tenant_id,
            ),
        )
        .where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appt, room = row
    return _out(appt, room)


@router.patch("/{appt_id}", response_model=AppointmentResponse)
async def update_appointment(
    appt_id: str,
    body: AppointmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if body.visitor_name is not None:
        appt.visitor_name = body.visitor_name.strip()
    if body.company is not None:
        appt.company = body.company
    if body.purpose is not None:
        appt.purpose = body.purpose
    if body.staff is not None:
        appt.staff = body.staff
    if "meeting_room_id" in body.model_fields_set:
        await _ensure_room_belongs_to_tenant(body.meeting_room_id, user.tenant_id, db)
        appt.meeting_room_id = body.meeting_room_id
    if body.scheduled_at is not None:
        sched = body.scheduled_at
        if sched.tzinfo is not None:
            sched = sched.replace(tzinfo=None)
        appt.scheduled_at = sched
    if body.notes is not None:
        appt.notes = body.notes
    if body.status is not None:
        appt.status = body.status
    if body.duration_minutes is not None:
        appt.duration_minutes = body.duration_minutes

    await db.commit()
    await db.refresh(appt)
    room = None
    if appt.meeting_room_id is not None:
        room_result = await db.execute(select(MeetingRoom).where(MeetingRoom.id == appt.meeting_room_id))
        room = room_result.scalar_one_or_none()
    return _out(appt, room)


@router.delete("/{appt_id}", status_code=204)
async def delete_appointment(
    appt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    await db.delete(appt)
    await db.commit()
