"""Public kiosk endpoints — authenticated by device token, not JWT.

The device token is stored in the kiosk's localStorage and sent via
the X-Kiosk-Token header. It identifies both the device and the tenant.
"""
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import secrets
import zoneinfo
from datetime import datetime, timedelta, timezone
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

# 審査用デモモードの自動返信タスク参照(fire-and-forget の GC 回避に保持)。
_demo_auto_tasks: set[asyncio.Task] = set()


async def _demo_auto_accept(tenant_id: str, log_id: str) -> None:
    """審査用デモ: 実通知の後に担当者の「受付(参ります)」応答を自動再現する。

    展示・審査ではスマホ側で担当者が返信する人手が無いので、3〜5秒待ってから accepted を
    確定させる＝キオスクは本番と同じ `GET /kiosk/reception/{id}` ポーリングで結果画面へ遷移する。
    `_apply_decision` は idempotent(確定後は上書き不可)なので、万一実担当者が先に押しても衝突しない。
    通知タスク(Slack join 等で最大〜30s)と別の task にして、体感タイミングを本番同様に保つ。"""
    lo = settings.demo_auto_reply_min_sec
    hi = max(lo, settings.demo_auto_reply_max_sec)
    await asyncio.sleep(random.uniform(lo, hi))
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ReceptionLog).where(
                    ReceptionLog.id == log_id,
                    ReceptionLog.tenant_id == tenant_id,
                )
            )
            log = result.scalar_one_or_none()
            if log is None:
                return
            from app.api.reception import _apply_decision
            await _apply_decision(db, log, "accept")
    except Exception:
        logger.warning("demo auto-accept failed (tenant=%s, reception=%s)", tenant_id, log_id)


def _spawn_demo_auto_accept(tenant_id: str, log_id: str) -> None:
    task = asyncio.create_task(_demo_auto_accept(tenant_id, log_id))
    _demo_auto_tasks.add(task)
    task.add_done_callback(_demo_auto_tasks.discard)


def _generate_delivery_pin() -> str:
    """Cryptographically-random 4-digit PIN for 置き配 (drop-off) lockers."""
    return f"{secrets.randbelow(10000):04d}"


