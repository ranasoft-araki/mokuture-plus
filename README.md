# mokuture+

磯野木工所の自社CMSプラットフォーム。デジタルサイネージ・受付・ロッカー制御を一元管理するマルチテナント型SaaSです。

---

## サービス構成

```
ブラウザ / キオスク端末
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
└────────────┬──────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────┐   ┌────────────────┐
│  Neon    │   │ Cloudflare R2  │
│PostgreSQL│   │  (メディア保存)  │
└──────────┘   └────────────────┘
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

受付に置くタブレット・PCで以下を開きます。

```
https://mokuture-plus.netlify.app/{slug}/kiosk
```

- 待機中はデジタルサイネージ（登録したプレイリスト）が自動再生されます
- 来訪者が画面をタップすると受付フォームに進みます
- 受付完了後、Slack に通知が送信されます（設定済みの場合）
- 自動的に待機画面に戻ります（60秒タイムアウト）

### 4. Slack 通知の設定

管理ダッシュボードの「通知設定」から Slack Webhook URL を登録します。  
受付が完了するたびに指定チャンネルに通知が届きます。

---

## API エンドポイント

ベース URL: `https://mokuture-plus-api.onrender.com/api`

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
| `GET/POST` | `/notifications` | 通知設定 |

すべてのエンドポイント（登録・ログイン以外）は `Authorization: Bearer {token}` ヘッダーが必要です。

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

ブラウザで `http://localhost:3000/login` を開きます。

### 環境変数 (.env)

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

---

## Phase 1 予定機能

- [ ] QRコード受付
- [ ] Google Calendar 連携（予約との突合）
- [ ] Chatwork 通知
- [ ] PWA プッシュ通知
- [ ] メディア管理画面（アップロードUI）
- [ ] スケジュール管理画面
- [ ] Raspberry Pi GPIO ブリッジ（ロッカー実機連携）
- [ ] テナント登録の招待制化
- [ ] Cloudflare R2 本番設定
