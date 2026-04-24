from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.content import Media, Playlist, PlaylistItem, Schedule
from app.models.user import User
from app.services import storage

router = APIRouter(prefix="/content", tags=["content"])


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


class MediaOut(BaseModel):
    id: str
    filename: str
    mime_type: str
    url: str
    size_bytes: int
    duration_sec: float | None
    uploaded_at: str

    model_config = {"from_attributes": True}


@router.post("/media/upload-url")
async def get_upload_url(body: UploadUrlRequest, user: User = Depends(get_current_user)):
    try:
        return storage.generate_presigned_upload_url(user.tenant_id, body.filename, body.mime_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/media", response_model=MediaOut, status_code=201)
async def register_media(body: MediaCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    import uuid
    media = Media(
        id=body.media_id or str(uuid.uuid4()),
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
async def delete_media(media_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Media).where(Media.id == media_id, Media.tenant_id == user.tenant_id))
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
async def create_playlist(body: PlaylistCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    pl = Playlist(tenant_id=user.tenant_id, name=body.name)
    db.add(pl)
    await db.commit()
    await db.refresh(pl)
    return {"id": pl.id, "name": pl.name, "items": []}


@router.get("/playlists", response_model=list[PlaylistOut])
async def list_playlists(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Playlist).where(Playlist.tenant_id == user.tenant_id))
    playlists = result.scalars().all()
    out = []
    for pl in playlists:
        items_result = await db.execute(
            select(PlaylistItem).where(PlaylistItem.playlist_id == pl.id).order_by(PlaylistItem.display_order)
        )
        items = items_result.scalars().all()
        out.append({"id": pl.id, "name": pl.name, "items": [
            {"id": i.id, "media_id": i.media_id, "display_order": i.display_order, "duration_sec": i.duration_sec}
            for i in items
        ]})
    return out


@router.put("/playlists/{playlist_id}/items", status_code=200)
async def update_playlist_items(
    playlist_id: str,
    items: list[PlaylistItemIn],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id, Playlist.tenant_id == user.tenant_id))
    pl = result.scalar_one_or_none()
    if pl is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    await db.execute(delete(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    for item in items:
        db.add(PlaylistItem(playlist_id=playlist_id, **item.model_dump()))
    await db.commit()
    return {"ok": True}


# ─── Schedules ───────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    playlist_id: str
    day_of_week: int  # 0=Mon … 6=Sun, -1=every day
    start_time: str   # "HH:MM"
    end_time: str     # "HH:MM"


@router.post("/schedules", status_code=201)
async def create_schedule(body: ScheduleCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = Schedule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(s)
    await db.commit()
    return {"id": s.id}


@router.get("/schedules")
async def list_schedules(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Schedule).where(Schedule.tenant_id == user.tenant_id))
    schedules = result.scalars().all()
    return [{"id": s.id, "playlist_id": s.playlist_id, "day_of_week": s.day_of_week, "start_time": s.start_time, "end_time": s.end_time} for s in schedules]


@router.get("/schedules/current")
async def current_schedule(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return the playlist that should be playing right now based on schedule."""
    from datetime import datetime, timezone
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
    schedule = result.scalar_one_or_none()
    if schedule is None:
        return {"playlist_id": None}
    return {"playlist_id": schedule.playlist_id, "schedule_id": schedule.id}