def _mirror_int(v) -> int | None:
    """ミラー item の door_number/id を安全に int 化（数値でなければ None）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


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
    "static/tap.mp3",   # タップ操作音の音源(木琴C6の単音。VSQ plus+のフリー効果音を加工)。kiosk.html が /tap.mp3 で再生
    "main.py",
    "updater.py",
    "gpio.py",
    "sync.py",
    "state.py",
    "config.py",
    "locker_store.py",  # ロッカーのローカル状態・ミラーペイロード生成。agent の MANAGED_FILES と一致させる
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
            existing.last_seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
        last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 連続オンライン開始時刻(online_since)を維持する。前回接続から3分超の空白があれば
    # 「一度オフラインになった」とみなしてリセット。連続稼働時間 = now - online_since。
    # 注: 本番Neonの日時列は timestamptz で aware に読み戻るため、naive の now と引き算する前に
    # naive-UTC へ揃える（揃えないと aware/naive 混在で TypeError→500。SQLite開発では naive で素通り）。
    prev = device.last_seen_at
    if prev is not None and prev.tzinfo is not None:
        prev = prev.astimezone(timezone.utc).replace(tzinfo=None)
    if device.online_since is None or prev is None or (now - prev) > timedelta(minutes=3):
        device.online_since = now
    device.last_seen_at = now
    await db.commit()

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == device.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid kiosk token")

    return tenant, device


class HeartbeatBody(BaseModel):
    version: str | None = None
    ip: str | None = None


@router.post("/heartbeat", status_code=200)
async def kiosk_heartbeat(
    body: HeartbeatBody | None = None,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """軽量生存確認。last_seen_at/online_since は get_kiosk_device が更新する。
    エージェントが版数/IP を body で送ってきたら端末テレメトリとして保存する(任意・後方互換)。"""
    _, device = ctx
    changed = False
    if body is not None:
        v = (body.version or "").strip()
        if v and v != device.agent_version:
            device.agent_version = v[:32]
            changed = True
        ip = (body.ip or "").strip()
        if ip and ip != device.ip_address:
            device.ip_address = ip[:64]
            changed = True
    if changed:
        await db.commit()
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

    async def _set_current_playlist(pid: str | None) -> None:
        """現在配信中のプレイリストを端末行に記録する（管理画面の「現在のプレイリスト」表示用）。変化時のみ commit。"""
        if device.current_playlist_id != pid:
            device.current_playlist_id = pid
            await db.commit()

    # 承認待ち端末はスケジュールを返さない — キオスクは承認待ち画面を表示する
    if (device.status or "active") == "pending":
        await _set_current_playlist(None)
        return {"pending": True, "playlist": None, "force_update_at": None, "device_name": device.name}

    # Return suspension status immediately — kiosk handles UI
    if tenant.is_suspended:
        await _set_current_playlist(None)
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
        await _set_current_playlist(None)
        return {"playlist": None, "force_update_at": force_update_at, "device_name": device.name}

    pl_result = await db.execute(select(Playlist).where(Playlist.id == schedule.playlist_id))
    pl = pl_result.scalar_one_or_none()
    if pl is None:
        await _set_current_playlist(None)
        return {"playlist": None, "force_update_at": force_update_at, "device_name": device.name}

    await _set_current_playlist(pl.id)

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
    department: str | None = None
    method: str = "form"
    appointment_id: str | None = None

    @field_validator("department")
    @classmethod
    def department_len(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        return v[:255]

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
    background: BackgroundTasks,
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
        department=body.department,
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

    # 通知はレスポンス送出後にバックグラウンドで送る（Slack / Web Push / Webhook, best-effort）。
    # inline で await すると通知の往復ぶんキオスク(agent)の応答待ちが延び、10秒プロキシタイムアウトを
    # 超えてキオスクに「リモートAPIに接続できません」が出る（配達系と同じ理由で非ブロック化する）。
    background.add_task(_fire_reception_notifications, tenant.id, log)

    # 審査用デモモード: 実通知の後、担当者返信「受付(参ります)」をサーバ側で自動再現する。
    # 通知は上の BackgroundTasks で即送信し、こちらは別 task で 3〜5 秒後に accepted を確定させる。
    if getattr(tenant, "is_demo", False):
        _spawn_demo_auto_accept(tenant.id, log.id)

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
        log,  # decision_log: 受付/電話 の対応ボタンを Slack/Push に付ける
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
    door_number = locker.door_number  # ORM属性はここで退避（下の _log_delivery_dropoff が rollback すると失効するため）
    device_label = device.name or "受付端末"
    title = "置き配のお知らせ"
    text = (
        f"📦 置き配がありました\n"
        f"「{locker_label}」に置き配されました。\n"
        f"解錠パスワード: {pin}\n"
        f"(受付端末: {device_label})"
    )

    # 通知を見逃しても後からPINを確認できるよう受付ログにも残す（best-effort）
    dropoff_log_id = await _log_delivery_dropoff(db, tenant.id, locker_label, pin, device_label)

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
            "door_number": door_number,
            "pin": pin,
            "device": device_label,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        dropoff_log_id=dropoff_log_id,
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

    施錠・PIN生成・照合・台帳(何口あるか)は agent がローカルで行う(端末が権威)。ここでは
    DB の lockers 行に依存せず（管理画面でロッカーを作っていなくても動く）、agent が渡す
    ラベル/PIN/端末名だけで「どのロッカーにこのPINで置き配されたか」を通知する。
    locker_id は端末側の識別子(door_number)。旧経路 /lockers/{id}/occupy-delivery は
    サーバ側PIN生成のまま後方互換で残置。"""
    tenant, device = ctx
    pin = (body.pin or "").strip()
    locker_label = (body.locker_label or "").strip() or f"ロッカー {locker_id}"
    device_label = (body.device_name or "").strip() or device.name or "受付端末"
    try:
        door_number: object = int(locker_id)
    except (TypeError, ValueError):
        door_number = locker_id
    title = "置き配のお知らせ"
    text = (
        f"📦 置き配がありました\n"
        f"「{locker_label}」に置き配されました。\n"
        f"解錠パスワード: {pin}\n"
        f"(受付端末: {device_label})"
    )
    # 通知を見逃しても後からPINを確認できるよう受付ログにも残す（best-effort）
    dropoff_log_id = await _log_delivery_dropoff(db, tenant.id, locker_label, pin, device_label)
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
            "door_number": door_number,
            "pin": pin,
            "device": device_label,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        dropoff_log_id=dropoff_log_id,
    )
    return {"ok": True}


class LockerMirrorItem(BaseModel):
    id: str
    occupied: bool = False
    has_pin: bool = False
    # 新 agent は表示用に name/door_number/kind も送る（旧 agent は id/occupied/has_pin のみ）。
    name: str | None = None
    door_number: int | None = None
    kind: str | None = None


