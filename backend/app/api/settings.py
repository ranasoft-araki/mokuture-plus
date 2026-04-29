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
ALLOWED_KIOSK_STYLES = {
    "default", "medical", "retail", "hotel", "startup",
    "school", "craft", "industrial", "restaurant", "mono", "gym",
}
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class TenantSettingsOut(BaseModel):
    tenant_name: str
    tenant_slug: str
    brand_color: str
    logo_url: str | None
    font: str
    kiosk_welcome_message: str
    kiosk_sub_message: str
    kiosk_calling_message: str
    kiosk_complete_message: str
    kiosk_idle_timeout_sec: int
    kiosk_complete_timeout_sec: int
    logo_pos_x: float
    logo_pos_y: float
    logo_width_pct: float
    kiosk_style: str


class PublicTenantSettingsOut(BaseModel):
    brand_color: str
    logo_url: str | None
    font: str
    kiosk_welcome_message: str
    kiosk_sub_message: str
    kiosk_calling_message: str
    kiosk_complete_message: str
    kiosk_idle_timeout_sec: int
    kiosk_complete_timeout_sec: int
    logo_pos_x: float
    logo_pos_y: float
    logo_width_pct: float
    kiosk_style: str


class TenantSettingsPatch(BaseModel):
    brand_color: str | None = None
    font: str | None = None
    kiosk_welcome_message: str | None = None
    kiosk_sub_message: str | None = None
    kiosk_calling_message: str | None = None
    kiosk_complete_message: str | None = None
    kiosk_idle_timeout_sec: int | None = None
    kiosk_complete_timeout_sec: int | None = None
    logo_pos_x: float | None = None
    logo_pos_y: float | None = None
    logo_width_pct: float | None = None
    kiosk_style: str | None = None


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
        kiosk_welcome_message=getattr(tenant, "kiosk_welcome_message", "ようこそ"),
        kiosk_sub_message=getattr(tenant, "kiosk_sub_message", "ご用件をお選びください"),
        kiosk_calling_message=getattr(tenant, "kiosk_calling_message", "担当者をお呼びしています。少々お待ちください。"),
        kiosk_complete_message=getattr(tenant, "kiosk_complete_message", "担当者がご案内します"),
        kiosk_idle_timeout_sec=getattr(tenant, "kiosk_idle_timeout_sec", 60),
        kiosk_complete_timeout_sec=getattr(tenant, "kiosk_complete_timeout_sec", 10),
        logo_pos_x=getattr(tenant, "logo_pos_x", 0.04),
        logo_pos_y=getattr(tenant, "logo_pos_y", 0.04),
        logo_width_pct=getattr(tenant, "logo_width_pct", 8.0),
        kiosk_style=getattr(tenant, "kiosk_style", "default"),
    )


def _public_out(tenant: Tenant) -> PublicTenantSettingsOut:
    return PublicTenantSettingsOut(
        brand_color=tenant.brand_color,
        logo_url=tenant.logo_url,
        font=getattr(tenant, "font", "Noto Sans JP / Inter"),
        kiosk_welcome_message=getattr(tenant, "kiosk_welcome_message", "ようこそ"),
        kiosk_sub_message=getattr(tenant, "kiosk_sub_message", "ご用件をお選びください"),
        kiosk_calling_message=getattr(tenant, "kiosk_calling_message", "担当者をお呼びしています。少々お待ちください。"),
        kiosk_complete_message=getattr(tenant, "kiosk_complete_message", "担当者がご案内します"),
        kiosk_idle_timeout_sec=getattr(tenant, "kiosk_idle_timeout_sec", 60),
        kiosk_complete_timeout_sec=getattr(tenant, "kiosk_complete_timeout_sec", 10),
        logo_pos_x=getattr(tenant, "logo_pos_x", 0.04),
        logo_pos_y=getattr(tenant, "logo_pos_y", 0.04),
        logo_width_pct=getattr(tenant, "logo_width_pct", 8.0),
        kiosk_style=getattr(tenant, "kiosk_style", "default"),
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
    if body.kiosk_welcome_message is not None:
        tenant.kiosk_welcome_message = body.kiosk_welcome_message[:255]
    if body.kiosk_sub_message is not None:
        tenant.kiosk_sub_message = body.kiosk_sub_message[:255]
    if body.kiosk_calling_message is not None:
        tenant.kiosk_calling_message = body.kiosk_calling_message[:255]
    if body.kiosk_complete_message is not None:
        tenant.kiosk_complete_message = body.kiosk_complete_message[:255]
    if body.kiosk_idle_timeout_sec is not None:
        tenant.kiosk_idle_timeout_sec = max(10, min(300, body.kiosk_idle_timeout_sec))
    if body.kiosk_complete_timeout_sec is not None:
        tenant.kiosk_complete_timeout_sec = max(5, min(60, body.kiosk_complete_timeout_sec))
    if body.logo_pos_x is not None:
        tenant.logo_pos_x = max(0.0, min(0.9, body.logo_pos_x))
    if body.logo_pos_y is not None:
        tenant.logo_pos_y = max(0.0, min(0.9, body.logo_pos_y))
    if body.logo_width_pct is not None:
        tenant.logo_width_pct = max(2.0, min(30.0, body.logo_width_pct))
    if body.kiosk_style is not None:
        if body.kiosk_style not in ALLOWED_KIOSK_STYLES:
            raise HTTPException(status_code=422, detail=f"kiosk_style not allowed: {body.kiosk_style}")
        tenant.kiosk_style = body.kiosk_style
    await db.commit()
    return _out(tenant)


@router.get("/public/{tenant_slug}", response_model=PublicTenantSettingsOut)
async def get_public_settings(tenant_slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _public_out(tenant)


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
