"""審査環境の閲覧専用アカウント向けサーバ側ガード。

demo1@ranasoft.co.jp 等の「閲覧専用」アカウント（アクセストークンに ro=true）が発行する
ミューテーション（POST/PUT/PATCH/DELETE）を、来社予定(appointments) API を除いて 403 で拒否する。
フロント（lib/api.ts の request ガード / AdminShell）でも同様に閲覧専用化しているが、これは
UI をすり抜けた直接リクエストにも効く最終防衛線。
GET でも状態を変える入口(Slack 連携の開始)は `_RO_BLOCKED_GET` で個別に止める。

CORS より内側に置く（main.py で CORS を後から add_middleware＝最外に）ことで、
ここで返す 403 にも CORS ヘッダが付き、ブラウザが detail を読める。"""
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# 閲覧専用でも書き込み(POST)を許すパス。来社予定(appointments)は審査で操作してもらう対象。
# /events/ticket は管理画面のリアルタイム更新(SSE)の接続チケットを取るだけで、何も変えない。
_RO_ALLOWED_PREFIXES = ("/appointments",)
_RO_ALLOWED_EXACT = ("/events/ticket",)

# GET でも状態を変える操作の入口。閲覧専用アカウントには開かせない。
#  - Slack 連携の開始: 認可 URL を受け取って進めると、テナントの Slack 連携が差し替わる。
#  - Google カレンダー連携の開始: 同じく、テナントの Google アカウントの連携が差し替わる。
_RO_BLOCKED_GET = ("/notifications/slack/oauth/url", "/integrations/google-calendar/oauth/url")


def _ro_allows_write(path: str) -> bool:
    prefix = settings.api_prefix
    for p in _RO_ALLOWED_PREFIXES:
        base = prefix + p
        if path == base or path.startswith(base + "/"):
            return True
    return any(path == prefix + p for p in _RO_ALLOWED_EXACT)


def _is_ro_token(request: Request) -> bool:
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return False
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return False
    return payload.get("ro") is True


class ReadOnlyGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _SAFE_METHODS:
            path = request.url.path.rstrip("/")
            if (
                request.method.upper() != "OPTIONS"
                and any(path == settings.api_prefix + p for p in _RO_BLOCKED_GET)
                and _is_ro_token(request)
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "審査環境では閲覧のみです（この操作はできません）"},
                )
            return await call_next(request)

        auth = request.headers.get("authorization")
        if not auth or not auth.lower().startswith("bearer "):
            # アクセストークンを持たない書込（例: /auth/refresh, /auth/login）は対象外。
            return await call_next(request)

        token = auth.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(
                token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
            )
        except JWTError:
            # 無効/失効トークンは通常の認証（get_current_user）の 401 に委ねる。
            return await call_next(request)

        if payload.get("ro") is True:
            if not _ro_allows_write(request.url.path):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "審査環境では閲覧のみです（操作できるのは来社予定のみ）"},
                )

        return await call_next(request)