class LockerMirrorBody(BaseModel):
    lockers: list[LockerMirrorItem] = []


@router.post("/lockers/mirror")
async def kiosk_mirror_lockers(
    body: LockerMirrorBody,
    ctx: tuple[Tenant, Device] = Depends(get_kiosk_device),
    db: AsyncSession = Depends(get_db),
):
    """ローカルファースト構成の agent から占有状態を best-effort ミラーする(管理画面の表示専用)。

    ロッカーは各端末の GPIO 直結＝端末が真実の源。PIN 本体は受け取らず、occupied/has_pin の
    ブール値のみを**端末ごとの全件スナップショット**として devices 行(locker_state_json)に保存する。
    DB の lockers 台帳には依存しない（管理画面でロッカーを作っていなくても状況が見える）。
    管理画面は GET /lockers/status で端末ごとに表示する。agent が権威なので冪等に丸ごと置換。"""
    _, device = ctx
    items = []
    for it in body.lockers:
        door = it.door_number if it.door_number is not None else _mirror_int(it.id)
        items.append({
            "id": str(it.id),
            "door_number": door,
            "name": it.name or f"ロッカー {door if door is not None else it.id}",
            "occupied": bool(it.occupied),
            "has_pin": bool(it.has_pin),
            "kind": it.kind,
        })
    device.locker_state_json = json.dumps(items, ensure_ascii=False)
    device.locker_state_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"ok": True, "updated": len(items)}


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
            department=log.department,
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
    if log.department:
        body += f" 部署：{log.department}"
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
                "department": log.department,
                "purpose": log.purpose,
                "method": log.method,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            await _send_webhook(webhook_url, payload)
    except Exception:
        pass


async def _fire_reception_notifications(tenant_id: str, log: ReceptionLog) -> None:
    """受付通知(Slack / Web Push / Webhook)をレスポンス送出後に新しいDBセッションで送る（BackgroundTasks 用）。

    inline で await すると通知の往復時間ぶんキオスク(agent)の応答待ちが延び、10秒プロキシタイムアウトを
    超えて「リモートAPIに接続できません」を招く（Slack chat.postMessage は未参加chの join+retry で最大
    ~30s、Web Push は死んだ購読を逐次送信）。配達系(_fire_delivery_notifications)と同様に非ブロック化する。
    log は呼び出し元で commit 済み（AsyncSessionLocal は expire_on_commit=False なので列値は失効せず、
    別セッションの本関数からも安全に読める）。各チャネルは best-effort（失敗しても受付は成立済み）。"""
    try:
        async with AsyncSessionLocal() as db:
            await _notify_slack(tenant_id, log, db)
            await _notify_push(tenant_id, log, db)
            await _notify_webhook(tenant_id, log, db)
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
    tenant_id: str, text: str, db: AsyncSession, types: tuple[str, ...] = ("slack",),
    decision: tuple[list[dict], str] | None = None,
) -> None:
    """Send a plain text message to the first configured Slack webhook among ``types``.

    Best-effort. ``types`` is an ordered preference (e.g. delivery-specific first,
    then the normal reception destination as fallback). ``decision`` = (actions, token)
    を渡すと、署名シークレット設定済み & Bot Token 経路のときだけ 受付/電話 の対応ボタン
    (Block Kit)を付ける。押下は受付通知と同じ interactions エンドポイントで処理される。"""
    setting = await _first_configured_setting(tenant_id, types, db)
    if setting is None:
        return
    try:
        config = decrypt_dict(setting.config_json)
        blocks = None
        if (decision is not None and settings.slack_signing_secret
                and config.get("bot_access_token") and config.get("channel_id")):
            actions, dtoken = decision
            blocks = SlackNotifier.build_reception_blocks(text, actions, dtoken)
        # Bot Token(chat.postMessage) と 旧Webhook のどちらの設定でも送れる(webhook はボタン無し)。
        await SlackNotifier.send_to_config(config, text, blocks=blocks)
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
    url: str | None = None, data: dict | None = None, actions: list | None = None,
    tag: str | None = None,
) -> None:
    """Fire Web Push with a plain title/body to all subscriptions. Best-effort.

    ``url`` は通知タップ時に開くURL。未指定なら受付ログ一覧を開く。``data``/``actions``/``tag``
    を渡すと、通知に 受付/電話 アクションボタン(SWが署名トークンで応答)を付けられる
    (配達の呼び出し用。受付通知と同じ仕組み)。"""
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
                    tag=tag or "reception",
                    data=data,
                    actions=actions,
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


