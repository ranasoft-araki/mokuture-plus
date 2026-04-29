# mokuture+ — CLAUDE.md

> このファイルは Claude が本プロジェクトを扱う際の参照ドキュメント。
> **コードを追加・変更したらこのファイルの該当箇所も必ず更新すること。**
> **Codexとレビューしあって進めること。**

---

## システム概要

磯野木工所の自社 CMS プラットフォーム。デジタルサイネージ・キオスク受付・ロッカー制御を一元管理する SaaS。

| 項目 | 内容 |
|---|---|
| リポジトリ | https://github.com/ranasoft-araki/mokuture-plus |
| フロントエンド本番 | https://mokuture-plus.netlify.app |
| バックエンド本番 | https://mokuture-plus-api.onrender.com |
| DB 本番 | Neon PostgreSQL (Project ID: `broad-moon-06415649`, us-east-1) |

---

## 技術スタック

| レイヤー | 技術 |
|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind CSS |
| Backend | Python 3.11 + FastAPI + SQLAlchemy (async) + asyncpg |
| DB | Neon PostgreSQL (本番) / SQLite (ローカル開発) |
| Storage | Cloudflare R2 / MinIO (S3 互換、Presigned URL) |
| 認証 | JWT HS256 (access + refresh) + bcrypt |
| デプロイ | Frontend → Netlify、Backend → Render (512MB free) |

---

## ローカル起動

```bash
# Backend (port 8001)
cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Frontend (port 3000)
cd frontend && npm run dev

# Kiosk Agent (port 8080) — Raspberry Pi / ローカル動作確認
cd kiosk_agent && uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload
# ブラウザで http://localhost:8080 を開く (Chromium キオスクモード: chromium-browser --kiosk http://localhost:8080)
```

### Kiosk Agent — Raspberry Pi 本番セットアップ

```bash
# 1. インストール & systemd 登録
cd kiosk_agent && bash install.sh

# 2. デバイス登録 (管理画面で PIN を発行してから)
curl -X POST http://localhost:8080/setup \
     -H 'Content-Type: application/json' \
     -d '{"pin_code":"取得したPIN"}'

# 3. サービス管理
sudo systemctl status mokuture-kiosk
journalctl -u mokuture-kiosk -f
```

---

## ディレクトリ構成

