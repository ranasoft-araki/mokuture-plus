"""Web Push notification service (VAPID / RFC 8030)."""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

try:
    from pywebpush import webpush, WebPushException
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.warning("pywebpush not installed — web push disabled. Run: uv add pywebpush")


def _send_sync(endpoint: str, p256dh: str, auth: str, payload: dict, private_key: str, subject: str) -> None:
    """Synchronous send (called in thread pool). Raises on failure."""
    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=json.dumps(payload),
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},
    )


async def send_push(
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    url: str = "/",
    private_key: str = "",
    subject: str = "mailto:admin@mokuture.jp",
) -> tuple[bool, str]:
    """Send a single web push notification. Returns (success, error_message)."""
    if not _AVAILABLE:
        return False, "pywebpush not installed"
    if not private_key:
        return False, "VAPID private key not configured"

    payload = {
        "title": title,
        "body": body,
        "url": url,
        "tag": "reception",
        "icon": "/icons/icon.svg",
    }
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None, _send_sync, endpoint, p256dh, auth, payload, private_key, subject
        )
        return True, ""
    except WebPushException as e:
        response_body = ""
        status_code = None
        if e.response is not None:
            status_code = e.response.status_code
            try:
                response_body = e.response.text[:400]
            except Exception:
                pass
        error_msg = f"HTTP {status_code}: {response_body}" if status_code else str(e)[:400]
        logger.error("webpush failed endpoint=%s… : %s", endpoint[:50], error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = str(e)[:400]
        logger.error("webpush error endpoint=%s… : %s", endpoint[:50], error_msg)
        return False, error_msg


def generate_vapid_keys() -> tuple[str, str]:
    """Generate a new VAPID key pair. Returns (private_key_pem, public_key_base64url)."""
    from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption
    )
    import base64

    private = generate_private_key(SECP256R1())
    public = private.public_key()

    # PKCS8 format is more universally compatible with pywebpush 2.x
    priv_pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    pub_bytes = public.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

    return priv_pem, pub_b64
