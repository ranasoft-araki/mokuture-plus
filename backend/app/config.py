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
    jwt_refresh_expire_days: int = 30  # 「ログイン状態を保持」= localStorage の refresh token でこの期間ログインを維持

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

    # Public absolute API base (scheme+host+prefix) used to build URLs embedded in
    # push payloads that the Service Worker (served cross-origin from Netlify) must call.
    public_api_url: str = "https://mokuture-plus-api.onrender.com/api"

    # Public web app base (Netlify). Used to build the mokuture common inquiry-form URL
    # (/{slug}/inquiry) shown as a QR on the kiosk お断り screen when no external form URL is set.
    public_web_url: str = "https://mokuture-plus.netlify.app"

    # Slack OAuth (Bot Token + chat.postMessage). Lets a tenant admin connect Slack from
    # the admin panel ("Slackに追加") instead of pasting a token by hand; the channel is
    # chosen afterward in the UI. Bot Token Scopes: chat:write, channels:read, groups:read,
    # channels:join. Feature is DISABLED unless all three are set (see slack_oauth_enabled).
    # SLACK_REDIRECT_URI must exactly match a Redirect URL registered on the Slack App,
    # e.g. https://mokuture-plus-api.onrender.com/api/notifications/slack/callback
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_redirect_uri: str = ""
    # Slack Interactivity (受付通知の 受付/電話/お断り ボタン). 設定時のみボタンを出し押下を受け付ける。
    # Slack App の Interactivity Request URL に <API>/notifications/slack/interactions を登録し、
    # 各リクエストをこの署名シークレットで検証する。未設定ならボタン無し(従来のテキスト通知)。
    slack_signing_secret: str = ""

    @property
    def slack_oauth_enabled(self) -> bool:
        return bool(self.slack_client_id and self.slack_client_secret and self.slack_redirect_uri)


settings = Settings()
