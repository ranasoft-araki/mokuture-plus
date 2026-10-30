"""受付応答は同時操作でも先着1件だけを確定する。"""

import asyncio

from app.api.reception import _apply_decision
from app.database import AsyncSessionLocal
from conftest import add_reception  # type: ignore[import-not-found]


async def test_kioskの時間切れAPIが電話案内を確定する(client, kiosk_headers):
    created = await client.post(
        "/api/kiosk/reception",
        headers=kiosk_headers,
        json={"visitor_name": "来客", "staff": "田中太郎", "method": "form"},
    )
    assert created.status_code == 201
    log_id = created.json()["id"]

    expired = await client.post(
        f"/api/kiosk/reception/{log_id}/timeout",
        headers=kiosk_headers,
        json={},
    )
    assert expired.status_code == 200
    assert expired.json()["state"] == "phone"
    assert expired.json()["timeout_applied"] is True
    assert expired.json()["decision_expired"] is True

    repeated = await client.post(
        f"/api/kiosk/reception/{log_id}/timeout",
        headers=kiosk_headers,
        json={},
    )
    assert repeated.status_code == 200
    assert repeated.json()["timeout_applied"] is False


async def test_同時応答は一人だけが確定する(tenant):
    log = await add_reception(tenant.id, "田中太郎")
    ready = asyncio.Event()
    loaded = 0
    lock = asyncio.Lock()

    async def decide(decision: str, name: str):
        nonlocal loaded
        async with AsyncSessionLocal() as db:
            row = await db.get(type(log), log.id)
            async with lock:
                loaded += 1
                if loaded == 2:
                    ready.set()
            await ready.wait()
            return await _apply_decision(db, row, decision, actor_name=name)

    first, second = await asyncio.gather(
        decide("accept", "担当者A"),
        decide("phone", "担当者B"),
    )

    assert sum(result.applied for result in (first, second)) == 1
    winner = first if first.applied else second
    loser = second if first.applied else first
    assert loser.state == winner.state
    assert loser.decided_by_name == winner.decided_by_name

    async with AsyncSessionLocal() as db:
        saved = await db.get(type(log), log.id)
        assert saved.state == winner.state
        assert saved.decided_by_name == winner.decided_by_name


async def test_電話案内の時間切れ後は担当者の応答で更新されない(tenant):
    log = await add_reception(tenant.id, "田中太郎")
    async with AsyncSessionLocal() as db:
        row = await db.get(type(log), log.id)
        timeout = await _apply_decision(
            db, row, "phone", actor_name="システム", via="kiosk_timeout",
        )
        assert timeout.applied is True
        assert timeout.decision_expired is True

    async with AsyncSessionLocal() as db:
        row = await db.get(type(log), log.id)
        late = await _apply_decision(db, row, "accept", actor_name="田中太郎")
        assert late.applied is False
        assert late.state == "phone"
        assert late.decision_expired is True

        saved = await db.get(type(log), log.id)
        assert saved.state == "phone"
        assert saved.decided_via == "kiosk_timeout"
