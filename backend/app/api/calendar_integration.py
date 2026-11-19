"""Google カレンダー連携の API。→ CLAUDE.md「Google カレンダー連携」・services/google_calendar.py。

管理画面「カレンダー連携」(`/{slug}/admin/calendar`)が使う。連携・設定・今すぐ同期・解除は管理者だけ。
連携状態の参照だけはスタッフにも許す(「来社予定」画面に連携中かどうかを出すため)。

OAuth: 認可 URL を JWT 付きで受け取り → ブラウザが Google へ → Google は画面の
`/google-calendar/callback`(GOOGLE_REDIRECT_URI)へ戻す → 画面がログイン中の管理者の JWT 付きで
`POST /oauth/complete` にコードと state を渡す → state の利用者 = JWT の利用者のときだけトークンを
暗号化保存。Slack のように未認証の callback で保存しないのは、他人に認可 URL を踏ませて、その人の
カレンダーを自分のテナントへつながせる手(ログイン CSRF)を塞ぐため。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from jose import JWTError
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.tenant import get_current_user, require_tenant_admin
from app.models.calendar_integration import CalendarEventTombstone, CalendarIntegration
from app.models.tenant import Tenant
from app.models.user import User
from app.models.visitor_appointment import VisitorAppointment
from app.services import google_calendar as gcal
from app.services.auth import create_google_state_token, verify_google_state_token
from app.services.timeutil import iso_z, utcnow_naive

router = APIRouter(prefix="/integrations/google-calendar", tags=["google-calendar"])

_NOT_CONNECTED = "先に「Googleアカウントで連携」で Google アカウントを連携してください。"


def _staff_list(tenant: Tenant | None) -> list[str]:
    return [s.strip() for s in ((tenant.staff_list if tenant else "") or "").split(",") if s.strip()]


async def _status(db: AsyncSession, tenant_id: str) -> dict:
    integ = await gcal.load_integration(db, tenant_id)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    connected = bool(integ and integ.status in ("active", "reauth_required") and gcal.has_refresh_token(integ))
    unsynced = 0
    if integ is not None and connected and integ.direction == "to_google" and integ.calendar_id:
        since = gcal.now_jst_wall() - timedelta(days=gcal.PUSH_DAYS_BEHIND)
        unsynced = (await db.execute(
            select(func.count()).select_from(VisitorAppointment).where(
                VisitorAppointment.tenant_id == tenant_id,
                VisitorAppointment.gcal_origin.is_(None),
                VisitorAppointment.scheduled_at >= since,
                or_(
                    VisitorAppointment.gcal_sync_state.is_(None),
                    VisitorAppointment.gcal_sync_state != "synced",
                    VisitorAppointment.gcal_calendar_id.is_(None),
                    VisitorAppointment.gcal_calendar_id != integ.calendar_id,
                ),
            )
        )).scalar_one()
    return {
        "enabled": gcal.enabled(),
        "connected": connected,
        "status": integ.status if integ else "disconnected",
        "account_email": integ.account_email if integ and connected else None,
        "direction": integ.direction if integ else None,
        "calendar_id": integ.calendar_id if integ else None,
        "calendar_name": integ.calendar_name if integ else None,
        "import_keyword": (integ.import_keyword or "") if integ else "",
        "default_staff": (integ.default_staff or "") if integ else "",
        "active": gcal.is_active(integ),
        "last_synced_at": iso_z(integ.last_synced_at) if integ else None,
        "last_error": integ.last_error if integ else None,
        "last_error_at": iso_z(integ.last_error_at) if integ else None,
        "unsynced_count": unsynced,
        "staff_list": _staff_list(tenant),
    }


@router.get("")
async def get_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """連携状態。トークンは返さない。スタッフも見られる(来社予定画面の表示用)。"""
    return await _status(db, user.tenant_id)


@router.get("/oauth/url")
async def oauth_url(user: User = Depends(require_tenant_admin())):
    """Google の認可 URL。画面はこれへ `window.location` で移る。env 未設定なら {enabled:false}。"""
    if not gcal.enabled():
        return {"enabled": False}
    state = create_google_state_token(user.tenant_id, user.id)
    return {"enabled": True, "authorize_url": gcal.build_authorize_url(state)}


class CompleteBody(BaseModel):
    code: str = ""
    state: str = ""
    error: str = ""


@router.post("/oauth/complete")
async def oauth_complete(
    body: CompleteBody,
    user: User = Depends(require_tenant_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Google から戻った画面(/google-calendar/callback)が呼ぶ。結果は `{result}` で返し、画面が
    「カレンダー連携」へ ?google=<result> を付けて移る。result: connected / denied / scope / error / mismatch。"""
    if not gcal.enabled():
        raise HTTPException(status_code=404, detail="この環境では Google カレンダー連携は使えません。")
    tenant_id = user.tenant_id
    try:
        state_tenant, state_user = verify_google_state_token(body.state)
    except JWTError:
        return {"result": "error"}
    if state_tenant != tenant_id or state_user != user.id:
        # 連携を始めた人と、いまログインしている人が違う。他人が作った認可 URL を踏まされた可能性がある。
        return {"result": "mismatch"}
    if body.error or not body.code:
        return {"result": "denied"}

    try:
        creds = await gcal.exchange_code(body.code)
    except gcal.GoogleOAuthError:
        return {"result": "error"}
    if gcal.missing_scopes(creds.get("scope", "")) or not creds.get("refresh_token"):
        # 同意画面で「予定の表示と編集」などのチェックを外された。足りないまま保存しない。
        # (取り消しの要求は送らない: 同じアカウントで使っている今の連携まで道連れに取り消しうるため)
        return {"result": "scope" if creds.get("refresh_token") or creds.get("scope") else "error"}

    async with gcal.tenant_lock(tenant_id):
        integ = await gcal.load_integration(db, tenant_id)
        previous_email = (integ.account_email or "").lower() if integ else ""
        old_creds = gcal.load_credentials(integ) if integ else {}
        if integ is None:
            integ = CalendarIntegration(tenant_id=tenant_id, provider="google")
            db.add(integ)
        gcal.store_credentials(integ, {
            "refresh_token": creds["refresh_token"],
            "access_token": creds["access_token"],
            "access_expires_at": creds["access_expires_at"],
        })
        integ.status = "active"
        await db.flush()

        try:
            email = await gcal.primary_calendar_id(db, integ)
            # 書き出し中なら「書き込める」ことまで要る(見えるだけでは送るたびに 403 になる)
            visible = {
                c["id"] for c in await gcal.list_calendars(db, integ)
                if integ.direction != "to_google" or c["writable"]
            }
        except (gcal.GoogleApiError, gcal.GoogleAuthError):
            # アカウントを確かめられないまま「別のアカウント」とみなすと、取り込んだ予定の結び付きを
            # 外して二重に取り込んでしまう。何も変えずに失敗として返す(もう一度押してもらう)。
            await db.rollback()
            return {"result": "error"}

        switched = bool(previous_email) and email.lower() != previous_email
        if switched and integ.calendar_id and integ.calendar_id not in visible:
            # 前に選んでいたカレンダーが新しいアカウントから見えない。結び付きを外す。
            await gcal.unlink_all(db, tenant_id)
            integ.calendar_id = None
            integ.calendar_name = None
        integ.account_email = email or None
        integ.status = "active"
        gcal.record_error(integ, None)
        integ.updated_at = utcnow_naive()
        await db.commit()
    if switched and old_creds.get("refresh_token"):
        await gcal.revoke(old_creds["refresh_token"])  # 前のアカウントの許可は要らなくなった
    return {"result": "connected"}


