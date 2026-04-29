import csv
import io
from datetime import date, datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.reception import ReceptionLog
from app.models.notification import NotificationSetting, PushSubscription
from app.models.user import User
from app.services.slack import send_slack_notification
from app.services.webpush import send_push
from app.services.crypto import decrypt_dict
from app.config import settings

router = APIRouter(prefix="/reception", tags=["reception"])

_ALLOWED_METHODS = {"form", "qr", "calendar"}


class ReceptionCreate(BaseModel):
    visitor_name: str
    company: str | None = None
    purpose: str | None = None
    staff: str | None = None
    method: str = "form"

    @field_validator("visitor_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("visitor_name must not be empty")
        if len(v) > 255:
            raise ValueError("visitor_name too long (max 255 chars)")
        return v

    @field_validator("method")
    @classmethod
    def method_allowed(cls, v: str) -> str:
        if v not in _ALLOWED_METHODS:
            raise ValueError(f"method must be one of: {_ALLOWED_METHODS}")
        return v


class ReceptionOut(BaseModel):
    id: str
    visitor_name: str
    company: str | None
    purpose: str | None
    staff: str | None
    method: str
    state: str
    created_at: str

    model_config = {"from_attributes": True}


@router.post("", response_model=ReceptionOut, status_code=201)
async def create_reception(
    body: ReceptionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = ReceptionLog(tenant_id=user.tenant_id, **body.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)

    await _notify_slack(user.tenant_id, log, db)
    await _notify_push(user.tenant_id, log, db)

    return _log_out(log)


@router.get("", response_model=list[ReceptionOut])
async def list_reception(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    method: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ReceptionLog).where(ReceptionLog.tenant_id == user.tenant_id).order_by(ReceptionLog.created_at.desc())
    if date_from:
        q = q.where(func.date(ReceptionLog.created_at) >= date_from)
    if date_to:
        q = q.where(func.date(ReceptionLog.created_at) <= date_to)
    if method:
        q = q.where(ReceptionLog.method == method)
    result = await db.execute(q)
    return [_log_out(r) for r in result.scalars()]


@router.get("/export.csv")
async def export_reception_csv(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    method: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(ReceptionLog).where(ReceptionLog.tenant_id == user.tenant_id).order_by(ReceptionLog.created_at.desc())
    if date_from:
        q = q.where(func.date(ReceptionLog.created_at) >= date_from)
    if date_to:
        q = q.where(func.date(ReceptionLog.created_at) <= date_to)
    if method:
        q = q.where(ReceptionLog.method == method)
    result = await db.execute(q)
    logs = result.scalars().all()

    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output)
    writer.writerow(["日時", "訪問者名", "会社名", "担当者", "目的", "受付方法", "ステータス"])
    for r in logs:
        writer.writerow([
            r.created_at.isoformat() if r.created_at else "",
            r.visitor_name,
            r.company or "",
            r.staff or "",
            r.purpose or "",
            r.method,
            r.state,
        ])
    output.seek(0)

    filename = f"reception_{datetime.today().strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/stats/today")
async def today_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    today = date.today()
    result = await db.execute(
        select(func.count()).where(
            ReceptionLog.tenant_id == user.tenant_id,
            func.date(ReceptionLog.created_at) == today,
        )
    )
    count = result.scalar_one()
    return {"date": today.isoformat(), "count": count}


async def _notify_push(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    vapid_result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "vapid",
        )
    )
    vapid_setting = vapid_result.scalar_one_or_none()
    private_key = ""
    if vapid_setting and vapid_setting.config_json and vapid_setting.config_json != "{}":
        try:
            vapid_config = decrypt_dict(vapid_setting.config_json)
            private_key = vapid_config.get("private_key", "")
        except Exception:
            pass
    if not private_key:
        private_key = settings.vapid_private_key
    if not private_key:
        return

    subs_result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == tenant_id)
    )
    subs = subs_result.scalars().all()
    if not subs:
        return

    title = "来客のお知らせ"
    body = f"{log.visitor_name}様（{log.company or '—'}）が受付を完了しました。"
    if log.purpose:
        body += f" 用件：{log.purpose}"

    for sub in subs:
        await send_push(
            endpoint=sub.endpoint,
            p256dh=sub.p256dh,
            auth=sub.auth_key,
            title=title,
            body=body,
            url=f"/{tenant_id}/admin/reception",
            private_key=private_key,
            subject=settings.vapid_subject,
        )


async def _notify_slack(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "slack",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return
    try:
        config = decrypt_dict(setting.config_json)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            msg = f"*新規受付* {log.visitor_name}様（{log.company or '—'}）\n用件: {log.purpose or '—'}　担当: {log.staff or '—'}"
            await send_slack_notification(webhook_url, msg)
    except Exception:
        pass  # notification failure must not affect reception


def _log_out(r: ReceptionLog) -> dict:
    return {
        "id": r.id,
        "visitor_name": r.visitor_name,
        "company": r.company,
        "purpose": r.purpose,
        "staff": r.staff,
        "method": r.method,
        "state": r.state,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }
