"""画面から送るメールの回数制限（テナント単位・プロセス内）。

来社予定 QR のメール送信と、担当者ごとの通知先のテスト送信は、宛先を画面で自由に
指定できる。共有の SMTP アカウントから送るので、1テナントが短時間に大量に送ると
送信元の評価が下がり、全テナントのメールが届かなくなる。直近1時間で30通までにする。

受付時の自動通知メール(reception_notify)は来訪者の受付に応じて送る本来の通知なので
数えない。単一ワーカー前提(複数ワーカーにするなら共有ストアへ移すこと)。
"""
from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException

LIMIT_PER_HOUR = 30
WINDOW_SEC = 3600.0

QUOTA_DETAIL = "メールの送信回数が上限(1時間に30通)に達しました。しばらく待ってからお試しください。"

_sent: dict[str, deque] = {}


def consume(tenant_id: str, count: int = 1) -> None:
    """これから送る `count` 通ぶんの枠を先に確保する。足りなければ 429。

    送信の await より前に確保するので、同時に押されても上限を超えない。"""
    if count <= 0:
        return
    now = time.monotonic()
    q = _sent.setdefault(tenant_id or "", deque())
    while q and now - q[0] > WINDOW_SEC:
        q.popleft()
    if len(q) + count > LIMIT_PER_HOUR:
        raise HTTPException(status_code=429, detail=QUOTA_DETAIL)
    q.extend([now] * count)
    # 空になったテナントの行を残さない(辞書が増え続けないように)。
    for key in [k for k, v in _sent.items() if not v]:
        del _sent[key]


def clear_all() -> None:
    """テスト用。"""
    _sent.clear()
