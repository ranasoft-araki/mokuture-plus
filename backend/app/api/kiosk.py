"""Public kiosk endpoints — authenticated by device token, not JWT.

The device token is stored in the kiosk's localStorage and sent via
the X-Kiosk-Token header. It identifies both the device and the tenant.
"""
import asyncio
import hashlib
import logging
import os
import re
import secrets
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

_JST = zoneinfo.ZoneInfo("Asia/Tokyo")
logger = logging.getLogger(__name__)

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal, get_db
from app.models.device import Device, Locker
from app.models.tenant import Tenant
from app.models.content import Media, Playlist, PlaylistItem, Schedule
from app.models.reception import ReceptionLog
from app.models.notification import NotificationSetting, PushSubscription
from app.models.visitor_appointment import VisitorAppointment
from app.models.room import MeetingRoom
from app.services.slack import SlackNotifier
from app.services.storage import generate_presigned_get_url
from app.services.crypto import decrypt_dict
from app.services.webpush import send_push
from app.services.auth import hash_password, verify_password, create_decision_token
from app.config import settings

_PIN_RE = re.compile(r"^\d{4}$")


def _generate_delivery_pin() -> str:
    """Cryptographically-random 4-digit PIN for 置き配 (drop-off) lockers."""
    return f"{secrets.randbelow(10000):04d}"


# ローカルファースト構成では PIN を端末(agent)が保持する。管理画面の has_pin 表示のためだけに、
# backend 側には「照合不能な実bcryptハッシュ」を1つだけ使い回す(誰のPINにも一致しない)。
_mirror_sentinel_cache: str | None = None


def _mirror_pin_sentinel() -> str:
    global _mirror_sentinel_cache
    if _mirror_sentinel_cache is None:
        _mirror_sentinel_cache = hash_password(secrets.token_hex(16))
    return _mirror_sentinel_cache


router = APIRouter(prefix="/kiosk", tags=["kiosk"])
_limiter = Limiter(key_func=get_remote_address)

_ALLOWED_METHODS = {"form", "qr", "appointment"}

# ── OTA bundle ────────────────────────────────────────────────────────────────
# Env var override; default resolves to <repo>/kiosk_agent relative to this file.
_KIOSK_AGENT_DIR = Path(
    os.environ.get("KIOSK_BUNDLE_DIR", str(Path(__file__).parents[3] / "kiosk_agent"))
)

