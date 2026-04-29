from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.user import User
from app.services.auth import hash_password, verify_password

router = APIRouter(prefix="/users", tags=["users"])

_ALLOWED_ROLES = {"admin", "staff"}


class UserListItem(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str


class UpdateUserRequest(BaseModel):
    role: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    new_password: str


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
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'staff'")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already exists")
    new_user = User(
        tenant_id=user.tenant_id,
        email=body.email,
        hashed_password=hash_password(body.password),
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
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="User not found in your tenant")
    await db.delete(target)
    await db.commit()


@router.patch("/{user_id}", response_model=UserListItem)
async def update_user_role(
    user_id: str,
    body: UpdateUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
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


@router.patch("/me/password")
async def change_own_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")
    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    body: ResetPasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="User not found in your tenant")
    target.hashed_password = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


def _out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "role": u.role,
        "created_at": u.created_at,
    }
