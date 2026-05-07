"""運営（Operator）専用 API — クロステナント全権管理"""
import csv
import io
from datetime import datetime, timezone, timedelta, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
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

class DailyStatItem(BaseModel):
    date: str
    count: int

class DailyStatsResponse(BaseModel):
    data: list[DailyStatItem]


@router.get("/reception/daily-stats", response_model=DailyStatsResponse)
async def get_operator_reception_daily_stats(
    days: int = Query(14, ge=1, le=30),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    dates = [(today - timedelta(days=i)) for i in range(days - 1, -1, -1)]
    result = await db.execute(
        select(
            func.date(ReceptionLog.created_at).label("day"),
            func.count().label("cnt"),
        )
        .where(ReceptionLog.created_at >= str(dates[0]))
        .group_by("day")
        .order_by("day")
    )
    rows = {str(r.day): r.cnt for r in result.all()}
    data = [DailyStatItem(date=str(d), count=rows.get(str(d), 0)) for d in dates]
    return DailyStatsResponse(data=data)


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

    online_cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    online_device_count = (await db.execute(
        select(func.count()).select_from(Device).where(Device.last_seen_at >= online_cutoff)
    )).scalar()

    suspended_tenant_count = (await db.execute(
        select(func.count()).select_from(Tenant).where(Tenant.is_reseller == False, Tenant.is_suspended == True)
    )).scalar()

    today_utc = datetime.now(timezone.utc).date()
    reception_today = (await db.execute(
        select(func.count()).select_from(ReceptionLog).where(
            func.date(ReceptionLog.created_at) == today_utc
        )
    )).scalar()

    week_start = today_utc - timedelta(days=today_utc.weekday())
    reception_this_week = (await db.execute(
        select(func.count()).select_from(ReceptionLog).where(
            func.date(ReceptionLog.created_at) >= week_start
        )
    )).scalar()

    active_tenant_count = (await db.execute(
        select(func.count()).select_from(
            select(Device.tenant_id).join(Tenant, Device.tenant_id == Tenant.id).where(
                Tenant.is_reseller == False
            ).group_by(Device.tenant_id).subquery()
        )
    )).scalar()

    today_start_dt = datetime(today_utc.year, today_utc.month, today_utc.day, tzinfo=timezone.utc)
    reception_today_unread = (await db.execute(
        select(func.count()).select_from(ReceptionLog).where(
            ReceptionLog.state == "received",
            ReceptionLog.created_at >= today_start_dt,
        )
    )).scalar()

    return {
        "tenant_count": tenant_count,
        "reseller_count": reseller_count,
        "user_count": user_count,
        "device_count": device_count,
        "reception_count": reception_count,
        "online_device_count": online_device_count,
        "suspended_tenant_count": suspended_tenant_count,
        "reception_today": reception_today,
        "reception_this_week": reception_this_week,
        "active_tenant_count": active_tenant_count,
        "reception_today_unread": reception_today_unread,
    }


# ── Tenants ────────────────────────────────────────────────────────────────

@router.get("/tenants")
async def list_tenants(
    reseller_id: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    base_stmt = select(Tenant).where(Tenant.is_reseller == False)
    if reseller_id:
        base_stmt = base_stmt.where(Tenant.reseller_id == reseller_id)
    if q:
        base_stmt = base_stmt.where(
            Tenant.name.ilike(f"%{q}%") | Tenant.slug.ilike(f"%{q}%")
        )
    if status == "suspended":
        base_stmt = base_stmt.where(Tenant.is_suspended == True)
    elif status == "active":
        base_stmt = base_stmt.where(Tenant.is_suspended == False)

    total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = total_result.scalar() or 0

    stmt = base_stmt.order_by(Tenant.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    tenants = result.scalars().all()

    import math
    total_pages = math.ceil(total / page_size) if page_size else 1

    tenant_ids = [t.id for t in tenants]
    device_counts: dict[str, int] = {}
    reception_counts: dict[str, int] = {}
    if tenant_ids:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        dc_rows = (await db.execute(
            select(Device.tenant_id, func.count(Device.id))
            .where(Device.tenant_id.in_(tenant_ids))
            .group_by(Device.tenant_id)
        )).all()
        device_counts = {row[0]: row[1] for row in dc_rows}
        rc_rows = (await db.execute(
            select(ReceptionLog.tenant_id, func.count(ReceptionLog.id))
            .where(
                ReceptionLog.tenant_id.in_(tenant_ids),
                ReceptionLog.created_at >= today_start,
            )
            .group_by(ReceptionLog.tenant_id)
        )).all()
        reception_counts = {row[0]: row[1] for row in rc_rows}

    return {
        "items": [
            {
                "id": t.id,
                "slug": t.slug,
                "name": t.name,
                "reseller_id": t.reseller_id,
                "brand_color": t.brand_color,
                "is_suspended": t.is_suspended,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "operator_notes": t.operator_notes,
                "device_count": device_counts.get(t.id, 0),
                "reception_today": reception_counts.get(t.id, 0),
            }
            for t in tenants
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


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


class SuspendTenantRequest(BaseModel):
    suspended: bool
    reason: str | None = None


@router.patch("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: str,
    body: SuspendTenantRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.is_suspended = body.suspended
    await db.commit()
    return {"ok": True, "tenant_id": tenant_id, "is_suspended": tenant.is_suspended}


class UpdateNotesRequest(BaseModel):
    notes: str


@router.patch("/tenants/{tenant_id}/notes")
async def update_tenant_notes(
    tenant_id: str,
    body: UpdateNotesRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.operator_notes = body.notes if body.notes else None
    await db.commit()
    return {"ok": True}


class UpdateResellerRequest(BaseModel):
    reseller_id: str | None = None  # None = remove from reseller (make direct)


@router.patch("/tenants/{tenant_id}/reseller")
async def update_tenant_reseller(
    tenant_id: str,
    body: UpdateResellerRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(404, "Tenant not found")
    if body.reseller_id is not None:
        # verify reseller exists and is actually a reseller
        r = await db.execute(select(Tenant).where(Tenant.id == body.reseller_id, Tenant.is_reseller == True))
        if r.scalar_one_or_none() is None:
            raise HTTPException(400, "Invalid reseller")
    tenant.reseller_id = body.reseller_id
    await db.commit()
    return {"ok": True}


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

    # Safety guard: block if active devices exist
    device_count = (await db.execute(
        select(func.count()).select_from(Device).where(Device.tenant_id == tenant_id)
    )).scalar() or 0
    if device_count > 0:
        raise HTTPException(
            status_code=400,
            detail="デバイスが存在するため削除できません（先にデバイスを削除してください）",
        )

    # Safety guard: block if reception logs exist in the last 30 days
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
    log_count = (await db.execute(
        select(func.count()).select_from(ReceptionLog).where(
            ReceptionLog.tenant_id == tenant_id,
            ReceptionLog.created_at >= cutoff_30d,
        )
    )).scalar() or 0
    if log_count > 0:
        raise HTTPException(
            status_code=400,
            detail="受付ログが残っているため削除できません（ログをエクスポート・削除してから再試行してください）",
        )

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
        raise HTTPException(status_code=404, detail="このテナントに管理者ユーザーがいません")

    from app.config import settings as _settings
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": admin_user.id,
        "tenant_id": tenant_id,
        "role": "admin",
        "exp": expire,
        "type": "access",
        "proxy": True,
    }
    from jose import jwt as _jwt
    short_token = _jwt.encode(payload, _settings.jwt_secret_key, algorithm=_settings.jwt_algorithm)

    return {
        "access_token": short_token,
        "tenant_slug": tenant.slug,
        "tenant_name": tenant.name,
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

    reseller_ids = [r.id for r in resellers]
    customer_counts: dict[str, int] = {}
    device_counts: dict[str, int] = {}
    if reseller_ids:
        # Count customer tenants per reseller (is_reseller = false)
        cc_rows = (await db.execute(
            select(Tenant.reseller_id, func.count(Tenant.id))
            .where(Tenant.reseller_id.in_(reseller_ids), Tenant.is_reseller == False)
            .group_by(Tenant.reseller_id)
        )).all()
        customer_counts = {row[0]: row[1] for row in cc_rows}

        # Count devices across all customer tenants of each reseller
        dc_rows = (await db.execute(
            select(Tenant.reseller_id, func.count(Device.id))
            .join(Device, Device.tenant_id == Tenant.id)
            .where(Tenant.reseller_id.in_(reseller_ids), Tenant.is_reseller == False)
            .group_by(Tenant.reseller_id)
        )).all()
        device_counts = {row[0]: row[1] for row in dc_rows}

    return [
        {
            "id": r.id,
            "slug": r.slug,
            "name": r.name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "customer_count": customer_counts.get(r.id, 0),
            "device_count": device_counts.get(r.id, 0),
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

    # Safety guard: block if customer tenants exist under this reseller
    customer_count = (await db.execute(
        select(func.count()).select_from(Tenant).where(
            Tenant.reseller_id == reseller.id,
            Tenant.is_reseller == False,
        )
    )).scalar() or 0
    if customer_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"顧客テナントが{customer_count}件存在するため削除できません（先に顧客テナントを別の代理店に移動または削除してください）",
        )

    await db.delete(reseller)
    await db.commit()


# ── Users ──────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    tenant_id: Optional[str] = None,
    role: Optional[str] = None,
    reseller_id: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    base_stmt = select(User).where(User.role != "kiosk")
    if tenant_id:
        base_stmt = base_stmt.where(User.tenant_id == tenant_id)
    if role:
        base_stmt = base_stmt.where(User.role == role)
    if reseller_id:
        base_stmt = base_stmt.join(Tenant, User.tenant_id == Tenant.id).where(Tenant.reseller_id == reseller_id)
    if q:
        base_stmt = base_stmt.where(User.email.ilike(f"%{q}%"))

    total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = total_result.scalar() or 0

    stmt = base_stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    users = result.scalars().all()

    import math
    total_pages = math.ceil(total / page_size) if page_size else 1

    return {
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "tenant_id": u.tenant_id,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


class CreateOperatorUserRequest(BaseModel):
    tenant_id: str
    email: str
    password: str
    role: str = "staff"  # admin | staff


class UpdateOperatorUserRequest(BaseModel):
    role: str


@router.patch("/users/{user_id}")
async def update_operator_user(
    user_id: str,
    body: UpdateOperatorUserRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    allowed_roles = {"admin", "staff", "reseller", "kiosk"}
    if body.role not in allowed_roles:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(sorted(allowed_roles))}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "operator":
        raise HTTPException(status_code=403, detail="Cannot change role of an operator user")

    user.role = body.role
    await db.commit()
    await db.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operator_user(
    user_id: str,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role in ("operator", "superadmin"):
        raise HTTPException(status_code=403, detail="Cannot delete operator or superadmin users")
    await db.delete(user)
    await db.commit()


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_operator_user(
    body: CreateOperatorUserRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    if body.role not in {"admin", "staff"}:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'staff'")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == body.tenant_id))
    if not tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tenant not found")

    existing = await db.execute(
        select(User).where(User.email == body.email, User.tenant_id == body.tenant_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already exists in this tenant")

    new_user = User(
        tenant_id=body.tenant_id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return {
        "id": new_user.id,
        "email": new_user.email,
        "role": new_user.role,
        "tenant_id": new_user.tenant_id,
        "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
    }


# ── Devices ────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_all_devices(
    tenant_id: Optional[str] = None,
    reseller_id: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    import math

    online_cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)

    # Build joined query so we can fetch tenant + reseller names
    tenant_alias = Tenant.__table__.alias("t")
    reseller_alias = Tenant.__table__.alias("r")

    base_stmt = (
        select(
            Device,
            tenant_alias.c.name.label("tenant_name"),
            reseller_alias.c.name.label("reseller_name"),
        )
        .join(tenant_alias, Device.tenant_id == tenant_alias.c.id)
        .outerjoin(reseller_alias, tenant_alias.c.reseller_id == reseller_alias.c.id)
    )

    if tenant_id:
        base_stmt = base_stmt.where(Device.tenant_id == tenant_id)
    if reseller_id:
        base_stmt = base_stmt.where(tenant_alias.c.reseller_id == reseller_id)
    if status == "online":
        base_stmt = base_stmt.where(
            Device.last_seen_at.is_not(None),
            Device.last_seen_at >= online_cutoff,
        )
    elif status == "offline":
        base_stmt = base_stmt.where(
            (Device.last_seen_at == None) | (Device.last_seen_at < online_cutoff)
        )
    if q:
        base_stmt = base_stmt.where(
            Device.name.ilike(f"%{q}%") | Device.location.ilike(f"%{q}%")
        )

    # Count total
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    total_pages = math.ceil(total / page_size) if page_size else 1

    # Paginated results
    stmt = base_stmt.order_by(Device.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for row in rows:
        d = row[0]
        t_name = row[1]
        r_name = row[2]
        is_online = (
            d.last_seen_at is not None and d.last_seen_at >= online_cutoff
        )
        items.append({
            "id": d.id,
            "name": d.name,
            "location": d.location,
            "tenant_id": d.tenant_id,
            "tenant_name": t_name,
            "reseller_name": r_name,
            "last_seen_at": d.last_seen_at.isoformat() + "Z" if d.last_seen_at else None,
            "is_online": is_online,
            "pin_code": d.pin_code if hasattr(d, "pin_code") else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


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
    method: Optional[str] = Query(None),
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
    if method:
        stmt = stmt.where(ReceptionLog.method == method)
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


class UpdateOperatorReceptionRequest(BaseModel):
    state: str | None = None
    staff_notes: str | None = None


@router.patch("/reception/{log_id}", response_model=OperatorReceptionItem)
async def update_operator_reception(
    log_id: str,
    body: UpdateOperatorReceptionRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReceptionLog, Tenant.name.label("tenant_name"))
        .join(Tenant, ReceptionLog.tenant_id == Tenant.id)
        .where(ReceptionLog.id == log_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Reception log not found")
    log, tenant_name = row
    if body.state is not None:
        log.state = body.state
    if body.staff_notes is not None:
        log.staff_notes = body.staff_notes
    await db.commit()
    await db.refresh(log)
    return OperatorReceptionItem(
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


class BulkDeleteReceptionRequest(BaseModel):
    ids: list[str]
    tenant_id: str | None = None

    @field_validator("ids")
    @classmethod
    def ids_max(cls, v: list[str]) -> list[str]:
        if len(v) > 500:
            raise ValueError("ids must have at most 500 items")
        return v


@router.delete("/reception/bulk")
async def bulk_delete_operator_reception(
    body: BulkDeleteReceptionRequest,
    _: User = Depends(require_operator()),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(ReceptionLog).where(ReceptionLog.id.in_(body.ids))
    if body.tenant_id:
        stmt = stmt.where(ReceptionLog.tenant_id == body.tenant_id)
    result = await db.execute(stmt)
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/reception/export.csv")
async def export_operator_reception_csv(
    tenant_id: Optional[str] = Query(None),
    reseller_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
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
    stmt = stmt.order_by(ReceptionLog.created_at.desc())
    result = await db.execute(stmt)
    rows = result.all()

    output = io.StringIO()
    output.write("﻿")  # UTF-8 BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["日時", "テナント名", "訪問者名", "会社名", "担当者", "目的", "受付方法", "ステータス", "スタッフメモ"])
    for log, tenant_name in rows:
        writer.writerow([
            log.created_at.isoformat() if log.created_at else "",
            tenant_name,
            log.visitor_name,
            log.company or "",
            log.staff or "",
            log.purpose or "",
            log.method or "",
            log.state or "",
            log.staff_notes or "",
        ])
    output.seek(0)

    filename = f"reception_{datetime.today().strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
