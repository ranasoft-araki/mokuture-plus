"""PWA Push Notification API — VAPID key management and subscription CRUD."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.middleware.tenant import require_roles
from app.models.notification import NotificationSetting, PushSubscription
from app.models.user import User
from app.services.crypto import encrypt_dict, decrypt_dict
from app.services.webpush import generate_vapid_keys, send_push
from app.config import settings

router = APIRouter(prefix="/notifications/push", tags=["push"])

_VAPID_TYPE = "vapid"


# ── VAPID key helpers ─────────────────────────────────────────────────

async def _get_vapid(tenant_id: str, db: AsyncSession) -> dict | None:
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == _VAPID_TYPE,
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        return None
    try:
        return decrypt_dict(setting.config_json)
    except Exception:
        return None


async def _upsert_vapid(tenant_id: str, private_pem: str, public_b64: str, db: AsyncSession) -> None:
    encrypted = encrypt_dict({"private_key": private_pem, "public_key": public_b64})
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == _VAPID_TYPE,
        )
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.config_json = encrypted
    else:
        db.add(NotificationSetting(tenant_id=tenant_id, type=_VAPID_TYPE, config_json=encrypted))
    await db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/vapid-public-key")
async def get_vapid_public_key(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Return the VAPID public key for this tenant (used by front-end to subscribe)."""
    vapid = await _get_vapid(user.tenant_id, db)
    # Fall back to global settings if available
    pub_key = (vapid or {}).get("public_key") or settings.vapid_public_key or None
    return {"public_key": pub_key}


@router.post("/setup")
async def setup_vapid(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Generate and store VAPID keys for this tenant (idempotent)."""
    existing = await _get_vapid(user.tenant_id, db)
    if existing and existing.get("public_key"):
        return {"public_key": existing["public_key"], "generated": False}

    private_pem, public_b64 = generate_vapid_keys()
    await _upsert_vapid(user.tenant_id, private_pem, public_b64, db)
    return {"public_key": public_b64, "generated": True}


# ── Subscription CRUD ────────────────────────────────────────────────

class SubscribeBody(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscribeBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Register a push subscription for the current user (upsert by endpoint)."""
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.p256dh = body.p256dh
        existing.auth_key = body.auth
        existing.user_id = user.id
    else:
        db.add(PushSubscription(
            tenant_id=user.tenant_id,
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth_key=body.auth,
        ))
    await db.commit()
    return {"ok": True}


@router.delete("/unsubscribe")
async def unsubscribe(
    body: UnsubscribeBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a push subscription by endpoint."""
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.tenant_id == user.tenant_id,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/subscriptions")
async def list_subscriptions(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """List all registered push subscriptions for this tenant."""
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == user.tenant_id)
    )
    subs = result.scalars().all()
    return [
        {
            "id": s.id,
            "endpoint": s.endpoint,
            "display_endpoint": s.endpoint[:60] + "…",
            "user_id": s.user_id,
            "created_at": s.created_at.isoformat() if s.created_at else "",
        }
        for s in subs
    ]


@router.post("/test")
async def test_push(
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Send a test push to all subscriptions for this tenant."""
    vapid = await _get_vapid(user.tenant_id, db)
    private_key = (vapid or {}).get("private_key") or settings.vapid_private_key
    subject = settings.vapid_subject

    if not private_key:
        raise HTTPException(status_code=400, detail="VAPID not configured. Call /setup first.")

    result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == user.tenant_id)
    )
    subs = result.scalars().all()
    if not subs:
        raise HTTPException(status_code=404, detail="No push subscriptions registered.")

    sent = 0
    for s in subs:
        ok = await send_push(
            endpoint=s.endpoint,
            p256dh=s.p256dh,
            auth=s.auth_key,
            title="mokuture+ テスト通知",
            body="プッシュ通知の設定が完了しました。",
            url="/",
            private_key=private_key,
            subject=subject,
        )
        if ok:
            sent += 1
    return {"sent": sent, "total": len(subs)}
