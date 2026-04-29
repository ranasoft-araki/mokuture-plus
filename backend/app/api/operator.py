"""運営（Operator）専用 API — クロステナント全権管理"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.middleware.tenant import require_operator
from app.models.tenant import Tenant
from app.models.user import User
from app.models.device import Device
from app.models.reception import ReceptionLog
from app.services.auth import hash_password, create_access_token, create_refresh_token

router = APIRouter(prefix="/operator", tags=["operator"])


# ── Stats ──────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_operator_stats(
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    tenant_count = (await db.execute(select(func.count()).select_from(Tenant).where(Tenant.is_reseller == False))).scalar()
    reseller_count = (await db.execute(select(func.count()).select_from(Tenant).where(Tenant.is_reseller == True))).scalar()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar()
    device_count = (await db.execute(select(func.count()).select_from(Device))).scalar()
    reception_count = (await db.execute(select(func.count()).select_from(ReceptionLog))).scalar()
    return {
        "tenant_count": tenant_count,
        "reseller_count": reseller_count,
        "user_count": user_count,
        "device_count": device_count,
        "reception_count": reception_count,
    }


# ── Tenants ────────────────────────────────────────────────────────────────

@router.get("/tenants")
async def list_tenants(
    reseller_id: Optional[str] = None,
    q: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Tenant).where(Tenant.is_reseller == False)
    if reseller_id:
        stmt = stmt.where(Tenant.reseller_id == reseller_id)
    if q:
        stmt = stmt.where(
            Tenant.name.ilike(f"%{q}%") | Tenant.slug.ilike(f"%{q}%")
        )
    stmt = stmt.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    tenants = result.scalars().all()
    return [
        {
            "id": t.id,
            "slug": t.slug,
            "name": t.name,
            "reseller_id": t.reseller_id,
            "brand_color": t.brand_color,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tenants
    ]


class CreateTenantRequest(BaseModel):
    name: str
    slug: str
    reseller_id: Optional[str] = None
    admin_email: str
    admin_password: str

    @field_validator("slug")
    @classmethod
    def slug_valid(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9\-]{3,64}$", v):
            raise ValueError("Slug must be 3-64 lowercase alphanumeric or hyphens")
        return v


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: CreateTenantRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    existing_slug = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing_slug.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already taken")

    existing_email = await db.execute(select(User).where(User.email == body.admin_email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Admin email already in use")

    if body.reseller_id:
        reseller = await db.execute(select(Tenant).where(Tenant.id == body.reseller_id, Tenant.is_reseller == True))
        if not reseller.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Reseller not found")

    tenant = Tenant(slug=body.slug, name=body.name, reseller_id=body.reseller_id)
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
    return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name, "admin_email": body.admin_email}


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(tenant)
    await db.commit()


@router.post("/tenants/{tenant_id}/proxy-login")
async def proxy_login(
    tenant_id: str,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    user_result = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.role == "admin").limit(1)
    )
    admin_user = user_result.scalar_one_or_none()
    if not admin_user:
        raise HTTPException(status_code=404, detail="No admin user found for this tenant")

    access_token = create_access_token(tenant_id=tenant_id, user_id=admin_user.id, role="admin")
    refresh_token = create_refresh_token(tenant_id=tenant_id, user_id=admin_user.id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "tenant_slug": tenant.slug,
        "role": "admin",
    }


# ── Resellers ──────────────────────────────────────────────────────────────

@router.get("/resellers")
async def list_resellers(
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Tenant).where(Tenant.is_reseller == True).order_by(Tenant.created_at.desc())
    )
    resellers = result.scalars().all()
    return [
        {
            "id": r.id,
            "slug": r.slug,
            "name": r.name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in resellers
    ]


class CreateResellerRequest(BaseModel):
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


@router.post("/resellers", status_code=status.HTTP_201_CREATED)
async def create_reseller(
    body: CreateResellerRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    existing_slug = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing_slug.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Slug already taken")

    existing_email = await db.execute(select(User).where(User.email == body.admin_email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Admin email already in use")

    tenant = Tenant(slug=body.slug, name=body.name, is_reseller=True)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=body.admin_email,
        hashed_password=hash_password(body.admin_password),
        role="reseller",
    )
    db.add(user)
    await db.commit()
    return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name, "admin_email": body.admin_email}


@router.delete("/resellers/{reseller_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reseller(
    reseller_id: str,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == reseller_id, Tenant.is_reseller == True))
    reseller = result.scalar_one_or_none()
    if not reseller:
        raise HTTPException(status_code=404, detail="Reseller not found")
    await db.delete(reseller)
    await db.commit()


# ── Users ──────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    tenant_id: Optional[str] = None,
    role: Optional[str] = None,
    reseller_id: Optional[str] = None,
    q: Optional[str] = None,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.role != "kiosk")
    if tenant_id:
        stmt = stmt.where(User.tenant_id == tenant_id)
    if role:
        stmt = stmt.where(User.role == role)
    if reseller_id:
        stmt = stmt.join(Tenant, User.tenant_id == Tenant.id).where(Tenant.reseller_id == reseller_id)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(User.created_at.desc()))
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


# ── Devices ────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_all_devices(
    tenant_id: Optional[str] = None,
    reseller_id: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Device)
    if tenant_id:
        stmt = stmt.where(Device.tenant_id == tenant_id)
    if reseller_id:
        stmt = stmt.join(Tenant, Device.tenant_id == Tenant.id).where(Tenant.reseller_id == reseller_id)
    if status == "online":
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stmt = stmt.where(Device.last_seen_at >= cutoff)
    elif status == "offline":
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        stmt = stmt.where(
            (Device.last_seen_at == None) | (Device.last_seen_at < cutoff)
        )
    if q:
        stmt = stmt.where(Device.name.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(Device.created_at.desc()))
    devices = result.scalars().all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "tenant_id": d.tenant_id,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in devices
    ]


# ── Reception Logs ────────────────────────────────────────────────────────

class OperatorReceptionItem(BaseModel):
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


@router.get("/reception", response_model=list[OperatorReceptionItem])
async def list_operator_reception(
    tenant_id: Optional[str] = Query(None),
    reseller_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    offset: int = Query(0),
    limit: int = Query(100),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ReceptionLog, Tenant.name.label("tenant_name"))
        .join(Tenant, ReceptionLog.tenant_id == Tenant.id)
    )
    if tenant_id:
        stmt = stmt.where(ReceptionLog.tenant_id == tenant_id)
    if reseller_id:
        stmt = stmt.where(Tenant.reseller_id == reseller_id)
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
        OperatorReceptionItem(
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


# ── Emergency Broadcast ────────────────────────────────────────────────────

class BroadcastRequest(BaseModel):
    message: str
    tenant_ids: Optional[list[str]] = None  # None = all tenants


@router.post("/broadcast")
async def emergency_broadcast(
    body: BroadcastRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    """全テナント（または指定テナント）のキオスク緊急メッセージを更新する。"""
    from datetime import datetime, timezone

    q = select(Tenant).where(Tenant.is_reseller == False)
    if body.tenant_ids:
        q = q.where(Tenant.id.in_(body.tenant_ids))
    result = await db.execute(q)
    tenants = result.scalars().all()

    updated = 0
    for t in tenants:
        t.kiosk_calling_message = body.message
        t.kiosk_force_update_at = datetime.now(timezone.utc)
        updated += 1

    await db.commit()
    return {"updated_tenants": updated, "message": body.message}
