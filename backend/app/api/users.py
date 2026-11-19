import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update

from app.config import settings
from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.staff_route import StaffNotificationRoute
from app.models.tenant import Tenant
from app.models.user import User, UserInvitation
from app.services import accounts, mail_quota
from app.services import email as email_service
from app.services import invitations as invite_svc
from app.services.timeutil import iso_z, to_naive_utc
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_async,
    is_readonly_account,
    verify_password_async,
)
from app.services.timeutil import utcnow_naive

logger = logging.getLogger(__name__)

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


# ── 招待(メールで招待リンクを送り、本人がパスワードを決めて登録する) ────────────
#
# 公開側(リンクを開いた人が使う照会・登録)は api/auth.py の /auth/invitations/*。

_SMTP_DISABLED_DETAIL = "メール送信が設定されていないため、招待メールを送れません。運営にSMTPの設定をご依頼ください。"
# 共有の SMTP へ同時に開く接続の数(1通最大20秒なので、直列だと30通でプロキシの待ち時間を越える)。
_SEND_CONCURRENCY = 4


class InviteRequest(BaseModel):
    emails: list[str] = Field(default_factory=list)
    role: str = "staff"


def _out_invitation(inv: UserInvitation, now: datetime) -> dict:
    expires = to_naive_utc(inv.expires_at)
    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "created_at": iso_z(inv.created_at),
        "sent_at": iso_z(inv.sent_at),
        "expires_at": iso_z(inv.expires_at),
        "expired": bool(expires and expires <= now),
    }


def _require_manager(user: User) -> None:
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail=_ADMIN_REQUIRED)


