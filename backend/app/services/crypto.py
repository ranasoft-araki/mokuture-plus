"""Fernet-based encryption for sensitive config values stored in DB (e.g. Slack Webhook URLs)."""
import base64
import json

from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    key = settings.encryption_key.encode()
    try:
        return Fernet(key)
    except Exception as e:
        # Invalid key format — fail loudly rather than silently using a weak derived key.
        # Fix: run `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and set ENCRYPTION_KEY.
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from e


def encrypt_dict(data: dict) -> str:
    """Encrypt a dict and return a base64 string for DB storage."""
    f = _get_fernet()
    return f.encrypt(json.dumps(data).encode()).decode()


def decrypt_dict(token: str) -> dict:
    """Decrypt DB-stored string back to dict."""
    f = _get_fernet()
    return json.loads(f.decrypt(token.encode()).decode())
