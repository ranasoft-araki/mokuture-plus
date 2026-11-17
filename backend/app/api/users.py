from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.staff_route import StaffNotificationRoute
from app.models.user import User
from app.services import accounts
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    is_readonly_account,
    verify_password_async,
)
from app.services.timeutil import utcnow_naive

router = APIRouter(prefix="/users", tags=["users"])

_ALLOWED_ROLES = {"admin", "staff"}
# ユーザー管理(追加・削除・権限変更・パスワード再設定)ができるロール。
_MANAGER_ROLES = ("admin", "superadmin")
_ADMIN_REQUIRED = "この操作は管理者のみ行えます"


def _password_changed_now():
    """パスワード変更時刻。トークンの iat(秒)と比べるので秒に切り捨てて保存する。"""
    return utcnow_naive().replace(microsecond=0)


class UserListItem(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime


class MeResponse(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    tenant_id: str | None
    created_at: datetime


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str


class UpdateUserRequest(BaseModel):
    role: str


class UpdateMeRequest(BaseModel):
    name: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: User = Depends(get_current_user),
):
    return _out_me(user)


@router.patch("/me", response_model=MeResponse)
async def update_me(
    body: UpdateMeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is not None:
        user.name = body.name
    await db.commit()
    await db.refresh(user)
    return _out_me(user)


@router.get("", response_model=list[UserListItem])
async def list_users(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .where(User.tenant_id == user.tenant_id)
        .order_by(User.created_at.desc())
    )
    return [_out(u) for u in result.scalars()]


@router.post("", response_model=UserListItem, status_code=201)
async def create_user(
    body: CreateUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'staff'")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    # メールアドレスはログイン ID。どのテナントのユーザーとも重ねない(大文字小文字は区別しない)。
    if await accounts.email_in_use(db, body.email):
        raise HTTPException(status_code=409, detail=accounts.EMAIL_TAKEN_DETAIL)
    new_user = User(
        tenant_id=user.tenant_id,
        email=accounts.normalize_email(body.email),
        hashed_password=await hash_password_async(body.password),
        role=body.role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return _out(new_user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="User not found in your tenant")
    # 担当者ごとのプッシュ宛先から外す。本番 DB の push_user_id は ALTER TABLE で
    # 足した列で外部キー制約が無く、ON DELETE SET NULL が効かない。残すと画面上は
    # 「指定しない」に見えるのに、実際は宛先が解決できず届かない状態になる。
    await db.execute(
        update(StaffNotificationRoute)
        .where(
            StaffNotificationRoute.tenant_id == user.tenant_id,
            StaffNotificationRoute.push_user_id == user_id,
        )
        .values(push_user_id=None)
    )
    await db.delete(target)
    await db.commit()


_PROXY_PASSWORD_DETAIL = "代理ログイン中は管理者のパスワードを変更できません。ご本人がログインして変更してください"


def _is_proxy_request(request: Request) -> bool:
    """代理ログイン(運営・代理店が顧客の管理者として入っている)のトークンか。"""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return False
    try:
        return decode_token(auth.split(" ", 1)[1].strip()).get("proxy") is True
    except JWTError:
        return False


@router.patch("/me/password")
async def change_own_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """自分のパスワードを変更する。

    変更より前に発行されたトークン(他の端末のログイン)は使えなくなる。変更した本人の
    画面がログアウトされないよう、新しいトークンを返す(フロントはこれに差し替える)。

    代理ログイン(運営・代理店が顧客の管理者として入っている)では変更させない。
    顧客の管理者本人のパスワードであり、変えると本人の全端末がログアウトされるため。"""
    if _is_proxy_request(request):
        raise HTTPException(status_code=403, detail=_PROXY_PASSWORD_DETAIL)
    if not await verify_password_async(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="現在のパスワードが正しくありません")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="新しいパスワードは8文字以上にしてください")
    changed_at = _password_changed_now()
    user.hashed_password = await hash_password_async(body.new_password)
    user.password_changed_at = changed_at
    await db.commit()
    tenant_id = user.tenant_id or ""
    access = create_access_token(
        tenant_id, user.id, user.role,
        readonly=is_readonly_account(user.email), issued_at=changed_at,
    )
    refresh = create_refresh_token(tenant_id, user.id, issued_at=changed_at)
    return {
        "message": "パスワードを変更しました",
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
    }


@router.patch("/{user_id}", response_model=UserListItem)
async def update_user_role(
    user_id: str,
    body: UpdateUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'staff'")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="User not found in your tenant")
    target.role = body.role
    await db.commit()
    await db.refresh(target)
    return _out(target)


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    body: ResetPasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="User not found in your tenant")
    # 代理ログインでは顧客の管理者(自分自身を含む)のパスワードは再設定させない
    # (PATCH /users/me/password と同じ理由)。スタッフの再設定は従来どおりできる。
    if _is_proxy_request(request) and (target.id == user.id or target.role in _MANAGER_ROLES):
        raise HTTPException(status_code=403, detail=_PROXY_PASSWORD_DETAIL)
    target.hashed_password = await hash_password_async(body.new_password)
    # 再設定前のログイン(その人の全端末)を無効にする。
    target.password_changed_at = _password_changed_now()
    await db.commit()
    return {"message": "パスワードをリセットしました"}


def _out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "created_at": u.created_at,
    }


def _out_me(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "tenant_id": u.tenant_id,
        "created_at": u.created_at,
    }
