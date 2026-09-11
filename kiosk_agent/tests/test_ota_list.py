"""OTA 配信リストの整合性。

配信リストは agent(updater.MANAGED_FILES) と backend(kiosk.BUNDLE_FILES) の 2 か所に
あり、ズレると「その端末だけ古いコードのまま動く」という気付きにくい壊れ方をする。
ハッシュの計算順にも使われるので、並び順まで一致させる。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
BACKEND_KIOSK = AGENT_DIR.parent / "backend" / "app" / "api" / "kiosk.py"


def _list_literal(text: str, name: str) -> list[str]:
    body = text.split(f"{name} = [", 1)[1].split("\n]", 1)[0]
    return [m.group(1) for m in re.finditer(r'"([^"]+)"', body)]


def _managed() -> list[str]:
    import updater
    return list(updater.MANAGED_FILES)


def test_配信対象のファイルが実在する():
    for rel in _managed():
        assert (AGENT_DIR / rel).exists(), f"配信対象なのにファイルが無い: {rel}"


def test_名刺モジュールが配信対象に入っている():
    managed = set(_managed())
    card_files = {
        str(p.relative_to(AGENT_DIR)).replace("\\", "/")
        for p in (AGENT_DIR / "card").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    missing = card_files - managed
    assert not missing, f"OTA に入っていない名刺モジュール: {sorted(missing)}"


def test_辞書とモデルは配信対象に入れない():
    """辞書は現場で追記されうるので上書きしない。モデルは大きすぎる。"""
    for rel in _managed():
        assert not rel.startswith("models/"), rel
        assert not rel.startswith("card/dictionaries/"), rel


def test_agentとbackendの配信リストが一致する():
    if not BACKEND_KIOSK.exists():
        pytest.skip("backend が同じチェックアウトに無い")
    backend = _list_literal(BACKEND_KIOSK.read_text(encoding="utf-8"), "BUNDLE_FILES")
    assert _managed() == backend, (
        "agent と backend で配信リストがズレている。"
        f"\n  agent のみ: {sorted(set(_managed()) - set(backend))}"
        f"\n  backend のみ: {sorted(set(backend) - set(_managed()))}"
    )


def test_Pythonの変更は再起動扱いになる():
    import updater
    for rel in _managed():
        if rel.endswith(".py"):
            name = Path(rel).name
            top = Path(rel).parts[0]
            assert name in updater.RESTART_FILES or top in updater._RESTART_DIRS, \
                f"{rel} を更新しても再起動されない"
