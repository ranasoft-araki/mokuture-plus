"""Local-first locker state for the kiosk agent.

各ロッカーは物理的にこの端末の GPIO に直結している＝**この端末が占有状態と暗証番号の
真実の源**。PIN はソルト付き pbkdf2 ハッシュで保存し（平文は端末に置かない）、状態は
locker_state.json に永続化して再起動をまたいで保持する。

台帳（locker_id → name / door_number）はバックエンドから best-effort で同期するが、
**占有(occupied)と PIN はローカルが権威**なので、解錠はクラウド往復なしで（オフラインでも）
成立する。バックエンドへは best-effort でミラー＋置き配通知の中継のみを行う。
"""
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

_STATE_FILE = Path(__file__).parent / "locker_state.json"
_lock = RLock()
_PBKDF2_ROUNDS = 120_000


class LockerError(Exception):
    """HTTP ステータス付きのロッカー操作エラー（main.py で HTTPException に変換）。"""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _PBKDF2_ROUNDS).hex()


def _generate_pin() -> str:
    return f"{secrets.randbelow(10000):04d}"


def _load() -> dict:
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("lockers", {})
                data.setdefault("pending_notify", [])
                data.setdefault("roster_synced_at", None)
                return data
        except Exception:
            pass
    return {"lockers": {}, "pending_notify": [], "roster_synced_at": None}


def _save(data: dict) -> None:
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_STATE_FILE)


def _entry_public(lid: str, e: dict) -> dict:
    return {
        "id": lid,
        "name": e.get("name") or f"ロッカー {e.get('door_number')}",
        "door_number": e.get("door_number"),
        "occupied": bool(e.get("occupied")),
        "has_pin": bool(e.get("pin_hash")),
    }


# ── 読み取り ────────────────────────────────────────────────────────────────

def snapshot() -> dict:
    """kiosk のグリッド用。台帳＋ローカル状態を返す。"""
    with _lock:
        data = _load()
        lockers = data["lockers"]
        items = [
            _entry_public(lid, e)
            for lid, e in sorted(lockers.items(), key=lambda kv: (kv[1].get("door_number") or 0, kv[0]))
        ]
        return {
            "lockers": items,
            "available_count": sum(1 for it in items if not it["occupied"]),
        }


def roster_age_sec() -> float | None:
    """台帳の最終同期からの経過秒。未同期なら None。"""
    with _lock:
        ts = _load().get("roster_synced_at")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def door_of(locker_id: str) -> int | None:
    with _lock:
        e = _load()["lockers"].get(str(locker_id))
        return e.get("door_number") if e else None


# ── 台帳同期（backend → ローカル。占有/PIN は触らない） ─────────────────────

def sync_roster(items: list[dict]) -> None:
    """backend の /kiosk/lockers 応答（[{id,name,door_number,...}]）で台帳を更新。
    占有(occupied)・PIN 等のローカル状態は保持する。"""
    with _lock:
        data = _load()
        lockers = data["lockers"]
        next_lockers = {}
        for it in items or []:
            lid = str(it.get("id") or "")
            if not lid:
                continue
            door_number = it.get("door_number")
            e = lockers.get(lid)
            if e is None and door_number is not None:
                e = next((old for old in lockers.values() if old.get("door_number") == door_number), None)
            if e is None:
                e = {
                    "door_number": None, "name": None, "occupied": False,
                    "pin_salt": None, "pin_hash": None, "occupied_at": None, "kind": None,
                }
            e = dict(e)
            e["door_number"] = door_number
            e["name"] = it.get("name")
            next_lockers[lid] = e
        data["lockers"] = next_lockers
        data["roster_synced_at"] = _now_iso()
        _save(data)


# ── 書き込み（ローカルが権威） ─────────────────────────────────────────────

