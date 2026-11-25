"""管理画面「受付ログ」の一覧(期間・条件で絞った1ページぶん)と CSV 出力。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.database import AsyncSessionLocal
from app.models.reception import ReceptionLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth import create_access_token


def _utc(*args) -> datetime:
    return datetime(*args)  # naive-UTC(DB の書き方)


async def _add(tenant_id: str, at: datetime, *, visitor="来客 花子", company="テスト株式会社",
               method="form", state="completed") -> str:
    async with AsyncSessionLocal() as db:
        log = ReceptionLog(
            id=str(uuid.uuid4()), tenant_id=tenant_id, visitor_name=visitor, company=company,
            method=method, state=state, created_at=at,
        )
        db.add(log)
        await db.commit()
        return log.id


@pytest.fixture
async def admin_headers(tenant):
    async with AsyncSessionLocal() as db:
        u = User(id=str(uuid.uuid4()), tenant_id=tenant.id, email="admin-page@example.test",
                 hashed_password="x", role="admin", name="管理者")
        db.add(u)
        await db.commit()
    return {"Authorization": f"Bearer {create_access_token(tenant.id, u.id, 'admin')}"}


async def test_30日より前も期間で取れる_境目はUTCの時刻で比べる(client, tenant, admin_headers):
    old = await _add(tenant.id, _utc(2026, 8, 1, 3, 0))          # 約4か月前
    # 日本時間 2026-11-01 08:30 = UTC 10-31 23:30。日付(UTC)で比べると前日に落ちる受付。
    early = await _add(tenant.id, _utc(2026, 10, 31, 23, 30))
    await _add(tenant.id, _utc(2026, 10, 31, 14, 59))             # JST 10-31 23:59 = 範囲外

    # 日本時間 11/1 0:00 = UTC 10/31 15:00 以降、11/2 0:00 未満
    r = await client.get("/api/reception/page", headers=admin_headers, params={
        "since": "2026-10-31T15:00:00Z", "until": "2026-11-01T15:00:00Z",
    })
    assert r.status_code == 200
    body = r.json()
    assert [i["id"] for i in body["items"]] == [early]
    assert body["total"] == 1
    assert body["all_total"] == 3

    r = await client.get("/api/reception/page", headers=admin_headers, params={"until": "2026-09-01T00:00:00Z"})
    assert [i["id"] for i in r.json()["items"]] == [old]


async def test_ページ送りと件数(client, tenant, admin_headers):
    base = _utc(2026, 11, 1, 0, 0)
    ids = [await _add(tenant.id, base + timedelta(minutes=i)) for i in range(25)]
    r = await client.get("/api/reception/page", headers=admin_headers, params={"offset": 20, "limit": 10})
    body = r.json()
    assert body["total"] == 25
    # 新しい順。21番目〜25番目 = 古いほうの5件
    assert [i["id"] for i in body["items"]] == list(reversed(ids[:5]))


async def test_検索_経路_状態で絞る_記号はそのままの文字として探す(client, tenant, admin_headers):
    at = _utc(2026, 11, 1, 1, 0)
    hit = await _add(tenant.id, at, visitor="Yamada Taro", company="100%商事", method="qr", state="received")
    await _add(tenant.id, at, visitor="山田 花子", company="1000商事", method="qr", state="received")
    await _add(tenant.id, at, visitor="yamada", company="x", method="form", state="received")

    r = await client.get("/api/reception/page", headers=admin_headers, params={"q": "100%"})
    assert [i["id"] for i in r.json()["items"]] == [hit]  # % がワイルドカードにならない

    r = await client.get("/api/reception/page", headers=admin_headers,
                         params={"q": "YAMADA", "method": "qr", "state": "received"})
    assert [i["id"] for i in r.json()["items"]] == [hit]  # 大文字小文字を区別しない


async def test_対応待ちと今日の未対応は期間に関係なく数える(client, tenant, admin_headers):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await _add(tenant.id, now - timedelta(days=40), state="received")   # 古い未対応(待ちに数える)
    await _add(tenant.id, now - timedelta(minutes=20), state="received")
    await _add(tenant.id, now - timedelta(minutes=2), state="received")  # 15分未満
    await _add(tenant.id, now - timedelta(minutes=30), state="completed")
    today_since = (now - timedelta(hours=1)).isoformat() + "Z"
    r = await client.get("/api/reception/page", headers=admin_headers, params={
        "since": (now - timedelta(minutes=5)).isoformat() + "Z", "today_since": today_since,
    })
    body = r.json()
    assert body["total"] == 1
    assert body["waiting_count"] == 2
    assert body["unread_today"] == 2


async def test_他のテナントの受付は出ない_1件取得も(client, tenant, admin_headers):
    async with AsyncSessionLocal() as db:
        other = Tenant(id=str(uuid.uuid4()), slug="other-page", name="他社")
        db.add(other)
        await db.commit()
    mine = await _add(tenant.id, _utc(2026, 11, 1))
    theirs = await _add(other.id, _utc(2026, 11, 1))

    r = await client.get("/api/reception/page", headers=admin_headers)
    assert [i["id"] for i in r.json()["items"]] == [mine]
    assert r.json()["all_total"] == 1

    assert (await client.get(f"/api/reception/{mine}", headers=admin_headers)).status_code == 200
    assert (await client.get(f"/api/reception/{theirs}", headers=admin_headers)).status_code == 404
    # 固定パスの GET を 1件取得が飲み込まない
    assert (await client.get("/api/reception/daily-stats", headers=admin_headers)).status_code == 200


async def test_CSVは画面と同じ条件で出す(client, tenant, admin_headers):
    await _add(tenant.id, _utc(2026, 8, 1), visitor="古い 来客")
    await _add(tenant.id, _utc(2026, 11, 1), visitor="新しい 来客", state="received")
    await _add(tenant.id, _utc(2026, 11, 1), visitor="新しい 完了")

    r = await client.get("/api/reception/export.csv", headers=admin_headers, params={
        "since": "2026-10-31T15:00:00Z", "state": "received",
    })
    assert r.status_code == 200
    text = r.text
    assert "新しい 来客" in text
    assert "古い 来客" not in text and "新しい 完了" not in text

    r = await client.get("/api/reception/export.csv", headers=admin_headers)  # 条件なし=全件(従来どおり)
    assert all(n in r.text for n in ("古い 来客", "新しい 来客", "新しい 完了"))


async def test_CSVの日時は日本時間_一覧の時刻はZ付き(client, tenant, admin_headers):
    await _add(tenant.id, _utc(2026, 10, 31, 23, 30), visitor="朝の 来客")  # JST 11/1 08:30
    r = await client.get("/api/reception/export.csv", headers=admin_headers)
    assert "2026-11-01 08:30:00" in r.text

    r = await client.get("/api/reception/page", headers=admin_headers)
    assert r.json()["items"][0]["created_at"] == "2026-10-31T23:30:00Z"
