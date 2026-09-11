"""設定の解決（既定値 → YAML 上書き → 環境変数上書き）。

優先順位は後勝ち:
  1. card/defaults.py の DEFAULTS
  2. kiosk_agent/card_reader.yaml （任意。PyYAML が無ければ黙って飛ばす）
  3. 環境変数 CARD_<SECTION>__<KEY>（例: CARD_OCR__ENGINE, CARD_QUALITY__FOCUS_MIN）

値の型は既定値の型に合わせて変換する（既定が float なら float、list なら
カンマ区切りを分解）。既定に無いキーは無視する（打ち間違いで壊れないように）。
"""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

from card.defaults import DEFAULTS

log = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("CARD_CONFIG", str(AGENT_DIR / "card_reader.yaml")))

_cache: dict[str, Any] | None = None
_load_notes: list[str] = []


def _deep_merge(base: dict, over: dict, path: str = "") -> None:
    """over の値で base を再帰的に上書きする。base に無いキーは警告して捨てる。"""
    for k, v in over.items():
        here = f"{path}.{k}" if path else k
        if k not in base:
            _load_notes.append(f"unknown key ignored: {here}")
            continue
        if isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v, here)
        else:
            base[k] = v


def _coerce(default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw


def _apply_env(cfg: dict) -> None:
    """CARD_A__B__C=値 の形の環境変数を反映する。"""
    for env_key, raw in os.environ.items():
        if not env_key.startswith("CARD_") or env_key == "CARD_CONFIG":
            continue
        parts = [p.lower() for p in env_key[len("CARD_"):].split("__") if p]
        if not parts:
            continue
        node: Any = cfg
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                node = None
                break
            node = node[p]
        leaf = parts[-1]
        if not isinstance(node, dict) or leaf not in node:
            _load_notes.append(f"unknown env key ignored: {env_key}")
            continue
        try:
            node[leaf] = _coerce(node[leaf], raw)
        except ValueError:
            _load_notes.append(f"bad value for {env_key} (kept default)")


def _load() -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    _load_notes.clear()

    if CONFIG_PATH.exists():
        try:
            import yaml  # type: ignore
        except ImportError:
            _load_notes.append("PyYAML not installed; card_reader.yaml skipped")
        else:
            try:
                data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    _deep_merge(cfg, data)
                    _load_notes.append(f"loaded {CONFIG_PATH.name}")
                else:
                    _load_notes.append("card_reader.yaml is not a mapping; ignored")
            except Exception as e:  # 壊れた YAML でキオスクを止めない
                _load_notes.append(f"card_reader.yaml parse failed ({type(e).__name__}); using defaults")

    _apply_env(cfg)
    for note in _load_notes:
        log.info("[card] config: %s", note)
    return cfg


def cfg() -> dict[str, Any]:
    """解決済みの設定辞書を返す（初回のみ読み込み、以降はキャッシュ）。"""
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def get(path: str, default: Any = None) -> Any:
    """ドット区切りで取り出す。例: get("quality.focus_min")"""
    node: Any = cfg()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def resolve_path(value: str) -> Path:
    """設定に書かれた相対パスを kiosk_agent 直下基準で絶対化する。"""
    p = Path(value)
    return p if p.is_absolute() else (AGENT_DIR / p)


def notes() -> list[str]:
    """設定読み込み時のメモ（status API がそのまま返す。値は含まない）。"""
    cfg()
    return list(_load_notes)


def reload() -> dict[str, Any]:
    """設定を読み直す（テスト用・運用で YAML を編集したあとの再読込用）。"""
    global _cache
    _cache = None
    return cfg()