# Files distributed via OTA (relative to kiosk_agent root); order is stable for hashing.
BUNDLE_FILES = [
    "static/kiosk.html",
    "static/tap.mp3",   # タップ操作音の音源(Business22-3 を参考に合成)。kiosk.html が /tap.mp3 で再生
    "main.py",
    "updater.py",
    "gpio.py",
    "sync.py",
    "state.py",
    "config.py",
]
_FORCE_WINDOW_SEC = 7200  # force flag stays active for 2 hours after trigger


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _bundle_version() -> str:
    parts = []
    for rel in BUNDLE_FILES:
        p = _KIOSK_AGENT_DIR / rel
        if p.exists():
            parts.append(f"{rel}:{_file_sha(p)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class RegisterRequest(BaseModel):
    tenant_slug: str
    device_name: str | None = None
    location: str | None = None
    hardware_id: str | None = None


_DEFAULT_DEVICE_NAME = "新しい端末"


@router.post("/register")
@_limiter.limit("20/minute")
async def register_device(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """端末の自己登録（PIN 不要）。承認待ち(status=pending)の Device を作成し、
    デバイストークンを返す。端末はトークンで status をポーリングし、管理画面で
    承認(active)されると起動する。

    (tenant_slug, hardware_id) が既存端末に一致する場合は再作成せず、その端末の
    トークンと現在の status を返す（再起動・キャッシュ消去での重複登録を防ぐ）。"""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == body.tenant_slug))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="テナントが見つかりません")

    hardware_id = (body.hardware_id or "").strip() or None
    if hardware_id:
        existing_result = await db.execute(
            select(Device).where(
                Device.tenant_id == tenant.id,
                Device.hardware_id == hardware_id,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            existing.last_seen_at = datetime.now(_JST).replace(tzinfo=None)
            await db.commit()
            return {
                "device_token": existing.token,
                "device_name": existing.name,
                "status": existing.status or "active",
            }

    name = (body.device_name or "").strip() or _DEFAULT_DEVICE_NAME
    if len(name) > 100:
        name = name[:100]
    location = (body.location or "").strip() or None
    device = Device(
        tenant_id=tenant.id,
        name=name,
        location=location,
        token=secrets.token_hex(32),  # 64-char hex, cryptographically secure
        status="pending",
        hardware_id=hardware_id,
        last_seen_at=datetime.now(_JST).replace(tzinfo=None),
    )
    db.add(device)
    try:
        await db.commit()
    except IntegrityError:
        # 同一 (tenant_id, hardware_id) の並行登録と競合 → 既存端末を返す（冪等）
        await db.rollback()
        if hardware_id:
            existing_result = await db.execute(
                select(Device).where(
                    Device.tenant_id == tenant.id,
                    Device.hardware_id == hardware_id,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing is not None:
                return {
                    "device_token": existing.token,
                    "device_name": existing.name,
                    "status": existing.status or "active",
                }
        raise
    await db.refresh(device)
    return {"device_token": device.token, "device_name": device.name, "status": device.status}


async def get_kiosk_device(
    x_kiosk_token: str = Header(alias="X-Kiosk-Token"),
    db: AsyncSession = Depends(get_db),
) -> tuple[Tenant, Device]:
    result = await db.execute(select(Device).where(Device.token == x_kiosk_token))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")

    device.last_seen_at = datetime.now(_JST).replace(tzinfo=None)
    await db.commit()

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == device.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")

    return tenant, device


@router.post("/heartbeat", status_code=200)
async def kiosk_heartbeat(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device)):
    """軽量生存確認。get_kiosk_device が last_seen_at を更新するためここでの追加処理不要。"""
    return {"ok": True}


@router.get("/status")
async def kiosk_status(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device)):
    """承認状態の軽量ポーリング用。承認待ち画面がこれを見て active になったら起動する。
    get_kiosk_device が last_seen_at を更新するので、承認待ち端末も管理画面で「稼働中」に見える。"""
    tenant, device = ctx
    return {"status": device.status or "active", "device_name": device.name}


@router.get("/schedule")
async def kiosk_schedule(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device), db: AsyncSession = Depends(get_db)):
    """Return the current scheduled playlist with embedded media data."""
    tenant, device = ctx

    # 承認待ち端末はスケジュールを返さない — キオスクは承認待ち画面を表示する
    if (device.status or "active") == "pending":
        return {"pending": True, "playlist": None, "force_update_at": None, "device_name": device.name}

    # Return suspension status immediately — kiosk handles UI
    if tenant.is_suspended:
        return {"suspended": True, "message": "このテナントは現在停止中です", "playlist": None, "force_update_at": None, "device_name": device.name}

    now = datetime.now(_JST)
    day = now.weekday()
    time_str = now.strftime("%H:%M")

    result = await db.execute(
        select(Schedule).where(
            Schedule.tenant_id == tenant.id,
            (Schedule.day_of_week == day) | (Schedule.day_of_week == -1),
            Schedule.start_time <= time_str,
            Schedule.end_time > time_str,
        )
    )
    schedule = result.scalars().first()
    force_update_at = device.force_update_at.isoformat() if device.force_update_at else None

    if schedule is None:
        return {"playlist": None, "force_update_at": force_update_at, "device_name": device.name}

    pl_result = await db.execute(select(Playlist).where(Playlist.id == schedule.playlist_id))
    pl = pl_result.scalar_one_or_none()
    if pl is None:
        return {"playlist": None, "force_update_at": force_update_at, "device_name": device.name}

    items_result = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.playlist_id == pl.id)
        .order_by(PlaylistItem.display_order)
    )
    items = items_result.scalars().all()

    if not items:
        return {"playlist": {"id": pl.id, "name": pl.name, "items": []}, "force_update_at": force_update_at, "device_name": device.name}

    media_ids = [i.media_id for i in items]
    media_result = await db.execute(
        select(Media).where(Media.id.in_(media_ids), Media.tenant_id == tenant.id)
    )
    media_map = {m.id: m for m in media_result.scalars()}

    storage_base = settings.storage_public_url.rstrip("/") + "/"

    def _media_url(url: str) -> str:
        if url.startswith(storage_base):
            return generate_presigned_get_url(url.removeprefix(storage_base), expires_in=3600)
        return url

    return {
        "playlist": {
            "id": pl.id,
            "name": pl.name,
            "transition_type": pl.transition_type,
            "items": [
                {
                    "id": i.id,
                    "media_id": i.media_id,
                    "display_order": i.display_order,
                    "duration_sec": i.duration_sec,
                    "media": (
                        {
                            "id": m.id,
                            "url": _media_url(m.url),
                            "mime_type": m.mime_type,
                            "filename": m.filename,
                        }
                        if (m := media_map.get(i.media_id))
                        else None
                    ),
                }
                for i in items
            ],
        },
        "force_update_at": force_update_at,
        "device_name": device.name,
    }