```
mokuture/
├── CLAUDE.md                  ← このファイル
├── backend/                   ← FastAPI バックエンド
│   └── app/
│       ├── main.py            ← FastAPI アプリ初期化・CORS・ルーター登録
│       ├── config.py          ← 環境変数・設定値 (Pydantic Settings)
│       ├── database.py        ← SQLAlchemy async エンジン・セッション
│       ├── api/               ← エンドポイント (各ファイルが1ドメイン)
│       │   ├── auth.py        ← /auth/login, /auth/refresh, /auth/register
│       │   ├── settings.py    ← /settings (ブランディング・キオスク文言・ロゴ配置)
│       │   ├── content.py     ← /media, /playlists, /schedules
│       │   ├── devices.py     ← /devices (キオスク端末管理・PIN 発行)
│       │   ├── kiosk.py       ← /kiosk/* (公開API: スケジュール・受付送信・PIN検証)
│       │   ├── reception.py   ← /reception (受付ログ一覧)
│       │   ├── notifications.py ← /notifications (Slack/Chatwork 設定)
│       │   ├── lockers.py     ← /lockers (ロッカー制御モック)
│       │   └── push.py        ← /push (Web Push 購読管理)
│       ├── models/            ← SQLAlchemy ORM モデル
│       │   ├── tenant.py      ← Tenant (ブランディング・キオスク設定・ロゴ配置)
│       │   ├── user.py        ← User (email, password_hash, role, tenant_id)
│       │   ├── content.py     ← Media, Playlist, PlaylistItem, Schedule
│       │   ├── device.py      ← Device (token, PIN), Locker
│       │   ├── reception.py   ← ReceptionLog (visitor_name, company, staff, purpose)
│       │   └── notification.py ← NotificationSetting, PushSubscription
│       ├── middleware/
│       │   └── tenant.py      ← JWT 検証・テナント分離 (get_current_user)
│       └── services/
│           ├── auth.py        ← JWT 生成・検証
│           ├── crypto.py      ← Fernet 暗号化 (Slack URL 等の秘密情報)
│           ├── storage.py     ← R2/MinIO Presigned URL 生成
│           ├── slack.py       ← Slack Webhook 通知
│           └── webpush.py     ← Web Push 送信
│
├── frontend/                  ← Next.js フロントエンド
│   ├── app/
│   │   ├── layout.tsx         ← ルートレイアウト (Google Fonts 等)
│   │   ├── page.tsx           ← / → /login リダイレクト
│   │   ├── login/page.tsx     ← ログイン画面
│   │   └── [tenant]/          ← テナント別ルート (slug でテナント識別)
│   │       ├── layout.tsx     ← テナントレイアウト
│   │       ├── admin/         ← 管理画面 (JWT 必須)
│   │       │   ├── page.tsx           ← ダッシュボード (KPI・デバイス状態・受付ログ)
│   │       │   ├── media/page.tsx     ← メディア管理 (アップロード・一覧)
│   │       │   ├── playlists/page.tsx ← プレイリスト管理
│   │       │   ├── schedules/page.tsx ← スケジュール管理
│   │       │   ├── kiosk/page.tsx     ← キオスク端末管理・PIN 発行
│   │       │   ├── reception/page.tsx ← 受付ログ一覧・フィルター
│   │       │   ├── kiosk-settings/page.tsx ← 受付設定 (キオスク文言・ロゴ配置ドラッグ)
│   │       │   ├── settings/page.tsx  ← 基本設定 (ブランディング: ロゴ・カラー・フォント)
│   │       │   ├── notify/page.tsx    ← 通知設定 (Slack/Chatwork/PWA)
│   │       │   └── locker/page.tsx    ← ロッカー管理
│   │       └── kiosk/         ← キオスク受付画面 (デバイストークン必須)
│   │           ├── page.tsx           ← KioskFlow マウント
│   │           ├── KioskFlow.tsx      ← メインキオスクコンポーネント (全画面遷移管理)
│   │           ├── setup/page.tsx     ← デバイスセットアップ (PIN 入力)
│   │           └── top|reception|qr|calling|complete/page.tsx ← 各画面 (KioskFlow へリダイレクト)
│   ├── components/
│   │   ├── AdminShell.tsx     ← 管理画面レイアウト・サイドバーナビ・共通 UI コンポーネント
│   │   ├── KioskScaler.tsx    ← 1920×1080 キャンバスをビューポートに等比スケール
│   │   └── PWAInit.tsx        ← PWA Service Worker 登録
│   └── lib/
│       ├── api.ts             ← API クライアント・全型定義 (TenantSettings 等)
│       ├── auth.ts            ← JWT トークン管理 (localStorage)
│       └── push.ts            ← Web Push 購読ユーティリティ
│
└── kiosk_agent/               ← Raspberry Pi エージェント (Phase 1)
    ├── main.py                ← メインループ (API ポーリング・GPIO 制御)
    ├── gpio.py                ← GPIO モック / 実機切り替え
    ├── sync.py                ← バックエンドとのデータ同期
    └── state.py               ← デバイス状態管理
```

---

## DB スキーマ概要 (主要テーブル)

