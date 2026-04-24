from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "mokuture+"
    debug: bool = False
    api_prefix: str = "/api"

    # Database
    database_url: str = "sqlite+aiosqlite:///./mokuture.db"

    # JWT (RS256 would need key files; use HS256 for Phase 0 simplicity, upgrade to RS256 in Phase 1)
    jwt_secret_key: str = "change-me-in-production-use-256bit-random"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    # Cloudflare R2 / MinIO (S3-compatible)
    storage_endpoint_url: str = "http://localhost:9000"
    storage_access_key_id: str = "minioadmin"
    storage_secret_access_key: str = "minioadmin"
    storage_bucket_name: str = "mokuture"
    storage_public_url: str = "http://localhost:9000/mokuture"

    # Encryption key for stored webhook URLs / API tokens (Fernet)
    encryption_key: str = "change-me-generate-with-Fernet.generate_key()"

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # VAPID for Web Push
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@mokuture.jp"


settings = Settings()
