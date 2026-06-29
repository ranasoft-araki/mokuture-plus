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
