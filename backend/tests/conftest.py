"""バックエンドのテスト共通設定。

**本番/開発DBには一切触らない**。`DATABASE_URL` を一時ファイルの SQLite へ上書きしてから
`app` を import する（`backend/.env` の値より環境変数が優先される）。`:memory:` だと接続ごとに
別 DB になり、テストクライアントとセットアップが別のデータを見てしまうのでファイルにする。

外部サービス(Slack / Chatwork / Web Push / SMTP)へは一切出さない。送信関数は各テストで
差し替え、呼ばれた宛先だけを記録する。

クライアントは 2 種類ある。
  - `client`       … 本番と同じ app 全体へ ASGI で入る（分析ログの取り込み経路など）
  - `staff_client` … 対象ルーターだけを載せ、認証を差し替える（担当者ごとの通知先など）
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
# プッシュの鍵が空だと送信手前で打ち切られる。実際の送信関数はテストで差し替えるので、
# 鍵の中身は「空でない」ことだけが意味を持つ。
os.environ["VAPID_PRIVATE_KEY"] = "test-vapid-private-key"
# SMTP は未設定＝無効のままにする（メール送信テストで外へ出さない）
for _key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"):
    os.environ.pop(_key, None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware.tenant import get_current_user  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.notification import NotificationSetting, PushSubscription  # noqa: E402
from app.models.reception import ReceptionLog  # noqa: E402
from app.models.staff_route import StaffNotificationRoute  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import create_access_token  # noqa: E402
from app.services.crypto import encrypt_dict  # noqa: E402


@pytest.fixture(autouse=True)
async def fresh_db():
    """テストごとにテーブルを作り直す（テスト間で行が残らないように）。

    本番だけにある一意インデックス（`main.py` の `_ensure_schema` が生 SQL で作る。
    モデル定義には無い）もここで作る。無いままだと「重複行ができてしまう」系のバグを
    テストで踏めず、本番のインデックス頼みになる — しかもその作成は例外を握り潰す。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_staff_routes_tenant_staff "
            "ON staff_notification_routes (tenant_id, staff_name)"
        ))
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """app 全体へ ASGI で入るクライアント。"""
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


# ── 管理画面 API 用（担当者ごとの通知先など） ─────────────────────────────────

@pytest.fixture
async def admin(tenant: Tenant) -> User:
    async with AsyncSessionLocal() as db:
        u = User(
            id=str(uuid.uuid4()), tenant_id=tenant.id, email="admin@example.test",
            hashed_password="x", role="admin", name="管理者",
        )
        db.add(u)
        await db.commit()
        return u


@pytest.fixture
def staff_client(admin: User):
    """担当者ごとの通知先 API を叩くクライアント（admin としてログイン済み）。"""
    from app.api.staff_routes import router

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api")
    test_app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(test_app) as c:
        yield c


# ── 組み立てヘルパー ───────────────────────────────────────────────────────────

async def set_staff_list(tenant_id: str, names: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        t = await db.get(Tenant, tenant_id)
        t.staff_list = ",".join(names) or None
        await db.commit()


async def add_user(tenant_id: str, name: str, *, role: str = "staff") -> User:
    async with AsyncSessionLocal() as db:
        u = User(
            id=str(uuid.uuid4()), tenant_id=tenant_id,
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            hashed_password="x", role=role, name=name,
        )
        db.add(u)
        await db.commit()
        return u


async def add_push_subscription(tenant_id: str, user_id: str | None, endpoint: str) -> PushSubscription:
    async with AsyncSessionLocal() as db:
        s = PushSubscription(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            endpoint=endpoint, p256dh="p256dh-" + endpoint, auth_key="auth-" + endpoint,
        )
        db.add(s)
        await db.commit()
        return s


async def set_notification_setting(tenant_id: str, type_: str, config: dict) -> None:
    async with AsyncSessionLocal() as db:
        s = NotificationSetting(
            id=str(uuid.uuid4()), tenant_id=tenant_id, type=type_,
            config_json=encrypt_dict(config),
        )
        db.add(s)
        await db.commit()


async def add_route(
    tenant_id: str, staff_name: str, *, config: dict | None = None,
    push_user_id: str | None = None, include_default: bool = True,
    fallback: str | None = None, escalate_after_sec: int = 60,
) -> StaffNotificationRoute:
    async with AsyncSessionLocal() as db:
        r = StaffNotificationRoute(
            id=str(uuid.uuid4()), tenant_id=tenant_id, staff_name=staff_name,
            config_json=encrypt_dict(config or {}),
            push_user_id=push_user_id,
            include_default=include_default,
            fallback_staff_name=fallback,
            escalate_after_sec=escalate_after_sec,
        )
        db.add(r)
        await db.commit()
        return r


async def add_reception(
    tenant_id: str, staff: str, *, state: str = "received", visitor: str = "来客 花子"
) -> ReceptionLog:
    async with AsyncSessionLocal() as db:
        log = ReceptionLog(
            id=str(uuid.uuid4()), tenant_id=tenant_id, visitor_name=visitor,
            company="テスト株式会社", purpose="打ち合わせ", staff=staff,
            method="form", state=state,
        )
        db.add(log)
        await db.commit()
        return log
