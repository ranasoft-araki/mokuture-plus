import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.content import Media, Playlist, PlaylistItem, Schedule
from app.models.user import User
from app.services import storage
from app.config import settings

router = APIRouter(prefix="/content", tags=["content"])

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


# ─── Media ──────────────────────────────────────────────────────────────────

class UploadUrlRequest(BaseModel):
    filename: str
    mime_type: str


class MediaCreate(BaseModel):
    media_id: str
    filename: str
    mime_type: str
    url: str
    size_bytes: int = 0
    duration_sec: float | None = None

    @field_validator("url")
    @classmethod
    def url_must_be_storage_origin(cls, v: str) -> str:
        # Only allow URLs from the configured storage public URL to prevent arbitrary URL injection
        allowed = settings.storage_public_url.rstrip("/")
        if not v.startswith(allowed):
            raise ValueError(f"URL must originate from configured storage ({allowed})")
        return v

    @field_validator("mime_type")
    @classmethod
    def mime_allowed(cls, v: str) -> str:
        from app.services.storage import ALLOWED_MIME_TYPES
        if v not in ALLOWED_MIME_TYPES:
            raise ValueError(f"MIME type not allowed: {v}")
        return v


class MediaOut(BaseModel):
    id: str
    filename: str
    mime_type: str
    url: str
    size_bytes: int
    duration_sec: float | None
    uploaded_at: str

    model_config = {"from_attributes": True}


