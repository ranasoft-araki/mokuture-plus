from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(tenant_id: str, user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_expire_minutes)
    payload = {"sub": user_id, "tenant_id": tenant_id, "role": role, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(tenant_id: str, user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {"sub": user_id, "tenant_id": tenant_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Raises JWTError on invalid/expired token."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# 受付 OK/NG 応答用の署名トークン。スタッフのプッシュ通知アクションボタンから
# Service Worker が（ログイン=JWT を持たずに）1受付の accepted/declined を更新するために使う。
# 署名のみ（暗号化不要）で十分：漏れても TTL 内に該当受付を accepted/declined にできるだけで、
# それはスタッフが元々持つ権限と同じ。
_DECISION_TOKEN_EXPIRE_HOURS = 2


def create_decision_token(log_id: str, tenant_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_DECISION_TOKEN_EXPIRE_HOURS)
    payload = {"sub": log_id, "tenant_id": tenant_id, "type": "decision", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
