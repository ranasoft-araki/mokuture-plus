from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select, update

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserInvitation
from app.services.timeutil import iso_z, to_naive_utc, utcnow_naive
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


# ── 招待リンクから登録する(公開・認証なし) ──────────────────────────────────
# 招待を送る側は api/users.py の /users/invitations。トークンは URL のパスではなく
# 本文で受け取る(パスに載せるとアクセスログに残るため)。

_INVITE_NOT_FOUND = "この招待リンクは使えません。取り消されたか、新しいリンクが送り直されています。最新の招待メールを開いてください。"
_INVITE_EXPIRED = "この招待リンクは有効期限が切れています。招待した人に送り直しを頼んでください。"
_INVITE_USED = "この招待リンクは登録に使用済みです。ログイン画面からログインしてください。"
_INVITE_EMAIL_TAKEN = "このメールアドレスは既に登録されています。ログイン画面からログインしてください。"


class InvitationTokenRequest(BaseModel):
    token: str


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str
    name: str | None = None


async def _find_invitation(db: AsyncSession, token: str) -> tuple[UserInvitation, Tenant | None]:
    """トークンから招待を引く。見つからない・期限切れ・使用済みはそれぞれの理由で断る。"""
    from app.services.invitations import hash_token

    inv = (await db.execute(
        select(UserInvitation).where(UserInvitation.token_hash == hash_token((token or "").strip()))
    )).scalar_one_or_none()
    if inv is None or not token:
        raise HTTPException(status_code=404, detail=_INVITE_NOT_FOUND)
    if inv.accepted_at is not None:
        raise HTTPException(status_code=410, detail=_INVITE_USED)
    expires = to_naive_utc(inv.expires_at)
    if expires is None or expires <= utcnow_naive():
        raise HTTPException(status_code=410, detail=_INVITE_EXPIRED)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == inv.tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail=_INVITE_NOT_FOUND)
    return inv, tenant


@router.post("/invitations/lookup")
@_limiter.limit("30/minute")
async def lookup_invitation(request: Request, body: InvitationTokenRequest, db: AsyncSession = Depends(get_db)):
    """招待リンクを開いた画面が、誰をどのテナントへ招待しているかを表示するために使う。"""
    inv, tenant = await _find_invitation(db, body.token)
    return {
        "email": inv.email,
        "role": inv.role,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "expires_at": iso_z(inv.expires_at),
        "email_taken": await accounts.email_in_use(db, inv.email),
    }


@router.post("/invitations/accept", response_model=TokenResponse)
@_limiter.limit("10/minute")
async def accept_invitation(request: Request, body: AcceptInvitationRequest, db: AsyncSession = Depends(get_db)):
    """招待リンクからパスワードを決めて登録し、そのままログインした状態のトークンを返す。"""
    if len(body.password or "") < 8:
        raise HTTPException(status_code=422, detail="パスワードは8文字以上にしてください")
    inv, tenant = await _find_invitation(db, body.token)
    # 招待のあとで、同じアドレスが別の経路(別テナントの招待・直接追加)で登録されていることがある。
    if await accounts.email_in_use(db, inv.email):
        raise HTTPException(status_code=409, detail=_INVITE_EMAIL_TAKEN)
    # 同じリンクで同時に2回押されても、ユーザーを2人作らない(先に「使用済み」へ条件つきで書く)。
    # token_hash も条件に入れる: 照会から確定までの間に送り直されたら、古いリンクでは登録させない。
    claimed = await db.execute(
        update(UserInvitation)
        .where(
            UserInvitation.id == inv.id,
            UserInvitation.token_hash == inv.token_hash,
            UserInvitation.accepted_at.is_(None),
        )
        .values(accepted_at=utcnow_naive())
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=410, detail=_INVITE_USED)
    # 同じテナントで同じアドレスへの招待が他にも残っていれば消す(同時に送られた等。「招待中」に残り続けないように)。
    await db.execute(
        delete(UserInvitation).where(
            UserInvitation.tenant_id == inv.tenant_id,
            UserInvitation.id != inv.id,
            UserInvitation.accepted_at.is_(None),
            func.lower(UserInvitation.email) == inv.email.lower(),
        )
    )
    name = (body.name or "").strip()[:255] or None
    user = User(
        tenant_id=inv.tenant_id,
        email=accounts.normalize_email(inv.email),
        hashed_password=await hash_password_async(body.password),
        role=inv.role if inv.role in ("admin", "staff") else "staff",
        name=name,
    )
    db.add(user)
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(
            user.tenant_id or "", user.id, user.role, readonly=is_readonly_account(user.email),
        ),
        refresh_token=create_refresh_token(user.tenant_id or "", user.id),
        tenant_slug=tenant.slug,
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
