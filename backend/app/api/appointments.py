"""Visitor appointment management — admin JWT required."""
import re
from datetime import datetime
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.room import MeetingRoom
from app.models.tenant import Tenant
from app.models.user import User
from app.models.visitor_appointment import VisitorAppointment
from app.services import email as email_service
from app.services.honorific import with_honorific

router = APIRouter(prefix="/appointments", tags=["appointments"])

# 簡易メール形式チェック(email-validator を新規依存にしないための最小限)。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


class AppointmentCreate(BaseModel):
    visitor_name: str
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    meeting_room_id: Optional[str] = None
    scheduled_at: datetime
    notes: Optional[str] = None
    duration_minutes: Optional[int] = None

    @field_validator("visitor_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("visitor_name must not be empty")
        return v


class AppointmentUpdate(BaseModel):
    visitor_name: Optional[str] = None
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    meeting_room_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    duration_minutes: Optional[int] = None


class MeetingRoomResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    location: Optional[str] = None
    capacity: Optional[int] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: datetime


class AppointmentResponse(BaseModel):
    id: str
    visitor_name: str
    company: Optional[str] = None
    purpose: Optional[str] = None
    staff: Optional[str] = None
    scheduled_at: str
    token: str
    status: str
    notes: Optional[str] = None
    meeting_room_id: Optional[str] = None
    meeting_room: Optional[MeetingRoomResponse] = None
    duration_minutes: Optional[int] = None
    created_at: Optional[str] = None


def _room_out(room: Optional[MeetingRoom]) -> Optional[dict]:
    if room is None:
        return None
    return {
        "id": room.id,
        "tenant_id": room.tenant_id,
        "name": room.name,
        "location": room.location,
        "capacity": room.capacity,
        "color": room.color,
        "description": room.description,
        "is_active": room.is_active,
        "created_at": room.created_at,
    }


def _out(appt: VisitorAppointment, room: Optional[MeetingRoom] = None) -> dict:
    return {
        "id": appt.id,
        "visitor_name": appt.visitor_name,
        "company": appt.company,
        "purpose": appt.purpose,
        "staff": appt.staff,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "token": appt.token,
        "status": appt.status,
        "notes": appt.notes,
        "meeting_room_id": appt.meeting_room_id,
        "meeting_room": _room_out(room),
        "duration_minutes": appt.duration_minutes,
        "created_at": appt.created_at.isoformat() if appt.created_at else None,
    }


async def _ensure_room_belongs_to_tenant(
    room_id: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> None:
    if room_id is None:
        return
    result = await db.execute(
        select(MeetingRoom.id).where(
            MeetingRoom.id == room_id,
            MeetingRoom.tenant_id == tenant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Meeting room not found")


@router.get("", response_model=list[AppointmentResponse])
async def list_appointments(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(VisitorAppointment, MeetingRoom)
        .outerjoin(
            MeetingRoom,
            and_(
                VisitorAppointment.meeting_room_id == MeetingRoom.id,
                MeetingRoom.tenant_id == user.tenant_id,
            ),
        )
        .where(VisitorAppointment.tenant_id == user.tenant_id)
        .order_by(VisitorAppointment.scheduled_at)
    )
    if status:
        stmt = stmt.where(VisitorAppointment.status == status)
    if date_from:
        try:
            stmt = stmt.where(VisitorAppointment.scheduled_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            stmt = stmt.where(VisitorAppointment.scheduled_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    result = await db.execute(stmt)
    return [_out(appt, room) for appt, room in result.all()]


@router.post("", status_code=201, response_model=AppointmentResponse)
async def create_appointment(
    body: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scheduled_at = body.scheduled_at
    if scheduled_at.tzinfo is not None:
        scheduled_at = scheduled_at.replace(tzinfo=None)
    await _ensure_room_belongs_to_tenant(body.meeting_room_id, user.tenant_id, db)

    appt = VisitorAppointment(
        tenant_id=user.tenant_id,
        visitor_name=body.visitor_name.strip(),
        company=body.company,
        purpose=body.purpose,
        staff=body.staff,
        meeting_room_id=body.meeting_room_id,
        scheduled_at=scheduled_at,
        notes=body.notes,
        duration_minutes=body.duration_minutes,
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    room = None
    if appt.meeting_room_id is not None:
        room_result = await db.execute(select(MeetingRoom).where(MeetingRoom.id == appt.meeting_room_id))
        room = room_result.scalar_one_or_none()
    return _out(appt, room)


@router.get("/{appt_id}", response_model=AppointmentResponse)
async def get_appointment(
    appt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitorAppointment, MeetingRoom)
        .outerjoin(
            MeetingRoom,
            and_(
                VisitorAppointment.meeting_room_id == MeetingRoom.id,
                MeetingRoom.tenant_id == user.tenant_id,
            ),
        )
        .where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appt, room = row
    return _out(appt, room)


@router.patch("/{appt_id}", response_model=AppointmentResponse)
async def update_appointment(
    appt_id: str,
    body: AppointmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if body.visitor_name is not None:
        appt.visitor_name = body.visitor_name.strip()
    if body.company is not None:
        appt.company = body.company
    if body.purpose is not None:
        appt.purpose = body.purpose
    if body.staff is not None:
        appt.staff = body.staff
    if "meeting_room_id" in body.model_fields_set:
        await _ensure_room_belongs_to_tenant(body.meeting_room_id, user.tenant_id, db)
        appt.meeting_room_id = body.meeting_room_id
    if body.scheduled_at is not None:
        sched = body.scheduled_at
        if sched.tzinfo is not None:
            sched = sched.replace(tzinfo=None)
        appt.scheduled_at = sched
    if body.notes is not None:
        appt.notes = body.notes
    if body.status is not None:
        appt.status = body.status
    if body.duration_minutes is not None:
        appt.duration_minutes = body.duration_minutes

    await db.commit()
    await db.refresh(appt)
    room = None
    if appt.meeting_room_id is not None:
        room_result = await db.execute(select(MeetingRoom).where(MeetingRoom.id == appt.meeting_room_id))
        room = room_result.scalar_one_or_none()
    return _out(appt, room)


@router.delete("/{appt_id}", status_code=204)
async def delete_appointment(
    appt_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    await db.delete(appt)
    await db.commit()


# ── 来社予定QRのメール送信 ────────────────────────────────────────────────────

class SendEmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("有効なメールアドレスを入力してください")
        return v


def _fmt_scheduled_jp(dt: datetime) -> str:
    """来社日時を和文表記に。scheduled_at は管理画面が入力した壁時計(JST naive)なのでそのまま整形する。"""
    return f"{dt.year}年{dt.month}月{dt.day}日({_WEEKDAY_JP[dt.weekday()]}) {dt.hour:02d}:{dt.minute:02d}"


def _build_appointment_email(
    tenant_name: str,
    brand_color: str,
    appt: VisitorAppointment,
    room: Optional[MeetingRoom],
) -> tuple[str, str, str]:
    """(subject, text, html) を返す。QRは HTML 内で cid:qr として参照する。"""
    when = _fmt_scheduled_jp(appt.scheduled_at)
    subject = f"【{tenant_name}】ご来社予定のご案内（QRコード）"

    # 明細行(値のあるものだけ)
    rows: list[tuple[str, str]] = [("来社日時", when)]
    if appt.company:
        rows.append(("会社名", appt.company))
    if appt.purpose:
        rows.append(("ご用件", appt.purpose))
    if appt.staff:
        rows.append(("担当", appt.staff))
    if room is not None:
        rows.append(("お部屋", room.name + (f"（{room.location}）" if room.location else "")))

    # ── text ──
    text_lines = [
        with_honorific(appt.visitor_name),
        "",
        f"{tenant_name} でございます。ご来社の予定をご案内いたします。",
        "当日は受付にて、このメールに添付のQRコードを受付カメラにおかざしください。",
        "",
    ]
    text_lines += [f"{k}：{v}" for k, v in rows]
    text_lines += [
        "",
        f"予約コード: {appt.token}",
        "",
        "※このメールは送信専用です。ご返信いただけません。",
        f"— {tenant_name} 受付システム",
    ]
    text = "\n".join(text_lines)

    # ── html ── ユーザー入力(氏名・会社・会議室名・テナント名等)は全て escape する。
    # 正当な値(「A&B商事」等)でのレイアウト崩れ防止＋メール経由の任意HTML混入防止。
    e_name = escape(with_honorific(appt.visitor_name))
    e_tenant = escape(tenant_name)
    # brand_color は tenant 設定(#RRGGBB, 最大7文字)だが CSS 文脈に挿すので `#` 以外は落として無害化。
    accent = brand_color if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", brand_color or "") else "#4a7c4e"
    detail_html = "".join(
        f'<tr>'
        f'<td style="padding:6px 14px 6px 0;color:#8a8478;font-size:13px;white-space:nowrap;vertical-align:top">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#2d2a24;font-size:14px;font-weight:600">{escape(v)}</td>'
        f'</tr>'
        for k, v in rows
    )
    html = f"""\
<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f1ea;font-family:'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif">
  <div style="max-width:520px;margin:0 auto;padding:28px 16px">
    <div style="background:#fffefb;border:1px solid #e7e3d9;border-radius:16px;overflow:hidden">
      <div style="height:6px;background:{accent}"></div>
      <div style="padding:28px 30px">
        <p style="margin:0 0 4px;font-size:12px;color:#a8a198;letter-spacing:.04em">{e_tenant}</p>
        <h1 style="margin:0 0 18px;font-size:20px;color:#1d1a15">{e_name}</h1>
        <p style="margin:0 0 20px;font-size:14px;line-height:1.8;color:#4a463d">
          ご来社の予定をご案内いたします。当日は受付にて、<br>下記のQRコードを受付カメラにおかざしください。
        </p>
        <div style="text-align:center;margin:0 0 22px">
          <img src="cid:qr" alt="来社予定QRコード" width="220" height="220"
               style="width:220px;height:220px;border:1px solid #efece5;border-radius:12px;background:#fff;padding:10px">
        </div>
        <table style="width:100%;border-collapse:collapse;margin:0 0 20px">{detail_html}</table>
        <p style="margin:0;font-size:11px;color:#c8c3b8;font-family:monospace;word-break:break-all">予約コード: {escape(appt.token)}</p>
      </div>
      <div style="padding:14px 30px;background:#f7f5f0;border-top:1px solid #efece5">
        <p style="margin:0;font-size:11px;color:#a8a198;line-height:1.7">
          ※このメールは送信専用です。ご返信いただけません。<br>— {e_tenant} 受付システム
        </p>
      </div>
    </div>
  </div>
</body></html>"""
    return subject, text, html


@router.post("/{appt_id}/send-email")
async def send_appointment_email(
    appt_id: str,
    body: SendEmailRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """来社予定のQRコードを指定メールアドレスへ送信する。宛先は保存しない(都度入力)。"""
    if not settings.smtp_enabled:
        raise HTTPException(
            status_code=503,
            detail="メール送信が設定されていません。管理者にSMTPの設定をご依頼ください。",
        )

    # 予定 + 会議室 + テナントを取得(全てテナントスコープ)
    result = await db.execute(
        select(VisitorAppointment, MeetingRoom)
        .outerjoin(
            MeetingRoom,
            and_(
                VisitorAppointment.meeting_room_id == MeetingRoom.id,
                MeetingRoom.tenant_id == user.tenant_id,
            ),
        )
        .where(
            VisitorAppointment.id == appt_id,
            VisitorAppointment.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appt, room = row

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    ).scalar_one_or_none()
    tenant_name = tenant.name if tenant else settings.app_name
    brand_color = tenant.brand_color if tenant else "#4a7c4e"

    qr_png = email_service.build_appointment_qr_png(appt.token)
    subject, text, html = _build_appointment_email(tenant_name, brand_color, appt, room)

    ok, err = await email_service.send_email(
        to=body.email,
        subject=subject,
        html=html,
        text=text,
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_addr=settings.smtp_from or settings.smtp_username,
        from_name=settings.smtp_from_name or tenant_name,
        starttls=settings.smtp_starttls,
        use_ssl=settings.smtp_ssl,
        inline_images=[("qr", qr_png, "png")],
        attachments=[(f"QR_{appt.token[:8]}.png", qr_png, "image", "png")],
    )
    if not ok:
        raise HTTPException(status_code=502, detail=f"メール送信に失敗しました: {err}")
    return {"ok": True, "sent_to": body.email}