@router.post("/media/upload", response_model=MediaOut, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    if len(data) > storage.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="ファイルサイズが大きすぎます（最大500MB）")
    try:
        result = storage.upload_file(
            user.tenant_id,
            file.filename or "upload",
            file.content_type or "application/octet-stream",
            data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    media = Media(
        id=result["media_id"],
        tenant_id=user.tenant_id,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        url=result["public_url"],
        size_bytes=len(data),
    )
    db.add(media)
    await db.commit()
    await db.refresh(media)
    return _media_out(media)


@router.post("/media/upload-url")
async def get_upload_url(body: UploadUrlRequest, user: User = Depends(get_current_user)):
    try:
        return storage.generate_presigned_upload_url(user.tenant_id, body.filename, body.mime_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/media", response_model=MediaOut, status_code=201)
async def register_media(
    body: MediaCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    media = Media(
        id=body.media_id,
        tenant_id=user.tenant_id,
        filename=body.filename,
        mime_type=body.mime_type,
        url=body.url,
        size_bytes=body.size_bytes,
        duration_sec=body.duration_sec,
    )
    db.add(media)
    await db.commit()
    await db.refresh(media)
    return _media_out(media)


@router.get("/media", response_model=list[MediaOut])
async def list_media(
    type_filter: str | None = Query(None, alias="type"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Media).where(Media.tenant_id == user.tenant_id).order_by(Media.uploaded_at.desc())
    if type_filter == "video":
        q = q.where(Media.mime_type == "video/mp4")
    elif type_filter == "image":
        q = q.where(Media.mime_type.in_(["image/jpeg", "image/png"]))
    result = await db.execute(q)
    return [_media_out(m) for m in result.scalars()]


@router.delete("/media/{media_id}", status_code=204)
async def delete_media(
    media_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Media).where(Media.id == media_id, Media.tenant_id == user.tenant_id)
    )
    media = result.scalar_one_or_none()
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")
    await db.delete(media)
    await db.commit()


def _media_out(m: Media) -> dict:
    return {
        "id": m.id,
        "filename": m.filename,
        "mime_type": m.mime_type,
        "url": m.url,
        "size_bytes": m.size_bytes,
        "duration_sec": m.duration_sec,
        "uploaded_at": m.uploaded_at.isoformat() if m.uploaded_at else "",
    }


# ─── Playlists ───────────────────────────────────────────────────────────────

class PlaylistCreate(BaseModel):
    name: str


class PlaylistItemIn(BaseModel):
    media_id: str
    display_order: int
    duration_sec: int = 10


class PlaylistOut(BaseModel):
    id: str
    name: str
    items: list[dict]

    model_config = {"from_attributes": True}


@router.post("/playlists", response_model=PlaylistOut, status_code=201)
async def create_playlist(
    body: PlaylistCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pl = Playlist(tenant_id=user.tenant_id, name=body.name)
    db.add(pl)
    await db.commit()
    await db.refresh(pl)
    return {"id": pl.id, "name": pl.name, "items": []}


@router.get("/playlists", response_model=list[PlaylistOut])
async def list_playlists(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Use selectinload to avoid N+1 queries (one query for playlists + one for all items)
    result = await db.execute(
        select(Playlist)
        .where(Playlist.tenant_id == user.tenant_id)
        .options(selectinload(Playlist.items))
    )
    playlists = result.scalars().all()
    return [
        {
            "id": pl.id,
            "name": pl.name,
            "items": [
                {
                    "id": i.id,
                    "media_id": i.media_id,
                    "display_order": i.display_order,
                    "duration_sec": i.duration_sec,
                }
                for i in sorted(pl.items, key=lambda x: x.display_order)
            ],
        }
        for pl in playlists
    ]


@router.delete("/playlists/{playlist_id}", status_code=204)
async def delete_playlist(
    playlist_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist).where(Playlist.id == playlist_id, Playlist.tenant_id == user.tenant_id)
    )
    pl = result.scalar_one_or_none()
    if pl is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    await db.delete(pl)
    await db.commit()


@router.put("/playlists/{playlist_id}/items", status_code=200)
async def update_playlist_items(
    playlist_id: str,
    items: list[PlaylistItemIn],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist).where(Playlist.id == playlist_id, Playlist.tenant_id == user.tenant_id)
    )
    pl = result.scalar_one_or_none()
    if pl is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Verify all media_ids belong to this tenant (prevent cross-tenant media reference)
    media_ids = [i.media_id for i in items]
    if media_ids:
        owned = await db.execute(
            select(Media.id).where(
                Media.id.in_(media_ids),
                Media.tenant_id == user.tenant_id,
            )
        )
        owned_ids = {row[0] for row in owned.all()}
        unknown = set(media_ids) - owned_ids
        if unknown:
            raise HTTPException(status_code=400, detail=f"Media IDs not found in your library: {unknown}")

    await db.execute(delete(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    for item in items:
        db.add(PlaylistItem(playlist_id=playlist_id, **item.model_dump()))
    await db.commit()
    return {"ok": True}


class ReorderItemsRequest(BaseModel):
    items: list[dict]  # [{ id: str, sort_order: int }]


@router.patch("/playlists/{playlist_id}/items/reorder")
async def reorder_playlist_items(
    playlist_id: str,
    body: ReorderItemsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify playlist belongs to this tenant
    result = await db.execute(
        select(Playlist).where(Playlist.id == playlist_id, Playlist.tenant_id == user.tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    for item_update in body.items:
        await db.execute(
            update(PlaylistItem)
            .where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.media_id == item_update["id"],
            )
            .values(display_order=item_update["sort_order"])
        )
    await db.commit()
    return {"ok": True}


# ─── Schedules ───────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    playlist_id: str
    day_of_week: int  # 0=Mon … 6=Sun, -1=every day
    start_time: str   # "HH:MM"
    end_time: str     # "HH:MM"

    @field_validator("day_of_week")
    @classmethod
    def dow_range(cls, v: int) -> int:
        if v not in range(-1, 7):
            raise ValueError("day_of_week must be -1 (everyday) or 0-6 (Mon-Sun)")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def time_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("Time must be in HH:MM format")
        h, m = int(v[:2]), int(v[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time value")
        return v

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, v: str, info) -> str:
        start = info.data.get("start_time", "")
        if start and v <= start:
            raise ValueError("end_time must be after start_time")
        return v


@router.post("/schedules", status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify playlist belongs to this tenant
    pl_result = await db.execute(
        select(Playlist).where(Playlist.id == body.playlist_id, Playlist.tenant_id == user.tenant_id)
    )
    if pl_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    s = Schedule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(s)
    await db.commit()
    return {"id": s.id}


@router.get("/schedules")
async def list_schedules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Schedule).where(Schedule.tenant_id == user.tenant_id))
    schedules = result.scalars().all()
    return [
        {
            "id": s.id,
            "playlist_id": s.playlist_id,
            "day_of_week": s.day_of_week,
            "start_time": s.start_time,
            "end_time": s.end_time,
        }
        for s in schedules
    ]


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id, Schedule.tenant_id == user.tenant_id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(s)
    await db.commit()


@router.get("/schedules/current")
async def current_schedule(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the playlist that should be playing right now based on schedule."""
    now = datetime.now(timezone.utc)
    day = now.weekday()  # 0=Mon
    time_str = now.strftime("%H:%M")

    result = await db.execute(
        select(Schedule).where(
            Schedule.tenant_id == user.tenant_id,
            (Schedule.day_of_week == day) | (Schedule.day_of_week == -1),
            Schedule.start_time <= time_str,
            Schedule.end_time > time_str,
        )
    )
    # Use first() instead of scalar_one_or_none() — overlapping schedules shouldn't crash the kiosk
    schedule = result.scalars().first()
    if schedule is None:
        return {"playlist_id": None}
    return {"playlist_id": schedule.playlist_id, "schedule_id": schedule.id}