def occupy(locker_id: str, pin: str, kind: str = "store") -> dict:
    lid = str(locker_id)
    with _lock:
        data = _load()
        e = data["lockers"].get(lid)
        if e is None:
            raise LockerError(404, "Locker not found")
        if e.get("occupied"):
            raise LockerError(409, "already occupied")
        salt = os.urandom(16)
        e["pin_salt"] = salt.hex()
        e["pin_hash"] = _hash_pin(pin, salt)
        e["occupied"] = True
        e["occupied_at"] = _now_iso()
        e["kind"] = kind
        _save(data)
        return {"ok": True, "door_number": e.get("door_number")}


def occupy_delivery(locker_id: str) -> dict:
    """置き配: ランダム4桁PINを生成してローカル施錠状態にし、通知用に平文PINを返す。"""
    lid = str(locker_id)
    with _lock:
        data = _load()
        e = data["lockers"].get(lid)
        if e is None:
            raise LockerError(404, "Locker not found")
        if e.get("occupied"):
            raise LockerError(409, "already occupied")
        pin = _generate_pin()
        salt = os.urandom(16)
        e["pin_salt"] = salt.hex()
        e["pin_hash"] = _hash_pin(pin, salt)
        e["occupied"] = True
        e["occupied_at"] = _now_iso()
        e["kind"] = "delivery"
        _save(data)
        return {
            "ok": True,
            "pin": pin,
            "door_number": e.get("door_number"),
            "name": e.get("name") or f"ロッカー {e.get('door_number')}",
        }


def release(locker_id: str, pin: str) -> dict:
    """ローカルで PIN 照合して解錠状態にする（クラウド不要）。"""
    lid = str(locker_id)
    with _lock:
        data = _load()
        e = data["lockers"].get(lid)
        if e is None:
            raise LockerError(404, "Locker not found")
        if not e.get("occupied"):
            raise LockerError(409, "not occupied")
        salt_hex = e.get("pin_salt") or ""
        stored = e.get("pin_hash") or ""
        ok = False
        if salt_hex and stored:
            calc = _hash_pin(pin, bytes.fromhex(salt_hex))
            ok = hmac.compare_digest(calc, stored)
        if not ok:
            raise LockerError(403, "invalid pin")
        door = e.get("door_number")
        e["occupied"] = False
        e["pin_salt"] = None
        e["pin_hash"] = None
        e["occupied_at"] = None
        e["kind"] = None
        _save(data)
        return {"ok": True, "door_number": door}


def release_all() -> dict:
    """全ロッカーを解錠状態にリセット（緊急・メンテ用）。"""
    with _lock:
        data = _load()
        doors = []
        for e in data["lockers"].values():
            if e.get("door_number") is not None:
                doors.append(e["door_number"])
            e["occupied"] = False
            e["pin_salt"] = None
            e["pin_hash"] = None
            e["occupied_at"] = None
            e["kind"] = None
        _save(data)
        return {"ok": True, "door_numbers": doors, "count": len(doors)}


# ── ミラー用スナップショット（occupied/has_pin のみ・PIN は出さない） ───────

def mirror_payload() -> dict:
    with _lock:
        data = _load()
        return {"lockers": [
            {"id": lid, "occupied": bool(e.get("occupied")), "has_pin": bool(e.get("pin_hash"))}
            for lid, e in data["lockers"].items()
        ]}


# ── 置き配通知の保留キュー（オフライン時に貯めて再接続で送る） ──────────────

def enqueue_notify(item: dict) -> None:
    with _lock:
        data = _load()
        data["pending_notify"].append(item)
        _save(data)


def take_pending_notify() -> list[dict]:
    """保留通知を取り出してキューを空にする（呼び出し側が送信を試みる）。"""
    with _lock:
        data = _load()
        pending = data.get("pending_notify") or []
        if pending:
            data["pending_notify"] = []
            _save(data)
        return pending


def requeue_notify(items: list[dict]) -> None:
    with _lock:
        data = _load()
        data["pending_notify"] = list(items) + (data.get("pending_notify") or [])
        _save(data)