async def _connected_integration(db: AsyncSession, tenant_id: str) -> CalendarIntegration:
    if not gcal.enabled():
        raise HTTPException(status_code=404, detail="この環境では Google カレンダー連携は使えません。")
    integ = await gcal.load_integration(db, tenant_id)
    if integ is None or not gcal.has_refresh_token(integ) or integ.status == "disconnected":
        raise HTTPException(status_code=400, detail=_NOT_CONNECTED)
    if integ.status == "reauth_required":
        raise HTTPException(status_code=400, detail=gcal.REAUTH_MESSAGE)
    return integ


@router.get("/calendars")
async def calendars(user: User = Depends(require_tenant_admin()), db: AsyncSession = Depends(get_db)):
    """選べるカレンダー(マイカレンダー＝自分がオーナーのもの / 他のカレンダー)。"""
    integ = await _connected_integration(db, user.tenant_id)
    try:
        items = await gcal.list_calendars(db, integ)
    except gcal.GoogleAuthError:
        raise HTTPException(status_code=400, detail=gcal.REAUTH_MESSAGE)
    except gcal.GoogleApiError as e:
        raise HTTPException(status_code=502, detail=e.message)
    return {"calendars": items}


class SettingsBody(BaseModel):
    direction: Literal["to_google", "from_google"]
    calendar_id: str
    import_keyword: str = ""
    default_staff: str = ""

    @field_validator("calendar_id")
    @classmethod
    def _cal(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("同期するカレンダーを選んでください")
        return v

    @field_validator("import_keyword", "default_staff")
    @classmethod
    def _trim(cls, v: str) -> str:
        return (v or "").strip()


@router.put("/settings")
async def save_settings(
    body: SettingsBody,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_tenant_admin()),
    db: AsyncSession = Depends(get_db),
):
    """連携の方向・カレンダーなどを保存し、続けて 1 回同期する。"""
    integ = await _connected_integration(db, user.tenant_id)
    try:
        cals = await gcal.list_calendars(db, integ)
    except gcal.GoogleAuthError:
        raise HTTPException(status_code=400, detail=gcal.REAUTH_MESSAGE)
    except gcal.GoogleApiError as e:
        raise HTTPException(status_code=502, detail=e.message)
    cal = next((c for c in cals if c["id"] == body.calendar_id), None)
    if cal is None:
        raise HTTPException(status_code=422, detail="選んだカレンダーが見つかりません。一覧を読み直して選び直してください。")
    if body.direction == "to_google" and not cal["writable"]:
        raise HTTPException(
            status_code=422,
            detail="このカレンダーには予定を書き込めません（閲覧だけの権限です）。編集できるカレンダーを選んでください。",
        )
    if len(body.import_keyword) > 64:
        raise HTTPException(status_code=422, detail="取り込む予定の言葉は 64 文字までにしてください。")
    tenant = (await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
    if body.default_staff and body.default_staff not in _staff_list(tenant):
        raise HTTPException(status_code=422, detail="担当者は「通知設定」の「担当者ごとの通知先」にある担当者から選んでください。")

    async with gcal.tenant_lock(user.tenant_id):
        removed_imports = await _apply_settings(db, user.tenant_id, integ, body, cal)
    background_tasks.add_task(gcal.sync_tenant, user.tenant_id)
    return {**(await _status(db, user.tenant_id)), "removed_imports": removed_imports}


async def _apply_settings(
    db: AsyncSession, tenant_id: str, integ: CalendarIntegration, body: SettingsBody, cal: dict
) -> int:
    """方向・カレンダーの切り替えに伴う後始末をして保存する。消した取り込み予定の数を返す。"""
    await db.refresh(integ)  # 鍵を待つ間に同期が書いた値の上に積む
    old_dir, old_cal = integ.direction, integ.calendar_id
    removed_imports = 0
    now_wall = gcal.now_jst_wall()
    if old_dir == "to_google" and old_cal and body.direction == "to_google" and body.calendar_id != old_cal:
        # 書き出し先を変えた: 前のカレンダーに書いたこれからの予定は消し、新しいカレンダーへ書き直す。
        moved = (await db.execute(select(VisitorAppointment).where(
            VisitorAppointment.tenant_id == tenant_id,
            VisitorAppointment.gcal_origin.is_(None),
            VisitorAppointment.gcal_calendar_id == old_cal,
            VisitorAppointment.gcal_event_id.is_not(None),
            VisitorAppointment.scheduled_at >= now_wall - timedelta(days=gcal.PUSH_DAYS_BEHIND),
        ))).scalars().all()
        for a in moved:
            db.add(CalendarEventTombstone(
                tenant_id=tenant_id, kind="delete", calendar_id=old_cal,
                event_id=a.gcal_event_id, scheduled_at=a.scheduled_at,
            ))
            a.gcal_event_id = None
            a.gcal_calendar_id = None
            a.gcal_updated = None
            a.gcal_sync_state = "pending"
    if old_dir == "from_google" and old_cal and body.direction == "from_google" and body.calendar_id != old_cal:
        # 取り込み元を変えた: 前のカレンダーから取り込んだ、まだ受付していないこれからの予定は消す。
        stale = (await db.execute(select(VisitorAppointment).where(
            VisitorAppointment.tenant_id == tenant_id,
            VisitorAppointment.gcal_origin == "google",
            VisitorAppointment.gcal_calendar_id == old_cal,
            VisitorAppointment.status == "pending",
            VisitorAppointment.scheduled_at >= now_wall,
        ))).scalars().all()
        for a in stale:
            await db.delete(a)
        removed_imports = len(stale)
        await db.execute(delete(CalendarEventTombstone).where(
            CalendarEventTombstone.tenant_id == tenant_id,
            CalendarEventTombstone.kind == "ignore",
            CalendarEventTombstone.calendar_id == old_cal,
        ))

    integ.direction = body.direction
    integ.calendar_id = cal["id"]
    integ.calendar_name = cal["name"][:255]
    integ.import_keyword = body.import_keyword or None
    integ.default_staff = body.default_staff or None
    gcal.record_error(integ, None)
    integ.updated_at = utcnow_naive()
    await db.commit()
    return removed_imports


@router.post("/sync")
async def sync_now(user: User = Depends(require_tenant_admin()), db: AsyncSession = Depends(get_db)):
    """「今すぐ同期」。終わるまで待って件数を返す。"""
    tenant_id = user.tenant_id  # 下の expire_all でユーザーの属性も読み直し扱いになるので先に取る
    integ = await _connected_integration(db, tenant_id)
    if not gcal.is_active(integ):
        raise HTTPException(status_code=400, detail="連携の方向と同期するカレンダーを選んで保存してください。")
    res = await gcal.sync_tenant(tenant_id)
    db.expire_all()  # 同期は別のセッションで書いたので、この画面へ返す値は読み直す
    return {"result": res.as_dict(), **(await _status(db, tenant_id))}


@router.post("/disconnect")
async def disconnect(user: User = Depends(require_tenant_admin()), db: AsyncSession = Depends(get_db)):
    """連携を解除する。Google 側の許可も取り消す(best-effort)。カレンダーに書いた予定・取り込んだ
    来社予定はどちらも消さない。同じアカウントで結び直せば、方向とカレンダーの選択を引き継ぐ。"""
    integ = await gcal.load_integration(db, user.tenant_id)
    if integ is None:
        return {"ok": True}
    creds = gcal.load_credentials(integ)
    if creds.get("refresh_token"):
        await gcal.revoke(creds["refresh_token"])
    gcal.store_credentials(integ, {})
    integ.status = "disconnected"
    gcal.record_error(integ, None)
    integ.updated_at = utcnow_naive()
    # 送れないまま残る削除の印は片付ける(結び直したあとに古い予定を消しに行かない)。
    await db.execute(delete(CalendarEventTombstone).where(
        CalendarEventTombstone.tenant_id == user.tenant_id, CalendarEventTombstone.kind == "delete",
    ))
    await db.commit()
    return {"ok": True}
