"""ログイン失敗の回数制限（アカウント単位・プロセス内）。

接続元 IP ではなく「ログイン ID」(メールアドレス / 代理店 ID)ごとに数える。IP 単位だと
接続元を変えながら同じアカウントを試し続けられるため。10分間に8回失敗したら、
その ID は10分間ログインを受け付けない(正しいパスワードでも 429)。成功したら数え直す。
存在しない ID も同じように数える(応答の違いでアカウントの有無が分からないように)。

本番は単一ワーカー(SSE の pub/sub と同じ前提)なのでプロセス内の辞書で足りる。
複数ワーカーにするなら共有ストアへ移すこと。辞書の大きさには上限を設ける。
"""
from __future__ import annotations

import time
from collections import OrderedDict

from fastapi import HTTPException

MAX_FAILURES = 8
WINDOW_SEC = 600.0
LOCK_SEC = 600.0
_MAX_KEYS = 10000

LOCKED_DETAIL = "ログインの失敗が続いたため、このアカウントのログインを一時的に止めています。10分ほど待ってからお試しください。"


class _Entry:
    __slots__ = ("failures", "locked_until")

    def __init__(self) -> None:
        self.failures: list[float] = []
        self.locked_until: float = 0.0


_entries: "OrderedDict[str, _Entry]" = OrderedDict()


def _now() -> float:
    return time.monotonic()


def key_for(kind: str, login_id: str | None) -> str:
    """ログイン ID を正規化したキー(前後空白を落とし小文字に)。"""
    return f"{kind}:{(login_id or '').strip().lower()}"


def _prune(now: float) -> None:
    if len(_entries) <= _MAX_KEYS:
        return
    for k in list(_entries.keys()):
        e = _entries[k]
        if e.locked_until <= now and (not e.failures or now - e.failures[-1] > WINDOW_SEC):
            del _entries[k]
    while len(_entries) > _MAX_KEYS:
        _entries.popitem(last=False)  # いちばん古く触られたものから捨てる


def check(key: str) -> None:
    """止めている最中なら 429 を投げる。パスワード照合より前に呼ぶ。"""
    e = _entries.get(key)
    if e is not None and e.locked_until > _now():
        raise HTTPException(status_code=429, detail=LOCKED_DETAIL)


def record_failure(key: str) -> None:
    now = _now()
    e = _entries.get(key)
    if e is None:
        e = _Entry()
        _entries[key] = e
    else:
        _entries.move_to_end(key)
    e.failures = [t for t in e.failures if now - t <= WINDOW_SEC]
    e.failures.append(now)
    if len(e.failures) >= MAX_FAILURES:
        e.locked_until = now + LOCK_SEC
        e.failures = []
    _prune(now)


def reset(key: str) -> None:
    _entries.pop(key, None)


def clear_all() -> None:
    """テスト用。"""
    _entries.clear()
