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
    jwt_access_expire_minutes: int = 60  # 15→60: ホーム画面起動(間隔が空きがち)での refresh 往復頻度を削減。失効時は lib/api.ts の先読みrefreshで無駄な401往復も省く
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

    # 審査用デモモード(demo テナント: tenants.is_demo=true)向け設定。
    # DEMO_LOCKER_PIN: 手荷物預かりで来訪者が何を入力しても内部的に施錠する固定PIN(受取もこれ)。既定 0805。
    # DEMO_AUTO_REPLY_MIN/MAX_SEC: 受付通知後、担当者返信「受付(参ります)」を自動再現するまでの待機秒。
    # スマホへの実プッシュ通知が届く前に画面が遷移しないよう、2026-07-27に 3〜5 → 5〜7 秒へ延長。
    demo_locker_pin: str = "0805"
    demo_auto_reply_min_sec: float = 5.0
    demo_auto_reply_max_sec: float = 7.0

    # 審査環境の閲覧専用アカウント。ここに列挙した email でログインしたアカウントは、
    # アクセストークンに ro=true が付与され、来社予定(appointments)以外のミューテーションを
    # サーバ側(ReadOnlyGuardMiddleware)とフロント(lib/api.ts, AdminShell)の双方で拒否する。
    # env 上書き例: REVIEW_READONLY_EMAILS='["demo1@ranasoft.co.jp","demo2@ranasoft.co.jp"]'
    review_readonly_emails: list[str] = ["demo1@ranasoft.co.jp"]

    # SMTP メール送信(来社予定QRのメール送信)。host/username/password が揃ったときのみ有効(smtp_enabled)。
    # 587=STARTTLS(smtp_starttls=True)、465=implicit TLS(smtp_ssl=True)。Gmail は「アプリパスワード」を smtp_password に。
    # 注意: Render は無料/starter プランで送信SMTPポート(587/465)を塞ぐことがあり、その場合本番で送信に失敗する。
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""       # 差出人アドレス(空なら smtp_username を使う)
    smtp_from_name: str = ""  # 差出人表示名(空ならテナント名 → app_name)
    smtp_starttls: bool = True  # 587: STARTTLS で暗号化
    smtp_ssl: bool = False      # 465: implicit TLS を使う場合 True(starttls は無視)

    @property
    def slack_oauth_enabled(self) -> bool:
        return bool(self.slack_client_id and self.slack_client_secret and self.slack_redirect_uri)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password)


settings = Settings()