### tenants
テナント設定を全て保持。キオスク設定もここに集約。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| slug | VARCHAR(64) | URL識別子 (ユニーク) |
| name | VARCHAR(255) | テナント名 |
| brand_color | VARCHAR(7) | テーマカラー (#RRGGBB) |
| logo_url | VARCHAR(512) | ロゴ公開 URL |
| font | VARCHAR(64) | フォント設定 |
| kiosk_welcome_message | VARCHAR(255) | トップ画面メインメッセージ |
| kiosk_sub_message | VARCHAR(255) | トップ画面サブメッセージ |
| kiosk_calling_message | VARCHAR(255) | 呼び出し中メッセージ |
| kiosk_complete_message | VARCHAR(255) | 完了画面メッセージ |
| kiosk_idle_timeout_sec | INT | 無操作タイムアウト秒数 (10–300) |
| kiosk_complete_timeout_sec | INT | 完了画面表示秒数 (5–60) |
| logo_pos_x | FLOAT | ロゴ X 位置 (0.0–0.9、画面幅比) |
| logo_pos_y | FLOAT | ロゴ Y 位置 (0.0–0.9、画面高比) |
| logo_width_pct | FLOAT | ロゴ幅 (2.0–30.0、画面幅に対する %) |
| kiosk_style | VARCHAR(32) | ようこそ画面デザインパターン ID (default / medical / retail / hotel / startup / school / craft / industrial / restaurant / mono / gym) |

### その他テーブル
- **users** — email / password_hash / role / tenant_id
- **media** — アップロードファイル (URL, mime_type, duration_sec)
- **playlists / playlist_items** — メディアのプレイリスト
- **schedules** — 曜日・時間帯ごとのプレイリスト割当
- **devices** — キオスク端末 (token, PIN, last_seen_at)
- **lockers** — ロッカー (gpio_pin, state)
- **reception_logs** — 受付ログ (visitor_name, company, staff, purpose, method, state)
- **notification_settings** — Slack/Chatwork Webhook URL (Fernet 暗号化)
- **push_subscriptions** — Web Push 購読情報

---

## API エンドポイント概要

全エンドポイントは `/api/v1` プレフィックス。

| メソッド | パス | 認証 | 説明 |
|---|---|---|---|
| POST | /auth/login | なし | JWT 取得 |
| POST | /auth/register | なし | テナント + 管理者ユーザー作成 |
| POST | /auth/refresh | refresh token | access token 更新 |
| GET | /settings | JWT | テナント設定取得 |
| PATCH | /settings | JWT | テナント設定更新 |
| GET | /settings/public/{slug} | なし | キオスク用公開設定 |
| POST | /settings/logo-upload-url | JWT | R2 Presigned URL 取得 |
| PATCH | /settings/logo | JWT | ロゴ URL 確定 |
| GET | /media | JWT | メディア一覧 |
| POST | /media/upload-url | JWT | メディア Presigned URL 取得 |
| GET/POST/DELETE | /playlists | JWT | プレイリスト CRUD |
| GET/POST/DELETE | /schedules | JWT | スケジュール CRUD |
| GET/POST/DELETE | /devices | JWT | デバイス CRUD |
| POST | /devices/{id}/pin | JWT | PIN 発行 |
| GET | /kiosk/schedule | デバイストークン | 現在のプレイリスト取得 |
| POST | /kiosk/reception | デバイストークン | 受付フォーム送信 |
| POST | /kiosk/verify-pin | なし | PIN → デバイストークン交換 |
| GET | /reception | JWT | 受付ログ一覧 |
| GET/PATCH | /notifications | JWT | 通知設定 |
| GET/POST | /lockers | JWT | ロッカー管理 |
| POST | /lockers/{id}/open | JWT | ロッカー開錠 |

---

## 重要な実装ルール

### マルチテナント分離
- **全 DB クエリに `tenant_id` フィルタを必ずつけること。**
- `get_current_user` が JWT から `user.tenant_id` を取得し、各エンドポイントで `WHERE tenant_id = user.tenant_id` を適用。
- キオスク公開 API (`/kiosk/*`) はデバイストークンで `tenant_id` を解決。

### キオスク デザインパターン追加方法

新しい「ようこそ」画面パターンを追加するには以下の3箇所を更新すること:

1. **`frontend/app/[tenant]/admin/kiosk-settings/kioskStyles.ts`** に `KioskStyleDef` エントリを追加
2. **`backend/app/api/settings.py`** の `ALLOWED_KIOSK_STYLES` セットに ID を追加
3. **`kiosk_agent/static/kiosk.html`** に `buildComplete_XXX(vName, staff, bc, count, now, completeMsg)` 関数を追加し、`COMPLETE_TEMPLATES` オブジェクトに登録

DB マイグレーション不要（`kiosk_style` カラムはフリーテキスト）。

### キオスク画面
- `KioskFlow.tsx` が全画面状態 (`idle → top → reception/qr → calling → complete`) を管理。
- `KioskScaler` が 1920×1080 固定サイズを CSS `transform: scale()` でビューポートにフィット。
- `PublicTenantSettings` は `localStorage` にキャッシュ（オフライン対応）。
- TopScreen にはロゴを `position: absolute` で `logo_pos_x/y/width_pct` に従い表示。

### 「戻る」ボタンの配置ルール（キオスク・管理画面 共通）

**キオスク (`kiosk.html`)**: 「← 戻る」ボタンは **必ずページ最上部・コンテンツグリッドの外側**に配置する。
- ラッパー: `<div style="padding:20px 80px 0;flex-shrink:0">`
- ボタンスタイル: `display:inline-flex;align-items:center;gap:8px;padding:10px 20px;background:#fffefb;border:1px solid #d8d3c7;border-radius:999px;font-size:15px;color:#6b6559;cursor:pointer`
- **コンテンツグリッド内（左右どちらの列にも）配置しないこと。**

```html
<!-- ✅ 正しい配置 -->
<div style="width:1920px;height:1080px;...display:flex;flex-direction:column">
  <div style="padding:20px 80px 0;flex-shrink:0">
    <button id="xxx-back" style="display:inline-flex;align-items:center;gap:8px;padding:10px 20px;background:#fffefb;border:1px solid #d8d3c7;border-radius:999px;font-size:15px;color:#6b6559;cursor:pointer">← 戻る</button>
  </div>
  <div style="flex:1;padding:...;display:grid;...">
    <!-- グリッドの中には戻るボタンを入れない -->
  </div>
</div>
```

**管理画面 (`AdminShell`)**: ページ内に「一覧へ戻る」などのナビゲーションが必要な場合は、**必ず `AdminShell` の `actions` props** に `MkBtn` で配置する（コンテンツエリア内には置かない）。
```tsx
// ✅ 正しい配置
<AdminShell ... actions={
  <MkBtn variant="default" size="sm" onClick={...}>← 一覧へ</MkBtn>
}>
```

### 管理画面ナビゲーション
- `AdminShell.tsx` の `NavId` 型・`NAV_SETTINGS`・`NAV_PATHS`・`NavIcon` を一括管理。
- ページを追加したら 4 箇所全て更新すること。
- 現在の設定メニュー: 通知設定 / ロッカー / **受付設定** / 基本設定

### 秘密情報の暗号化
- Slack/Chatwork Webhook URL は `services/crypto.py` (Fernet) で暗号化して DB 保存。
- `ENCRYPTION_KEY` 環境変数が必須。

### DB マイグレーション
- Alembic 未導入のため、カラム追加は Neon Console または `mcp__Neon__run_sql` で手動 `ALTER TABLE`。
- SQLAlchemy モデルと DB スキーマを常に同期すること。

---

## 環境変数

### Backend (.env)
```
DATABASE_URL=postgresql+asyncpg://...
JWT_SECRET_KEY=...
ENCRYPTION_KEY=...           # Fernet key (base64)
STORAGE_ENDPOINT=...         # R2/MinIO endpoint
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
STORAGE_BUCKET=...
STORAGE_PUBLIC_URL=...
```

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1
```
