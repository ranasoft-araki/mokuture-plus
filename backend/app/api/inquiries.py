"""Inquiry endpoints — the mokuture common contact form.

Public submission (no auth, rate-limited) is used by the kiosk お断り screen's
form (/{slug}/inquiry) when a tenant has not configured an external form URL.
Admins list/manage the received inquiries from the management console.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/inquiries", tags=["inquiries"])
_limiter = Limiter(key_func=get_remote_address)

_ALLOWED_STATES = {"new", "read", "archived"}


class InquiryCreate(BaseModel):
    name: str
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    message: str

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("お名前を入力してください")
        return v[:255]

    @field_validator("message")
    @classmethod
    def message_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("お問い合わせ内容を入力してください")
        return v[:4000]


class InquiryOut(BaseModel):
    id: str
    name: str
    company: str | None
    email: str | None
    phone: str | None
    message: str
    state: str
    created_at: str

    model_config = {"from_attributes": True}


def _out(r: Inquiry) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "company": r.company,
        "email": r.email,
        "phone": r.phone,
        "message": r.message,
        "state": r.state,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


@router.post("/public/{tenant_slug}", status_code=201)
@_limiter.limit("10/minute")
async def create_inquiry_public(
    request: Request,
    tenant_slug: str,
    body: InquiryCreate,
    db: AsyncSession = Depends(get_db),
):
    """公開の問い合わせ送信。テナントを slug で解決して保存する（認証不要）。"""
    result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="テナントが見つかりません")

    inquiry = Inquiry(
        tenant_id=tenant.id,
        name=body.name,
        company=(body.company or "").strip()[:255] or None,
        email=(body.email or "").strip()[:255] or None,
        phone=(body.phone or "").strip()[:64] or None,
        message=body.message,
    )
    db.add(inquiry)
    await db.commit()
    return {"ok": True}


@router.get("", response_model=list[InquiryOut])
async def list_inquiries(
    state: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Inquiry)
        .where(Inquiry.tenant_id == user.tenant_id)
        .order_by(Inquiry.created_at.desc())
    )
    if state:
        q = q.where(Inquiry.state == state)
    if date_from:
        q = q.where(func.date(Inquiry.created_at) >= date_from)
    if date_to:
        q = q.where(func.date(Inquiry.created_at) <= date_to)
    result = await db.execute(q)
    return [_out(r) for r in result.scalars()]


class InquiryUpdate(BaseModel):
    state: str


@router.patch("/{inquiry_id}", response_model=InquiryOut)
async def update_inquiry(
    inquiry_id: str,
    body: InquiryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.state not in _ALLOWED_STATES:
        raise HTTPException(status_code=422, detail=f"state must be one of {_ALLOWED_STATES}")
    result = await db.execute(select(Inquiry).where(Inquiry.id == inquiry_id))
    inquiry = result.scalar_one_or_none()
    if inquiry is None or inquiry.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    inquiry.state = body.state
    await db.commit()
    await db.refresh(inquiry)
    return _out(inquiry)


@router.delete("/{inquiry_id}", status_code=204)
async def delete_inquiry(
    inquiry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Inquiry).where(Inquiry.id == inquiry_id))
    inquiry = result.scalar_one_or_none()
    if inquiry is None or inquiry.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    await db.delete(inquiry)
    await db.commit()
