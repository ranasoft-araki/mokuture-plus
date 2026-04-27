"""Tenant settings API – brand_color, font, logo_url."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.tenant import get_current_user
from app.models.tenant import Tenant
from app.models.user import User
from app.services import storage
from app.config import settings as app_settings

router = APIRouter(prefix="/settings", tags=["settings"])

ALLOWED_FONTS = {
    "Noto Sans JP / Inter",
    "Noto Serif JP / Georgia",
    "BIZ UDPGothic / System",
}
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class TenantSettingsOut(BaseModel):
    tenant_name: str
    tenant_slug: str
    brand_color: str
    logo_url: str | None
    font: str


class TenantSettingsPatch(BaseModel):
    brand_color: str | None = None
    font: str | None = None


class LogoUploadUrlRequest(BaseModel):
    filename: str
    mime_type: str


class LogoUrlPatch(BaseModel):
    logo_url: str


async def _get_tenant(user: User, db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _out(tenant: Tenant) -> TenantSettingsOut:
    return TenantSettingsOut(
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        brand_color=tenant.brand_color,
        logo_url=tenant.logo_url,
        font=getattr(tenant, "font", "Noto Sans JP / Inter"),
    )


@router.get("", response_model=TenantSettingsOut)
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return _out(await _get_tenant(user, db))


@router.patch("", response_model=TenantSettingsOut)
async def patch_settings(
    body: TenantSettingsPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant = await _get_tenant(user, db)
    if body.brand_color is not None:
        if not _COLOR_RE.match(body.brand_color):
            raise HTTPException(status_code=422, detail="Invalid color format (expected #RRGGBB)")
        tenant.brand_color = body.brand_color
    if body.font is not None:
        if body.font not in ALLOWED_FONTS:
            raise HTTPException(status_code=422, detail=f"Font not allowed: {body.font}")
        tenant.font = body.font
    await db.commit()
    return _out(tenant)


@router.post("/logo-upload-url")
async def logo_upload_url(
    body: LogoUploadUrlRequest,
    user: User = Depends(get_current_user),
):
    if body.mime_type not in {"image/jpeg", "image/png", "image/svg+xml"}:
        raise HTTPException(status_code=422, detail="Logo must be JPEG, PNG, or SVG")
    try:
        data = storage.generate_presigned_upload_url(user.tenant_id, body.filename, body.mime_type)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Storage unavailable: {exc}")
    return data


@router.patch("/logo", response_model=TenantSettingsOut)
async def confirm_logo(
    body: LogoUrlPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = app_settings.storage_public_url.rstrip("/")
    if not body.logo_url.startswith(allowed):
        raise HTTPException(status_code=422, detail="logo_url must originate from configured storage")
    tenant = await _get_tenant(user, db)
    tenant.logo_url = body.logo_url
    await db.commit()
    return _out(tenant)
