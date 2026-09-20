"""実証実験用の匿名メトリクス(§11・§12)。

**書いてよいのは個人を特定できない数値と固定語彙だけ。** 認識したテキスト・氏名・
会社名・担当者名は 1 文字も書かない。修正されたかどうかは真偽値だけを残す(§12)。

安全のしくみは「書ける項目を列挙しておき、それ以外は捨てる」方式にした(`_ALLOWED`)。
あとから項目を足すときに、うっかり本文を混ぜても落ちるだけで漏れない。

1 行 1 レコードの JSON Lines。サイズが上限を超えたら世代を回す(ログ基盤には送らない。
端末の中だけで完結する)。

レコード例:

    {"sessionId": "8f3c…", "screenId": "visitor-name-input", "inputMethod": "voice",
     "model": "whisper-base-q5", "audioDurationMs": 3200, "recognitionDurationMs": 1400,
     "result": "success", "retryCount": 0, "errorCode": null, "timestamp": "..."}

`sessionId` は音声入力を始めるたびに作る使い捨ての乱数で、受付ログ(reception_logs)とは
一切ひも付けない。受付が終わった後にこの ID から個人へ戻る経路は存在しない(§11)。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voice import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()

# 画面(項目)→ screenId。要件の例に合わせた固定語彙。
SCREEN_IDS = {
    "company": "company-input",
    "person_name": "visitor-name-input",
    "staff": "host-select",
    "command": "voice-command",
}

# 書き出してよいキーと型。ここに無いキーは黙って捨てる。
_ALLOWED: dict[str, type | tuple[type, ...]] = {
    "sessionId": str,
    "screenId": str,
    "inputMethod": str,          # "voice" | "touch"
    "model": str,
    "engine": str,
    "audioDurationMs": int,
    "recognitionDurationMs": int,
    "totalMs": int,              # 発話終了 → 結果表示(§3-1・§12)
    "result": str,               # success | retry | cancel | error | confirm | fallback_touch
    "retryCount": int,
    "errorCode": (str, type(None)),
    "stopReason": (str, type(None)),
    "edited": bool,              # 利用者が結果を直したか(中身は残さない)
    "accepted": bool,
    "candidateCount": int,
    "timestamp": str,
}

# 万一混ざっても書かないキー(名前で弾く二重の網)。
_FORBIDDEN = {
    "text", "raw_text", "rawText", "value", "name", "visitor_name", "company",
    "staff", "transcript", "result_text", "pcm", "audio", "words",
}


def _path() -> Path:
    return Path(str(settings.get("metrics.path"))).expanduser()


def _sanitize(event: dict[str, Any]) -> dict[str, Any]:
    """許可した項目だけを、型を確かめて取り出す。"""
    out: dict[str, Any] = {}
    for key, want in _ALLOWED.items():
        if key not in event:
            continue
        if key in _FORBIDDEN:
            continue
        value = event[key]
        if isinstance(want, tuple):
            ok = isinstance(value, want)
        elif want is bool:
            ok = isinstance(value, bool)
        elif want is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok = isinstance(value, want)
        if not ok:
            continue
        if isinstance(value, str) and len(value) > 64:
            # 固定語彙しか入らない項目なので、長い文字列は異常。切るのではなく捨てる。
            continue
        out[key] = value
    return out


def _rotate_if_needed(path: Path) -> None:
    limit = int(settings.get("metrics.max_bytes"))
    keep = max(1, int(settings.get("metrics.keep_files")))
    try:
        if not path.exists() or path.stat().st_size < limit:
            return
        for i in range(keep - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            dst = path.with_suffix(path.suffix + f".{i + 1}")
            if src.exists():
                os.replace(src, dst)
        os.replace(path, path.with_suffix(path.suffix + ".1"))
    except OSError as e:
        log.warning("[voice] metrics rotate failed: %s", type(e).__name__)


def record(event: dict[str, Any]) -> None:
    """1 レコード書く。失敗しても呼び出し側は止めない(実験ログのために受付を壊さない)。"""
    if not bool(settings.get("metrics.enabled")):
        return
    row = _sanitize(event)
    if not row:
        return
    row.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    row.setdefault("inputMethod", "voice")
    path = _path()
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("[voice] metrics write failed: %s", type(e).__name__)


def _read_rows() -> list[dict[str, Any]]:
    path = _path()
    rows: list[dict[str, Any]] = []
    keep = max(1, int(settings.get("metrics.keep_files")))
    files = [path] + [path.with_suffix(path.suffix + f".{i}") for i in range(1, keep + 1)]
    for f in files:
        try:
            if not f.exists():
                continue
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
        except OSError:
            continue
    return rows


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[idx]


def summary() -> dict[str, Any]:
    """§12 の指標を集計する。個票は返さない(件数と割合と時間だけ)。"""
    rows = _read_rows()
    attempts = [r for r in rows if r.get("result") in ("success", "error", "cancel")]
    total = len(attempts)
    success = sum(1 for r in attempts if r.get("result") == "success")
    errors = sum(1 for r in attempts if r.get("result") == "error")
    cancels = sum(1 for r in attempts if r.get("result") == "cancel")
    retries = sum(1 for r in attempts if int(r.get("retryCount") or 0) > 0)

    confirms = [r for r in rows if r.get("result") == "confirm"]
    edited = sum(1 for r in confirms if r.get("edited") is True)
    fallbacks = sum(1 for r in rows if r.get("result") == "fallback_touch")
    sessions = {r.get("sessionId") for r in rows if r.get("sessionId")}

    def ratio(n: int, d: int) -> float | None:
        return round(n / d, 4) if d else None

    # 項目別の再入力率
    by_screen: dict[str, dict[str, Any]] = {}
    for r in attempts:
        sid = str(r.get("screenId") or "unknown")
        b = by_screen.setdefault(sid, {"attempts": 0, "success": 0, "retried": 0, "cancel": 0, "error": 0})
        b["attempts"] += 1
        if r.get("result") == "success":
            b["success"] += 1
        if r.get("result") == "cancel":
            b["cancel"] += 1
        if r.get("result") == "error":
            b["error"] += 1
        if int(r.get("retryCount") or 0) > 0:
            b["retried"] += 1
    for b in by_screen.values():
        b["success_rate"] = ratio(b["success"], b["attempts"])
        b["retry_rate"] = ratio(b["retried"], b["attempts"])

    # モデル別の処理時間
    by_model: dict[str, dict[str, Any]] = {}
    for r in attempts:
        model = str(r.get("model") or "unknown")
        m = by_model.setdefault(model, {"count": 0, "_rec": [], "_total": []})
        m["count"] += 1
        rec = r.get("recognitionDurationMs")
        if isinstance(rec, int):
            m["_rec"].append(rec)
        tot = r.get("totalMs")
        if isinstance(tot, int):
            m["_total"].append(tot)
    for m in by_model.values():
        rec, tot = m.pop("_rec"), m.pop("_total")
        m["recognition_ms_p50"] = _percentile(rec, 0.5)
        m["recognition_ms_p95"] = _percentile(rec, 0.95)
        m["end_to_display_ms_p50"] = _percentile(tot, 0.5)
        m["end_to_display_ms_p95"] = _percentile(tot, 0.95)

    all_total = [r["totalMs"] for r in attempts if isinstance(r.get("totalMs"), int)]
    return {
        "voice_sessions": len(sessions),
        "attempts": total,
        "success_rate": ratio(success, total),
        "error_rate": ratio(errors, total),
        "cancel_rate": ratio(cancels, total),
        "retry_rate": ratio(retries, total),
        "edited_rate": ratio(edited, len(confirms)),
        "confirms": len(confirms),
        "fallback_to_touch": fallbacks,
        "fallback_rate": ratio(fallbacks, len(sessions)) if sessions else None,
        "end_to_display_ms_p50": _percentile(all_total, 0.5),
        "end_to_display_ms_p95": _percentile(all_total, 0.95),
        "by_screen": by_screen,
        "by_model": by_model,
    }
