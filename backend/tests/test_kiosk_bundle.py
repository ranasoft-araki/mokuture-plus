"""OTA の配信一覧(GET /kiosk/bundle/manifest)。

Render ではデプロイしたコミットに固定して GitHub から取り寄せ、そのコミットの名前
(短縮 SHA・日時・件名)を端末に名乗る。端末のデバイスチェック画面はこれを
「配信中」の版として表示する。GitHub へは出さず、モックで確かめる。
"""
from __future__ import annotations

import types

import httpx
import pytest

from app.api import kiosk

SHA = "585655b" + "1" * 33
KIOSK_COMMIT = {
    "sha": "a1da2fe" + "2" * 33,
    "commit": {"message": "声の操作: 直す\n\n本文", "committer": {"date": "2026-10-01T12:14:00Z"}},
}


def _older(sha: str, date: str) -> dict:
    return {"sha": sha * 40, "commit": {"message": "前の更新", "committer": {"date": date}}}


# GitHub API の並び(新しい順)。先頭が配信中の版(日本時間 10/1 21:14)。
KIOSK_COMMITS = [
    KIOSK_COMMIT,
    _older("b", "2026-10-01T01:00:00Z"),   # 日本時間 10/1 10:00
    _older("c", "2026-09-30T16:30:00Z"),   # 日本時間 10/1 01:30(UTC では前日だが日本時間で数える)
    _older("d", "2026-09-30T14:00:00Z"),   # 日本時間 9/30 23:00 → 数えない
]


@pytest.fixture
def github(monkeypatch, tmp_path):
    """kiosk_agent の無い Render のイメージで、GitHub の raw / API をモックする。"""
    state = {"raw": [], "api": [], "api_status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "api.github.com":
            state["api"].append(url)
            if state["api_status"] != 200:
                return httpx.Response(state["api_status"], json={"message": "rate limited"})
            return httpx.Response(200, json=KIOSK_COMMITS)
        state["raw"].append(url)
        return httpx.Response(200, content=b"file:" + request.url.path.encode())

    real_client = httpx.AsyncClient
    fake = types.SimpleNamespace(
        AsyncClient=lambda *a, **k: real_client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(kiosk, "httpx", fake)
    monkeypatch.setattr(kiosk, "_KIOSK_AGENT_DIR", tmp_path / "no-kiosk-agent")
    monkeypatch.setattr(kiosk, "_bundle_bytes_cache", {})
    monkeypatch.setattr(kiosk, "_bundle_source_cache", None)
    monkeypatch.setattr(kiosk, "_bundle_source_tried_at", None)
    return state


def _pin(monkeypatch, ref: str, pinned: bool):
    monkeypatch.setattr(kiosk, "_BUNDLE_REF", ref)
    monkeypatch.setattr(kiosk, "_BUNDLE_PINNED", pinned)
    monkeypatch.setattr(
        kiosk, "_BUNDLE_GITHUB_RAW",
        f"https://raw.githubusercontent.com/ranasoft-araki/mokuture-plus/{ref}/kiosk_agent",
    )


async def test_コミットに固定した配信はその名前を名乗り取り寄せは一度だけ(client, kiosk_headers, github, monkeypatch):
    _pin(monkeypatch, SHA, True)
    r1 = await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)
    assert r1.status_code == 200
    m = r1.json()
    assert len(m["files"]) == len(kiosk.BUNDLE_FILES)
    assert all(f"/{SHA}/kiosk_agent/" in u for u in github["raw"])
    assert m["source"] == {"commit": KIOSK_COMMIT["sha"], "date": "2026-10-01T12:14:00Z",
                           "subject": "声の操作: 直す", "label": "261001-003"}
    # kiosk_agent に触れた最後のコミットを、デプロイしたコミットから辿って引く
    assert "path=kiosk_agent" in github["api"][0] and f"sha={SHA}" in github["api"][0]

    raw_count = len(github["raw"])
    r2 = await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)
    assert r2.json() == m
    assert len(github["raw"]) == raw_count  # 中身は変わらないので取り寄せ直さない
    assert len(github["api"]) == 1


async def test_master追従のときは名前を付けない(client, kiosk_headers, github, monkeypatch):
    _pin(monkeypatch, "master", False)
    m = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m["files"]
    assert m["source"] is None
    assert github["api"] == []


async def test_コミット名を引けないときはデプロイのSHAだけ名乗りあとで引き直す(client, kiosk_headers, github, monkeypatch):
    _pin(monkeypatch, SHA, True)
    github["api_status"] = 403
    m = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m["source"] == {"commit": SHA, "date": None, "subject": None}

    await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)
    assert len(github["api"]) == 1  # すぐには叩き直さない(回数制限)

    github["api_status"] = 200
    monkeypatch.setattr(kiosk, "_bundle_source_tried_at", kiosk._bundle_source_tried_at - kiosk._BUNDLE_SOURCE_RETRY_SEC)
    m = (await client.get("/api/kiosk/bundle/manifest", headers=kiosk_headers)).json()
    assert m["source"]["subject"] == "声の操作: 直す"
    assert m["source"]["label"] == "261001-003"


def test_版番号は日本時間の日付とその日の何番目か():
    assert kiosk._bundle_label(KIOSK_COMMITS) == "261001-003"
    assert kiosk._bundle_label(KIOSK_COMMITS[1:]) == "261001-002"  # 1つ前の版の番号は変わらない
    assert kiosk._bundle_label(KIOSK_COMMITS[3:]) == "260930-001"
