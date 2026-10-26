"""実証実験用の匿名メトリクス(声で操作する)。

**書いてよいのは個人を特定できない数値と固定語彙だけ。** 認識した言葉は 1 文字も書かない。
残すのは画面名・選ばれた選択肢の id(画面が決めた固定語彙)・外れた理由・所要時間だけ。

安全のしくみは「書ける項目を列挙しておき、それ以外は捨てる」方式にした(`_ALLOWED`)。
あとから項目を足すときに、うっかり本文を混ぜても落ちるだけで漏れない。

1 行 1 レコードの JSON Lines。サイズが上限を超えたら世代を回す(ログ基盤には送らない。
端末の中だけで完結する)。

レコード例:

    {"sessionId": "8f3c…", "screenId": "command-top", "model": "vosk-small-ja-0.22",
     "recognitionDurationMs": 62, "result": "success", "choiceId": "locker",
     "errorCode": null, "timestamp": "..."}

`sessionId` は音声モードに入るたびに作る使い捨ての乱数で、受付ログ(reception_logs)とは
一切ひも付けない。
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

# 書き出してよいキーと型。ここに無いキーは黙って捨てる。
_ALLOWED: dict[str, type | tuple[type, ...]] = {
    "sessionId": str,
    "screenId": str,             # command-<画面名>
    "model": str,
    "engine": str,
    "audioDurationMs": int,
    "recognitionDurationMs": int,
    "totalMs": int,              # 話し終わり → 判定
    "result": str,               # success | error
    "accepted": bool,
    # 選ばれた選択肢。画面が決めた固定語彙(「visit」「back」)で、話した言葉そのものではない。
    "choiceId": (str, type(None)),
    "errorCode": (str, type(None)),
    "stopReason": (str, type(None)),
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
    """話しかけられた回のうち、画面が動いた割合と外れ方。個票は返さない。

    embedded(文の一部として言われた)が多い画面は、周りの会話を拾っている。
    誤爆(言っていないのに当たった)はここからは分からない。ロビーの録音で測る
    (scripts/voice_command_eval.py / VOICE_COMMAND.md)。
    """
    rows = [r for r in _read_rows() if str(r.get("screenId") or "").startswith("command-")]
    by_screen: dict[str, dict[str, Any]] = {}
    by_choice: dict[str, int] = {}
    rec_ms: list[int] = []
    tot_ms: list[int] = []
    for r in rows:
        screen = str(r.get("screenId") or "unknown").removeprefix("command-")
        b = by_screen.setdefault(screen, {"attempts": 0, "matched": 0, "unmatched": 0,
                                          "ambiguous": 0, "embedded": 0, "error": 0})
        b["attempts"] += 1
        code = r.get("errorCode")
        if r.get("choiceId"):
            b["matched"] += 1
            by_choice[str(r["choiceId"])] = by_choice.get(str(r["choiceId"]), 0) + 1
        elif code in ("unmatched", "ambiguous", "embedded"):
            b[code] += 1
        else:
            b["error"] += 1
        if isinstance(r.get("recognitionDurationMs"), int):
            rec_ms.append(r["recognitionDurationMs"])
        if isinstance(r.get("totalMs"), int):
            tot_ms.append(r["totalMs"])
    total = sum(b["attempts"] for b in by_screen.values())
    matched = sum(b["matched"] for b in by_screen.values())
    for b in by_screen.values():
        b["matched_rate"] = round(b["matched"] / b["attempts"], 4) if b["attempts"] else None
    return {
        "voice_sessions": len({r.get("sessionId") for r in rows if r.get("sessionId")}),
        "attempts": total,
        "matched_rate": round(matched / total, 4) if total else None,
        "recognition_ms_p50": _percentile(rec_ms, 0.5),
        "recognition_ms_p95": _percentile(rec_ms, 0.95),
        "end_to_display_ms_p50": _percentile(tot_ms, 0.5),
        "end_to_display_ms_p95": _percentile(tot_ms, 0.95),
        "by_screen": by_screen,
        "by_choice": by_choice,
    }
