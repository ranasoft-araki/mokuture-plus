"""代理店（Reseller）専用 API — 自管理テナント群の管理"""
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.middleware.tenant import require_reseller_or_operator
from app.models.tenant import Tenant
from app.models.user import User
from app.models.device import Device
from app.models.reception import ReceptionLog
from app.services.auth import hash_password

router = APIRouter(prefix="/reseller", tags=["reseller"])


def _get_reseller_tenant_id(user: User) -> str:
    if not user.tenant_id:
        raise HTTPException(status_code=403, detail="No reseller tenant associated")
    return user.tenant_id


# ── Stats ──────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_reseller_stats(
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)

    customer_q = select(Tenant).where(Tenant.reseller_id == reseller_tid, Tenant.is_reseller == False)
    customer_ids_result = await db.execute(customer_q)
    customer_tenants = customer_ids_result.scalars().all()
    customer_ids = [t.id for t in customer_tenants]

    device_count = 0
    user_count = 0
    reception_count = 0
    if customer_ids:
        device_count = (await db.execute(
            select(func.count()).select_from(Device).where(Device.tenant_id.in_(customer_ids))
        )).scalar()
        user_count = (await db.execute(
            select(func.count()).select_from(User).where(User.tenant_id.in_(customer_ids))
        )).scalar()
        reception_count = (await db.execute(
            select(func.count()).select_from(ReceptionLog).where(ReceptionLog.tenant_id.in_(customer_ids))
        )).scalar()

    return {
        "customer_count": len(customer_tenants),
        "device_count": device_count,
        "user_count": user_count,
        "reception_count": reception_count,
    }


# ── Customers ──────────────────────────────────────────────────────────────

@router.get("/customers")
async def list_customers(
    q: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)
    stmt = select(Tenant).where(Tenant.reseller_id == reseller_tid, Tenant.is_reseller == False)
    if q:
        stmt = stmt.where(Tenant.name.ilike(f"%{q}%") | Tenant.slug.ilike(f"%{q}%"))
    stmt = stmt.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    tenants = result.scalars().all()
    return [
        {
            "id": t.id,
            "slug": t.slug,
            "name": t.name,
            "brand_color": t.brand_color,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tenants
    ]


class CreateCustomerRequest(BaseModel):
    name: str
    slug: str
    admin_email: str
    admin_password: str

    @field_validator("slug")
    @classmethod
    def slug_valid(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9\-]{3,64}$", v):
            raise ValueError("Slug must be 3-64 lowercase alphanumeric or hyphens")
        return v


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    body: CreateCustomerRequest,
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)

    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already taken")

    tenant = Tenant(slug=body.slug, name=body.name, reseller_id=reseller_tid)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=body.admin_email,
        hashed_password=hash_password(body.admin_password),
        role="admin",
    )
    db.add(user)

    try:
        from app.services.webpush import generate_vapid_keys
        from app.services.crypto import encrypt_dict
        from app.models.notification import NotificationSetting
        priv_b64, pub_b64 = generate_vapid_keys()
        vapid_setting = NotificationSetting(
            tenant_id=tenant.id,
            type="webpush",
            config_json=encrypt_dict({"private_key": priv_b64, "public_key": pub_b64}),
        )
        db.add(vapid_setting)
    except Exception:
        pass

    await db.commit()
    return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name}


@router.delete("/customers/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    tenant_id: str,
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.reseller_id == reseller_tid)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Customer not found")
    await db.delete(tenant)
    await db.commit()


# ── Devices ────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_reseller_devices(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)
    customer_result = await db.execute(
        select(Tenant.id).where(Tenant.reseller_id == reseller_tid, Tenant.is_reseller == False)
    )
    customer_ids = [row[0] for row in customer_result.all()]
    if not customer_ids:
        return []

    if tenant_id and tenant_id in customer_ids:
        filter_ids = [tenant_id]
    elif tenant_id:
        return []
    else:
        filter_ids = customer_ids

    stmt = select(Device).where(Device.tenant_id.in_(filter_ids))
    if q:
        stmt = stmt.where(Device.name.ilike(f"%{q}%"))
    if status == "online":
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        stmt = stmt.where(Device.last_seen_at >= cutoff)
    elif status == "offline":
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        stmt = stmt.where((Device.last_seen_at == None) | (Device.last_seen_at < cutoff))
    stmt = stmt.order_by(Device.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    devices = result.scalars().all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "tenant_id": d.tenant_id,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
        }
        for d in devices
    ]


# ── Reception Logs ────────────────────────────────────────────────────────

class ResellerReceptionItem(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    visitor_name: str
    company: str | None
    staff: str | None
    purpose: str | None
    method: str | None
    state: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/reception", response_model=list[ResellerReceptionItem])
async def list_reseller_reception(
    tenant_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)
    customer_result = await db.execute(
        select(Tenant.id).where(Tenant.reseller_id == reseller_tid, Tenant.is_reseller == False)
    )
    customer_ids = [row[0] for row in customer_result.all()]
    if not customer_ids:
        return []

    if tenant_id and tenant_id in customer_ids:
        filter_ids = [tenant_id]
    elif tenant_id:
        return []
    else:
        filter_ids = customer_ids

    stmt = (
        select(ReceptionLog, Tenant.name.label("tenant_name"))
        .join(Tenant, ReceptionLog.tenant_id == Tenant.id)
        .where(ReceptionLog.tenant_id.in_(filter_ids))
    )
    if q:
        stmt = stmt.where(
            ReceptionLog.visitor_name.ilike(f"%{q}%") | ReceptionLog.company.ilike(f"%{q}%")
        )
    if status:
        stmt = stmt.where(ReceptionLog.state == status)
    if date_from:
        stmt = stmt.where(ReceptionLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(ReceptionLog.created_at <= date_to + " 23:59:59")
    stmt = stmt.order_by(ReceptionLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()
    return [
        ResellerReceptionItem(
            id=log.id,
            tenant_id=log.tenant_id,
            tenant_name=tenant_name,
            visitor_name=log.visitor_name,
            company=log.company,
            staff=log.staff,
            purpose=log.purpose,
            method=log.method,
            state=log.state,
            created_at=log.created_at,
        )
        for log, tenant_name in rows
    ]


# ── Users ──────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_reseller_users(
    tenant_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)
    customer_result = await db.execute(
        select(Tenant.id).where(Tenant.reseller_id == reseller_tid, Tenant.is_reseller == False)
    )
    customer_ids = [row[0] for row in customer_result.all()]
    if not customer_ids:
        return []

    if tenant_id and tenant_id in customer_ids:
        filter_ids = [tenant_id]
    elif tenant_id:
        return []
    else:
        filter_ids = customer_ids

    stmt = select(User).where(User.tenant_id.in_(filter_ids), User.role != "kiosk")
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "tenant_id": u.tenant_id,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]
