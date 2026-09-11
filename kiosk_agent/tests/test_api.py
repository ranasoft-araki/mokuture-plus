"""名刺読み取り API（キオスクのブラウザが叩く経路）。

FastAPI の TestClient で、セッション開始 → 検出フレーム → 撮影 → 確定 まで通す。
入力検証（不正なセッション ID・大きすぎる本文・対応しない形式）と、
ループバック制限も確認する。
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from card import session as session_mod, settings
from card.api import router
from card.types import FIELD_NAMES


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    # キオスクのブラウザは端末自身から叩く。同じ条件にする。
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def remote_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("192.0.2.10", 50000))


def jpeg(bgr, width: int, quality: int = 85) -> bytes:
    if bgr.shape[1] != width:
        scale = width / bgr.shape[1]
        bgr = cv2.resize(bgr, (width, int(bgr.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return buf.tobytes()


def start(client) -> str:
    r = client.post("/card/session")
    assert r.status_code == 200
    return r.json()["session_id"]


# ── 状態 ──────────────────────────────────────────────────────────────────────

def test_status_が画面に必要な情報を返す(client):
    r = client.get("/card/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"available", "enabled", "engine", "detail", "engines",
                         "dictionaries", "capture", "confidence", "guidance", "fields"}
    assert body["fields"] == list(FIELD_NAMES)
    assert body["capture"]["detect_interval_ms"] > 0
    assert 0 < body["confidence"]["warn"] < body["confidence"]["ok"] <= 1.0
    # 案内文言は全状態ぶん揃っている
    assert body["guidance"]["no_card"]["ja"]
    assert body["guidance"]["blurry"]["ja"]


def test_機能を無効にすると使えないと返る(client, monkeypatch):
    monkeypatch.setenv("CARD_ENABLED", "false")
    settings.reload()
    assert client.get("/card/status").json()["available"] is False
    assert client.post("/card/session").status_code == 404


def test_ループバック以外からは拒否する(remote_client):
    assert remote_client.get("/card/status").status_code == 403
    assert remote_client.post("/card/session").status_code == 403


def test_設定でループバック制限を外せる(remote_client, monkeypatch):
    monkeypatch.setenv("CARD_BIND_LOOPBACK_ONLY", "false")
    settings.reload()
    assert remote_client.get("/card/status").status_code == 200


# ── セッション ────────────────────────────────────────────────────────────────

def test_セッションを開始して破棄できる(client):
    sid = start(client)
    assert session_mod.store.count() == 1
    r = client.delete(f"/card/session/{sid}")
    assert r.status_code == 200 and r.json()["dropped"] is True
    assert session_mod.store.count() == 0


def test_同時に持てるセッション数に上限がある(client, monkeypatch):
    monkeypatch.setenv("CARD_SESSION__MAX_SESSIONS", "2")
    settings.reload()
    for _ in range(5):
        start(client)
    assert session_mod.store.count() <= 2


def test_不正なセッションIDは拒否する(client):
    assert client.delete("/card/session/short").status_code == 400
    assert client.delete("/card/session/" + "x" * 200).status_code == 400
    assert client.get("/card/session/" + "a" * 20 + "/result").status_code == 404


# ── 検出フレーム ──────────────────────────────────────────────────────────────

def test_フレームを送ると案内と枠が返る(client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")
    body = jpeg(bgr, 640)

    r = client.post(f"/card/frame?session_id={sid}", content=body,
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["session_id"] == sid
    assert payload["message"]
    assert payload["quad"] and len(payload["quad"]) == 4
    for x, y in payload["quad"]:
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0     # 比率で返る
    assert payload["metrics"]["area"] > 0


def test_静止したフレームが続くと自動撮影が立つ(client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")
    body = jpeg(bgr, 640)
    need = int(settings.get("quality.stable_frames"))

    fired = False
    for _ in range(need + 4):
        payload = client.post(f"/card/frame?session_id={sid}", content=body,
                              headers={"Content-Type": "image/jpeg"}).json()
        if payload["should_capture"]:
            fired = True
            assert payload["state"] == "capturing"
            break
    assert fired, "静止し続けても自動撮影にならなかった"


def test_名刺が無いフレームでは撮影しない(client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("empty_desk")
    body = jpeg(bgr, 640)
    for _ in range(10):
        payload = client.post(f"/card/frame?session_id={sid}", content=body,
                              headers={"Content-Type": "image/jpeg"}).json()
        assert payload["should_capture"] is False
        assert payload["quad"] is None


def test_存在しないセッションのフレームは拒否する(client, scene):
    bgr, _truth, _spec = scene("landscape_ja")
    r = client.post("/card/frame?session_id=" + "a" * 24, content=jpeg(bgr, 640),
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 404


def test_大きすぎる本文は拒否する(client, monkeypatch):
    monkeypatch.setenv("CARD_SESSION__MAX_FRAME_BYTES", "1000")
    settings.reload()
    sid = start(client)
    r = client.post(f"/card/frame?session_id={sid}", content=b"x" * 5000,
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 413


def test_対応しない形式は拒否する(client):
    sid = start(client)
    r = client.post(f"/card/frame?session_id={sid}", content=b"hello",
                    headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_画像として読めない本文は拒否する(client):
    sid = start(client)
    r = client.post(f"/card/frame?session_id={sid}", content=b"not an image",
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 400


def test_空の本文は拒否する(client):
    sid = start(client)
    r = client.post(f"/card/frame?session_id={sid}", content=b"",
                    headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 400


# ── 撮影・確定 ────────────────────────────────────────────────────────────────

@pytest.mark.ocr
def test_撮影から確定までの一連の流れ(ocr_engine, client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")

    r = client.post(f"/card/capture?session_id={sid}",
                    content=jpeg(bgr, 1280, 92), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200
    result = r.json()
    assert set(result["fields"]) == set(FIELD_NAMES)
    assert result["fields"]["company_name"]["value"] == "株式会社サンプル商会"
    assert result["card_image"].startswith("data:image/jpeg;base64,")
    assert result["lines"]
    assert result["timings_ms"]["total"] > 0

    # 撮り直しに備えて結果は取り直せる
    again = client.get(f"/card/session/{sid}/result")
    assert again.status_code == 200
    assert again.json()["fields"] == result["fields"]

    # 利用者が氏名を直して確定
    r = client.post(f"/card/session/{sid}/confirm",
                    json={"values": {"person_name": "山田 太郎", "company_name": "株式会社サンプル商会"}})
    assert r.status_code == 200
    confirmed = r.json()
    assert confirmed["person_name"] == "山田 太郎"
    assert confirmed["confirmed_by_user"] is True
    assert confirmed["captured_at"].endswith("Z")
    assert 0.0 <= confirmed["ocr_confidence"] <= 1.0
    # 修正した項目と OCR のままの項目を区別して返す
    assert "person_name" in confirmed["edited_fields"]
    assert "company_name" not in confirmed["edited_fields"]
    # §11 のデータ形式どおり、全項目が入っている
    for name in FIELD_NAMES:
        assert name in confirmed

    # 確定でセッション（＝画像と抽出結果）が消えている
    assert client.get(f"/card/session/{sid}/result").status_code == 404
    assert session_mod.store.count() == 0


def test_撮影していないのに確定はできない(client):
    sid = start(client)
    r = client.post(f"/card/session/{sid}/confirm", json={"values": {}})
    assert r.status_code == 409


@pytest.mark.ocr
def test_知らない項目名は拒否する(ocr_engine, client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")
    client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280, 92),
                headers={"Content-Type": "image/jpeg"})
    r = client.post(f"/card/session/{sid}/confirm", json={"values": {"password": "x"}})
    assert r.status_code == 400


def test_名刺が写っていない画像でも落ちない(client, scene):
    """撮影ボタンを押したときに何も写っていなかった場合。"""
    sid = start(client)
    bgr, _truth, _spec = scene("empty_desk")
    r = client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280, 92),
                    headers={"Content-Type": "image/jpeg"})
    # OCR が無い環境では 503、ある環境では 200（項目は空）
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        fields = r.json()["fields"]
        assert not fields["email"]["value"]
        assert not fields["phone"]["value"]


def test_期限切れセッションは掃除される(client, monkeypatch):
    sid = start(client)
    monkeypatch.setenv("CARD_SESSION__TTL_SEC", "0")
    settings.reload()
    assert session_mod.store.purge() >= 1
    assert client.get(f"/card/session/{sid}/result").status_code == 404
