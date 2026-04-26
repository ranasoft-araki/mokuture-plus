"""Web Push notification service (VAPID / RFC 8030)."""
import asyncio
import base64
import json
import logging

logger = logging.getLogger(__name__)

try:
    from pywebpush import webpush, WebPushException, Vapid
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.warning("pywebpush not installed — web push disabled. Run: uv add pywebpush")


def _build_vapid(raw_b64: str) -> "Vapid":
    """Build a Vapid object from raw base64url private key — bypasses PEM parsing entirely."""
    from cryptography.hazmat.primitives.asymmetric.ec import derive_private_key, SECP256R1

    raw = base64.urlsafe_b64decode(raw_b64 + "==")
    private_int = int.from_bytes(raw, "big")
    ec_key = derive_private_key(private_int, SECP256R1())

    # Try constructor keyword arg first; fall back to direct attribute assignment
    try:
        v = Vapid(private_key=ec_key)
    except TypeError:
        v = Vapid()
        v._private_key = ec_key  # type: ignore[attr-defined]
        v._public_key = ec_key.public_key()  # type: ignore[attr-defined]
    return v


def _send_sync(
    endpoint: str, p256dh: str, auth: str,
    payload: dict, raw_private_key: str, subject: str,
) -> None:
    """Synchronous send. raw_private_key is base64url of 32-byte EC scalar. Raises on failure."""
    vapid = _build_vapid(raw_private_key)
    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=json.dumps(payload),
        vapid_private_key=vapid,
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
    """Generate VAPID key pair. Returns (raw_private_key_base64url, public_key_base64url).

    Stores the private key as raw 32-byte EC scalar in base64url to avoid
    PEM format dependency on pywebpush version.
    """
    from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = generate_private_key(SECP256R1())
    public = private.public_key()

    priv_raw = private.private_numbers().private_value.to_bytes(32, "big")
    priv_b64 = base64.urlsafe_b64encode(priv_raw).decode().rstrip("=")

    pub_bytes = public.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

    return priv_b64, pub_b64
