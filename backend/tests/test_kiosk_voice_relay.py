"""キオスクからの音声認識中継。

**鍵を端末に置かないための口。** 発売済みの端末すべてに APPKEY を配って回るのは
現実的でないので、キオスクはここへ音声を送り、サーバが AmiVoice を呼ぶ。

ここで押さえるのは 3 つ:
  - サーバに鍵があり、**かつ**テナントが許可しているときだけ中継する
  - どちらか欠けたら 503（端末はローカル認識だけで従来どおり動く）
  - 承認されていない端末からは呼べない
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.device import Device
from app.models.tenant import Tenant
from app.services import speech as speech_service

WAV = b"RIFF" + b"\x00" * 40 + b"\x01\x02" * 800


@pytest.fixture
def cloud_key(monkeypatch):
    monkeypatch.setattr(settings, "amivoice_appkey", "test-key")
    return "test-key"


async def allow_tenant(tenant_id: str, allowed: bool = True) -> None:
    async with AsyncSessionLocal() as db:
        t = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        t.voice_cloud_enabled = allowed
        await db.commit()


async def set_device_status(device_id: str, status: str) -> None:
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(Device).where(Device.id == device_id))).scalar_one()
        d.status = status
        await db.commit()


def post(client, headers, words: str = ""):
    return client.post("/api/kiosk/voice/transcribe", headers=headers,
                       files={"audio": ("a.wav", WAV, "audio/wav")},
                       data={"words": words})


async def test_鍵が無ければ中継しない(client, kiosk_headers, tenant):
    """サーバに鍵を入れるまでは、テナントが許可していても外へ出さない。"""
    await allow_tenant(tenant.id)
    r = await post(client, kiosk_headers)
    assert r.status_code == 503


async def test_テナントが許可していなければ中継しない(client, kiosk_headers, cloud_key):
    """鍵があるだけでは有効にならない。来訪者の音声を外へ出すかはテナントの判断。"""
    r = await post(client, kiosk_headers)
    assert r.status_code == 503


async def test_両方そろえば文字起こしを返す(client, kiosk_headers, tenant, cloud_key, monkeypatch):
    sent = {}

    async def fake_transcribe(wav: bytes, words: list[str]):
        sent["wav"] = wav
        sent["words"] = words
        return "磯野木工所の荒木と申します", 900

    monkeypatch.setattr(speech_service, "transcribe", fake_transcribe)
    await allow_tenant(tenant.id)

    r = await post(client, kiosk_headers, words="服部健一 はっとりけんいち")
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "磯野木工所の荒木と申します"
    assert body["engine"] == "amivoice"
    assert sent["wav"] == WAV
    assert sent["words"] == ["服部健一 はっとりけんいち"]


async def test_承認待ちの端末は呼べない(client, kiosk_headers, tenant, device, cloud_key):
    await allow_tenant(tenant.id)
    await set_device_status(device.id, "pending")
    r = await post(client, kiosk_headers)
    assert r.status_code == 403


async def test_トークンが無ければ呼べない(client, tenant, cloud_key):
    await allow_tenant(tenant.id)
    r = await post(client, {"X-Kiosk-Token": "nope"})
    assert r.status_code == 401


async def test_大きすぎる音声は受け取らない(client, kiosk_headers, tenant, cloud_key, monkeypatch):
    """取り違え・悪用の防止。受付の一文は最長でも15秒。"""
    monkeypatch.setattr(settings, "voice_max_audio_bytes", 100)
    await allow_tenant(tenant.id)
    r = await post(client, kiosk_headers)
    assert r.status_code == 413


async def test_認識に失敗しても502で返す(client, kiosk_headers, tenant, cloud_key, monkeypatch):
    """端末はローカルの結果へ落ちるだけ。受付は止まらない。"""
    async def boom(wav, words):
        raise speech_service.SpeechFailed("ConnectError")

    monkeypatch.setattr(speech_service, "transcribe", boom)
    await allow_tenant(tenant.id)
    r = await post(client, kiosk_headers)
    assert r.status_code == 502


def test_読みの無い語は渡さない():
    """読みの推測は禁止(VOICE_INPUT.md 2-4)。"""
    assert speech_service.profile_words(["服部健一 はっとりけんいち", "田中一郎", ""]) == \
        "服部健一 はっとりけんいち"


async def test_運営が切り替えられる(client, operator_headers, tenant, cloud_key):
    """テナント管理者ではなく運営が開ける。音声の行き先が変わる設定のため。"""
    r = await client.patch(f"/api/operator/tenants/{tenant.id}/voice-cloud",
                           headers=operator_headers, json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["voice_cloud_enabled"] is True
    assert r.json()["server_key_configured"] is True

    r = await client.patch(f"/api/operator/tenants/{tenant.id}/voice-cloud",
                           headers=operator_headers, json={"enabled": False})
    assert r.json()["voice_cloud_enabled"] is False
