from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth import hash_password, verify_password, create_access_token, create_refresh_token

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


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Phase 0: open registration for self-onboarding.
    # Phase 1 TODO: require invite token or restrict to superadmin to prevent unauthorized tenant creation.

    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.tenant_slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tenant slug already taken")

    tenant = Tenant(slug=body.tenant_slug, name=body.tenant_name)
    db.add(tenant)
    await db.flush()  # get tenant.id

    user = User(
        tenant_id=tenant.id,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="admin",
    )
    db.add(user)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(tenant.id, user.id, user.role),
        refresh_token=create_refresh_token(tenant.id, user.id),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    # Always run verify_password even when user is None to prevent timing-based user enumeration.
    _dummy_hash = "$2b$12$KIXjMCBz9g8Zv1RRi.QjGOm8iI2u1RjwCZ7HXSRXHBrz8fDZWJGhK"
    candidate_hash = user.hashed_password if user else _dummy_hash
    password_ok = verify_password(body.password, candidate_hash)
    if user is None or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return TokenResponse(
        access_token=create_access_token(user.tenant_id, user.id, user.role),
        refresh_token=create_refresh_token(user.tenant_id, user.id),
    )
