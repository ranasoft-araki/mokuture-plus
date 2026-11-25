"""Microsoft Teams 通知と、ログイン無しで返事できるリンク（メール・Teams 用）。

- 返事用の画面が読む `POST /reception/decision/lookup` は**何も書き換えない**
  （メールや Teams のセキュリティ機能がリンクを勝手に開いても返事にならないように）。
- Teams の URL は Webhook と同じく秘密。設定の取得・担当者ごとの一覧に URL を出さない。
- 来訪者の入力は Teams のマークダウンとして無害化してからカードに入れる。
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.middleware.tenant import get_current_user
from app.models.notification import NotificationSetting
from app.models.reception import ReceptionLog
from app.services import reception_notify, teams
from app.services.auth import create_decision_token, create_slack_state_token
from app.services.crypto import decrypt_dict
from conftest import add_reception, add_route, set_notification_setting, set_staff_list  # type: ignore[import-not-found]

WORKFLOW_URL = "https://prod-00.japaneast.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=SECRET"
WORKFLOW_URL_2 = "https://default0123.ab.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/xyz/triggers/manual/paths/invoke?sig=SECRET2"


@pytest.fixture
def settings_client(admin):
    from app.api.notifications import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
        yield c


@pytest.fixture
def posted(monkeypatch):
    """teams.post を差し替え、送られた (url, payload) を記録する（外へは送らない）。"""
    sent: list[tuple[str, dict]] = []

    async def fake_post(url: str, payload: dict) -> bool:
        sent.append((url, payload))
        return True

    monkeypatch.setattr(teams, "post", fake_post)
    return sent


async def _reload(log_id: str) -> ReceptionLog:
    async with AsyncSessionLocal() as db:
        return await db.get(ReceptionLog, log_id)


def _fragment(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).fragment).items()}


# ── 返事用の画面の API ─────────────────────────────────────────────────────────

async def test_lookupは読むだけで受付を変えない(client, tenant):
    log = await add_reception(tenant.id, "山田")
    token = create_decision_token(log.id, tenant.id)

    r = await client.post("/api/reception/decision/lookup", json={"token": token})

    assert r.status_code == 200
    body = r.json()
    assert body["visitor_name"] == log.visitor_name
    assert body["tenant_slug"] == tenant.slug
    assert body["decided"] is False
    assert [a["action"] for a in body["actions"]] == ["accept", "phone", "decline"]
    after = await _reload(log.id)
    assert after.state == "received"
    assert after.decided_at is None


async def test_lookupは返事用以外のトークンを断る(client, tenant):
    log = await add_reception(tenant.id, "山田")
    r1 = await client.post("/api/reception/decision/lookup", json={"token": create_slack_state_token(tenant.id)})
    r2 = await client.post("/api/reception/decision/lookup", json={"token": "garbage"})
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert (await _reload(log.id)).state == "received"


async def test_lookupは別テナントの受付を見せない(client, tenant):
    log = await add_reception(tenant.id, "山田")
    token = create_decision_token(log.id, "another-tenant")
    r = await client.post("/api/reception/decision/lookup", json={"token": token})
    assert r.status_code == 404


async def test_リンクからの返事は経路を記録する(client, tenant, monkeypatch):
    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(reception_notify, "fire_decision_notifications", noop)
    log = await add_reception(tenant.id, "山田")
    token = create_decision_token(log.id, tenant.id, actor_name="山田")

    r = await client.post("/api/reception/decision", json={"token": token, "decision": "accept", "via": "teams"})

    assert r.status_code == 200
    assert r.json()["decision_applied"] is True
    after = await _reload(log.id)
    assert after.state == "accepted"
    assert after.decided_via == "teams"
    assert after.decided_by_name == "山田"

    # 決まったあとに開いた画面は「すでに返事が済んでいる」を出せる
    looked = (await client.post("/api/reception/decision/lookup", json={"token": token})).json()
    assert looked["decided"] is True
    assert looked["decided_by_name"] == "山田"


async def test_知らない経路はpushとして扱う(client, tenant, monkeypatch):
    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(reception_notify, "fire_decision_notifications", noop)
    log = await add_reception(tenant.id, "山田")
    token = create_decision_token(log.id, tenant.id)
    await client.post("/api/reception/decision", json={"token": token, "decision": "phone", "via": "<script>"})
    assert (await _reload(log.id)).decided_via == "push"


# ── Teams の設定 ───────────────────────────────────────────────────────────────

async def test_旧方式のコネクタのURLは断る(settings_client):
    r = settings_client.put("/api/notifications/settings/teams",
                            json={"webhook_url": "https://example.webhook.office.com/webhookb2/abc"})
    assert r.status_code == 400
    assert "Incoming Webhook" in r.json()["detail"]


async def test_ワークフロー以外のURLは断る(settings_client):
    r = settings_client.put("/api/notifications/settings/teams", json={"webhook_url": "https://hooks.example.com/x"})
    assert r.status_code == 400
    assert "ワークフロー" in r.json()["detail"]


async def test_TeamsのURLは伏せて返す(settings_client, tenant):
    assert settings_client.put("/api/notifications/settings/teams", json={"webhook_url": WORKFLOW_URL}).status_code == 200

    res = settings_client.get("/api/notifications/settings")
    assert res.json()["teams"]["webhook_url"] == "***"
    assert "SECRET" not in res.text

    # 伏せ字のまま保存しても元の URL が残る
    settings_client.put("/api/notifications/settings/teams", json={"webhook_url": "***"})
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(NotificationSetting).where(
            NotificationSetting.tenant_id == tenant.id, NotificationSetting.type == "teams"))).scalar_one()
    assert decrypt_dict(row.config_json)["webhook_url"] == WORKFLOW_URL


async def test_healthはTeamsを含めて返す(settings_client):
    settings_client.put("/api/notifications/settings/teams", json={"webhook_url": WORKFLOW_URL})
    r = settings_client.get("/api/notifications/health")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"]["teams"] is True
    assert body["enabled"]["teams"] is True
    assert body["no_active_channel"] is False


async def test_担当者ごとのTeamsのURLは一覧に出さない(staff_client, tenant):
    await set_staff_list(tenant.id, ["山田"])
    r = staff_client.put("/api/notifications/staff-routes", json={"staff_name": "山田", "teams_webhook_url": WORKFLOW_URL})
    assert r.status_code == 200

    listing = staff_client.get("/api/notifications/staff-routes")
    assert "SECRET" not in listing.text
    route = listing.json()["routes"][0]
    assert route["teams_configured"] is True

    # 項目を省略して保存しても URL は残る（null/未指定=変更しない）
    staff_client.put("/api/notifications/staff-routes", json={"staff_name": "山田", "email": "a@example.test"})
    assert staff_client.get("/api/notifications/staff-routes").json()["routes"][0]["teams_configured"] is True

    # "" で解除
    staff_client.put("/api/notifications/staff-routes", json={"staff_name": "山田", "teams_webhook_url": ""})
    assert staff_client.get("/api/notifications/staff-routes").json()["routes"][0]["teams_configured"] is False


async def test_担当者ごとのTeamsも旧方式のURLは断る(staff_client, tenant):
    await set_staff_list(tenant.id, ["山田"])
    r = staff_client.put("/api/notifications/staff-routes",
                         json={"staff_name": "山田", "teams_webhook_url": "https://x.webhook.office.com/webhookb2/a"})
    assert r.status_code == 400


# ── 無害化とカード ─────────────────────────────────────────────────────────────

def test_来訪者の入力のマークダウンを無効にする():
    out = teams.escape_md("[押して](https://evil.example) **太字** # 見出し\n- 箇条書き")
    assert "[" not in out and "]" not in out and "(" not in out
    assert "**" not in out and "#" not in out
    assert "\n" not in out
    assert teams.escape_md("- 先頭").startswith("－")
    assert teams.escape_md("1. 一番").startswith("1．")
    assert teams.escape_md("株式会社テスト 山田") == "株式会社テスト 山田"


def test_受付カードはワークフローが受け取る形():
    payload = teams.build_reception_card(
        visitor_name="[悪](https://evil.example)", company="テスト株式会社", host_name="山田",
        department=None, purpose="打ち合わせ", when=None,
        decision_links=[("受付", "https://web.example/pilot/respond#token=t&d=accept")],
        admin_url="https://web.example/pilot/admin/reception?respond=1",
    )
    assert payload["type"] == "message"
    att = payload["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = att["content"]
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.4"
    assert card["actions"][0] == {
        "type": "Action.OpenUrl", "title": "受付",
        "url": "https://web.example/pilot/respond#token=t&d=accept", "style": "positive",
    }
    facts = next(b for b in card["body"] if b["type"] == "FactSet")["facts"]
    name = next(f for f in facts if f["title"] == "お名前")["value"]
    assert "](" not in name and "[" not in name


# ── 送信の経路 ─────────────────────────────────────────────────────────────────

async def test_受付は担当者のTeamsと共通のTeamsへ返事のリンク付きで送る(tenant, posted):
    await set_notification_setting(tenant.id, "teams", {"webhook_url": WORKFLOW_URL})
    await add_route(tenant.id, "山田", config={"teams_webhook_url": WORKFLOW_URL_2})
    log = await add_reception(tenant.id, "山田")

    async with AsyncSessionLocal() as db:
        await reception_notify.notify_reception(db, tenant.id, log)

    urls = [u for u, _ in posted]
    assert sorted(urls) == sorted([WORKFLOW_URL, WORKFLOW_URL_2])
    for url, payload in posted:
        card = payload["attachments"][0]["content"]
        titles = [a["title"] for a in card["actions"]]
        assert titles == ["受付", "電話", "お断り"]
        link = card["actions"][0]["url"]
        assert urlsplit(link).path == f"/{tenant.slug}/respond"
        frag = _fragment(link)
        assert frag["via"] == "teams" and frag["d"] == "accept" and frag["token"]
        # トークンはパスやクエリに載せない（アクセスログに残さない）
        assert "token" not in urlsplit(link).query


async def test_担当者のTeamsのトークンには担当者名が入る(tenant, posted):
    from app.services.auth import decode_token

    await add_route(tenant.id, "山田", config={"teams_webhook_url": WORKFLOW_URL_2}, include_default=False)
    log = await add_reception(tenant.id, "山田")
    async with AsyncSessionLocal() as db:
        await reception_notify.notify_reception(db, tenant.id, log)

    assert [u for u, _ in posted] == [WORKFLOW_URL_2]
    token = _fragment(posted[0][1]["attachments"][0]["content"]["actions"][0]["url"])["token"]
    assert decode_token(token)["actor_name"] == "山田"


async def test_Teamsを通知しないにすると共通のURLへは送らない(tenant, posted):
    await set_notification_setting(tenant.id, "teams", {"webhook_url": WORKFLOW_URL})
    await set_notification_setting(tenant.id, "channel_enabled_teams", {"enabled": False})
    log = await add_reception(tenant.id, "山田")
    async with AsyncSessionLocal() as db:
        await reception_notify.notify_reception(db, tenant.id, log)
    assert posted == []


async def test_返事が済んだらTeamsへ知らせる(tenant, posted):
    await set_notification_setting(tenant.id, "teams", {"webhook_url": WORKFLOW_URL})
    log = await add_reception(tenant.id, "山田", visitor="[x](https://evil.example)")
    async with AsyncSessionLocal() as db:
        row = await db.get(ReceptionLog, log.id)
        row.state = "accepted"
        row.decided_by_name = "山田"
        await db.commit()

    await reception_notify.fire_decision_notifications(tenant.id, log.id)

    assert len(posted) == 1
    text = json.dumps(posted[0][1], ensure_ascii=False)
    assert "山田さんが対応済みです" in text
    assert "](https://evil.example)" not in text


def test_メールに返事のボタンが付く(tenant):
    log = ReceptionLog(id="r1", tenant_id=tenant.id, visitor_name="来客", company=None, staff="山田", method="form")
    links = [("受付", "https://web.example/pilot/respond#token=t&via=email&d=accept")]
    _subject, text, html = reception_notify.build_reception_email("テスト", "#4a7c4e", log, "https://web.example/a", "", links)
    assert "返事をする（ログイン不要）" in text
    assert "https://web.example/pilot/respond#token=t&amp;via=email&amp;d=accept" in html
    assert "受付ログを開く（ログインが必要です）" in html


async def test_完了にした受付は返事を受け付けない扱いで見せる(client, tenant):
    log = await add_reception(tenant.id, "山田", state="completed")
    token = create_decision_token(log.id, tenant.id)
    body = (await client.post("/api/reception/decision/lookup", json={"token": token})).json()
    assert body["decided"] is True
