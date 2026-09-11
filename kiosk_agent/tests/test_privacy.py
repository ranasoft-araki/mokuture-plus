"""セキュリティ・プライバシー要件（§12）の確認。

  - 外部へ一切通信しない（ネットワークを切断しても動く）
  - 画像をディスクに書かない
  - 氏名・電話番号・メールアドレスをログに出さない
  - 確定・取り消し・タイムアウトのいずれでも画像と抽出結果が消える
"""
from __future__ import annotations

import logging
import socket
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from card import session as session_mod, settings
from card.api import router
from card.detect import detect_card
from card.extract import extract
from card.pipeline import read_card

AGENT_DIR = settings.AGENT_DIR

# フィクスチャに出てくる架空の個人情報。ログに現れてはいけない文字列。
SECRETS = [
    "山田", "太郎", "山田 太郎",
    "taro.yamada@example.jp", "taro.yamada",
    "03-1234-5678", "090-1234-5678", "0312345678",
    "東京都千代田区千代田1-2-3",
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 50000))


def jpeg(bgr, width: int) -> bytes:
    if bgr.shape[1] != width:
        scale = width / bgr.shape[1]
        bgr = cv2.resize(bgr, (width, int(bgr.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    assert ok
    return buf.tobytes()


# ── 完全ローカル動作 ──────────────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    """ネットワークを塞ぐ。何か通信しようとしたら即座に失敗させる。"""
    opened: list = []

    class Blocked(RuntimeError):
        pass

    def blocked(*args, **kwargs):
        opened.append(args)
        raise Blocked("この機能はネットワークを使ってはいけない")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    return opened


@pytest.mark.ocr
def test_ネットワークを切っても撮影から抽出まで動く(ocr_engine, scene, no_network):
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    assert det is not None
    result = read_card(bgr, det.quad)
    assert result is not None
    assert result.fields.company_name.value == "株式会社サンプル商会"
    assert not no_network, "外部へ接続しようとした"


def test_検出と抽出はネットワークを使わない(scene, no_network):
    from card.types import OcrLine
    bgr, _truth, _spec = scene("landscape_ja")
    assert detect_card(bgr) is not None
    lines = [OcrLine("株式会社サンプル商会", ((0, 0), (200, 0), (200, 30), (0, 30)), 0.98, 0)]
    assert extract(lines, (1024, 620)).company_name.value == "株式会社サンプル商会"
    assert not no_network


def test_ソースに外部URLが書かれていない():
    """OCR API・生成 AI・CDN を呼ぶコードが紛れ込んでいないこと。

    モデル取得スクリプト(scripts/)は導入時だけ動くので対象外。
    """
    suspicious = ("http://", "https://")
    allowed = ("https://raw.githubusercontent.com",)   # コメント内の参照のみ
    for path in sorted((AGENT_DIR / "card").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(s in line for s in suspicious) and not any(a in line for a in allowed):
                pytest.fail(f"{path.name}:{line_no} に外部 URL がある: {line.strip()}")


def test_名刺モジュールはHTTPクライアントを取り込んでいない():
    import importlib
    names = ("card.detect", "card.extract", "card.pipeline", "card.session",
             "card.preprocess", "card.quality", "card.ocr.paddle_onnx",
             "card.ocr.tesseract", "card.api")
    mod_sources = []
    for name in names:
        mod = importlib.import_module(name)
        mod_sources.append(Path(mod.__file__).read_text(encoding="utf-8"))
    joined = "\n".join(mod_sources)
    for banned in ("import requests", "import httpx", "urllib.request", "aiohttp"):
        assert banned not in joined, f"{banned} が使われている"


# ── 画像を残さない ────────────────────────────────────────────────────────────

@pytest.mark.ocr
def test_読み取りでファイルを作らない(ocr_engine, scene, tmp_path, monkeypatch):
    """画像も中間ファイルも書き出さないこと（/dev/shm も含め一切書かない）。"""
    written: list[str] = []
    real_open = open

    def watched_open(file, mode="r", *args, **kwargs):
        if any(m in mode for m in ("w", "a", "x", "+")):
            written.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", watched_open)
    real_imwrite = cv2.imwrite
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: written.append(str(a[0])) or True)

    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    result = read_card(bgr, det.quad)
    assert result is not None
    assert written == [], f"ファイルを書いた: {written}"
    monkeypatch.setattr(cv2, "imwrite", real_imwrite)


@pytest.mark.ocr
def test_確定するとセッションから画像が消える(ocr_engine, client, scene):
    sid = client.post("/card/session").json()["session_id"]
    bgr, _truth, _spec = scene("landscape_ja")
    client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280),
                headers={"Content-Type": "image/jpeg"})
    assert session_mod.store.get(sid).result is not None

    client.post(f"/card/session/{sid}/confirm", json={"values": {}})
    assert session_mod.store.get(sid) is None
    assert session_mod.store.count() == 0


@pytest.mark.ocr
def test_取り消してもセッションから画像が消える(ocr_engine, client, scene):
    sid = client.post("/card/session").json()["session_id"]
    bgr, _truth, _spec = scene("landscape_ja")
    client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280),
                headers={"Content-Type": "image/jpeg"})
    client.delete(f"/card/session/{sid}")
    assert session_mod.store.get(sid) is None


