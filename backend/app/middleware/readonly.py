"""審査環境の閲覧専用アカウント向けサーバ側ガード。

demo1@ranasoft.co.jp 等の「閲覧専用」アカウント（アクセストークンに ro=true）が発行する
ミューテーション（POST/PUT/PATCH/DELETE）を、来社予定(appointments) API を除いて 403 で拒否する。
フロント（lib/api.ts の request ガード / AdminShell）でも同様に閲覧専用化しているが、これは
UI をすり抜けた直接リクエストにも効く最終防衛線。

CORS より内側に置く（main.py で CORS を後から add_middleware＝最外に）ことで、
ここで返す 403 にも CORS ヘッダが付き、ブラウザが detail を読める。"""
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class ReadOnlyGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _SAFE_METHODS:
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
            allowed = f"{settings.api_prefix}/appointments"
            path = request.url.path
            if not (path == allowed or path.startswith(allowed + "/")):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "審査環境では閲覧のみです（操作できるのは来社予定のみ）"},
                )

        return await call_next(request)
