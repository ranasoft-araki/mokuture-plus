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


def test_応答に四隅の由来が入る(client, scene):
    """画面のデバッグ表示(?carddebug=1)が「縁で取れたのか文字で取れたのか」を出す。

    読み取れないときに直すべき場所（縁が出ていない / 文字も拾えていない）を
    利用者ではなく調整する側が切り分けられるようにするための値。
    """
    sid = start(client)

    bgr, _truth, _spec = scene("landscape_ja")
    payload = client.post(f"/card/frame?session_id={sid}",
                          content=jpeg(bgr, 640),
                          headers={"Content-Type": "image/jpeg"}).json()
    assert payload["source"] == "edge"

    bgr, _truth, _spec = scene("no_edges")           # 縁が出ず文字から決まる場面
    payload = client.post(f"/card/frame?session_id={sid}",
                          content=jpeg(bgr, 640),
                          headers={"Content-Type": "image/jpeg"}).json()
    assert payload["source"] == "text"
    assert payload["metrics"]["text_height"] > 0     # 大きさの判定に使う字の高さ

    bgr, _truth, _spec = scene("empty_desk")         # 名刺が無い
    payload = client.post(f"/card/frame?session_id={sid}",
                          content=jpeg(bgr, 640),
                          headers={"Content-Type": "image/jpeg"}).json()
    assert payload["source"] is None


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


# ── 自動撮影と撮り直し ────────────────────────────────────────────────────────
# 「名刺を認識したら自動で読み取りに入り、実際に項目が取れたときだけ確認画面へ進む」
# という流れの検証。取れなかった場合は黙って撮り直すので、利用者は空っぽの確認画面を
# 見ない。

@pytest.mark.ocr
def test_項目が取れたら確認画面へ進む(ocr_engine, client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")
    r = client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280, 92),
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["accepted"] is True
    assert r["proceed"] is True
    assert r["accept_reason"] == "ok"
    assert r["attempt"] == 1


@pytest.mark.ocr
def test_何も読めなければ確認画面へ進まない(ocr_engine, client, scene):
    """撮影はできたが項目が取れなかったケース。画面側はこれを見て撮り直す。"""
    sid = start(client)
    bgr, _truth, _spec = scene("empty_desk")
    r = client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280, 92),
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["accepted"] is False
    assert r["proceed"] is False
    assert r["accept_reason"] != "ok"
    assert r["retry_cooldown_sec"] > 0


@pytest.mark.ocr
def test_読み取れなかった直後も自動撮影を続けられる(ocr_engine, client, scene):
    """撮り直しができるよう、失敗時は自動撮影の抑止をかけない。"""
    sid = start(client)
    blank, _t, _s = scene("empty_desk")
    r = client.post(f"/card/capture?session_id={sid}", content=jpeg(blank, 1280, 92),
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["proceed"] is False

    card, _t2, _s2 = scene("landscape_ja")
    body = jpeg(card, 640)
    need = int(settings.get("quality.stable_frames"))
    fired = False
    for _ in range(need + 6):
        payload = client.post(f"/card/frame?session_id={sid}", content=body,
                              headers={"Content-Type": "image/jpeg"}).json()
        if payload["should_capture"]:
            fired = True
            break
    assert fired, "読み取り失敗後に自動撮影が再開しなかった"


@pytest.mark.ocr
def test_確認画面へ進んだら自動撮影は止まる(ocr_engine, client, scene):
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")
    r = client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280, 92),
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["proceed"] is True

    body = jpeg(bgr, 640)
    for _ in range(int(settings.get("quality.stable_frames")) + 6):
        payload = client.post(f"/card/frame?session_id={sid}", content=body,
                              headers={"Content-Type": "image/jpeg"}).json()
        assert payload["should_capture"] is False


