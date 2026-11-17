"""システム更新(OS の設定・パッケージ・ライブラリ)の状態を読む。

OTA(updater.py)はエージェントの利用者権限でファイルを置き換えるだけで、OS の設定変更や
ライブラリの導入はできない。それは管理者権限で動く別の仕組み(system/sysupdate-root.sh ―
署名を確かめられた手順だけを実行する)が受け持つ。エージェントは管理者権限を持たないので、
ここは**結果を読むだけ**: デバイスチェック画面へ状態を出すことと、その仕組みから頼まれた
再起動に(待機画面へ戻ったときに)応じること。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HELPER = Path("/usr/local/lib/mokuture/sysupdate-root.sh")
STATE_DIR = Path("/var/lib/mokuture")
MANIFEST = Path(__file__).parent / "system" / "SYSTEM_MANIFEST"

_IS_DEVICE = sys.platform.startswith("linux")   # 端末は Linux だけ(開発機では画面に出さない)


def _restart_token() -> str:
    """再起動の頼みの印(中身は頼むたびに変わる)。無ければ空。"""
    try:
        return (STATE_DIR / "restart-requested").read_text(encoding="utf-8", errors="replace").strip()[:80]
    except OSError:
        return ""


# 起動したときの印。これと違う印が置かれたら「起動のあとに頼まれた」。
# 時刻では比べない: 時計を持たない Pi は起動直後の時刻が前回の停止時刻まで戻るので、
# 置かれた印が「未来」に見えて、待機画面のたびに再起動し続ける。
_TOKEN_AT_START = _restart_token()


def wanted_version() -> str | None:
    """配信されているシステム更新の版(sysupdate-root.sh と同じ算法)。届いていなければ None。"""
    try:
        return hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _applied() -> dict:
    try:
        data = json.loads((STATE_DIR / "sysupdate.status").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def status() -> dict:
    """state:
    unsupported   端末(Linux)ではない
    not_delivered 仕組みは入っているが、システム更新がまだ配信されていない
    not_installed 管理者権限で動く側がまだ入っていない(install.sh を一度実行する)
    pending       新しい版が届いていて、まだ適用していない(10 分以内に自動で適用)
    ok            適用済み
    failed        適用したが失敗した手順がある(message に手順名。1 時間ごとにやり直す)
    rejected      署名などを確かめられず実行しなかった(message に理由)
    """
    if not _IS_DEVICE:
        return {"state": "unsupported"}
    wanted = wanted_version()
    if not HELPER.exists():
        return {"state": "not_installed", "wanted": wanted}
    if wanted is None:
        return {"state": "not_delivered", "wanted": None}
    last = _applied()
    out = {"wanted": wanted, "version": last.get("version"), "at": last.get("at"),
           "message": str(last.get("message") or "")}
    if last.get("version") != wanted:
        return {**out, "state": "pending"}
    state = last.get("state")
    return {**out, "state": state if state in ("ok", "failed", "rejected") else "pending"}


def restart_requested() -> bool:
    """システム更新が、このエージェントの起動より後に再起動を頼んでいるか。"""
    token = _restart_token()
    return bool(token) and token != _TOKEN_AT_START
