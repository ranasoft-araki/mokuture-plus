"""In-process per-tenant event bus for Server-Sent Events (near-real-time admin sync).

キオスク操作(受付送信/応答/置き配/ロッカーミラー)が受付・ロッカーの状態を変えた瞬間、
その変化をテナント単位で管理画面のブラウザへ push するための最小 pub/sub。

本番は uvicorn `--workers 1`（Dockerfile 参照）＝**単一プロセス単一イベントループ**なので、
プロセス内メモリのファンアウトで全ての接続中の管理画面へ確実に届く（Redis 等の外部ブローカー不要）。
複数ワーカー化する場合はこのモジュールをプロセス跨ぎのブローカーに差し替えること。

設計方針（best-effort・受付/ロッカー処理を絶対に止めない）:
- `publish()` は同期・ノンブロッキング(`put_nowait`)で、リクエスト経路に例外を投げない。
- 各 SSE 接続は上限付きの `asyncio.Queue` を1つ持つ。詰まった(遅い/固まった)クライアントは
  あふれた分を捨てる＝メモリ無限増加を防ぐ。取りこぼしてもフロントは次イベントか低頻度の
  ポーリング・フォールバックで再取得するので状態は失われない。
- ペイロードは「何を再取得すべきか」の型マーカー(`{"type": "reception"|"locker"}`)のみ。
  秘密情報・PIN・本文は一切載せない。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# tenant_id -> 接続中 SSE それぞれの受信キュー
_subscribers: dict[str, set["asyncio.Queue[dict]"]] = {}

# 1接続あたりのバックログ上限。これを超えた分は捨てる（遅いクライアント保護）。
_MAX_QUEUE = 100


def subscribe(tenant_id: str) -> "asyncio.Queue[dict]":
    """新しい SSE 接続用の受信キューを登録して返す。呼び出し側は必ず finally で unsubscribe する。"""
    q: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.setdefault(tenant_id, set()).add(q)
    return q


def unsubscribe(tenant_id: str, q: "asyncio.Queue[dict]") -> None:
    subs = _subscribers.get(tenant_id)
    if not subs:
        return
    subs.discard(q)
    if not subs:
        _subscribers.pop(tenant_id, None)


def publish(tenant_id: str, event: dict) -> None:
    """テナントの全 SSE 購読者へイベントをファンアウトする。**決して例外を投げない**。"""
    subs = _subscribers.get(tenant_id)
    if not subs:
        return
    for q in list(subs):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # 遅い/固まったクライアント: このイベントは捨てる。クライアントは次イベント or
            # ポーリング・フォールバックで再取得するので自己修復する（メモリは無限に増えない）。
            pass
        except Exception:  # pragma: no cover - 念のため（publish はリクエスト経路を止めない）
            logger.debug("event publish drop (tenant=%s)", tenant_id)


def subscriber_count(tenant_id: str) -> int:
    return len(_subscribers.get(tenant_id, ()))
