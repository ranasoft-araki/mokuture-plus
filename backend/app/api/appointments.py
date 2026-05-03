"""Visitor appointment management — admin JWT required."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.user import User
from app.models.visitor_appointment import VisitorAppointment

router = APIRouter(prefix="/appointments", tags=["appointments"])


class AppointmentCreate(BaseModel):
    visitor_name: str
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    scheduled_at: datetime
    notes: Optional[str] = None

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
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[str] = None


def _out(appt: VisitorAppointment) -> dict:
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
        "created_at": appt.created_at.isoformat() if appt.created_at else None,
    }


@router.get("")
async def list_appointments(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(VisitorAppointment)
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
    return [_out(a) for a in result.scalars().all()]


@router.post("", status_code=201)
async def create_appointment(
    body: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    appt = VisitorAppointment(
        tenant_id=user.tenant_id,
        visitor_name=body.visitor_name.strip(),
        company=body.company,
        purpose=body.purpose,
        staff=body.staff,
        scheduled_at=body.scheduled_at,
        notes=body.notes,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    return _out(appt)


@router.patch("/{appt_id}")
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
    if body.scheduled_at is not None:
        appt.scheduled_at = body.scheduled_at
    if body.notes is not None:
        appt.notes = body.notes
    if body.status is not None:
        appt.status = body.status

    await db.commit()
    await db.refresh(appt)
    return _out(appt)


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
