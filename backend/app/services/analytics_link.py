"""受付ログID → 匿名セッションID の一時対応（**プロセス内メモリのみ・永続化しない**）。

通知の成否はサーバ側でしか分からないので、`notification_succeeded` /
`notification_failed` / `notification_retried` を匿名セッションへ紐づけるには
「この受付はどのセッションの操作だったか」を知る必要がある。

しかしこの対応を DB に持つと **匿名セッション → 受付ログ（氏名・会社名・担当者）** の
逆引きが可能になり、ANALYTICS.md の大前提（個人情報と結び付けない）を破る。
そこで対応表は **プロセス内の TTL 付き辞書だけ** に置く:

- 永続化しない（プロセスが落ちれば消える＝通知イベントを取りこぼすだけ）
- 既定 2 時間で失効。上限件数を超えたら古いものから捨てる
- 保持するのは匿名の識別子とバージョン情報だけ（氏名・担当者・本文は持たない）

in-memory 前提は既存の SSE pub/sub（`app/services/events.py`・uvicorn 単一ワーカー）と同じ。
複数ワーカー化する場合はここも外部ストアへ移すこと（ただし**永続化はしない**設計を保つ）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

_TTL_SEC = 2 * 60 * 60  # 2時間。受付の通知〜応答はこれより遥かに短い
_MAX_ENTRIES = 2000  # 端末数 × 同時受付数に対して十分。超えたら古い順に捨てる


@dataclass
class SessionRef:
    """匿名セッションを指す最小限の情報（個人情報は含まない）。"""

    session_id: str
    tenant_id: str
    site_id: str
    device_id: str | None = None
    app_version: str | None = None
    ui_version: str | None = None
    flow_version: str | None = None
    created_at: float = field(default_factory=time.monotonic)


_links: dict[str, SessionRef] = {}


def _purge(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [k for k, v in _links.items() if now - v.created_at > _TTL_SEC]
    for k in expired:
        _links.pop(k, None)
    if len(_links) > _MAX_ENTRIES:
        # 古い順に落とす（dict は挿入順を保つ）
        for k in list(_links)[: len(_links) - _MAX_ENTRIES]:
            _links.pop(k, None)


def remember(reception_log_id: str, ref: SessionRef) -> None:
    """受付ログIDと匿名セッションの対応を一時的に覚える。`session_id` が空なら何もしない。"""
    if not reception_log_id or not ref.session_id:
        return
    _purge()
    _links[reception_log_id] = ref


def lookup(reception_log_id: str) -> SessionRef | None:
    """対応を引く。失効・未登録なら None（＝通知イベントを出さないだけ）。"""
    if not reception_log_id:
        return None
    ref = _links.get(reception_log_id)
    if ref is None:
        return None
    if time.monotonic() - ref.created_at > _TTL_SEC:
        _links.pop(reception_log_id, None)
        return None
    return ref


def forget(reception_log_id: str) -> None:
    _links.pop(reception_log_id, None)


def clear() -> None:
    """テスト用。"""
    _links.clear()


def size() -> int:
    return len(_links)