async def _tenant_of(db: AsyncSession, user: User) -> Tenant | None:
    return (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()


async def _send_invite_mail(
    tenant: Tenant | None, inviter: User, to: str, role: str, token: str, expires_at: datetime,
) -> bool:
    tenant_name = tenant.name if tenant else settings.app_name
    subject, text, html = invite_svc.build_email(
        tenant_name=tenant_name,
        brand_color=(tenant.brand_color if tenant else "") or "",
        inviter=inviter.name or inviter.email,
        to=to,
        role=role,
        url=invite_svc.invite_url(tenant.slug if tenant else "", token),
        expires_at=expires_at,
    )
    try:
        ok, err = await email_service.send_email(
            to=to,
            subject=subject,
            html=html,
            text=text,
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_addr=settings.smtp_from or settings.smtp_username,
            from_name=invite_svc.one_line(settings.smtp_from_name or tenant_name),
            starttls=settings.smtp_starttls,
            use_ssl=settings.smtp_ssl,
        )
    except Exception as e:  # noqa: BLE001 — 宛先の書式などで送る前に落ちても、他の宛先は続ける
        ok, err = False, str(e)
    if not ok:
        # メールサーバーの応答は画面に返さない(サーバーのログにだけ残す)。宛先は先頭だけ。
        logger.warning("invite email failed (tenant=%s to=%s…): %s", inviter.tenant_id, to[:3], (err or "")[:200])
    return ok


@router.get("/invitations")
async def list_invitations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """まだ登録されていない招待の一覧と、いまメールを送れるか(SMTP・残りの通数)。"""
    _require_manager(user)
    now = utcnow_naive()
    rows = (await db.execute(
        select(UserInvitation)
        .where(UserInvitation.tenant_id == user.tenant_id, UserInvitation.accepted_at.is_(None))
        .order_by(UserInvitation.created_at.desc())
    )).scalars().all()
    return {
        "smtp_enabled": settings.smtp_enabled,
        "mail_remaining": mail_quota.remaining(user.tenant_id),
        "mail_limit": mail_quota.LIMIT_PER_HOUR,
        "expire_days": invite_svc.EXPIRE_DAYS,
        "max_per_request": invite_svc.MAX_PER_REQUEST,
        "invitations": [_out_invitation(r, now) for r in rows],
    }


@router.post("/invitations")
async def invite_users(
    body: InviteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """複数のメールアドレスへまとめて招待メールを送る。

    結果はアドレスごとに返す(status: sent / resent / already_user / invalid / duplicate / failed)。
    - 形式の誤り・同じ依頼の中の重複・登録済み(どのテナントでも)は送らない。
    - このテナントで招待中のアドレスは、リンクを作り直して送り直す(前のリンクは使えなくなる)。
    - 送る件数が回数制限の残りを超えるときは、1通も送らず 429(一部だけ送られた状態にしない)。
    - 送れなかった宛先は招待を作らない/前のリンクを残す。
    """
    _require_manager(user)
    if body.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'staff'")
    if not body.emails:
        raise HTTPException(status_code=422, detail="メールアドレスを入力してください")
    if len(body.emails) > invite_svc.MAX_PER_REQUEST:
        raise HTTPException(status_code=422, detail=f"一度に招待できるのは{invite_svc.MAX_PER_REQUEST}件までです")
    if not settings.smtp_enabled:
        raise HTTPException(status_code=503, detail=_SMTP_DISABLED_DETAIL)

    results: list[dict] = []
    to_send: list[dict] = []
    seen: set[str] = set()
    for raw in body.emails:
        addr = invite_svc.normalize(raw)
        key = addr.lower()
        if not invite_svc.is_valid(addr):
            results.append({"email": addr or raw, "status": "invalid"})
            continue
        if key in seen:
            results.append({"email": addr, "status": "duplicate"})
            continue
        seen.add(key)
        if await accounts.email_in_use(db, addr):
            results.append({"email": addr, "status": "already_user"})
            continue
        pending = (await db.execute(
            select(UserInvitation)
            .where(
                UserInvitation.tenant_id == user.tenant_id,
                UserInvitation.accepted_at.is_(None),
                func.lower(UserInvitation.email) == key,
            )
            .order_by(UserInvitation.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        item = {"email": addr, "status": None, "existing": pending}
        results.append(item)
        to_send.append(item)

    if to_send:
        remaining = mail_quota.remaining(user.tenant_id)
        if len(to_send) > remaining:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"送信回数の上限(1時間に{mail_quota.LIMIT_PER_HOUR}通)を超えるため送れません。"
                    f"送る宛先は{len(to_send)}件、いま送れるのはあと{remaining}通です。"
                    "宛先を減らすか、しばらく待ってからお試しください。"
                ),
            )
        mail_quota.consume(user.tenant_id, len(to_send))

        tenant = await _tenant_of(db, user)
        sem = asyncio.Semaphore(_SEND_CONCURRENCY)

        async def _one(item: dict) -> None:
            token, token_hash = invite_svc.new_token()
            expires = invite_svc.new_expiry()
            async with sem:
                ok = await _send_invite_mail(tenant, user, item["email"], body.role, token, expires)
            item["ok"], item["token_hash"], item["expires"] = ok, token_hash, expires

        await asyncio.gather(*(_one(i) for i in to_send))

        now = utcnow_naive()
        for item in to_send:
            existing: UserInvitation | None = item["existing"]
            if not item["ok"]:
                item["status"] = "failed"
                continue
            if existing is not None:
                existing.token_hash = item["token_hash"]
                existing.expires_at = item["expires"]
                existing.role = body.role
                existing.sent_at = now
                existing.invited_by = user.id
                item["status"] = "resent"
            else:
                db.add(UserInvitation(
                    tenant_id=user.tenant_id,
                    email=item["email"],
                    role=body.role,
                    token_hash=item["token_hash"],
                    invited_by=user.id,
                    sent_at=now,
                    expires_at=item["expires"],
                ))
                item["status"] = "sent"
        await db.commit()

    out = [{"email": r["email"], "status": r["status"]} for r in results]
    counts: dict[str, int] = {}
    for r in out:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"results": out, "counts": counts, "mail_remaining": mail_quota.remaining(user.tenant_id)}


async def _get_invitation(db: AsyncSession, user: User, invitation_id: str) -> UserInvitation:
    inv = (await db.execute(
        select(UserInvitation).where(
            UserInvitation.id == invitation_id,
            UserInvitation.tenant_id == user.tenant_id,
            UserInvitation.accepted_at.is_(None),
        )
    )).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="招待が見つかりません（登録済みか、取り消されています）")
    return inv


@router.post("/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """招待メールを送り直す(リンクを作り直し、期限を延ばす。前のリンクは使えなくなる)。"""
    _require_manager(user)
    inv = await _get_invitation(db, user, invitation_id)
    if not settings.smtp_enabled:
        raise HTTPException(status_code=503, detail=_SMTP_DISABLED_DETAIL)
    if await accounts.email_in_use(db, inv.email):
        raise HTTPException(status_code=409, detail=accounts.EMAIL_TAKEN_DETAIL)
    mail_quota.consume(user.tenant_id, 1)
    token, token_hash = invite_svc.new_token()
    expires = invite_svc.new_expiry()
    ok = await _send_invite_mail(await _tenant_of(db, user), user, inv.email, inv.role, token, expires)
    if not ok:
        raise HTTPException(status_code=502, detail="招待メールを送れませんでした。宛先を確認して、しばらくしてからお試しください。")
    inv.token_hash = token_hash
    inv.expires_at = expires
    inv.sent_at = utcnow_naive()
    inv.invited_by = user.id
    await db.commit()
    return _out_invitation(inv, utcnow_naive())


@router.delete("/invitations/{invitation_id}", status_code=204)
async def cancel_invitation(
    invitation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """招待を取り消す(送ったリンクは使えなくなる)。"""
    _require_manager(user)
    inv = await _get_invitation(db, user, invitation_id)
    await db.delete(inv)
    await db.commit()
