"""PWA Push Notification API — VAPID public key and subscription CRUD.

The VAPID key pair is one system-wide pair (VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY env)
shared by every tenant. Regenerating it invalidates every subscription everywhere.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.middleware.tenant import require_roles
from app.models.notification import PushSubscription
from app.models.user import User
from app.services.url_safety import is_allowed_push_endpoint
from app.services.webpush import send_push
from app.config import settings

router = APIRouter(prefix="/notifications/push", tags=["push"])
logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "プッシュ通知が使えない状態です。運営にお問い合わせください。"
_KNOWN_OS_NAMES = {"Windows", "macOS", "iOS", "Android", "Linux", "ChromeOS"}


def _normalized_os_name(value: str | None) -> str | None:
    """画面表示用の既知ラベルだけを保存し、生の User-Agent 等を受け入れない。"""
    value = (value or "").strip()
    return value if value in _KNOWN_OS_NAMES else None


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/vapid-public-key")
async def get_vapid_public_key(
    user: User = Depends(require_roles("admin", "superadmin")),
):
    """Return the VAPID public key the front-end subscribes with."""
    return {"public_key": settings.vapid_public_key or None}


# ── Subscription CRUD ────────────────────────────────────────────────

class SubscribeBody(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    os_name: str | None = None


class UnsubscribeBody(BaseModel):
    endpoint: str


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscribeBody,
    user: User = Depends(require_roles("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Register a push subscription for the current user (upsert by endpoint).

    送信先はブラウザの配信サービス(FCM / Apple / Mozilla / Windows)のものだけ受け付ける
    (サーバーから任意の宛先へ送らせないため)。
    同じ送信先が既にあれば、テナントとユーザーをいまの利用者へ付け替える。ブラウザを別の
    テナントのアカウントで使い始めたとき、前のテナントの受付通知が届き続けないように。"""
    if not is_allowed_push_endpoint(body.endpoint):
        raise HTTPException(
            status_code=400,
            detail="このブラウザの通知の登録先は使用できません。別のブラウザでお試しください。",
        )
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.p256dh = body.p256dh
        existing.auth_key = body.auth
        existing.tenant_id = user.tenant_id
        existing.user_id = user.id
        existing.os_name = _normalized_os_name(body.os_name)
    else:
        db.add(PushSubscription(
            tenant_id=user.tenant_id,
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth_key=body.auth,
            os_name=_normalized_os_name(body.os_name),
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
            "os_name": s.os_name or "不明",
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
    private_key = settings.vapid_private_key
    subject = settings.vapid_subject

    if not private_key:
        raise HTTPException(status_code=400, detail=_NOT_CONFIGURED)

    result = await db.execute(
        select(PushSubscription).where(PushSubscription.tenant_id == user.tenant_id)
    )
    subs = result.scalars().all()
    if not subs:
        raise HTTPException(status_code=404, detail="No push subscriptions registered.")

    sent = 0
    errors: list[str] = []
    for s in subs:
        ok, err = await send_push(
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
        elif err:
            errors.append(err)

    if sent == 0 and errors:
        # 配信サービスの応答本文は画面に返さない(詳細はサーバーのログにだけ残す)。
        logger.warning("test push failed (tenant=%s): %s", user.tenant_id, errors[0][:200])
        raise HTTPException(
            status_code=502,
            detail="プッシュ通知を送信できませんでした。端末の登録をやり直してからお試しください。",
        )
    return {"sent": sent, "total": len(subs)}
