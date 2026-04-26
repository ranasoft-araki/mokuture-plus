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


def _send_sync(endpoint: str, p256dh: str, auth: str, payload: dict, private_key: str, subject: str) -> bool:
    """Synchronous send (called in thread pool to avoid blocking event loop)."""
    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=json.dumps(payload),
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},
    )
    return True


async def send_push(
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    url: str = "/",
    private_key: str = "",
    subject: str = "mailto:admin@mokuture.jp",
) -> bool:
    """Send a single web push notification. Returns True on success."""
    if not _AVAILABLE or not private_key:
        return False

    payload = {
        "title": title,
        "body": body,
        "url": url,
        "tag": "reception",
        "icon": "/icons/icon.svg",
    }
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, _send_sync, endpoint, p256dh, auth, payload, private_key, subject
        )
    except WebPushException as e:
        status = getattr(e.response, "status_code", None) if e.response else None
        logger.warning("push failed (endpoint=%s…, status=%s): %s", endpoint[:40], status, e)
        return False
    except Exception as e:
        logger.warning("push error (endpoint=%s…): %s", endpoint[:40], e)
        return False


def generate_vapid_keys() -> tuple[str, str]:
    """Generate a new VAPID key pair. Returns (private_key_pem, public_key_base64url)."""
    from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption
    )
    import base64

    private = generate_private_key(SECP256R1())
    public = private.public_key()

    priv_pem = private.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()
    pub_bytes = public.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

    return priv_pem, pub_b64
