"""代理店（Reseller）専用 API — 自管理テナント群の管理"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
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
    current_user: User = Depends(require_reseller_or_operator()),
    db: AsyncSession = Depends(get_db),
):
    reseller_tid = _get_reseller_tenant_id(current_user)
    result = await db.execute(
        select(Tenant)
        .where(Tenant.reseller_id == reseller_tid, Tenant.is_reseller == False)
        .order_by(Tenant.created_at.desc())
    )
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

    result = await db.execute(
        select(Device).where(Device.tenant_id.in_(customer_ids)).order_by(Device.created_at.desc())
    )
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


# ── Users ──────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_reseller_users(
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

    result = await db.execute(
        select(User).where(User.tenant_id.in_(customer_ids), User.role != "kiosk")
        .order_by(User.created_at.desc())
    )
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
