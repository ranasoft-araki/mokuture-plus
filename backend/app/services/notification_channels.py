"""Tenant-wide notification channel switches.

The switch controls shared/default and delivery notifications. Explicit destinations
selected in a per-staff route remain active so that those selectors keep their existing
"send / do not send" semantics.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationSetting
from app.services.crypto import decrypt_dict


CHANNELS = ("slack", "chatwork", "push")


def setting_type(channel: str) -> str:
    if channel not in CHANNELS:
        raise ValueError(f"unknown notification channel: {channel}")
    return f"channel_enabled_{channel}"


async def is_enabled(db: AsyncSession, tenant_id: str, channel: str) -> bool:
    """Return the tenant switch. Missing/broken settings default to ON for compatibility."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant_id,
            NotificationSetting.type == setting_type(channel),
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None or not setting.config_json or setting.config_json == "{}":
        return True
    try:
        return decrypt_dict(setting.config_json).get("enabled", True) is not False
    except Exception:
        return True
