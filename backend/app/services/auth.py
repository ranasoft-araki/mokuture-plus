import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.services.timeutil import to_naive_utc

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# bcrypt は1回あたり数百ミリ秒 CPU を使う。単一ワーカーのイベントループ上で直接呼ぶと、
# その間ほかの全リクエスト(キオスクの受付・SSE 等)が止まるので、API からはスレッドで呼ぶ。
async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, plain, hashed)


def _epoch(dt: datetime) -> int:
    """aware/naive(UTC 壁時計)どちらでも UTC の秒に直す。naive の .timestamp() は
    実行環境のタイムゾーンで解釈されてずれるので使わない。"""
    naive = to_naive_utc(dt)
    return int(naive.replace(tzinfo=timezone.utc).timestamp())


def _issued_at(issued_at: datetime | None) -> int:
    return _epoch(issued_at) if issued_at is not None else int(datetime.now(timezone.utc).timestamp())


def create_access_token(
    tenant_id: str,
    user_id: str,
    role: str,
    readonly: bool = False,
    *,
    expires_minutes: int | None = None,
    extra_claims: dict | None = None,
    issued_at: datetime | None = None,
) -> str:
    """アクセストークン。`iat`(発行時刻)を必ず載せる＝パスワード変更より前に発行された
    トークンを見分けるため(`token_predates_password_change`)。"""
    minutes = settings.jwt_access_expire_minutes if expires_minutes is None else expires_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        "sub": user_id, "tenant_id": tenant_id, "role": role, "exp": expire,
        "iat": _issued_at(issued_at), "type": "access",
    }
    # 審査環境の閲覧専用アカウント(demo1@ranasoft.co.jp 等)。この ro クレームを見て、
    # サーバ側(ReadOnlyGuardMiddleware)は来社予定以外のミューテーションを拒否し、
    # フロント(lib/auth.ts の getReadonly)は UI を閲覧専用に切り替える。
    if readonly:
        payload["ro"] = True
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# 代理ログイン(運営・代理店が顧客テナントの管理者として入る)。短い有効期限で、
# refresh トークンは出さない＝15分で必ず切れる。
PROXY_TOKEN_EXPIRE_MINUTES = 15


def create_proxy_access_token(tenant_id: str, user_id: str) -> str:
    return create_access_token(
        tenant_id, user_id, "admin",
        expires_minutes=PROXY_TOKEN_EXPIRE_MINUTES,
        extra_claims={"proxy": True},
    )


def token_predates_password_change(payload: dict, user) -> bool:
    """パスワード変更より前に発行されたトークンなら True(=受け付けない)。

    パスワードを変えたら、それ以前に発行されたログイン(他の端末・漏れたトークン)は
    無効にする。`password_changed_at` は秒単位に切り捨てて保存し、`iat < 変更時刻` を
    古いとみなす(同じ秒に発行された新しいトークンは通す)。`iat` の無い古い形式の
    トークンは、パスワード変更の記録があるユーザーに限って受け付けない。"""
    changed = getattr(user, "password_changed_at", None)
    if changed is None:
        return False
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)):
        return True
    return int(iat) < _epoch(changed)


def is_readonly_account(email: str | None) -> bool:
    """審査用の閲覧専用アカウントか（config の review_readonly_emails に一致する email か）。"""
    if not email:
        return False
    target = email.strip().lower()
    return any(target == e.strip().lower() for e in settings.review_readonly_emails)


def create_refresh_token(tenant_id: str, user_id: str, *, issued_at: datetime | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)
    payload = {
        "sub": user_id, "tenant_id": tenant_id, "exp": expire,
        "iat": _issued_at(issued_at), "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# SSE(管理画面のリアルタイム更新)の接続用チケット。EventSource はヘッダを送れないので
# URL に載せるしかないが、URL はアクセスログ等に残る。そこへ長く使えるアクセストークンを
# 載せないよう、接続のためだけの60秒で切れるトークンを別に発行する。
SSE_TICKET_EXPIRE_SECONDS = 60


def create_sse_ticket(tenant_id: str, user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(seconds=SSE_TICKET_EXPIRE_SECONDS)
    payload = {
        "sub": user_id, "tenant_id": tenant_id, "exp": expire,
        "iat": _issued_at(None), "type": "sse",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_sse_ticket(token: str) -> dict:
    """有効な SSE チケットの中身を返す。不正・期限切れ・別種のトークンは JWTError。"""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "sse":
        raise JWTError("wrong token type")
    if not payload.get("sub"):
        raise JWTError("missing subject")
    return payload


def decode_token(token: str) -> dict:
    """Raises JWTError on invalid/expired token."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# 受付 OK/NG 応答用の署名トークン。スタッフのプッシュ通知アクションボタンから
# Service Worker が（ログイン=JWT を持たずに）1受付の accepted/declined を更新するために使う。
# 署名のみ（暗号化不要）で十分：漏れても TTL 内に該当受付を accepted/declined にできるだけで、
# それはスタッフが元々持つ権限と同じ。
_DECISION_TOKEN_EXPIRE_HOURS = 2


def create_decision_token(
    log_id: str,
    tenant_id: str,
    *,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_DECISION_TOKEN_EXPIRE_HOURS)
    payload = {"sub": log_id, "tenant_id": tenant_id, "type": "decision", "exp": expire}
    if actor_user_id:
        payload["actor_user_id"] = actor_user_id
    if actor_name:
        payload["actor_name"] = actor_name[:255]
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# Slack OAuth CSRF `state`. A signed (not encrypted) JWT that binds the OAuth round-trip
# to a specific tenant without any server-side session store: the token itself carries the
# tenant_id, so the callback (which arrives with no JWT — Slack redirects the browser)
# can trust which tenant it is for. A random jti makes each state unique; the short TTL and
# Slack's single-use `code` prevent replay.
_SLACK_STATE_EXPIRE_MINUTES = 10


def create_slack_state_token(tenant_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_SLACK_STATE_EXPIRE_MINUTES)
    payload = {
        "tenant_id": tenant_id,
        "type": "slack_oauth",
        "jti": secrets.token_hex(8),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_slack_state_token(token: str) -> str:
    """Return the tenant_id embedded in a valid Slack OAuth state token.

    Raises JWTError if the token is invalid, expired, or not a slack_oauth token."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "slack_oauth":
        raise JWTError("wrong token type")
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise JWTError("missing tenant_id")
    return tenant_id
