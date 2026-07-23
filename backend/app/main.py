from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine, Base
from app.api import api_router


# Alembic 未導入のため、起動時に冪等な軽量カラム追加を適用する。
# 既存テーブルに後付けしたカラムを本番(Postgres/Neon)・開発(SQLite)双方で揃える。
# (テーブルが無ければ create_all が全カラム込みで作成するためここでは何もしない)
_ENSURE_COLUMNS = {
    "meeting_rooms": {
        "map_image_url": "VARCHAR(512)",
    },
    "tenants": {
        # 受付通知で「電話(対応不可)」応答時にキオスクへ表示する電話番号、
        # 「お断り」応答時に案内する外部問い合わせフォールURL(未設定時は共通フォームへ)。
        "kiosk_phone_number": "VARCHAR(32)",
        "inquiry_form_url": "VARCHAR(512)",
        # キオスク文言(受付メニュー見出し / ようこそ画面QR案内・フォームボタン)。
        # DEFAULT 付きで既存行も埋める。
        "kiosk_menu_title": "VARCHAR(255) DEFAULT 'ご用件をお選びください'",
        "kiosk_welcome_qr_guide": "VARCHAR(255) DEFAULT 'ご予約QRをお持ちの方はカメラへかざしてください'",
        "kiosk_welcome_form_label": "VARCHAR(255) DEFAULT 'QRをお持ちでない方はこちら'",
        # 来訪者が受付フォームで選べる訪問先部署のリスト(カンマ区切り)。
        "department_list": "TEXT",
    },
    "lockers": {
        "name": "VARCHAR(255)",
        "pin_hash": "VARCHAR(255)",
        "occupied": "BOOLEAN DEFAULT FALSE",
        "occupied_at": "TIMESTAMP",
    },
    "reception_logs": {
        "decided_at": "TIMESTAMP",
        # 来訪者が選んだ訪問先部署。
        "department": "VARCHAR(255)",
    },
    "devices": {
        # 承認フロー。既存端末は 'active' で埋めて後方互換を保つ。
        "status": "VARCHAR(16) DEFAULT 'active'",
        "hardware_id": "VARCHAR(128)",
    },
}


def _ensure_schema(sync_conn) -> None:
    inspector = inspect(sync_conn)
    try:
        tables = set(inspector.get_table_names())
    except Exception:
        return
    for table, cols in _ENSURE_COLUMNS.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col, ddl_type in cols.items():
            if col not in existing:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl_type}"))

    # 承認フロー: (tenant_id, hardware_id) の重複登録を防ぐ一意インデックス。
    # hardware_id が NULL の行(手動作成端末)は Postgres/SQLite とも「相異なる」扱いのため衝突しない。
    if "devices" in tables:
        try:
            sync_conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_devices_tenant_hardware "
                "ON devices (tenant_id, hardware_id)"
            ))
        except Exception:
            pass  # 既存の重複データ等で作成できなくても致命的ではない


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (dev only; use Alembic for production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema)
    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="mokuture+ API",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Kiosk-Token"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
