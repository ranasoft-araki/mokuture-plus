"""Persistent device state (device_token, device_name).

Stored in device_state.json alongside this file so it survives restarts.
The token is obtained once via self-registration (POST /register) and reused from then on.
"""
import json
import os
from pathlib import Path

_STATE_FILE = Path(__file__).parent / "device_state.json"
_warned_corrupt = False


def _read() -> dict:
    """保存内容を読む。無い・空・壊れている(停電で書きかけ等)ときは「状態なし」として {} を返す。

    以前は壊れた JSON で例外になり、登録のやり直しも定期処理も止まったままになった。
    「状態なし」なら次の /register で登録し直せる(トークンを添えられないので承認待ちに戻る)。"""
    global _warned_corrupt
    try:
        text = _STATE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        print(f"[state] device_state.json を読めません: {e}")
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        if not _warned_corrupt:
            _warned_corrupt = True
            print("[state] device_state.json が壊れているため、未登録として扱います")
        return {}
    return data if isinstance(data, dict) else {}


def get_device_token() -> str:
    return str(_read().get("device_token") or "")


def get_device_name() -> str:
    return str(_read().get("device_name") or "")


def save_device_state(token: str, name: str) -> None:
    """一時ファイルに書いてから置き換える(書いている途中で電源が落ちても元のファイルが残る)。"""
    global _warned_corrupt
    tmp = _STATE_FILE.with_name(_STATE_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps({"device_token": token, "device_name": name}, indent=2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _STATE_FILE)
    _warned_corrupt = False


def clear_device_state() -> None:
    """保存済みの端末トークンを削除する（別テナントへの付け替え/再登録用）。
    次回 /register で TENANT_SLUG による新規登録がやり直される。"""
    try:
        _STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def is_registered() -> bool:
    return bool(get_device_token())