@pytest.mark.ocr
def test_タイムアウトでもセッションから画像が消える(ocr_engine, client, scene, monkeypatch):
    sid = client.post("/card/session").json()["session_id"]
    bgr, _truth, _spec = scene("landscape_ja")
    client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280),
                headers={"Content-Type": "image/jpeg"})
    session = session_mod.store.get(sid)
    assert session.result is not None

    monkeypatch.setenv("CARD_SESSION__TTL_SEC", "0")
    settings.reload()
    session_mod.store.purge()
    assert session_mod.store.count() == 0
    assert session.result is None      # 保持していた画像も捨てている


# ── ログに個人情報を出さない ──────────────────────────────────────────────────

@pytest.mark.ocr
def test_ログに氏名や連絡先を出さない(ocr_engine, client, scene, caplog):
    caplog.set_level(logging.DEBUG)
    sid = client.post("/card/session").json()["session_id"]
    bgr, _truth, _spec = scene("landscape_ja")
    body = jpeg(bgr, 640)
    client.post(f"/card/frame?session_id={sid}", content=body,
                headers={"Content-Type": "image/jpeg"})
    client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280),
                headers={"Content-Type": "image/jpeg"})
    client.post(f"/card/session/{sid}/confirm",
                json={"values": {"person_name": "山田 太郎"}})

    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in SECRETS:
        assert secret not in logged, f"ログに「{secret}」が出ている\n{logged}"


def test_抽出モジュールはログを出さない():
    """extract.py は値そのものを扱うので、logging を一切使わない方針。"""
    source = (AGENT_DIR / "card" / "extract.py").read_text(encoding="utf-8")
    assert "import logging" not in source
    assert "print(" not in source


def test_APIのログ出力に値を混ぜていない():
    """log.* の呼び出しに fields や text を直接渡していないこと。"""
    import re
    source = (AGENT_DIR / "card" / "api.py").read_text(encoding="utf-8")
    for m in re.finditer(r"log\.\w+\((.*?)\)\n", source, re.S):
        call = m.group(1)
        for banned in (".value", ".text", "fields[", "values["):
            assert banned not in call, f"ログに値を渡している: {call.strip()}"


# ── エラー時に内部情報を出さない ──────────────────────────────────────────────

def test_エラー応答に内部パスやスタックトレースを出さない(client):
    sid = client.post("/card/session").json()["session_id"]
    r = client.post(f"/card/frame?session_id={sid}", content=b"broken",
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Traceback" not in detail
    assert "\\" not in detail and "/home" not in detail
    assert str(AGENT_DIR) not in detail
