"""OTA の配信一覧(GET /kiosk/bundle/manifest)。

Render ではデプロイしたコミットに固定して GitHub から取り寄せ、版番号(YYMMDD-NNN)と
コミットの名前を端末に名乗る。端末のデバイスチェック画面はこれを「配信中」の版として
表示する。GitHub へは出さず、モックで確かめる。
"""
from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api import kiosk
from app.database import AsyncSessionLocal

SHA = "585655b" + "1" * 33
KIOSK_COMMIT = {
    "sha": "a1da2fe" + "2" * 33,
    "commit": {"message": "声の操作: 直す\n\n本文", "committer": {"date": "2026-10-01T12:14:00Z"}},
}


def _today_label(n: int) -> str:
    return datetime.now(kiosk._JST).strftime("%y%m%d") + f"-{n:03d}"


@pytest.fixture
def github(monkeypatch, tmp_path):
    """kiosk_agent の無い Render のイメージで、GitHub の raw / API をモックする。"""
    state = {"raw": [], "api": [], "api_status": 200, "salt": b""}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "api.github.com":
            state["api"].append(url)
            if state["api_status"] != 200:
                return httpx.Response(state["api_status"], json={"message": "rate limited"})
            return httpx.Response(200, json=[KIOSK_COMMIT])
        state["raw"].append(url)
        return httpx.Response(200, content=b"file:" + request.url.path.encode() + state["salt"])

    real_client = httpx.AsyncClient
    fake = types.SimpleNamespace(
        AsyncClient=lambda *a, **k: real_client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(kiosk, "httpx", fake)
    monkeypatch.setattr(kiosk, "_KIOSK_AGENT_DIR", tmp_path / "no-kiosk-agent")
    monkeypatch.setattr(kiosk, "_bundle_bytes_cache", {})
    monkeypatch.setattr(kiosk, "_bundle_source_cache", None)
    monkeypatch.setattr(kiosk, "_bundle_source_tried_at", None)
    monkeypatch.setattr(kiosk, "_bundle_labels", {})
    return state


def _pin(monkeypatch, ref: str, pinned: bool):
    monkeypatch.setattr(kiosk, "_BUNDLE_REF", ref)
    monkeypatch.setattr(kiosk, "_BUNDLE_PINNED", pinned)
    monkeypatch.setattr(
        kiosk, "_BUNDLE_GITHUB_RAW",
        f"https://raw.githubusercontent.com/ranasoft-araki/mokuture-plus/{ref}/kiosk_agent",
    )


async def test_コミットに固定した配信は版番号とコミット名を名乗り取り寄せは一度だけ(client, kiosk_headers, github, monkeypatch):
    _pin(monkeypatch, SHA, True)
    r1 = await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)
    assert r1.status_code == 200
    m = r1.json()
    assert len(m["files"]) == len(kiosk.BUNDLE_FILES)
    assert all(f"/{SHA}/kiosk_agent/" in u for u in github["raw"])
    assert m["source"] == {"commit": KIOSK_COMMIT["sha"], "date": "2026-10-01T12:14:00Z",
                           "subject": "声の操作: 直す", "label": _today_label(1)}
    # kiosk_agent に触れた最後のコミットを、デプロイしたコミットから辿って引く
    assert "path=kiosk_agent" in github["api"][0] and f"sha={SHA}" in github["api"][0]

    raw_count = len(github["raw"])
    r2 = await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)
    assert r2.json() == m
    assert len(github["raw"]) == raw_count  # 中身は変わらないので取り寄せ直さない
    assert len(github["api"]) == 1


async def test_GitHubのAPIが通らなくても版番号は出る(client, kiosk_headers, github, monkeypatch):
    """Render の共有 IP では未認証 API が回数制限で通らないことがある(2026-10-02 本番で発生)。"""
    _pin(monkeypatch, SHA, True)
    github["api_status"] = 403
    m = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m["source"] == {"commit": SHA, "date": None, "subject": None, "label": _today_label(1)}

    await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)
    assert len(github["api"]) == 1  # すぐには叩き直さない(回数制限)

    github["api_status"] = 200
    monkeypatch.setattr(kiosk, "_bundle_source_tried_at", kiosk._bundle_source_tried_at - kiosk._BUNDLE_SOURCE_RETRY_SEC)
    m = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m["source"]["subject"] == "声の操作: 直す"
    assert m["source"]["label"] == _today_label(1)


async def test_master追従でも中身が変わるたびに番号が進む(client, kiosk_headers, github, monkeypatch):
    _pin(monkeypatch, "master", False)
    m1 = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m1["source"] == {"commit": None, "date": None, "subject": None, "label": _today_label(1)}
    assert github["api"] == []  # コミットとは一対一にならないので名前は引かない

    github["salt"] = b"v2"
    kiosk._bundle_bytes_cache.clear()
    m2 = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m2["version"] != m1["version"]
    assert m2["source"]["label"] == _today_label(2)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


async def test_版番号は日本時間の日付とその日に配り始めた順(monkeypatch):
    monkeypatch.setattr(kiosk, "_bundle_labels", {})
    async with AsyncSessionLocal() as db:
        assert await kiosk._bundle_label(db, "aaaa", _at("2026-10-01T23:00:00")) == "261002-001"  # 日本時間 10/2 8:00
        assert await kiosk._bundle_label(db, "bbbb", _at("2026-10-02T03:00:00")) == "261002-002"
        # 前の中身に戻しても番号は前のまま
        assert await kiosk._bundle_label(db, "aaaa", _at("2026-10-02T05:00:00")) == "261002-001"
        assert await kiosk._bundle_label(db, "cccc", _at("2026-10-02T16:00:00")) == "261003-001"  # 日本時間 10/3 1:00

    # 再起動(手元の写しが空)しても DB の記録から同じ番号になる
    monkeypatch.setattr(kiosk, "_bundle_labels", {})
    async with AsyncSessionLocal() as db:
        assert await kiosk._bundle_label(db, "bbbb", _at("2026-10-05T00:00:00")) == "261002-002"
        assert await kiosk._bundle_label(db, "dddd", _at("2026-10-02T16:30:00")) == "261003-002"
