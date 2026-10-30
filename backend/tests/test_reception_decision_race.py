"""受付応答は同時操作でも先着1件だけを確定する。"""

import asyncio

from app.api.reception import _apply_decision
from app.database import AsyncSessionLocal
from conftest import add_reception  # type: ignore[import-not-found]


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
