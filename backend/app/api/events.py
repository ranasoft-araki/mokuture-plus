"""Server-Sent Events (SSE) stream — 管理画面のニアリアルタイム連動。

管理画面の「受付ログ」「ロッカー状況」ページが各1本この `GET /events/stream` を開く。
キオスク操作が受付/ロッカーの状態を変えると backend はテナントの pub/sub(services/events)へ
publish し、~1秒以内にブラウザへ push される→ブラウザは該当リスト(受付一覧 / ロッカー状況)だけ
即再取得する。接続が切れた稀なケースは各ページの低頻度ポーリング・フォールバックが拾う。

認証: EventSource は Authorization ヘッダを送れないため、アクセストークンをクエリで受け取り
接続時に一度だけ検証する。ストリーム自体は秘密情報を運ばない（再取得対象を示す `{type}` のみ）。
DB セッションは接続時のユーザー解決に限って短命に開き、ストリーム保持中は**DB接続を握らない**
（`Depends(get_db)` を使うと応答終了までセッションを保持してしまうため使わない）。
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from jose import JWTError
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.auth import decode_token
from app.services import events as event_bus

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger(__name__)

# アイドル時にコメント行を流してプロキシのアイドル切断を防ぎ、切断を検出する間隔。
_KEEPALIVE_SEC = 20.0


async def _resolve_tenant_id(token: str) -> str:
    """アクセストークンを検証してテナントIDを返す（get_current_user と同じ判定・短命セッション）。"""
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user.tenant_id


@router.get("/stream")
async def stream(request: Request, token: str = Query(...)):
    tenant_id = await _resolve_tenant_id(token)

    async def gen():
        q = event_bus.subscribe(tenant_id)
        try:
            # 接続直後にコメントを流してクライアントの onopen を即発火させる。
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_SEC)
                except asyncio.TimeoutError:
                    # keepalive コメント（プロキシのアイドル切断防止＋切断検出のためのターン）
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            event_bus.unsubscribe(tenant_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # プロキシのレスポンスバッファリングを無効化(即時 flush)
        },
    )