@pytest.mark.ocr
def test_手動撮影は内容に関わらず確認画面へ進む(ocr_engine, client, scene):
    """「撮影する」は利用者の明示的な操作。読めなくても画面を出して手入力させる。"""
    sid = start(client)
    bgr, _truth, _spec = scene("empty_desk")
    r = client.post(f"/card/capture?session_id={sid}&force=1", content=jpeg(bgr, 1280, 92),
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["accepted"] is False
    assert r["proceed"] is True


@pytest.mark.ocr
def test_撮り直しの上限に達したら取れた分で進む(ocr_engine, client, scene, monkeypatch):
    """読めた行はあるが受理できない撮影は、上限まで数えてから手入力へ逃がす。"""
    monkeypatch.setenv("CARD_ACCEPT__MAX_ATTEMPTS", "2")
    monkeypatch.setenv("CARD_ACCEPT__MIN_CONFIDENCE", "0.99")  # 受理されない状況を作る
    settings.reload()
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")                # 文字は読める名刺
    body = jpeg(bgr, 1280, 92)

    first = client.post(f"/card/capture?session_id={sid}", content=body,
                        headers={"Content-Type": "image/jpeg"}).json()
    assert first["proceed"] is False and first["attempt"] == 1

    second = client.post(f"/card/capture?session_id={sid}", content=body,
                         headers={"Content-Type": "image/jpeg"}).json()
    assert second["accepted"] is False
    assert second["proceed"] is True          # 上限に達したので手入力できるよう進む
    assert second["attempt"] == 2


@pytest.mark.ocr
def test_何も読めない撮影は撮り直しの回数に数えない(ocr_engine, client, scene, monkeypatch):
    """名刺を出す前でも、背景の文字で自動撮影が走ることがある。

    それを撮り直しの回数に数えると、本命の 1 枚が来る前に上限へ達し、何も
    読めていない確認画面が出てしまう。ただし数えないだけだと「どうしても
    読めない名刺」で出口が無くなるので、上限の 2 倍で同じように逃がす。
    """
    monkeypatch.setenv("CARD_ACCEPT__MAX_ATTEMPTS", "2")
    settings.reload()
    sid = start(client)
    bgr, _truth, _spec = scene("empty_desk")                  # 1 行も読めない絵
    body = jpeg(bgr, 1280, 92)

    for _ in range(3):
        r = client.post(f"/card/capture?session_id={sid}", content=body,
                        headers={"Content-Type": "image/jpeg"}).json()
        assert r["attempt"] == 0 and r["proceed"] is False

    r = client.post(f"/card/capture?session_id={sid}", content=body,
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["proceed"] is True               # 2 倍に達したので手入力へ逃がす


@pytest.mark.ocr
def test_受理条件は設定で変えられる(ocr_engine, client, scene, monkeypatch):
    """会社名だけでも進めたい現場向けに、要求する項目を緩められること。"""
    monkeypatch.setenv("CARD_ACCEPT__REQUIRE_ANY", "email")
    monkeypatch.setenv("CARD_ACCEPT__MIN_FIELDS", "1")
    settings.reload()
    sid = start(client)
    bgr, _truth, _spec = scene("landscape_ja")
    r = client.post(f"/card/capture?session_id={sid}", content=jpeg(bgr, 1280, 92),
                    headers={"Content-Type": "image/jpeg"}).json()
    assert r["accepted"] is True


# ── 撮影画像のピント判定 ──────────────────────────────────────────────────────
# 検出用フレームで合焦と判定しても、ブラウザが実際に撮るのは別の瞬間の別フレーム。
# ボケた撮影に OCR（1 枚 4.5〜5.8 秒）を使う前に弾いて撮り直させる。

def test_ボケた撮影はOCRへ進まず撮り直しになる(client, scene, monkeypatch):
    import cv2
    bgr, _truth, _spec = scene("landscape_ja")
    sid = client.post("/card/session").json()["session_id"]

    blurred = cv2.GaussianBlur(bgr, (31, 31), 0)
    body = cv2.imencode(".jpg", blurred, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    r = client.post(f"/card/capture?session_id={sid}",
                    content=body, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["proceed"] is False
    assert payload["accept_reason"] == "blurry capture"
    # OCR を通していないので項目は返らない
    assert "fields" not in payload


def test_手動撮影はボケていても読む(client, scene):
    import cv2
    bgr, _truth, _spec = scene("landscape_ja")
    sid = client.post("/card/session").json()["session_id"]

    blurred = cv2.GaussianBlur(bgr, (31, 31), 0)
    body = cv2.imencode(".jpg", blurred, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
    r = client.post(f"/card/capture?session_id={sid}&force=1",
                    content=body, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200
    # 利用者が自分で押した撮影は内容に関わらず進む（手入力できるようにするため）
    assert r.json()["proceed"] is True
