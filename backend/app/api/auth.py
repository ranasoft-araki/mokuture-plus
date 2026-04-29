from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from jose import JWTError
from app.services.auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    tenant_name: str
    tenant_slug: str
    email: str
    password: str

    @field_validator("tenant_slug")
    @classmethod
    def slug_valid(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9\-]{3,64}$", v):
            raise ValueError("Slug must be 3-64 lowercase alphanumeric or hyphens")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class OperatorLoginRequest(BaseModel):
    email: str
    password: str


class ResellerLoginRequest(BaseModel):
    reseller_id: str  # = tenant slug of the reseller tenant
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant_slug: str = ""
    role: str = ""


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.tenant_slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already taken")

    tenant = Tenant(slug=body.tenant_slug, name=body.tenant_name)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=body.email,
        hashed_password=hash_password(body.password),
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

    return TokenResponse(
        access_token=create_access_token(tenant.id, user.id, user.role),
        refresh_token=create_refresh_token(tenant.id, user.id),
        tenant_slug=body.tenant_slug,
        role=user.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """利用者（Customer）ログイン — email + password, role=admin/staff"""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    _dummy_hash = "$2b$12$KIXjMCBz9g8Zv1RRi.QjGOm8iI2u1RjwCZ7HXSRXHBrz8fDZWJGhK"
    candidate_hash = user.hashed_password if user else _dummy_hash
    password_ok = verify_password(body.password, candidate_hash)
    if user is None or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.role not in ("admin", "staff", "superadmin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Use the appropriate login endpoint for your role")

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_result.scalar_one_or_none()

    return TokenResponse(
        access_token=create_access_token(user.tenant_id or "", user.id, user.role),
        refresh_token=create_refresh_token(user.tenant_id or "", user.id),
        tenant_slug=tenant.slug if tenant else "",
        role=user.role,
    )


@router.post("/operator/login", response_model=TokenResponse)
async def operator_login(body: OperatorLoginRequest, db: AsyncSession = Depends(get_db)):
    """運営（Operator）ログイン — email + password, role=operator のみ"""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    _dummy_hash = "$2b$12$KIXjMCBz9g8Zv1RRi.QjGOm8iI2u1RjwCZ7HXSRXHBrz8fDZWJGhK"
    candidate_hash = user.hashed_password if user else _dummy_hash
    password_ok = verify_password(body.password, candidate_hash)
    if user is None or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.role != "operator":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access only")

    return TokenResponse(
        access_token=create_access_token(user.tenant_id or "", user.id, user.role),
        refresh_token=create_refresh_token(user.tenant_id or "", user.id),
        tenant_slug="",
        role=user.role,
    )


@router.post("/reseller/login", response_model=TokenResponse)
async def reseller_login(body: ResellerLoginRequest, db: AsyncSession = Depends(get_db)):
    """代理店（Reseller）ログイン — reseller_id (= tenant slug) + password, role=reseller のみ"""
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.slug == body.reseller_id, Tenant.is_reseller == True)
    )
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user_result = await db.execute(
        select(User).where(User.tenant_id == tenant.id, User.role == "reseller")
    )
    user = user_result.scalar_one_or_none()
    _dummy_hash = "$2b$12$KIXjMCBz9g8Zv1RRi.QjGOm8iI2u1RjwCZ7HXSRXHBrz8fDZWJGhK"
    candidate_hash = user.hashed_password if user else _dummy_hash
    password_ok = verify_password(body.password, candidate_hash)
    if user is None or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(tenant.id, user.id, user.role),
        refresh_token=create_refresh_token(tenant.id, user.id),
        tenant_slug=tenant.slug,
        role=user.role,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    tenant = None
    if user.tenant_id:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()

    return TokenResponse(
        access_token=create_access_token(user.tenant_id or "", user.id, user.role),
        refresh_token=create_refresh_token(user.tenant_id or "", user.id),
        tenant_slug=tenant.slug if tenant else "",
        role=user.role,
    )
