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


def test_モデルは配信対象に入れない():
    """OCR モデルは大きすぎる（約 23MB）。導入時にだけ置く。"""
    for rel in _managed():
        assert not rel.startswith("models/"), rel


def test_辞書は配信するが現場の追記ファイルは配信しない():
    """辞書の中身はコードと一緒に育つので配信する。

    以前は「現場で追記されうるので上書きしない」として配信対象から外していたが、
    そのままだと辞書を直しても既設の端末に届かない（姓辞書を 113 件から約 2 万件へ
    増やしたときに問題になった）。現場の追記は `*.local.*` に分けることで守る。
    """
    managed = set(_managed())
    assert "card/dictionaries/surnames.tsv" in managed
    assert not [r for r in managed if ".local." in r]


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
    """配って反映されないコードを作らない。

    音声入力(voice/)だけは例外。キオスク本体とは**別プロセス**で動くので、本体を
    再起動しても入れ替わらない。代わりに音声サービスが自分のソースの変化を見て
    自ら終了し、systemd に起こし直してもらう。例外にする以上、その仕組みが実際に
    在ることを下の test で確かめる。
    """
    import updater
    for rel in _managed():
        if rel.endswith(".py"):
            name = Path(rel).name
            top = Path(rel).parts[0]
            if top == "voice":
                continue
            assert name in updater.RESTART_FILES or top in updater._RESTART_DIRS, \
                f"{rel} を更新しても再起動されない"


def test_音声サービスは自分でソース更新に気づいて再起動する():
    """voice/ を RESTART から外している根拠。仕組みが消えたら気付けるようにする。"""
    server = (AGENT_DIR / "voice" / "server.py").read_text(encoding="utf-8")
    assert "_sources_digest" in server, "ソースの指紋を取る仕組みが無い"
    assert "_watch_sources" in server, "ソース変化を見張る仕組みが無い"
    assert "os._exit" in server, "変化を見つけても終了していない"

    unit = (AGENT_DIR / "mokuture-voice.service").read_text(encoding="utf-8")
    assert "Restart=always" in unit, "終了しても起こし直されない"


def test_音声モジュールが配信対象に入っている():
    managed = set(_managed())
    voice_files = {
        str(p.relative_to(AGENT_DIR)).replace("\\", "/")
        for p in (AGENT_DIR / "voice").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    missing = voice_files - managed
    assert not missing, f"OTA に入っていない音声モジュール: {sorted(missing)}"


def test_音声のモデルと端末ごとの設定は配信対象に入れない():
    """モデルは大きすぎる。設定は現場で調整したものを上書きしたくない。"""
    for rel in _managed():
        assert not rel.startswith("voice_models/"), rel
        assert not rel.startswith("vendor/"), rel
        assert rel != "voice_input.yaml", rel
        assert rel != "staff_readings.yaml", rel