@router.get("/content-manifest")
async def kiosk_content_manifest(ctx: tuple[Tenant, Device] = Depends(get_kiosk_device), db: AsyncSession = Depends(get_db)):
    """Return all scheduled-playlist media for local device caching."""
    tenant, _ = ctx

    sched_result = await db.execute(
        select(Schedule.playlist_id).where(
            Schedule.tenant_id == tenant.id,
            Schedule.playlist_id.isnot(None),
        ).distinct()
    )
    playlist_ids = [row[0] for row in sched_result.all()]
    if not playlist_ids:
        return {"items": []}

    items_result = await db.execute(
        select(PlaylistItem.media_id).where(
            PlaylistItem.playlist_id.in_(playlist_ids)
        ).distinct()
    )
    media_ids = [row[0] for row in items_result.all()]
    if not media_ids:
        return {"items": []}

    media_result = await db.execute(
        select(Media).where(Media.id.in_(media_ids), Media.tenant_id == tenant.id)
    )
    media_list = media_result.scalars().all()

    storage_base = settings.storage_public_url.rstrip("/") + "/"

    def _download_url(url: str) -> str:
        if url.startswith(storage_base):
            return generate_presigned_get_url(url.removeprefix(storage_base), expires_in=3600)
        return url

    return {
        "items": [
            {
                "id": m.id,
                "filename": m.filename,
                "mime_type": m.mime_type,
                "size_bytes": m.size_bytes,
                "url": _download_url(m.url),
            }
            for m in media_list
        ]
    }


class ReceptionCreate(BaseModel):
    visitor_name: str
    company: str | None = None
    purpose: str | None = None
    staff: str | None = None
    method: str = "form"
    appointment_id: str | None = None

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


