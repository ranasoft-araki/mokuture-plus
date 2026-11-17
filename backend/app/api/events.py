"""Server-Sent Events (SSE) stream — 管理画面のニアリアルタイム連動。

管理画面の「受付ログ」「ロッカー状況」ページが各1本この `GET /events/stream` を開く。
キオスク操作が受付/ロッカーの状態を変えると backend はテナントの pub/sub(services/events)へ
publish し、~1秒以内にブラウザへ push される→ブラウザは該当リスト(受付一覧 / ロッカー状況)だけ
即再取得する。接続が切れた稀なケースは各ページの低頻度ポーリング・フォールバックが拾う。

認証: EventSource は Authorization ヘッダを送れないため、`POST /events/ticket` で取った
60秒の接続用チケットをクエリ(`?ticket=`)で受け取り、接続時に一度だけ検証する
(移行期間中は従来の `?token=`(アクセストークン)も受ける)。ストリーム自体は秘密情報を運ばない（再取得対象を示す `{type}` のみ）。
DB セッションは接続時のユーザー解決に限って短命に開き、ストリーム保持中は**DB接続を握らない**
（`Depends(get_db)` を使うと応答終了までセッションを保持してしまうため使わない）。
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from jose import JWTError
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.middleware.tenant import get_current_user
from app.models.user import User
from app.services.auth import (
    SSE_TICKET_EXPIRE_SECONDS,
    create_sse_ticket,
    decode_token,
    token_predates_password_change,
    verify_sse_ticket,
)
from app.services import events as event_bus

router = APIRouter(prefix="/events", tags=["events"])
logger = logging.getLogger(__name__)

# アイドル時にコメント行を流してプロキシのアイドル切断を防ぎ、切断を検出する間隔。
_KEEPALIVE_SEC = 20.0


async def _tenant_for(payload: dict) -> str:
    """検証済みトークンの中身からユーザーを引き、テナントIDを返す(短命セッション)。"""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if token_predates_password_change(payload, user):
        raise HTTPException(status_code=401, detail="パスワードが変更されたため、もう一度ログインしてください")
    return user.tenant_id


async def _resolve_tenant_id(token: str) -> str:
    """アクセストークンを検証してテナントIDを返す（get_current_user と同じ判定・短命セッション）。"""
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")
    return await _tenant_for(payload)


async def _resolve_ticket(ticket: str) -> str:
    try:
        payload = verify_sse_ticket(ticket)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired ticket")
    return await _tenant_for(payload)


@router.post("/ticket")
async def create_ticket(user: User = Depends(get_current_user)):
    """SSE の接続用チケット(60秒で切れる)を発行する。通常のログイン(Authorization ヘッダ)で呼ぶ。

    EventSource はヘッダを送れず URL に認証情報を載せるしかない。URL はアクセスログ等に
    残るので、そこには長く使えるアクセストークンではなく、このチケットを載せる。"""
    return {
        "ticket": create_sse_ticket(user.tenant_id or "", user.id),
        "expires_in": SSE_TICKET_EXPIRE_SECONDS,
    }


@router.get("/stream")
async def stream(
    request: Request,
    ticket: str | None = Query(None),
    token: str | None = Query(None),
):
    if ticket:
        tenant_id = await _resolve_ticket(ticket)
    elif token:
        # 移行用: 画面とサーバーは別々にデプロイされるので、チケットに対応する前の画面の
        # ために、しばらくはアクセストークンを直接受ける。画面が切り替わったら外すこと。
        tenant_id = await _resolve_tenant_id(token)
    else:
        raise HTTPException(status_code=401, detail="認証情報がありません")

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
