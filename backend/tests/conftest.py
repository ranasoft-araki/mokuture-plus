"""バックエンドのテスト共通設定。

**本番/開発DBには一切触らない**。`DATABASE_URL` を一時ファイルの SQLite へ上書きしてから
`app` を import する（`backend/.env` の値より環境変数が優先される）。
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import uuid

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ── app を import する前に、必ずテスト用 DB / 鍵へ差し替える ──────────────────
_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix="mokuture-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-not-used-in-production"
os.environ["ENCRYPTION_KEY"] = "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHMtMzJieXRlcy0="
os.environ["DEBUG"] = "false"

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import create_access_token  # noqa: E402


@pytest.fixture(autouse=True)
async def fresh_db():
    """テストごとにテーブルを作り直す（テスト間で行が残らないように）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def tenant() -> Tenant:
    async with AsyncSessionLocal() as db:
        t = Tenant(
            id=str(uuid.uuid4()),
            slug="pilot",
            name="実証実験テナント",
            kiosk_idle_timeout_sec=60,
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return t


@pytest.fixture
async def device(tenant: Tenant) -> Device:
    async with AsyncSessionLocal() as db:
        d = Device(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            name="受付端末1",
            token=uuid.uuid4().hex * 2,
            status="active",
        )
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d


@pytest.fixture
def kiosk_headers(device: Device) -> dict:
    return {"X-Kiosk-Token": device.token}


@pytest.fixture
async def operator_headers() -> dict:
    async with AsyncSessionLocal() as db:
        u = User(
            id=str(uuid.uuid4()),
            tenant_id=None,
            email="ops@example.test",
            hashed_password="x",
            role="operator",
        )
        db.add(u)
        await db.commit()
        token = create_access_token(tenant_id="", user_id=u.id, role="operator")
    return {"Authorization": f"Bearer {token}"}