@router.get("/appointment/{token}")
async def kiosk_get_appointment(
    token: str,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """QR トークンから来社予定を取得（デバイストークン認証）"""
    tenant, _ = ctx
    result = await db.execute(
        select(VisitorAppointment).where(
            VisitorAppointment.token == token,
            VisitorAppointment.tenant_id == tenant.id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    meeting_room = None
    if appt.meeting_room_id:
        room_result = await db.execute(
            select(MeetingRoom).where(
                MeetingRoom.id == appt.meeting_room_id,
                MeetingRoom.tenant_id == tenant.id,
            )
        )
        room = room_result.scalar_one_or_none()
        if room is not None:
            meeting_room = {
                "name": room.name,
                "location": room.location,
                "map_image_url": room.map_image_url,
            }

    return {
        "id": appt.id,
        "visitor_name": appt.visitor_name,
        "company": appt.company,
        "purpose": appt.purpose,
        "staff": appt.staff,
        "scheduled_at": appt.scheduled_at.isoformat(),
        "status": appt.status,
        "meeting_room": meeting_room,
    }


@router.post("/reception", status_code=201)
async def kiosk_reception(
    body: ReceptionCreate,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Submit a reception form entry using device token authentication."""
    tenant, _ = ctx
    log = ReceptionLog(
        tenant_id=tenant.id,
        visitor_name=body.visitor_name,
        company=body.company,
        purpose=body.purpose,
        staff=body.staff,
        method=body.method,
        appointment_id=body.appointment_id,
    )
    db.add(log)

    # チェックイン時に予約ステータスを更新
    if body.appointment_id:
        appt_result = await db.execute(
            select(VisitorAppointment).where(
                VisitorAppointment.id == body.appointment_id,
                VisitorAppointment.tenant_id == tenant.id,
            )
        )
        appt = appt_result.scalar_one_or_none()
        if appt:
            appt.status = "received"

    await db.commit()
    await db.refresh(log)

    await _notify_slack(tenant.id, log, db)
    await _notify_push(tenant.id, log, db)
    await _notify_webhook(tenant.id, log, db)

    return {
        "id": log.id,
        "visitor_name": log.visitor_name,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }


@router.get("/reception/{log_id}")
async def kiosk_reception_status(
    log_id: str,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """キオスクの待機画面がポーリングして、スタッフの OK/NG 応答結果(state)を取得する。"""
    tenant, _ = ctx
    result = await db.execute(select(ReceptionLog).where(ReceptionLog.id == log_id))
    log = result.scalar_one_or_none()
    if log is None or log.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Reception log not found")
    return {"id": log.id, "state": log.state}


# ── Staff call (delivery) ──────────────────────────────────────────────────────

class CallStaffBody(BaseModel):
    message: str | None = None


@router.post("/call-staff")
async def kiosk_call_staff(
    body: CallStaffBody,
    background: BackgroundTasks,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Notify staff that delivery is waiting (配達の呼び出し) over all configured channels.

    通知はレスポンス送出後にバックグラウンドで送る（Slack / Web Push / Webhook / Chatwork,
    best-effort）。遅い/失敗するチャネルがあってもキオスクの応答をブロックしない。
    """
    tenant, device = ctx
    message = (body.message or "").strip() or None
    device_label = device.name or "受付端末"

    # 呼び出しを受付ログに残す。スタッフが 受付/電話 で応答でき、その結果をキオスクが
    # ポーリングして結果画面へ遷移できるようにする（来訪者受付と同じ仕組み。ただし配達では
    # お断りは無く 受付/電話 の2択）。company に呼び出し元端末、purpose に用件を入れて一覧で分かる。
    log = ReceptionLog(
        tenant_id=tenant.id,
        visitor_name="配達",
        company=device_label,
        purpose="配達の呼び出し" + (f"（{message}）" if message else ""),
        method="delivery",
        state="received",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    title = "配達の呼び出し"
    text = f"🔔 配達の呼び出し\n「{device_label}」から呼び出しがあります。{message or ''}"

    # 通知タップで該当受付の対応モーダル(受付/電話)を直接開かせる。
    push_url = f"/{tenant.id}/admin/reception?respond={log.id}"

    background.add_task(
        _fire_delivery_notifications,
        tenant.id,
        title,
        text,
        {
            "event": "call_staff",
            "tenant_id": tenant.id,
            "kind": "delivery",
            "device": device_label,
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        push_url,
    )

    # id を返してキオスクの待機画面が応答(受付/電話)をポーリングできるようにする。
    return {"ok": True, "id": log.id}


# ── Lockers (device token auth) ────────────────────────────────────────────────

class LockerPinBody(BaseModel):
    pin: str


async def _get_kiosk_locker(locker_id: str, tenant_id: str, db: AsyncSession) -> Locker:
    result = await db.execute(
        select(Locker).where(Locker.id == locker_id, Locker.tenant_id == tenant_id)
    )
    locker = result.scalar_one_or_none()
    if locker is None:
        raise HTTPException(status_code=404, detail="Locker not found")
    return locker


@router.get("/lockers")
async def kiosk_list_lockers(
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """List this tenant's lockers for the kiosk. Never exposes pin_hash."""
    tenant, _ = ctx
    result = await db.execute(
        select(Locker).where(Locker.tenant_id == tenant.id).order_by(Locker.door_number)
    )
    lockers = result.scalars().all()
    available = sum(1 for l in lockers if not l.occupied)
    return {
        "lockers": [
            {
                "id": l.id,
                "name": l.name or f"ロッカー {l.door_number}",
                "door_number": l.door_number,
                "occupied": bool(l.occupied),
                "has_pin": l.pin_hash is not None,
            }
            for l in lockers
        ],
        "available_count": available,
    }


@router.post("/lockers/open-all")
async def kiosk_open_all_lockers(
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """全ロッカーを解放(利用状態・PINをリセット)。物理開錠はキオスク側がGPIOで実施するため
    door_number の一覧を返す。緊急/メンテナンス用(設定画面のスタッフ操作)。"""
    tenant, _ = ctx
    result = await db.execute(
        select(Locker).where(Locker.tenant_id == tenant.id).order_by(Locker.door_number)
    )
    lockers = result.scalars().all()
    doors = [l.door_number for l in lockers]
    for l in lockers:
        l.occupied = False
        l.pin_hash = None
        l.occupied_at = None
    await db.commit()
    return {"ok": True, "door_numbers": doors, "count": len(doors)}


@router.post("/lockers/{locker_id}/occupy")
async def kiosk_occupy_locker(
    locker_id: str,
    body: LockerPinBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Hold a locker with a 4-digit PIN."""
    tenant, _ = ctx
    if not _PIN_RE.match(body.pin or ""):
        raise HTTPException(status_code=422, detail="pin must be exactly 4 digits")
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)
    if locker.occupied:
        raise HTTPException(status_code=409, detail="already occupied")
    locker.pin_hash = hash_password(body.pin)
    locker.occupied = True
    locker.occupied_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"ok": True}


@router.post("/lockers/{locker_id}/occupy-delivery")
async def kiosk_occupy_locker_delivery(
    locker_id: str,
    background: BackgroundTasks,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """置き配: 扉を閉じたタイミングでランダム4桁PINを自動設定して施錠し、
    「どのロッカーにこのPINで置き配されたか」を担当者へ通知する(best-effort)。

    PINは配達員には表示しない(キオスクUIは暗証番号不要のまま)。担当者は通知で
    受け取ったPINでロッカー画面から解錠して受け取る。"""
    tenant, device = ctx
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)
    if locker.occupied:
        raise HTTPException(status_code=409, detail="already occupied")
    pin = _generate_delivery_pin()
    locker.pin_hash = hash_password(pin)
    locker.occupied = True
    locker.occupied_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    locker_label = locker.name or f"ロッカー {locker.door_number}"
    device_label = device.name or "受付端末"
    title = "置き配のお知らせ"
    text = (
        f"📦 置き配がありました\n"
        f"「{locker_label}」に置き配されました。\n"
        f"解錠パスワード: {pin}\n"
        f"(受付端末: {device_label})"
    )

    # 通知はレスポンス送出後にバックグラウンドで送る（遅い/失敗するチャネルで施錠フローを止めない）
    background.add_task(
        _fire_delivery_notifications,
        tenant.id,
        title,
        text,
        {
            "event": "delivery_dropoff",
            "tenant_id": tenant.id,
            "kind": "delivery",
            "locker": locker_label,
            "door_number": locker.door_number,
            "pin": pin,
            "device": device_label,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {"ok": True}


@router.post("/lockers/{locker_id}/release")
async def kiosk_release_locker(
    locker_id: str,
    body: LockerPinBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """Release a held locker by verifying its 4-digit PIN."""
    tenant, _ = ctx
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)
    if not locker.occupied:
        raise HTTPException(status_code=409, detail="not occupied")
    # No-pin hold (should not happen in Phase 2): allow release.
    if locker.pin_hash is None:
        locker.occupied = False
        locker.occupied_at = None
        await db.commit()
        return {"ok": True, "door_number": locker.door_number}
    if not verify_password(body.pin or "", locker.pin_hash):
        raise HTTPException(status_code=403, detail="invalid pin")
    locker.pin_hash = None
    locker.occupied = False
    locker.occupied_at = None
    await db.commit()
    return {"ok": True, "door_number": locker.door_number}


class DeliveryNotifyBody(BaseModel):
    """ローカルファースト構成の agent から受ける置き配通知リクエスト。
    PINは端末が生成・保持し、ここへは通知目的で平文が渡る。状態は変更しない。"""
    pin: str | None = None
    locker_label: str | None = None
    device_name: str | None = None


@router.post("/lockers/{locker_id}/notify-delivery")
async def kiosk_notify_delivery(
    locker_id: str,
    body: DeliveryNotifyBody,
    background: BackgroundTasks,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """ローカルファースト置き配の通知だけを担当者へ発火する(best-effort)。

    施錠・PIN生成・照合は agent がローカルで行う(端末が権威)。ここでは占有状態を変更せず、
    「どのロッカーにこのPINで置き配されたか」を通知するのみ。可視化は /lockers/mirror が担う。
    旧経路 /lockers/{id}/occupy-delivery はサーバ側PIN生成のまま後方互換で残置。"""
    tenant, device = ctx
    locker = await _get_kiosk_locker(locker_id, tenant.id, db)  # 存在＋テナント越境チェック
    pin = (body.pin or "").strip()
    locker_label = (body.locker_label or "").strip() or locker.name or f"ロッカー {locker.door_number}"
    device_label = (body.device_name or "").strip() or device.name or "受付端末"
    title = "置き配のお知らせ"
    text = (
        f"📦 置き配がありました\n"
        f"「{locker_label}」に置き配されました。\n"
        f"解錠パスワード: {pin}\n"
        f"(受付端末: {device_label})"
    )
    background.add_task(
        _fire_delivery_notifications,
        tenant.id,
        title,
        text,
        {
            "event": "delivery_dropoff",
            "tenant_id": tenant.id,
            "kind": "delivery",
            "locker": locker_label,
            "door_number": locker.door_number,
            "pin": pin,
            "device": device_label,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"ok": True}


class LockerMirrorItem(BaseModel):
    id: str
    occupied: bool = False
    has_pin: bool = False


class LockerMirrorBody(BaseModel):
    lockers: list[LockerMirrorItem] = []


@router.post("/lockers/mirror")
async def kiosk_mirror_lockers(
    body: LockerMirrorBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """ローカルファースト構成の agent から占有状態を best-effort ミラーする(管理画面表示用)。

    PIN 本体は受け取らない。occupied を反映し、has_pin は照合不能な表示専用センチネルで表す
    (置き配で実PINハッシュを既に持つ行は上書きしない)。agent が権威なので全件スナップショット
    を冪等に適用する。"""
    tenant, _ = ctx
    if not body.lockers:
        return {"ok": True, "updated": 0}
    ids = [str(it.id) for it in body.lockers]
    result = await db.execute(
        select(Locker).where(Locker.tenant_id == tenant.id, Locker.id.in_(ids))
    )
    by_id = {l.id: l for l in result.scalars().all()}
    updated = 0
    for it in body.lockers:
        locker = by_id.get(str(it.id))
        if locker is None:
            continue
        if it.occupied:
            locker.occupied = True
            if it.has_pin and not locker.pin_hash:
                locker.pin_hash = _mirror_pin_sentinel()
        else:
            locker.occupied = False
            locker.pin_hash = None
            locker.occupied_at = None
        updated += 1
    await db.commit()
    return {"ok": True, "updated": updated}


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
        # 送信先が確定していない場合(Bot連携済だがチャンネル未選択 等)はエラーではないので静かに終了。
        has_dest = bool(config.get("bot_access_token") and config.get("channel_id")) or bool(config.get("webhook_url"))
        if not has_dest:
            return
        msg = SlackNotifier.build_reception_message(
            visitor_name=log.visitor_name,
            company=log.company,
            host_name=log.staff,
            when=log.created_at,
        )
        # 署名シークレット設定時のみ、受付/電話/お断りの対応ボタン(Block Kit)を付ける。
        # Bot Token 経路のときだけ(webhook はインタラクション不可)。押下は署名トークンで検証。
        blocks = None
        if settings.slack_signing_secret and config.get("bot_access_token") and config.get("channel_id"):
            from app.api.reception import decision_actions
            token = create_decision_token(log.id, tenant_id)
            blocks = SlackNotifier.build_reception_blocks(msg, decision_actions(log), token)
        ok = await SlackNotifier.send_to_config(config, msg, blocks=blocks)
        if not ok:
            # 受付は失敗させない(best-effort)。エラーは残すが Bot Token/Webhook URL は絶対に出さない。
            logger.warning("Slack reception notification failed (tenant=%s, reception=%s)", tenant_id, log.id)
    except Exception:
        # decrypt/整形エラー等。秘密情報を含めないため exc_info は付けない。
        logger.warning("Slack reception notification error (tenant=%s, reception=%s)", tenant_id, log.id)


async def _notify_push(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    """Fire Web Push to all registered subscriptions for this tenant."""
    # Get VAPID keys (from per-tenant setting or global config)
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

    from app.api.reception import build_decision_push_extras
    data, actions = build_decision_push_extras(tenant_id, log)
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
            tag=f"reception-{log.id}",
            data=data,
            actions=actions,
        )  # fire-and-forget: ignore (bool, str) return


async def _send_webhook(url: str, data: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=data)
    except Exception:
        pass


async def _notify_webhook(tenant_id: str, log: ReceptionLog, db: AsyncSession) -> None:
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "webhook",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return
    try:
        config = decrypt_dict(setting.config_json)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            payload = {
                "event": "reception",
                "tenant_id": tenant_id,
                "visitor_name": log.visitor_name,
                "company": log.company,
                "staff": log.staff,
                "purpose": log.purpose,
                "method": log.method,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            await _send_webhook(webhook_url, payload)
    except Exception:
        pass


# ── Generic-message notify helpers (staff call etc.) ───────────────────────────

async def _first_configured_setting(
    tenant_id: str, types: tuple[str, ...], db: AsyncSession
) -> NotificationSetting | None:
    """Return the first NotificationSetting whose type matches (in preference order)
    and that actually has a config (config_json present and != "{}"). Tenant-scoped."""
    for type_ in types:
        result = await db.execute(
            select(NotificationSetting).where(
                NotificationSetting.tenant_id == tenant_id,
                NotificationSetting.type == type_,
            )
        )
        setting = result.scalar_one_or_none()
        if setting is not None and setting.config_json and setting.config_json != "{}":
            return setting
    return None


async def _notify_slack_text(
    tenant_id: str, text: str, db: AsyncSession, types: tuple[str, ...] = ("slack",)
) -> None:
    """Send a plain text message to the first configured Slack webhook among ``types``.

    Best-effort. ``types`` is an ordered preference (e.g. delivery-specific first,
    then the normal reception destination as fallback)."""
    setting = await _first_configured_setting(tenant_id, types, db)
    if setting is None:
        return
    try:
        config = decrypt_dict(setting.config_json)
        # Bot Token(chat.postMessage) と 旧Webhook のどちらの設定でも送れる。
        await SlackNotifier.send_to_config(config, text)
    except Exception:
        pass


async def _push_delivery_enabled(tenant_id: str, db: AsyncSession) -> bool:
    """Whether Web Push should fire for the 配達の呼び出し flow.

    ON by default (backward compatible) — only a stored ``push_delivery`` setting
    with ``enabled == False`` disables it. Tenant-scoped."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == "push_delivery",
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return True
    try:
        return decrypt_dict(setting.config_json).get("enabled", True) is not False
    except Exception:
        return True


async def _notify_push_text(
    tenant_id: str, title: str, body: str, url_tenant_id: str, db: AsyncSession,
    url: str | None = None,
) -> None:
    """Fire Web Push with a plain title/body to all subscriptions. Best-effort.

    ``url`` は通知タップ時に開くURL。未指定なら受付ログ一覧を開く。"""
    target_url = url or f"/{url_tenant_id}/admin/reception"
    try:
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

        for sub in subs:
            try:
                await send_push(
                    endpoint=sub.endpoint,
                    p256dh=sub.p256dh,
                    auth=sub.auth_key,
                    title=title,
                    body=body,
                    url=target_url,
                    private_key=private_key,
                    subject=settings.vapid_subject,
                )
            except Exception:
                pass
    except Exception:
        pass


async def _notify_webhook_event(
    tenant_id: str, payload: dict, db: AsyncSession, types: tuple[str, ...] = ("webhook",)
) -> None:
    """POST an arbitrary event payload to the first configured webhook among ``types``.

    Best-effort. ``types`` is an ordered preference (delivery-specific first, then
    the normal reception destination as fallback)."""
    setting = await _first_configured_setting(tenant_id, types, db)
    if setting is None:
        return
    try:
        config = decrypt_dict(setting.config_json)
        webhook_url = config.get("webhook_url", "")
        if webhook_url:
            await _send_webhook(webhook_url, payload)
    except Exception:
        pass


async def _notify_chatwork_text(
    tenant_id: str, text: str, db: AsyncSession, types: tuple[str, ...] = ("chatwork",)
) -> None:
    """Post a message to the first configured Chatwork room among ``types``.

    Best-effort. ``types`` is an ordered preference (delivery-specific first, then
    the normal reception destination as fallback)."""
    setting = await _first_configured_setting(tenant_id, types, db)
    if setting is None:
        return
    try:
        config = decrypt_dict(setting.config_json)
        api_token = config.get("api_token", "")
        room_id = config.get("room_id", "")
        if not api_token or not room_id:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.chatwork.com/v2/rooms/{room_id}/messages",
                headers={"X-ChatWorkToken": api_token},
                data={"body": text},
            )
    except Exception:
        pass


async def _fire_delivery_notifications(
    tenant_id: str, title: str, text: str, webhook_payload: dict, push_url: str | None = None
) -> None:
    """置き配/呼び出しの通知を新しいDBセッションで並行送信する（BackgroundTasks 用）。

    レスポンス送出後に実行されるため、遅い/無効な通知先（例: 死んだ Web Push 購読）が
    あってもキオスクの受付・施錠をブロックせず、エージェント側の10秒タイムアウト
    （= キオスクに出る「APIエラー」）を防ぐ。各チャネルは best-effort。"""
    try:
        async with AsyncSessionLocal() as db:
            tasks = [
                _notify_slack_text(tenant_id, text, db, types=("slack_delivery", "slack")),
                _notify_webhook_event(tenant_id, webhook_payload, db, types=("webhook_delivery", "webhook")),
                _notify_chatwork_text(tenant_id, text, db, types=("chatwork_delivery", "chatwork")),
            ]
            if await _push_delivery_enabled(tenant_id, db):
                tasks.append(_notify_push_text(tenant_id, title, text, tenant_id, db, push_url))
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        pass


# ── OTA bundle endpoints ───────────────────────────────────────────────────────

@router.get("/bundle/manifest")
async def kiosk_bundle_manifest(
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
):
    """Return current bundle version + per-file hashes. Device uses this to detect changes."""
    tenant, _ = ctx
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    force = False
    fat = getattr(tenant, "kiosk_force_update_at", None)
    if fat is not None:
        diff = (now - fat).total_seconds()
        force = 0 <= diff <= _FORCE_WINDOW_SEC

    files = []
    for rel in BUNDLE_FILES:
        p = _KIOSK_AGENT_DIR / rel
        if p.exists():
            files.append({"path": rel, "hash": _file_sha(p), "size": p.stat().st_size})

    return {"version": _bundle_version(), "files": files, "force": force}


@router.get("/bundle/file/{file_path:path}")
async def kiosk_bundle_file(
    file_path: str,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
):
    """Download a single bundle file. Path must be in BUNDLE_FILES whitelist."""
    if file_path not in BUNDLE_FILES:
        raise HTTPException(status_code=404, detail="Not in bundle")
    p = _KIOSK_AGENT_DIR / file_path
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p)
