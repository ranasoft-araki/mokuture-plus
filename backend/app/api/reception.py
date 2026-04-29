import csv
import io
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

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
    staff_notes: str | None
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


@router.get("/contacts.csv")
async def export_contacts_csv(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            ReceptionLog.visitor_name,
            ReceptionLog.company,
            func.max(ReceptionLog.created_at).label("last_visit"),
            func.count(ReceptionLog.id).label("visit_count"),
        )
        .where(ReceptionLog.tenant_id == current_user.tenant_id)
        .group_by(ReceptionLog.visitor_name, ReceptionLog.company)
        .order_by(func.max(ReceptionLog.created_at).desc())
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["氏名", "会社名", "来訪回数", "最終来訪日"])
    for row in rows:
        writer.writerow([
            row.visitor_name,
            row.company or "",
            row.visit_count,
            row.last_visit.strftime("%Y-%m-%d") if row.last_visit else "",
        ])

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


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
    writer.writerow(["日時", "訪問者名", "会社名", "担当者", "目的", "受付方法", "ステータス", "スタッフメモ"])
    for r in logs:
        writer.writerow([
            r.created_at.isoformat() if r.created_at else "",
            r.visitor_name,
            r.company or "",
            r.staff or "",
            r.purpose or "",
            r.method,
            r.state,
            r.staff_notes or "",
        ])
    output.seek(0)

    filename = f"reception_{datetime.today().strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class UpdateReceptionRequest(BaseModel):
    state: str | None = None
    staff_notes: str | None = None


@router.patch("/{log_id}", response_model=ReceptionOut)
async def update_reception(
    log_id: str,
    body: UpdateReceptionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReceptionLog).where(ReceptionLog.id == log_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Reception log not found")
    if log.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if body.state is not None:
        log.state = body.state
    if body.staff_notes is not None:
        log.staff_notes = body.staff_notes
    await db.commit()
    await db.refresh(log)
    return _log_out(log)


class BulkDeleteRequest(BaseModel):
    ids: list[str]

    @field_validator("ids")
    @classmethod
    def ids_limit(cls, v: list[str]) -> list[str]:
        if len(v) > 200:
            raise ValueError("ids must not exceed 200 items")
        return v


@router.delete("/bulk", status_code=200)
async def bulk_delete_reception(
    body: BulkDeleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.ids:
        return {"deleted": 0}
    result = await db.execute(
        delete(ReceptionLog).where(
            ReceptionLog.id.in_(body.ids),
            ReceptionLog.tenant_id == user.tenant_id,
        )
    )
    await db.commit()
    return {"deleted": result.rowcount}


@router.delete("/{log_id}", status_code=204)
async def delete_reception(
    log_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReceptionLog).where(ReceptionLog.id == log_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Reception log not found")
    if log.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.delete(log)
    await db.commit()


class DailyStatItem(BaseModel):
    date: str
    count: int

class DailyStatsResponse(BaseModel):
    data: list[DailyStatItem]

class ReceptionDailyStat(BaseModel):
    date: str
    count: int

class ReceptionDailyStatsResponse(BaseModel):
    days: list[ReceptionDailyStat]
    today: int
    yesterday: int
    week_total: int


@router.get("/daily-stats", response_model=ReceptionDailyStatsResponse)
async def get_reception_daily_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    window_start = today - timedelta(days=13)  # 14 days inclusive: window_start..today
    dates = [(window_start + timedelta(days=i)) for i in range(14)]

    result = await db.execute(
        select(
            func.date(ReceptionLog.created_at).label("day"),
            func.count().label("cnt"),
        )
        .where(
            ReceptionLog.tenant_id == user.tenant_id,
            func.date(ReceptionLog.created_at) >= window_start,
        )
        .group_by("day")
        .order_by("day")
    )
    rows = {str(r.day): r.cnt for r in result.all()}

    days_list = [ReceptionDailyStat(date=str(d), count=rows.get(str(d), 0)) for d in dates]

    # week_total: Mon–Sun of current ISO week
    weekday = today.weekday()  # Mon=0, Sun=6
    week_start = today - timedelta(days=weekday)
    week_total = sum(
        rows.get(str(week_start + timedelta(days=i)), 0)
        for i in range(weekday + 1)
    )

    return ReceptionDailyStatsResponse(
        days=days_list,
        today=rows.get(str(today), 0),
        yesterday=rows.get(str(yesterday), 0),
        week_total=week_total,
    )


@router.get("/visitor-history")
async def visitor_history(
    name: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            func.count(ReceptionLog.id),
            func.min(ReceptionLog.created_at),
            func.max(ReceptionLog.created_at),
        ).where(
            ReceptionLog.tenant_id == user.tenant_id,
            ReceptionLog.visitor_name == name,
        )
    )
    count, first_visit, last_visit = result.one()
    return {
        "count": count,
        "first_visit": first_visit.isoformat() if first_visit else None,
        "last_visit": last_visit.isoformat() if last_visit else None,
    }


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
        "staff_notes": r.staff_notes,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }
