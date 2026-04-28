# mokuture+

磯野木工所の自社CMSプラットフォーム。デジタルサイネージ・受付・ロッカー制御を一元管理するマルチテナント型SaaSです。

---

## サービス構成

```
【クラウド側】
  ブラウザ (管理画面)
        │
        ▼
┌───────────────────────────┐
│  Frontend (Netlify)        │  https://mokuture-plus.netlify.app
│  Next.js 16 (App Router)   │
└────────────┬──────────────┘
             │ REST API (HTTPS)
             ▼
┌───────────────────────────┐
│  Backend API (Render)      │  https://mokuture-plus-api.onrender.com
│  FastAPI + SQLAlchemy      │
└──────┬──────────┬─────────┘
       │          │
  ┌────▼───┐  ┌───▼────────────┐
  │  Neon  │  │ Cloudflare R2  │
  │  Pg DB │  │  (メディア保存)  │
  └────────┘  └────────────────┘

【キオスク端末側 (Raspberry Pi)】
  Chromium --kiosk http://localhost:8080
        │
        ▼
┌───────────────────────────┐
│  Kiosk Agent (port 8080)  │  ← kiosk_agent/ (本リポジトリ)
│  FastAPI (local)          │
│  ・コンテンツ同期&キャッシュ  │
│  ・GPIO制御 (ロッカー/PIR)  │
│  ・Next.js 静的ビルド配信   │
└────────────┬──────────────┘
             │ API同期 (HTTPS)
             ▲
        (Backend API)
```

| レイヤー | サービス | 無料枠 |
|---|---|---|
| Frontend | [Netlify](https://mokuture-plus.netlify.app) | 無制限 (静的) |
| Backend API | [Render](https://mokuture-plus-api.onrender.com) | 512MB RAM / 15分スリープあり |
| データベース | [Neon PostgreSQL](https://console.neon.tech) | 512MB |
| ストレージ | Cloudflare R2 | 10GB/月 |
| コード | [GitHub](https://github.com/ranasoft-araki/mokuture-plus) | — |

> **注意**: Render の無料プランはアクセスがない状態が15分続くとスリープします。
> 初回アクセス時に30秒ほどかかる場合があります。

---

## 画面・URL一覧

### 本番環境

| 画面 | URL | 用途 |
|---|---|---|
| **テナントログイン** | `https://mokuture-plus.netlify.app/login` | 管理者ログイン |
| **管理ダッシュボード** | `https://mokuture-plus.netlify.app/{slug}/admin` | 受付ログ・統計確認 |
| **受付ログ一覧** | `https://mokuture-plus.netlify.app/{slug}/admin/reception` | 来訪者履歴 |
| **キオスク待機画面** | `https://mokuture-plus.netlify.app/{slug}/kiosk` | 受付端末 (待機・デジタルサイネージ) |
| **受付入力** | `https://mokuture-plus.netlify.app/{slug}/kiosk/reception` | 来訪者が情報入力 |
| **受付完了** | `https://mokuture-plus.netlify.app/{slug}/kiosk/complete` | 受付完了メッセージ |
| **API ヘルスチェック** | `https://mokuture-plus-api.onrender.com/health` | サーバー死活確認 |

`{slug}` はテナント登録時に設定したスラッグ（例: `isinokk`）

### ローカル開発環境

| 画面 | URL |
|---|---|
| フロントエンド | `http://localhost:3000` |
| バックエンド API | `http://localhost:8001` |
| API ドキュメント (Swagger) | `http://localhost:8001/docs` |
| キオスクエージェント | `http://localhost:8080` |

---

## 使い方

### 1. テナント登録

ログイン画面 (`/login`) の「新規登録」から以下を入力します。

| 項目 | 例 | 説明 |
|---|---|---|
| テナント名 | 磯野木工所 | 会社・店舗名 |
| スラッグ | `isinokk` | URLに使用する英数字 (変更不可) |
| メールアドレス | admin@isinokk.co.jp | ログインID |
| パスワード | — | 8文字以上推奨 |

登録完了後、自動的に管理ダッシュボードへリダイレクトされます。

### 2. 管理ダッシュボード

`/{slug}/admin` にログインして確認できます。

- 本日の受付件数
- 直近の受付ログ（来訪者名・会社・目的・担当者）
- ロッカー一覧と施錠/解錠操作

### 3. キオスク端末のセットアップ

#### ブラウザのみ（クラウド接続・動画は毎回CDNから再生）

受付に置くタブレット・PCで以下を開きます。

```
https://mokuture-plus.netlify.app/{slug}/kiosk
```

初回アクセス時にデバイス登録画面 (`/kiosk/setup`) が表示されます。  
管理画面の「デバイス管理」で発行した PIN を入力してください。

#### Raspberry Pi ローカルエージェント（動画をローカルキャッシュ・GPIO連携）

Raspberry Pi 上でキオスクエージェントを動作させると以下が有効になります。

- 動画/画像をローカルにダウンロードして再生（回線負荷ゼロ）
- GPIO でロッカーリレー制御・PIR 人感センサー連携
- ネットワーク断時も既キャッシュコンテンツで動作継続

→ 詳細は [キオスクエージェント セットアップ手順](#キオスクエージェント-raspberry-pi) を参照

### 4. Slack 通知の設定

管理ダッシュボードの「通知設定」から Slack Webhook URL を登録します。  
受付が完了するたびに指定チャンネルに通知が届きます。

---

## キオスクエージェント (Raspberry Pi)

`kiosk_agent/` ディレクトリのローカル FastAPI サーバー。  
Raspberry Pi 上で動き、コンテンツ同期・メディア配信・GPIO 制御を担当します。

### ファイル構成

```
kiosk_agent/
├── main.py               FastAPI 本体 (メディア配信・GPIO API・静的ファイル配信)
├── sync.py               コンテンツ同期デーモン (差分ダウンロード・定期実行)
├── gpio.py               GPIO 制御 (ロッカーリレー・PIR センサー)
├── state.py              デバイス登録状態の永続管理
├── config.py             設定読み込み (.env)
├── pyproject.toml        依存パッケージ
├── install.sh            RPi 向けセットアップスクリプト
├── mokuture-kiosk.service  systemd ユニットファイル
└── .env.example          環境変数サンプル
```

### 起動コマンド

> **前提**: `uv` が必要です。未インストールの場合は先にインストールしてください。
> - **Linux / RPi**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
> - **Windows**: PowerShell で `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` を実行後、PowerShell を再起動

**開発・動作確認（WSL または Linux）**

```bash
cd kiosk_agent

# 初回のみ: .env を用意
cp .env.example .env
# .env を編集:
#   MOCK_GPIO=true              ← GPIO をモックに切り替え
#   MEDIA_DIR=/tmp/kiosk-media  ← 書き込み可能なパスに変更

# 起動
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

**開発・動作確認（Windows PowerShell）**

```powershell
cd kiosk_agent

# 初回のみ: .env を用意（PowerShell では cp の代わりに Copy-Item）
Copy-Item .env.example .env
# .env を編集:
#   MOCK_GPIO=true
#   MEDIA_DIR=C:\Temp\kiosk-media

# 起動
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

> **注意**: Windows で実行する場合、キオスクエージェントの本番環境（Raspberry Pi / Linux）と
> 動作環境が異なります。開発確認目的のみに使用し、GPIO 関連の動作は WSL または RPi で確認してください。

**Raspberry Pi（本番）**

```bash
cd kiosk_agent

# セットアップ（初回のみ）: 依存インストール + systemd 登録
bash install.sh

# 以後は systemd で自動起動するため手動起動不要
# 手動操作が必要な場合:
sudo systemctl start  mokuture-kiosk
sudo systemctl stop   mokuture-kiosk
sudo systemctl status mokuture-kiosk
journalctl -u mokuture-kiosk -f   # ログ確認
```

### デバイス登録（PIN 交換）

エージェント起動後、**管理画面で発行した PIN** を使って一度だけ登録を行います。  
登録後は `device_state.json` にトークンが保存され、再起動しても維持されます。

**Linux / macOS / WSL**

```bash
curl -X POST http://<RPiのIPアドレス>:8080/setup \
     -H "Content-Type: application/json" \
     -d '{"pin_code":"123456"}'
```

**Windows PowerShell**

```powershell
# 方法1: curl.exe (Windows 10/11 標準搭載)
curl.exe -X POST "http://<RPiのIPアドレス>:8080/setup" `
         -H "Content-Type: application/json" `
         -d '{\"pin_code\":\"123456\"}'

# 方法2: Invoke-RestMethod
Invoke-RestMethod -Uri "http://<RPiのIPアドレス>:8080/setup" `
                  -Method POST `
                  -ContentType "application/json" `
                  -Body '{"pin_code":"123456"}'
```

登録成功時のレスポンス:

```json
{"status": "registered", "device_name": "受付キオスク"}
```

### エンドポイント一覧

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/health` | 動作確認・登録状態確認 |
| `POST` | `/setup` | PIN でデバイス登録（初回のみ） |
| `GET` | `/media/{media_id}` | ローカルキャッシュからメディア配信 |
| `POST` | `/device/locker/{id}/open` | ロッカー解錠 (GPIO) |
| `GET` | `/device/pir` | PIR センサー状態取得 |

### 環境変数 (.env)

| 変数 | デフォルト | 説明 |
|---|---|---|
| `REMOTE_API_URL` | `https://mokuture-plus-api.onrender.com/api` | リモート API |
| `MEDIA_DIR` | `/home/pi/kiosk-media` | 動画キャッシュ保存先 |
| `PORT` | `8080` | リッスンポート |
| `SYNC_INTERVAL_SEC` | `60` | コンテンツ同期間隔（秒） |
| `MOCK_GPIO` | `false` | `true` にすると GPIO をモック動作 |
| `PIR_PIN` | `4` | PIR センサーの GPIO ピン番号 (BCM) |
| `LOCKER_PINS_JSON` | `{}` | ロッカーID → GPIO ピンの対応 例: `{"1": 17, "2": 18}` |

### Chromium 自動起動設定（RPi）

```bash
# /etc/xdg/lxsession/LXDE-pi/autostart に追記
@chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:8080
```

---

## API エンドポイント

ベース URL: `https://mokuture-plus-api.onrender.com/api`

### 管理 API（JWT 認証）

| メソッド | パス | 説明 |
|---|---|---|
| `POST` | `/auth/register` | テナント新規登録 |
| `POST` | `/auth/login` | ログイン (JWT取得) |
| `POST` | `/auth/refresh` | トークンリフレッシュ |
| `GET` | `/reception` | 受付ログ一覧 |
| `POST` | `/reception` | 受付登録 |
| `GET` | `/reception/stats/today` | 本日の受付件数 |
| `GET` | `/content/media` | メディア一覧 |
| `POST` | `/content/media/upload-url` | アップロード URL 発行 (R2) |
| `GET` | `/content/playlists` | プレイリスト一覧 |
| `POST` | `/content/playlists` | プレイリスト作成 |
| `GET` | `/content/schedules/current` | 現在のスケジュール取得 |
| `GET` | `/lockers` | ロッカー一覧 |
| `POST` | `/lockers/{id}/unlock` | 解錠 |
| `POST` | `/lockers/{id}/lock` | 施錠 |
| `GET/PUT` | `/notifications/settings` | 通知設定 |

管理 API はすべて `Authorization: Bearer {token}` ヘッダーが必要です。

### キオスク API（デバイストークン認証）

| メソッド | パス | 説明 |
|---|---|---|
| `POST` | `/kiosk/verify-pin` | PIN → デバイストークン交換 |
| `GET` | `/kiosk/schedule` | 現在のプレイリスト取得 |
| `GET` | `/kiosk/content-manifest` | 全スケジュールメディア一覧（ローカルキャッシュ用） |
| `POST` | `/kiosk/reception` | 受付登録 |

キオスク API は `X-Kiosk-Token: {device_token}` ヘッダーを使用します。

---

## ローカル開発

### 必要なツール

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- Node.js 20+

### セットアップ

```bash
# リポジトリクローン
git clone https://github.com/ranasoft-araki/mokuture-plus.git
cd mokuture-plus
```

**バックエンド起動**

```bash
cd backend
cp .env.example .env        # 環境変数をコピーして編集
uv sync                     # 依存関係インストール
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

**フロントエンド起動**

```bash
cd frontend
npm install
npm run dev
```

**キオスクエージェント起動（開発用）**

```bash
cd kiosk_agent
cp .env.example .env
# .env: MOCK_GPIO=true, MEDIA_DIR=/tmp/kiosk-media に変更
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

ブラウザで `http://localhost:3000/login` を開きます。

### 環境変数 (.env) — バックエンド

```env
# DB (ローカルはSQLiteを使用)
DATABASE_URL=sqlite+aiosqlite:///./mokuture.db

# JWT
JWT_SECRET_KEY=your-secret-key-here

# Fernet暗号化 (Webhook URL保存用)
ENCRYPTION_KEY=your-fernet-key-here

# CORS
ALLOWED_ORIGINS=["http://localhost:3000"]

# ストレージ (MinIO ローカル or Cloudflare R2)
STORAGE_ENDPOINT_URL=http://localhost:9000
STORAGE_ACCESS_KEY_ID=minioadmin
STORAGE_SECRET_ACCESS_KEY=minioadmin
STORAGE_BUCKET_NAME=mokuture
STORAGE_PUBLIC_URL=http://localhost:9000/mokuture
```

---

## デプロイ構成

### CI/CD

`master` ブランチに `git push` すると自動デプロイされます。

| サービス | トリガー | 所要時間 |
|---|---|---|
| Render (Backend) | GitHub push → 自動ビルド | 約3〜5分 |
| Netlify (Frontend) | MCP / Netlify CLI で手動デプロイ | 約2〜3分 |

### インフラ設定ファイル

| ファイル | 用途 |
|---|---|
| `Dockerfile` | Render用 Docker イメージ (リポジトリルート) |
| `backend/Dockerfile` | Fly.io / ローカル Docker 用 |
| `render.yaml` | Render Blueprint 定義 |
| `backend/fly.toml` | Fly.io 設定 (現在未使用) |
| `frontend/netlify.toml` | Netlify ビルド設定 |

---

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| Frontend | Next.js 16 (App Router) / TypeScript / Tailwind CSS v4 |
| Backend | Python 3.11 / FastAPI / SQLAlchemy (async) / Alembic |
| DB Driver | asyncpg (PostgreSQL) / aiosqlite (SQLite) |
| 認証 | JWT (HS256) / bcrypt |
| ストレージ | S3互換 (Cloudflare R2 / MinIO) |
| 暗号化 | Fernet (Webhook URL・APIトークン保存) |
| レート制限 | slowapi |
| キオスクエージェント | FastAPI (local) / gpiozero / httpx |

---

## Phase 1 予定機能

- [ ] QRコード受付
- [ ] Google Calendar 連携（予約との突合）
- [ ] Chatwork 通知
- [ ] PWA プッシュ通知
- [ ] メディア管理画面（アップロードUI）
- [ ] スケジュール管理画面
- [x] Raspberry Pi GPIO ブリッジ（ロッカー実機連携）← kiosk_agent 実装済み
- [ ] テナント登録の招待制化
- [ ] Cloudflare R2 本番設定