async def _log_delivery_dropoff(
    db: AsyncSession, tenant_id: str, locker_label: str, pin: str, device_label: str
) -> str | None:
    """置き配を受付ログに記録する（best-effort）。記録できたら受付ログの id を返す。

    スタッフがプッシュ/Slack 等の通知を見逃しても、管理画面「受付ログ」から解錠PINを
    後追いで確認できるようにするための履歴。PINは一時的（受取時に端末側が破棄し、その番号は
    もう解錠に使えなくなる）ため、通知本文と同じく平文で残す。誰かの応答を待つ受付ではないので
    state=completed（受付/電話ボタンは出さない）。method="dropoff"（表示ラベル「置き配」）で
    配達の呼び出し(delivery)と区別する。DB書き込みが失敗しても通知・施錠フローは止めない。

    返す id は置き配プッシュの通知タップ先（?detail=<id>）に使い、受付ログ画面で該当置き配の
    詳細モーダル（解錠PINを大きく表示）を直接開かせる（受付応答通知の ?respond= と同じ導線）。"""
    try:
        log = ReceptionLog(
            tenant_id=tenant_id,
            visitor_name="置き配",
            company=locker_label or None,
            purpose=f"解錠PIN: {pin}" + (f"（受付端末: {device_label}）" if device_label else ""),
            method="dropoff",
            state="completed",
        )
        db.add(log)
        await db.commit()
        return log.id
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _fire_delivery_notifications(
    tenant_id: str, title: str, text: str, webhook_payload: dict, push_url: str | None = None,
    decision_log: "ReceptionLog | None" = None, dropoff_log_id: str | None = None,
) -> None:
    """置き配/呼び出しの通知を新しいDBセッションで並行送信する（BackgroundTasks 用）。

    レスポンス送出後に実行されるため、遅い/無効な通知先（例: 死んだ Web Push 購読）が
    あってもキオスクの受付・施錠をブロックせず、エージェント側の10秒タイムアウト
    （= キオスクに出る「APIエラー」）を防ぐ。各チャネルは best-effort。

    ``decision_log`` を渡すと（配達の呼び出し）、Slack/Web Push に 受付/電話 の対応ボタンを
    付ける。スタッフが通知から直接応答→`_apply_decision` で state=accepted→キオスクの待機画面が
    `GET /kiosk/reception/{id}` のポーリングで拾い「参ります」へ遷移する。log は呼び出し元で
    commit/refresh 済み（expire_on_commit=False のため列値は失効せず、別セッションの本関数からも安全に読める）。

    ``dropoff_log_id`` を渡すと（置き配）、応答ボタンは付けず、代わりに Web Push へ
    `kind=delivery_dropoff` / `logId` を載せる。通知本体タップで受付ログ画面の詳細モーダル
    （解錠PINを大きく表示）を直接開かせる（受付応答通知が対応モーダルを開くのと同じ導線）。"""
    slack_decision = None
    push_data = None
    push_actions = None
    push_tag = None
    if decision_log is not None:
        from app.api.reception import decision_actions, build_decision_push_extras
        dtoken = create_decision_token(decision_log.id, tenant_id)
        slack_decision = (decision_actions(decision_log), dtoken)
        push_data, push_actions = build_decision_push_extras(tenant_id, decision_log)
        push_tag = f"reception-{decision_log.id}"
    elif dropoff_log_id is not None:
        # 置き配: 応答不要なので受付/電話ボタンは付けない。通知タップで詳細モーダルを開く。
        push_data = {"kind": "delivery_dropoff", "logId": dropoff_log_id}
        push_tag = f"dropoff-{dropoff_log_id}"
        if push_url is None:
            push_url = f"/{tenant_id}/admin/reception?detail={dropoff_log_id}"
    try:
        async with AsyncSessionLocal() as db:
            tasks = [
                _notify_slack_text(tenant_id, text, db, types=("slack_delivery", "slack"), decision=slack_decision),
                _notify_webhook_event(tenant_id, webhook_payload, db, types=("webhook_delivery", "webhook")),
                _notify_chatwork_text(tenant_id, text, db, types=("chatwork_delivery", "chatwork")),
            ]
            if await _push_delivery_enabled(tenant_id, db):
                tasks.append(_notify_push_text(
                    tenant_id, title, text, tenant_id, db, push_url,
                    data=push_data, actions=push_actions, tag=push_tag,
                ))
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
