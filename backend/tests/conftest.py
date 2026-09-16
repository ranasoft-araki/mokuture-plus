"""バックエンドのテスト共通土台。

本番の設定(.env)を読み込まないよう、**app を import する前に**環境変数を差し替える。
DB はテスト専用の一時 SQLite ファイル（`:memory:` だと接続ごとに別 DB になり、
TestClient とセットアップで別のデータを見てしまう）。

外部サービス(Slack / Chatwork / Web Push / SMTP)へは一切出さない。送信関数は
テスト側で差し替え、呼ばれた宛先だけを記録する。
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── app より先に環境を固める ───────────────────────────────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="mokuture-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DIR.as_posix()}/test.db"
# Fernet の正規キー(テスト専用。本番の ENCRYPTION_KEY は読ませない)
os.environ["ENCRYPTION_KEY"] = "SjNMbVJ0WUJ3ZEZ2S2VfWjlYcUEtN3BOc0dfMlR4VmM="
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["DEBUG"] = "false"
# プッシュの鍵が空だと送信手前で打ち切られる。実際の送信関数はテストで差し替えるので、
# 鍵の中身は「空でない」ことだけが意味を持つ。
os.environ["VAPID_PRIVATE_KEY"] = "test-vapid-private-key"
# SMTP は未設定＝無効のままにする(メール送信テストで外へ出さない)
for key in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"):
    os.environ.pop(key, None)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 本番と同じ import 経路を通してから create_all する。models パッケージの __init__ だけだと
# visitor_appointments が読み込まれず、reception_logs の外部キーが解決できない。
import app.main  # noqa: E402,F401

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.middleware.tenant import get_current_user  # noqa: E402
from app.models.notification import NotificationSetting, PushSubscription  # noqa: E402
from app.models.reception import ReceptionLog  # noqa: E402
from app.models.staff_route import StaffNotificationRoute  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.crypto import encrypt_dict  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    """テストごとに空のスキーマから始める。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def tenant() -> Tenant:
    async with AsyncSessionLocal() as db:
        t = Tenant(id=str(uuid.uuid4()), name="テスト社", slug="test-" + uuid.uuid4().hex[:6])
        db.add(t)
        await db.commit()
        return t


@pytest_asyncio.fixture
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
def client(admin: User):
    """担当者ごとの通知先 API を叩くクライアント（admin としてログイン済み）。"""
    from app.api.staff_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as c:
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
