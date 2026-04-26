"""Cloudflare R2 / MinIO S3-compatible storage service."""
import uuid
from datetime import datetime

import boto3
from botocore.config import Config

from app.config import settings

ALLOWED_MIME_TYPES = {
    "video/mp4",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
}
ALLOWED_EXTENSIONS = {".mp4", ".jpg", ".jpeg", ".png", ".svg"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.storage_endpoint_url,
        aws_access_key_id=settings.storage_access_key_id,
        aws_secret_access_key=settings.storage_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _safe_filename(filename: str) -> str:
    """Strip path components and dangerous characters to prevent path traversal."""
    import os, re
    name = os.path.basename(filename)  # strip any directory prefix
    name = re.sub(r"[^\w.\-]", "_", name)  # allow only word chars, dots, hyphens
    return name or "upload"


def validate_upload(filename: str, mime_type: str) -> None:
    """Raise ValueError if the file type is not permitted."""
    import os
    safe = _safe_filename(filename)
    ext = os.path.splitext(safe)[1].lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(f"Unsupported MIME type: {mime_type}")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {ext}")


def generate_presigned_upload_url(tenant_id: str, filename: str, mime_type: str) -> dict:
    """Return a presigned PUT URL valid for 15 minutes. R2 does not support presigned POST."""
    safe_name = _safe_filename(filename)
    validate_upload(safe_name, mime_type)

    media_id = str(uuid.uuid4())
    key = f"{tenant_id}/{media_id}/{safe_name}"

    s3 = _s3_client()
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.storage_bucket_name,
            "Key": key,
            "ContentType": mime_type,
        },
        ExpiresIn=900,  # 15 minutes
    )
    public_url = f"{settings.storage_public_url}/{key}"
    return {"media_id": media_id, "upload_url": upload_url, "public_url": public_url, "storage_key": key}


def upload_file(tenant_id: str, filename: str, mime_type: str, data: bytes) -> dict:
    """Upload bytes directly to R2/MinIO and return media_id + public_url."""
    safe_name = _safe_filename(filename)
    validate_upload(safe_name, mime_type)

    media_id = str(uuid.uuid4())
    key = f"{tenant_id}/{media_id}/{safe_name}"

    s3 = _s3_client()
    s3.put_object(
        Bucket=settings.storage_bucket_name,
        Key=key,
        Body=data,
        ContentType=mime_type,
    )

    public_url = f"{settings.storage_public_url}/{key}"
    return {"media_id": media_id, "public_url": public_url, "storage_key": key}


def generate_presigned_get_url(key: str, expires_in: int = 3600) -> str:
    """Return a presigned GET URL valid for expires_in seconds (default 1 hour)."""
    s3 = _s3_client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.storage_bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(storage_key: str) -> None:
    s3 = _s3_client()
    s3.delete_object(Bucket=settings.storage_bucket_name, Key=storage_key)
