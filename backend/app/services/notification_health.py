"""Persist tenant-visible notification delivery problems without a schema change."""

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models.notification import NotificationSetting, PushSubscription
from app.services.crypto import decrypt_dict, encrypt_dict


CHANNELS = ("slack", "chatwork", "push")


def _type(channel: str) -> str:
    if channel not in CHANNELS:
        raise ValueError(f"unknown notification channel: {channel}")
    return f"notification_health_{channel}"


async def record_result(
    tenant_id: str,
    channel: str,
    *,
    failed: bool,
    target: str = "",
) -> None:
    """Store the latest failure, or clear it after a completely successful send."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == _type(channel),
        ))
        row = result.scalar_one_or_none()
        if not failed:
            if row is not None:
                await db.delete(row)
                await db.commit()
            return
        config = {
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "target": target[:120],
        }
        if row is None:
            db.add(NotificationSetting(
                tenant_id=tenant_id,
                type=_type(channel),
                config_json=encrypt_dict(config),
            ))
        else:
            row.config_json = encrypt_dict(config)
        await db.commit()


async def clear(tenant_id: str, channel: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == _type(channel),
        ))
        await db.commit()


async def get_issues(db, tenant_id: str) -> list[dict]:
    result = await db.execute(select(NotificationSetting).where(
        NotificationSetting.tenant_id == tenant_id,
        NotificationSetting.type.in_([_type(c) for c in CHANNELS]),
    ))
    issues = []
    for row in result.scalars().all():
        channel = row.type.removeprefix("notification_health_")
        try:
            config = decrypt_dict(row.config_json)
        except Exception:
            config = {}
        issues.append({
            "channel": channel,
            "failed_at": str(config.get("failed_at") or ""),
            "target": str(config.get("target") or ""),
        })
    return issues


async def delete_expired_push_subscription(subscription_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PushSubscription).where(PushSubscription.id == subscription_id))
        await db.commit()


def push_subscription_expired(error: str) -> bool:
    return error.startswith("HTTP 404:") or error.startswith("HTTP 410:")
