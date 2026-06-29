import asyncio
import os
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return "sqlite+aiosqlite:///./mokuture.db"


def _sqlite_path(database_url: str) -> Path:
    raw_path = database_url.removeprefix("sqlite+aiosqlite:///").removeprefix("sqlite:///")
    path = Path(raw_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _run_sqlite(database_url: str) -> None:
    db_path = _sqlite_path(database_url)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meeting_rooms (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                location VARCHAR(255),
                capacity INTEGER,
                color VARCHAR(32),
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                map_image_url VARCHAR(512),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_meeting_rooms_tenant_id ON meeting_rooms (tenant_id)")

        mr_columns = {row[1] for row in conn.execute("PRAGMA table_info(meeting_rooms)").fetchall()}
        if "map_image_url" not in mr_columns:
            conn.execute("ALTER TABLE meeting_rooms ADD COLUMN map_image_url VARCHAR(512)")

        visitor_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'visitor_appointments'"
        ).fetchone()
        if visitor_table:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(visitor_appointments)").fetchall()}
            if "meeting_room_id" not in columns:
                conn.execute(
                    """
                    ALTER TABLE visitor_appointments
                    ADD COLUMN meeting_room_id VARCHAR(36) REFERENCES meeting_rooms(id) ON DELETE SET NULL
                    """
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_visitor_appointments_meeting_room_id "
                "ON visitor_appointments (meeting_room_id)"
            )
        conn.commit()
    finally:
        conn.close()


async def _run_postgres(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required for PostgreSQL migrations. Install it with: pip install asyncpg") from exc

    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres+asyncpg://", "postgres://")
    conn = await asyncpg.connect(dsn=dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meeting_rooms (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                location VARCHAR(255),
                capacity INTEGER,
                color VARCHAR(32),
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                map_image_url VARCHAR(512),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS ix_meeting_rooms_tenant_id ON meeting_rooms (tenant_id)")
        await conn.execute("ALTER TABLE meeting_rooms ADD COLUMN IF NOT EXISTS map_image_url VARCHAR(512)")
        await conn.execute(
            """
            ALTER TABLE visitor_appointments
            ADD COLUMN IF NOT EXISTS meeting_room_id VARCHAR(36) REFERENCES meeting_rooms(id) ON DELETE SET NULL
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_visitor_appointments_meeting_room_id
            ON visitor_appointments (meeting_room_id)
            """
        )
    finally:
        await conn.close()


async def main() -> None:
    database_url = _database_url()
    if database_url.startswith("sqlite"):
        _run_sqlite(database_url)
    else:
        await _run_postgres(database_url)
    print("Meeting rooms migration completed")


if __name__ == "__main__":
    asyncio.run(main())
