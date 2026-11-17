from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from jose import JWTError
from app.services import accounts, login_throttle
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    is_readonly_account,
    token_predates_password_change,
    verify_password_async,
)
from app.services.ratelimit import client_ip

router = APIRouter(prefix="/auth", tags=["auth"])
_limiter = Limiter(key_func=client_ip)

# ユーザーが見つからないときも同じだけ時間をかけて照合する(応答時間でアカウントの有無が分からないように)。
_DUMMY_HASH = "$2b$12$KIXjMCBz9g8Zv1RRi.QjGOm8iI2u1RjwCZ7HXSRXHBrz8fDZWJGhK"


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
        return accounts.check_slug_not_reserved(v)

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
@_limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.tenant_slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already taken")
    # メールアドレスはログイン ID。既存ユーザー(どのテナントでも)と重ねさせない。
    if await accounts.email_in_use(db, body.email):
        raise HTTPException(status_code=409, detail=accounts.EMAIL_TAKEN_DETAIL)

    tenant = Tenant(slug=body.tenant_slug, name=body.tenant_name)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=accounts.normalize_email(body.email),
        hashed_password=await hash_password_async(body.password),
        role="admin",
    )
    db.add(user)

    await db.commit()

    return TokenResponse(
        access_token=create_access_token(tenant.id, user.id, user.role),
        refresh_token=create_refresh_token(tenant.id, user.id),
        tenant_slug=body.tenant_slug,
        role=user.role,
    )


async def _check_password(key: str, user: User | None, password: str) -> None:
    """パスワードを照合する。失敗は ID ごとに数え、続けば 429 で一時的に止める。"""
    candidate_hash = user.hashed_password if user else _DUMMY_HASH
    try:
        password_ok = await verify_password_async(password, candidate_hash)
    except ValueError:
        password_ok = False
    if user is None or not password_ok:
        login_throttle.record_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    login_throttle.reset(key)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """利用者（Customer）ログイン — email + password, role=admin/staff"""
    key = login_throttle.key_for("email", body.email)
    login_throttle.check(key)
    user = await accounts.find_login_user(db, body.email, ("admin", "staff", "superadmin"))
    await _check_password(key, user, body.password)
    if user.role not in ("admin", "staff", "superadmin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Use the appropriate login endpoint for your role")

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_result.scalar_one_or_none()

    return TokenResponse(
        access_token=create_access_token(user.tenant_id or "", user.id, user.role, readonly=is_readonly_account(user.email)),
        refresh_token=create_refresh_token(user.tenant_id or "", user.id),
        tenant_slug=tenant.slug if tenant else "",
        role=user.role,
    )


@router.post("/operator/login", response_model=TokenResponse)
async def operator_login(body: OperatorLoginRequest, db: AsyncSession = Depends(get_db)):
    """運営（Operator）ログイン — email + password, role=operator のみ"""
    key = login_throttle.key_for("email", body.email)
    login_throttle.check(key)
    user = await accounts.find_login_user(db, body.email, ("operator",))
    await _check_password(key, user, body.password)
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
    key = login_throttle.key_for("reseller", body.reseller_id)
    login_throttle.check(key)
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.slug == body.reseller_id.strip(), Tenant.is_reseller == True)
    )
    tenant = tenant_result.scalar_one_or_none()

    user = None
    if tenant is not None:
        # 代理店テナントに reseller ユーザーが複数いても 500 にせず、古い順の先頭に決める。
        user = (await db.execute(
            select(User)
            .where(User.tenant_id == tenant.id, User.role == "reseller")
            .order_by(User.created_at, User.id)
            .limit(1)
        )).scalars().first()
    await _check_password(key, user, body.password)

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
    # パスワード変更より前に発行された refresh トークンでは更新させない。
    if token_predates_password_change(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="パスワードが変更されたため、もう一度ログインしてください",
        )

    tenant = None
    if user.tenant_id:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()

    return TokenResponse(
        access_token=create_access_token(user.tenant_id or "", user.id, user.role, readonly=is_readonly_account(user.email)),
        refresh_token=create_refresh_token(user.tenant_id or "", user.id),
        tenant_slug=tenant.slug if tenant else "",
        role=user.role,
    )
