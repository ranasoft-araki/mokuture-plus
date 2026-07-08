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

# 2. デバイス登録 (承認フロー・PIN 不要)
#    キオスク画面(ブラウザ)を開くと TENANT_SLUG で自動自己登録。手動トリガーも可:
curl -X POST http://localhost:8080/register
#    → 端末は「承認待ち」になる。管理画面「キオスク端末」で「承認する」を押すと起動。

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
│       │   ├── devices.py     ← /devices (キオスク端末管理・承認)
│       │   ├── kiosk.py       ← /kiosk/* (公開API: スケジュール・受付送信・自己登録/承認状態)
│       │   ├── reception.py   ← /reception (受付ログ一覧)
│       │   ├── notifications.py ← /notifications (Slack/Chatwork 設定)
│       │   ├── lockers.py     ← /lockers (ロッカー制御モック)
│       │   ├── inquiries.py   ← /inquiries (共通問い合わせフォーム: 公開送信・管理閲覧)
│       │   ├── push.py        ← /push (Web Push 購読管理)
│       │   └── users.py       ← /users (テナント内ユーザー管理)
│       ├── models/            ← SQLAlchemy ORM モデル
│       │   ├── tenant.py      ← Tenant (ブランディング・キオスク設定・電話番号・問い合わせURL)
│       │   ├── user.py        ← User (email, password_hash, role, tenant_id)
│       │   ├── content.py     ← Media, Playlist, PlaylistItem, Schedule
│       │   ├── device.py      ← Device (token, status=承認状態, hardware_id), Locker
│       │   ├── reception.py   ← ReceptionLog (visitor_name, company, staff, purpose, state)
│       │   ├── inquiry.py     ← Inquiry (共通問い合わせフォーム受信)
│       │   └── notification.py ← NotificationSetting, PushSubscription
│       ├── middleware/
│       │   └── tenant.py      ← JWT 検証・テナント分離 (get_current_user)
│       └── services/
│           ├── auth.py        ← JWT 生成・検証
│           ├── crypto.py      ← Fernet 暗号化 (Slack URL 等の秘密情報)
│           ├── storage.py     ← R2/MinIO Presigned URL 生成
│           ├── slack.py       ← SlackNotifier(OAuth認可URL/code交換→Bot Token/chat.postMessage送信/チャンネル列挙・参加/受付文面生成)。旧Webhook送信も後方互換で残置
│           └── webpush.py     ← Web Push 送信
│
├── frontend/                  ← Next.js フロントエンド
│   ├── app/
│   │   ├── layout.tsx         ← ルートレイアウト (Google Fonts 等)
│   │   ├── page.tsx           ← / → /login リダイレクト
│   │   ├── login/page.tsx     ← ログイン画面
│   │   ├── ops-console/page.tsx ← 運営ログイン（隠しURL）
│   │   ├── partner-portal/page.tsx ← 代理店ログイン（隠しURL）
│   │   ├── operator/          ← 運営画面 (operator JWT 必須)
│   │   │   ├── page.tsx       ← 運営ダッシュボード
│   │   │   └── reception/page.tsx ← 受付ログ（クロステナント）
│   │   └── [tenant]/          ← テナント別ルート (slug でテナント識別)
│   │       ├── layout.tsx     ← テナントレイアウト
│   │       ├── admin/         ← 管理画面 (JWT 必須)
│   │       │   ├── page.tsx           ← ダッシュボード (KPI・デバイス状態・受付ログ)
│   │       │   ├── media/page.tsx     ← メディア管理 (アップロード・一覧)
│   │       │   ├── playlists/page.tsx ← プレイリスト管理
│   │       │   ├── schedules/page.tsx ← スケジュール管理
│   │       │   ├── kiosk/page.tsx     ← キオスク端末管理・承認待ち端末の承認・端末名/場所の変更(鉛筆ボタン or ダブルクリック)
│   │       │   ├── reception/page.tsx ← 受付ログ一覧・フィルター・受付/電話/お断り応答ボタン
│   │       │   ├── inquiries/page.tsx ← 共通問い合わせフォーム受信の閲覧・状態更新・削除
│   │       │   ├── appointments/page.tsx ← 来社予定管理・QRコード発行 (qrcode.react) + 日付/ステータスフィルタ + 会議室紐付け
│   │       │   ├── meeting-rooms/page.tsx ← 会議室管理 (CRUD・カラー・定員・場所)
│   │       │   ├── kiosk-settings/page.tsx ← 受付設定 (キオスク文言・ロゴ配置ドラッグ)
│   │       │   ├── settings/page.tsx  ← 基本設定 (ブランディング: ロゴ・カラー・フォント)
│   │       │   ├── notify/page.tsx    ← 通知設定 (Slack=OAuth「Slackに追加」/Chatwork/PWA/カスタムWebhook + 配達専用通知先: Slack/Chatwork/Webhook/プッシュON-OFF)
│   │       │   ├── locker/page.tsx    ← ロッカー管理
│   │       │   ├── users/page.tsx     ← テナント内ユーザー管理
│   │       │   └── profile/page.tsx   ← 管理者プロフィール（メール変更・パスワード変更）
│   │       ├── reseller/      ← 代理店画面 (reseller JWT 必須)
│   │       │   ├── page.tsx           ← 代理店ダッシュボード
│   │       │   ├── customers/page.tsx ← 顧客管理
│   │       │   ├── users/page.tsx     ← ユーザー管理
│   │       │   ├── devices/page.tsx   ← デバイス管理
│   │       │   ├── reception/page.tsx ← 代理店クロステナント受付ログ
│   │       │   ├── profile/page.tsx   ← 代理店プロフィール
│   │       │   └── settings/page.tsx  ← 代理店テナント設定
│   │       ├── inquiry/page.tsx ← 共通問い合わせフォーム(公開・認証不要)。お断り画面のQRリンク先
│   │       └── kiosk/         ← キオスク受付画面 (デバイストークン必須)
│   │           ├── page.tsx           ← KioskFlow マウント
│   │           ├── KioskFlow.tsx      ← メインキオスクコンポーネント (全画面遷移管理)
│   │           ├── setup/page.tsx     ← 旧PIN入力画面(廃止)。/kiosk へリダイレクトするだけ
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

## ロール設計（3ティア）

| role | 説明 | ログイン画面 | ログイン後URL |
|---|---|---|---|
| `operator` | 運営（クロステナント全権）| `/ops-console`（隠しURL）| `/operator` |
| `reseller` | 代理店（自管理テナント群）| `/partner-portal`（隠しURL、代理店ID＋PW）| `/{reseller_slug}/reseller` |
| `admin` | 利用者・管理者（自テナント）| `/login`（利用者専用ページ）| `/{tenant}/admin` |
| `staff` | 利用者・スタッフ | `/login`（利用者専用ページ）| `/{tenant}/admin` |
| `kiosk` | キオスクデバイス | 自己登録→管理画面で承認 | - |

### ログインエンドポイント分割
- `POST /auth/login` — 利用者（admin/staff）
- `POST /auth/operator/login` — 運営（operator）
- `POST /auth/reseller/login` — 代理店（reseller_id=スラッグ + password）

### フロントエンドルート
- `/ops-console` — 運営ログイン（隠しURL）
- `/partner-portal` — 代理店ログイン（隠しURL）
- `/operator` — 運営ダッシュボード（OperatorShell）
- `/operator/tenants` — 全テナント管理
- `/operator/resellers` — 代理店管理
- `/operator/users` — 全ユーザー管理
- `/operator/devices` — 全デバイス管理
- `/operator/broadcast` — 緊急配信
- `/operator/reception` — 受付ログ（クロステナント）
- `/{tenant}/reseller` — 代理店ダッシュボード（ResellerShell）
- `/{tenant}/reseller/customers` — 顧客管理
- `/{tenant}/reseller/users` — ユーザー管理
- `/{tenant}/reseller/devices` — デバイス管理
- `/{tenant}/admin` — 既存利用者管理画面（変更なし）
- `/{tenant}/admin/users` — テナント内ユーザー管理
- `/{tenant}/admin/profile` — 管理者プロフィール（メール変更・パスワード変更）
- `/{tenant}/reseller/reception` — 代理店クロステナント受付ログ
- `/{tenant}/reseller/profile` — 代理店プロフィール
- `/{tenant}/reseller/settings` — 代理店テナント設定

### 新規 API エンドポイント
- `GET/POST /operator/stats|tenants|resellers|users|devices|broadcast`
- `GET/POST /reseller/stats|customers|devices|users`
- `GET /operator/reception` — クロステナント受付ログ
- `POST /operator/tenants/{id}/proxy-login` — 代理ログイン
- `GET|POST|DELETE|PATCH /users` — テナント内ユーザー管理
- `POST /operator/tenants/{id}/suspend` — テナント停止/再開
- `POST /devices/{id}/force-refresh` — デバイス強制更新
- `GET /reception/export.csv` — 受付ログCSVエクスポート（管理者）
- `GET /operator/reception/export.csv` — 受付ログCSVエクスポート（運営）
- `GET /reseller/reception/export.csv` — 受付ログCSVエクスポート（代理店）
- `GET /reseller/reception` — 代理店クロステナント受付ログ
- `PATCH /reception/{id}` — 受付ログのステータス・スタッフメモ更新 (body: `{ state?, staff_notes? }`)
- `POST /reception/{id}/decision` — 受付応答 (JWT)。body `{ decision: accept|phone|decline }` → state を `accepted`/`phone`/`declined` に更新。管理画面「受付ログ」のアプリ内3ボタン(受付/電話/お断り)用（iOS PWA は通知アクション非対応のためのフォールバック兼・全端末共通経路）
- `POST /reception/decision` — 受付応答 (**認証なし・署名トークン**)。body `{ token, decision: accept|phone|decline }`。スタッフPWAの Service Worker が通知アクションボタン（受付/電話/お断り）から、JWTを持たずに応答するための経路。token は `services/auth.create_decision_token`（JWT HS256, type=decision, 2h）
- `POST /inquiries/public/{slug}` — mokuture共通問い合わせフォーム送信 (**認証なし**, rate-limit 10/min)。body `{ name, company?, email?, phone?, message }`。キオスク「営業お断り」画面が案内する共通フォームの受け皿
- `GET /inquiries` — 問い合わせ一覧 (JWT, `state`/`date_from`/`date_to` フィルタ)。`PATCH /inquiries/{id}`(state 更新)・`DELETE /inquiries/{id}` も管理者用
- `GET /kiosk/reception/{id}` — 受付のスタッフ応答結果(state) 取得 (デバイストークン)。キオスク「お待ちください」画面が 2.5s 間隔でポーリングして OK/NG 画面へ切替する
- `_apply_decision` は冪等：既に accepted/declined の受付は上書きしない（通知ボタン＋アプリ内ボタンの二重タップでも安全）
- `PATCH /users/me/password` — 自分のパスワード変更
- `POST /users/{id}/reset-password` — 管理者によるパスワードリセット
- `GET /settings/stats` — テナント統計（受付件数・デバイス数等）
- `DELETE /reception/bulk` — 受付ログ一括削除（管理者）
- `GET /users/me` — 自分のプロフィール取得
- `PATCH /users/me` — 自分のプロフィール更新（名前等）
- `POST /reseller/customers/{id}/proxy-login` — 代理店による顧客テナントへの代理ログイン
- `PATCH /operator/tenants/{id}/notes` — 運営によるテナントメモ更新
- `GET /reseller/reception/daily-stats` — 代理店向け受付日次統計（過去14日）

### フロントエンド機能
- 受付ログ自動更新（Auto-refresh）: 管理画面 `/reception` および運営画面 `/operator/reception` に ON/OFF トグル付き自動更新機能（`setInterval` ポーリング）を実装
- 受付OK/NG応答: 管理画面「受付ログ」の未応答行(received/notified)に「すぐ伺います」「只今対応できません」ボタン(`DecisionButtons`)を表示し `api.decideReception` を呼ぶ。ステータス `accepted`(対応中)/`declined`(対応不可) を `STATUS_LABEL`/`STATUS_COLOR`・フィルタに追加。
- Web Push: スタッフPWAの Service Worker(`public/sw.js`)は受付プッシュ(`kind==="reception_decision"`)に 受付/電話/お断り アクションボタンを表示し、通知タップ(`accept`/`phone`/`decline`)で署名トークン付き `POST /reception/decision` を送る。iOS PWA は通知アクション非対応のため上記アプリ内ボタンがフォールバック。
- Web Push 通知本体タップ→対応モーダル直起動: プッシュ payload の `data.url` は `/{tenant_id}/admin/reception?respond={log.id}`(`build_decision_push_extras`)。通知**本体**をタップすると受付ログ画面が該当受付の対応モーダル(`RespondModal`: 大型の 受付/電話/お断り ボタン)を自動で開く。SW `notificationclick` は既に受付ログ画面が開いていれば `/admin/reception` サフィックスで捕捉して focus + `postMessage({type:'FOCUS_RECEPTION', logId})`、無ければ `?respond=` 付きURLで `openWindow`。受付ログ画面は マウント時の `?respond=` 読取＋SW message 購読の両経路で `respondId` を立て、手元に無ければ即時リフレッシュしてモーダルを表示。通知アクション非対応端末(iOS PWA)の主要導線。
- ログイン(`login`/`partner-portal`/`ops-console`): 全入力欄に `name`/`id`/`autoComplete`(username / current-password、新規登録時は new-password) を付与し Chrome のパスワード保存/自動入力に対応。`login` の「ログイン状態を保持」チェックは既定ON(localStorage 保存)。JWT refresh は 30日(`jwt_refresh_expire_days`)＝この期間ログイン維持。401 時は `lib/api.ts` が refresh で自動更新。
- 問い合わせ管理: 管理画面「問い合わせ」(`/{tenant}/admin/inquiries`)で共通フォーム受信を閲覧・既読/対応済み/削除。公開入力ページは `/{tenant}/inquiry`(認証不要, `app/[tenant]/inquiry/page.tsx`)。

---

## セキュリティ設計

### ログインURL隠蔽
- 運営・代理店のログインページURLは `/login` に表示しない
- 運営: `/ops-console`（推測困難な内部URL）
- 代理店: `/partner-portal`

### 代理ログイン（Proxy Login）
- 運営は `POST /operator/tenants/{id}/proxy-login` で対象テナントの管理者JWTを取得
- 発行されるJWTの有効期限は15分（通常の24時間より短い）
- フロントエンドは一時キー（`mk_proxy_*`）でlocalStorageに保存し、新タブで管理画面を開く
- 管理画面マウント時にプロキシキーを消費して通常セッションとして引き継ぐ

### ログインページ類似不具合の横断確認

ログインページのいずれかで認証・チェックボックス・トークン保存に関するバグを修正した場合、**必ず他の全ログインページを確認し、類似の不具合がないか調べること。**

ログインページ一覧:
- `app/login/page.tsx` — 利用者ログイン
- `app/partner-portal/page.tsx` — 代理店ログイン
- `app/ops-console/page.tsx` — 運営ログイン

### テナント停止
- 運営は `PATCH /operator/tenants/{id}/suspend` でテナントを停止/再開
- 停止中のテナントのキオスクは `GET /kiosk/schedule` でメンテナンスレスポンスを受け取る
- 停止中テナントの公開設定（`GET /settings/public/{slug}`）にも `is_suspended: true` が含まれる

---

## DB スキーマ概要 (主要テーブル)

### tenants
テナント設定を全て保持。キオスク設定もここに集約。

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| slug | VARCHAR(64) | URL識別子 (ユニーク) |
| name | VARCHAR(255) | テナント名 |
| is_reseller | BOOLEAN | 代理店テナントフラグ |
| reseller_id | VARCHAR(36) | 親代理店テナントFK (nullable) |
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
| kiosk_style | VARCHAR(32) | （廃止予定・常に `default`）旧・業種別テーマID。テーマ機能廃止により UI からは選択不可。`ALLOWED_KIOSK_STYLES = {"default"}` |
| is_suspended | BOOLEAN | テナント停止フラグ |
| operator_notes | TEXT | 運営用内部メモ (nullable) |
| kiosk_phone_number | VARCHAR(32) | 受付応答「電話(対応不可)」時にキオスクへ表示する電話番号 (nullable) |
| inquiry_form_url | VARCHAR(512) | 「お断り」時に案内する外部問い合わせフォームURL (nullable、未設定時は共通フォーム `/{slug}/inquiry`) |

> `kiosk_phone_number` / `inquiry_form_url` は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS.tenants`)で追加。`GET /settings/public/{slug}` は解決済みの `inquiry_url`(外部 or 共通フォーム)＋`inquiry_qr`(SVG data URI, `segno` で生成)＋`kiosk_phone_number` を返す。

### devices (追加カラム)

| カラム | 型 | 説明 |
|---|---|---|
| force_update_at | TIMESTAMP | 強制更新フラグ（NULLでない場合キオスクがリロード）|

### その他テーブル
- **users** — email / password_hash / role / tenant_id
- **media** — アップロードファイル (URL, mime_type, duration_sec)
- **playlists / playlist_items** — メディアのプレイリスト（transition_type: fade/slide/zoom/wipe/random）
- **schedules** — 曜日・時間帯ごとのプレイリスト割当
- **devices** — キオスク端末 (token, **status**=`pending`承認待ち/`active`承認済み, **hardware_id**=物理端末の安定ID(冪等な再登録用) nullable, last_seen_at, force_update_at)。PIN列は廃止。status/hardware_id は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS`)で追加。既存端末は `active` で埋まる
- **lockers** — ロッカー (door_number=gpio_pin, state, **name**=表示ラベル, **pin_hash**=bcrypt(4桁PIN) nullable, **occupied**=利用中フラグ, **occupied_at**)
- **reception_logs** — 受付ログ (visitor_name, company, staff, purpose, method, **state**, staff_notes, appointment_id, **decided_at**)。`state`: `received | notified | accepted(受付=参ります) | phone(電話=対応不可・電話番号案内) | declined(お断り=営業お断り+フォーム案内) | completed | cancelled`。`decided_at`=スタッフが応答した時刻(nullable)。state/decided_at は素の型でDB制約なし＝カラム追加は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS`)で対応済み
- **inquiries** — mokuture 共通問い合わせフォーム受信 (tenant_id, name, company, email, phone, message, **state**=`new|read|archived`, created_at)。公開送信 `POST /inquiries/public/{slug}`、管理閲覧 `GET /inquiries`。キオスク「営業お断り」画面が案内する共通フォーム(`/{slug}/inquiry`)の受け皿。テーブルは起動時 `create_all` で自動作成
- **visitor_appointments** — 来社予定 (visitor_name, company, staff, purpose, scheduled_at, token, status: pending|received|expired, meeting_room_id FK nullable)
- **meeting_rooms** — 会議室 (name, location, capacity, color, description, is_active, **map_image_url**=館内マップ画像URL nullable)
- **notification_settings** — 通知先設定 (Fernet 暗号化, `type` で種別)。受付: `slack`/`chatwork`/`webhook`/`vapid`。配達専用: `slack_delivery`/`chatwork_delivery`/`webhook_delivery`(未設定時は受付用にフォールバック)、`push_delivery`(`{enabled}` プッシュ通知ON/OFF, 既定ON)。**`slack`(受付)は OAuth 連携で `{team_id, team_name, bot_access_token, bot_user_id, channel_id, channel_name, auth_method:"bot", created_at, updated_at}` を暗号化保存**(専用テーブルは作らず既存 row を拡張＝マイグレーション不要)。`bot_access_token` は API レスポンス・ログに一切出さない。旧・手入力 `{webhook_url}` の row も送信は後方互換で動く(`SlackNotifier.send_to_config` が bot/webhook を自動判別)
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
| PATCH | /playlists/{id} | JWT | プレイリスト名・transition_type更新 |
| GET/POST/DELETE | /schedules | JWT | スケジュール CRUD |
| GET/POST/DELETE | /devices | JWT | デバイス CRUD |
| PATCH | /devices/{id} | JWT | 端末名・場所の変更 (name 1〜100文字, location nullable) |
| POST | /devices/{id}/approve | JWT | 承認待ち端末を承認(status=active)して起動可能にする |
| GET | /kiosk/schedule | デバイストークン | 現在のプレイリスト取得。`device_name`(最新の端末名)も返し、キオスク/エージェントが名前をライブ同期する。承認待ち端末には `{pending:true, ...}` を返す(suspended と同様の短絡) |
| POST | /kiosk/reception | デバイストークン | 受付フォーム送信 (appointment_id 対応)。応答は `{id,...}` を返し、キオスクは id を待機画面のポーリングに使う |
| GET | /kiosk/reception/{id} | デバイストークン | 受付のスタッフ応答結果 `{id, state}` を返す。待機画面のポーリング用 |
| GET | /kiosk/appointment/{token} | デバイストークン | QR トークンから来社予定取得 (scheduled_at + meeting_room{name,location,map_image_url}\|null を含む) |
| POST | /kiosk/register | なし | 端末の自己登録。`{tenant_slug, device_name?, location?, hardware_id?}` → 承認待ち(status=pending)の Device を作成し `{device_token, device_name, status}` を返す。(tenant_slug, hardware_id) 一致時は再作成せず既存トークン+statusを返す(冪等)。rate-limit 20/min |
| GET | /kiosk/status | デバイストークン | 承認状態 `{status, device_name}` を返す。承認待ち画面がポーリングして active になったら起動する |
| GET | /appointments | JWT | 来社予定一覧 (status/date_from/date_to フィルタ対応) |
| POST | /appointments | JWT | 来社予定作成 (meeting_room_id 対応) |
| PATCH | /appointments/{id} | JWT | 来社予定更新 (meeting_room_id 対応) |
| DELETE | /appointments/{id} | JWT | 来社予定削除 |
| GET | /meeting-rooms | JWT | 会議室一覧 (active_only フィルタ) |
| POST | /meeting-rooms | JWT | 会議室作成 (map_image_url 対応) |
| POST | /meeting-rooms/map-upload-url | JWT | 館内マップ画像 Presigned URL 取得 (logo-upload と同形式) |
| PATCH | /meeting-rooms/{id} | JWT | 会議室更新 (map_image_url 対応) |
| DELETE | /meeting-rooms/{id} | JWT | 会議室削除 |
| GET | /reception | JWT | 受付ログ一覧 |
| POST | /inquiries/public/{slug} | なし | 共通問い合わせフォーム送信 (rate-limit 10/min) |
| GET/PATCH/DELETE | /inquiries | JWT | 問い合わせ閲覧・状態更新・削除 |
| GET/PATCH | /notifications | JWT | 通知設定 |
| GET | /notifications/slack | JWT | Slack連携状態 `{enabled, connected, channel_configured, team_name, channel_name, channel_id, auth_method, connected_at}`。**bot_access_token は返さない** |
| GET | /notifications/slack/oauth/url | JWT | Slack認可URLを返す `{enabled, authorize_url?}`。SPAが `window.location` で遷移。署名state(tenant紐付, TTL10分)を埋め込む。env未設定時 `{enabled:false}` |
| GET | /notifications/slack/callback | なし | Slackのリダイレクト受け口(SLACK_REDIRECT_URI)。**未認証＝tenantは署名stateで特定**。code交換→**Bot Token**を暗号化保存(チャンネルは未確定)→`{web}/{slug}/admin/notify?slack=connected\|denied\|error` へ302リダイレクト |
| GET | /notifications/slack/channels | JWT | 通知先候補チャンネル一覧 `{channels:[{id,name,is_private,is_member}]}`(`conversations.list`, 公開=channels:read/非公開=groups:read)。管理画面のチャンネル選択用 |
| POST | /notifications/slack/channel | JWT | 通知先チャンネル確定 `{channel_id}`。`conversations.info`で名称取得＋公開ch未参加なら`conversations.join`→`{channel_id, channel_name}`保存→`{ok, channel_name}` |
| POST | /notifications/slack/disconnect | JWT | Slack連携解除(type=slack の row 削除。Bot Token 破棄) |
| GET/POST | /lockers | JWT | ロッカー管理 (name 永続化, occupied/has_pin 返却) |
| GET | /kiosk/lockers | デバイストークン | ロッカー一覧 `{lockers:[{id,name,door_number,occupied,has_pin}], available_count}` |
| POST | /kiosk/lockers/{id}/occupy | デバイストークン | 空き→PIN設定 `{pin:4桁}`→`{ok}`。409 already occupied / 422 |
| POST | /kiosk/lockers/{id}/release | デバイストークン | 利用中→PIN照合 `{pin}`→`{ok,door_number}`。403 invalid pin / 409 not occupied |
| POST | /kiosk/lockers/{id}/occupy-delivery | デバイストークン | 置き配: 空き→**ランダム4桁PINを自動生成**して施錠(occupied=true, pin_hash=bcrypt)→担当者へ「どのロッカーにこのPINで置き配」を通知(Slack/WebPush/Webhook/Chatwork, delivery系優先)→`{ok}`。PINは配達員に非表示・通知経由でスタッフが受取。409 already occupied。**通知は `BackgroundTasks` でレスポンス送出後に並行送信**(`_fire_delivery_notifications`, 新DBセッション)＝遅い/無効な通知先でも応答をブロックせずエージェントのタイムアウトを防ぐ |
| POST | /kiosk/call-staff | デバイストークン | 配達の呼び出し: 担当者へ「どの端末(device.name)から呼び出し」を通知 `{message?}`→`{ok}`。Slack/WebPush/Webhook/Chatwork (best-effort)。WebPush は `push_delivery` 設定 (`{enabled}`, 既定ON) で ON/OFF 可。**通知は非ブロック(BackgroundTasks, `_fire_delivery_notifications`)** |
| POST | /lockers/{id}/open | JWT | ロッカー開錠 |

---

## 重要な実装ルール

### マルチテナント分離
- **全 DB クエリに `tenant_id` フィルタを必ずつけること。**
- `get_current_user` が JWT から `user.tenant_id` を取得し、各エンドポイントで `WHERE tenant_id = user.tenant_id` を適用。
- キオスク公開 API (`/kiosk/*`) はデバイストークンで `tenant_id` を解決。

### キオスク デザイン（単一デザインに統一）

**業種別テーマ機能は廃止済み。** キオスクは磯野木工所の和モダン（moss green アクセント）単一デザインに統一。
`kiosk.html` 内の各画面は単一のデザイントークン定数 `T`（`bg/canvas/ink/sub/muted/dark/idleBg/urgent` 等）と
`ST.brand_color`（アクセント）でレンダリングする。テーマビルダー（`buildIdle_XXX` / `*_TEMPLATES` / `FORM_THEMES` / `QR_THEMES` 等）は存在しない。

- `kiosk_style` カラムは DB に残存するが UI からは選択不可（`ALLOWED_KIOSK_STYLES = {"default"}`）。
- `kioskStyles.ts` は `default`（和モダン）1エントリのみ。

### 端末セットアップ（承認フロー・PIN 廃止）

**PIN は廃止。** キオスク端末は接続時に自己登録し、管理画面での承認で起動する。

- **device 版 (`kiosk.html` / agent)**: boot 時にトークンが無ければ agent `POST /register`（backend `POST /kiosk/register` へ `tenant_slug`+ホスト名+`hardware_id` を送信）→ トークンを `device_state.json` と localStorage に保存。status=pending なら `showPending()`（承認待ち画面）を表示し `GET /proxy/status`(→`/kiosk/status`) を **4s間隔でポーリング**、active になったら `location.reload()` で通常起動。agent の `/register` は既にトークンがあれば再登録せず現在の status を返す（冪等）。
- **Web 版 (`frontend/app/[tenant]/kiosk/page.tsx`)**: トークンが無ければ `api.registerKioskDevice({tenant_slug, hardware_id})`（hardware_id は localStorage に保存する `web-<uuid>`）。pending なら承認待ち画面＋`api.getKioskStatus` を 4s ポーリング、active で `KioskFlow` を描画。`setup/page.tsx`（旧PIN入力）は `/kiosk` へリダイレクトするだけ。
- **管理画面 (`admin/kiosk/page.tsx`)**: 端末一覧を 15s ごとに自動更新。`status==="pending"` の端末を「承認待ちの端末」セクションに表示し「承認する」(`api.approveDevice`→`POST /devices/{id}/approve`)で active に。不要な端末は「削除」で消す（拒否ボタンは無し）。端末名/場所は承認後に鉛筆ボタンで編集。
- **仮名**: 自己登録時の端末名はホスト名（Web版は「新しい端末」）。承認後に鉛筆ボタンで正式名称に変更する。

### キオスク画面（device 版 `kiosk_agent/static/kiosk.html`）
画面遷移フロー（`go(screen, data)` で管理）:

```
idle ──(人感センサー PIR / タップ)──▶ welcome(統合QR画面: 左=QRカメラ常時 / 右=案内＋「ご予約のない方はこちら」)
  welcome: QR検出(予約) → calling,  「こちら」ボタン → top(受付メニュー 3タイル)
  top: ご訪問 → reception(フォーム),  荷物の配達 → delivery,  ロッカー → lockerMode(保管/受取) → locker
  reception(フォーム・用件5択) → calling(お待ちください)
  calling ──(スタッフ応答)──▶ resultOk(受付) / resultPhone(電話) / resultDecline(お断り) / complete(予約マップ)
  各結果 ──▶ idle
```
※旧・独立QR画面(`showQr`)は `showWelcome` に統合して**廃止**。QR専用画面 `go("qr")` は無い。

**受付応答フロー（受付/電話/お断り）**（`showCalling` @ kiosk.html）— スタッフ側の3択応答をキオスクに反映:
- 受付送信で受け取った `receptionId` を `go("calling", {receptionId})` に渡す。`calling`(=「お待ちください」画面)は `GET /proxy/reception/{id}`(→backend `GET /kiosk/reception/{id}`) を **2.5s間隔でポーリング**する。
- **応答は来訪者ではなく「通知を受けたスタッフ」が押す**。プッシュ通知アクション or 管理画面「受付ログ」の3ボタン(`DecisionButtons`)。backend `_normalize_decision`/`_apply_decision` が state を `accepted`/`phone`/`declined` に更新(いずれも確定＝冪等、上書き不可)。
  - **受付(accepted)** → `showResultOk`「参りますので少々お待ちください」。予約(QR)で会議室マップがある場合は歓迎画面(`showComplete`)で案内。
  - **電話(phone)** → `showResultPhone`。管理画面設定の電話番号(`ST.kiosk_phone_number`)を大きく表示し「対応不可のため、こちらへお電話ください」。
  - **お断り(declined)** → `showResultDecline`「営業・セールス等のご訪問はご遠慮…」＋問い合わせフォールQR(`ST.inquiry_qr`)を表示。
- **通知ボタンは method 別**: QR予約(`method="appointment"`)は 受付/電話 の2択、非QR(form/qr)は 受付/電話/お断り の3択(`build_decision_push_extras`)。push は `sw.js` が `accept`/`phone`/`decline` を署名トークンで `POST /reception/decision`。
- **無応答フォールバック**: 90s で中立の歓迎画面(`showComplete`)→idle に復帰。受付ID が無い旧経路は数秒で `complete`。
- MOCK: `mockFetch` は受付ごとに `accepted`→`phone`→`declined` を巡回して返し、3つの結果画面をオフラインで確認できる。

- **idle**: 人感センサー（`GET /device/pir` を 700ms ポーリング）で来訪検知 → `welcome`(統合QR画面) へ自動遷移。タッチCTAは非表示（PIR非搭載/開発環境向けに画面タップでも遷移可）。画面は屋号(ロゴ/welcome_message)・タグラインのみ。signage メディアがあれば再生。
- **welcome（統合QRようこそ画面・`showWelcome`）**: 待機解除後の最初の画面。**左=QRカメラ常時スキャン**(BarcodeDetector→jsQR fallback、`parseQR`で `appt:<token>`/`name`付きURLのみ受付、未対応/エラーは `pauseScan`でクールダウン)、**右=案内＋「ご予約のない方はこちら →」ボタン**。QR検出→`/proxy/reception`送信して `calling` へ。「こちら」→ `top`。カメラは `disposed`/`stopStream` で離脱時に確実に解放。旧・独立QR画面(`showQr`)はここに統合済み。
- **top（受付メニュー）**: `ご訪問 / 荷物の配達 / ロッカー` の3タイル（日英併記・大型）。`welcome` の「こちら」から到達。ご訪問→`reception`、配達→`delivery`、ロッカー→`lockerMode`。
- **delivery（荷物の配達・Phase3実装済み）**: `showDelivery`。配達方法を選択 — **置き配**(空きロッカーへ施錠。空きが無ければ選択不可。空きロッカー選択→`pulseLocker`でGPIO開錠→「扉を閉めました」→`/proxy/lockers/{id}/occupy-delivery`。**backendがランダム4桁PINを自動生成してbcrypt保存し、「どのロッカーにこのPINで置き配された」を担当者へ通知**。配達員にはPINを表示しない) / **呼び出し**(`/proxy/call-staff`→担当者へ「どの端末から呼び出しか(device.name)」をSlack/WebPush/Webhook/Chatwork通知)。置き配ロッカーはPIN付き(`has_pin:true`)＝通常の「利用中」ロッカーとして扱われ、スタッフが通知で受け取ったPINでロッカー画面から解錠して受取。
- **lockerMode（ロッカー入口・`showLockerMode`）**: ロッカータイルの直後。**手荷物一時保管**(store: 空き=PIN未設定ロッカーのみ→`showLocker("store")`) / **荷物受け取り**(pickup: PIN設定済ロッカーのみ→`showLocker("pickup")`) を選ぶ。戻る→`top`。
- **locker（ロッカー・`showLocker(mode)`）**: モードでグリッドを絞り込む。store=`!occupied` のみ表示→`openEmpty`→4桁PIN設定(`/proxy/lockers/{id}/occupy`)。pickup=`occupied && has_pin` のみ表示→4桁PIN入力(`/proxy/lockers/{id}/release`)→照合OKでGPIO開錠。クリックは**絞込後の `shownLockers`** をインデックスする。該当0件は空状態メッセージ。戻る→`lockerMode`(mode時)。PINは backend で bcrypt 保存。扉開閉センサーが無いため閉扉は手動ボタン（センサー導入時は自動化可）。
  - **GPIO設定の注意**: kiosk は `POST /device/locker/{door_number}/open` を叩くため、kiosk_agent の `LOCKER_PINS_JSON` は **door_number(=GPIOピン番号)をキー**にすること。例: `{"17":17,"18":18,"19":19}`。
  - **ドアセンサー連動の自動施錠 (`main.py` `_open_with_autolock`)**: 電気ストライク(通電ON=解錠 / 無通電OFF=施錠位置)向け。`/device/locker/{id}/open` は該当ロッカーに**ドアセンサーが設定されていれば**、解錠通電→**扉が開いたら即無通電化**(以後は閉扉でラッチが自動施錠)する経路(`{state:"opening", autolock:true}` を即返す=非ブロック)に入る。開錠パルス長や「扉を閉めました」操作のタイミングに依存せず確実に施錠できる。**有効化には `DOOR_PINS_JSON` のキーを door_number(=`LOCKER_PINS_JSON` のキー)と一致**させること。ドアセンサー未設定のロッカーは従来の固定パルス(`LOCKER_PULSE_SEC`)にフォールバック。開錠通電の保持上限は `LOCKER_OPEN_WINDOW_SEC`(既定12s)。
- **モック方針（実機ハードのみ最小スタブ／バックエンドは常に実経路）**: MOCKは「処理ルートごと本番と分ける」のではなく、**実機でしか動かないハードだけ**を最小限スタブする。バックエンド通信（`/proxy/*`）は開発機でも常に実経路を通す。
  - **ハードのモック（agent 層）**: GPIO(ロッカーリレー/PIR/ドア)・カメラ/マイク状態・音量・WiFi は agent が自動モックする。`main.py` の `_MOCK_DEVICE`(=**非Linux で自動 True**、`MOCK_GPIO=true` でも)と `gpio.py`(`gpiozero` 不在時 `_MOCK=True`)が担当。→ Windows開発機でも `/device/*` は落ちずモック値を返す。
  - **ブラウザは常に実経路**: `kiosk.html` は `/proxy/*`=実バックエンド、`/device/*`=agent(ハード or モック)を叩く。`/config` の旧 `mock` フラグ／`config.kiosk_mock` は**廃止**（ブラウザ全スタブの自動有効化はしない）。
  - **開発機での確認手順**: `kiosk_agent/.env` に `TENANT_SLUG` と到達可能な `REMOTE_API_URL`(既定=本番) を設定 → `uvicorn main:app` → `http://localhost:8080` → 自己登録 → 管理画面で承認。**これで管理画面の実データ(会議室 `map_image_url` 等)がそのまま表示される**。QRはWebカメラがあれば読取（PIRはタップで代替可）。
  - **通知だけは MOCK でも実経路（`_isRealNotifyPath`）**: mock でも「通知を発火する呼び出し」＝`/proxy/reception`（受付通知）・`/proxy/reception/{id}`（OK/NG応答ポーリング）・`/proxy/call-staff`（配達呼び出し）・`/proxy/lockers/{id}/occupy-delivery`（置き配通知）は**実バックエンドを叩く**（`apiFetch` が `_realFetch` を優先）。実トークンが無ければ `_ensureRealToken` が agent 経由で `/register` して取得。到達可能な agent/バックエンドが無い（完全オフライン）場合のみ mock にフォールバックしてUIプレビューを維持。→ **mock で見た目を確認しつつ、スマホへの実プッシュ通知もテストできる**。`bootMock` は既存の実トークンを温存する。MOCKバッジは「通知のみ実送信」と明記。
  - **完全オフラインプレビュー（`?mock=1`・明示オプトイン＋記憶）**: `kiosk.html?mock=1` で `mockFetch` が（上記の通知系を除く）APIをスタブし、バックエンド/agent 無しで全画面フローを確認できる。**一度 `?mock=1` を付けると localStorage(`mokuture_kiosk_mock`) に記憶し、以降はパラメータ無しでもモックのまま起動**（ローカルUIプレビューで毎回付けなくてよい）。解除は `?mock=0`。**環境(ホスト名等)による自動有効化はしない**（＝過去の「mockが実データを握りつぶす」不具合を回避）—あくまで明示オプトインの記憶で、常時表示のMOCKバッジで状態が一目で分かる。この時のみ有効:
    - MOCKロッカー: A/C=空き、B=利用中(解錠PIN `1234`)。QR画面の「（MOCK）予約QRを読み取ったことにする」で歓迎画面＋館内マップを確認可。
    - **固定ダミーデータ**: `mockFetch` は管理画面設定を参照せず固定値を返す。`/proxy/appointment/*` は常に「（MOCK）商談ルーム A / 2階」＋組み込みSVG地図＝**管理画面の地図とは一致しない**（仕様。実データ確認は上記の実経路手順で）。
    - **MOCKバッジ**: `showMockBadge()`(`bootMock` で呼ぶ)が上部中央に固定の「MOCK モード…」バッジを常時表示し、ダミー表示だと一目で分かる（`body`直下・`pointer-events:none`で操作を妨げない）。通常起動(実経路)では出ない。
- **reception（フォーム・`showReception`）**: OS標準ソフトキーボード前提の1画面。お名前(必須)/会社名/担当者名 は上半分2列。**ご用件は5択の選択形式**(チップ: 管理画面 `purpose_list` があればそれ、無ければ既定「ご予約のあるお客様/お打ち合わせ/納品/採用面接/その他」)＋注記「※営業・セールス・勧誘等のご訪問はお受けしておりません」。チップ選択は `form.purpose` 更新＋チップのスタイルのみ差し替え（テキスト入力を再描画しない）。送信→`method:"form"` で `calling`。
- **QR読取**: `welcome`(統合)に統合。`parseQR()` は **`appt:<token>` / `name` パラメータ付きURLのみ受付**、未対応/エラーは `pauseScan()` でメッセージ＋クールダウン。`scanLoop` は ≈8fps 間引き、`getUserMedia` は `disposed` フラグで teardown ガード。
- **resultPhone（電話案内・`showResultPhone`）**: スタッフ「電話(対応不可)」応答時。`ST.kiosk_phone_number` を大きく表示（未設定時は「受付までお声がけください」）。一定時間で idle 復帰。
- **resultDecline（営業お断り・`showResultDecline`）**: スタッフ「お断り」応答時。「営業・セールス等の…ご協力をお願いいたします」＋「お問い合わせフォームよりお願いいたします。受付でのお取次ぎは行っておりません」＋`ST.inquiry_qr`(SVG data URI, backend生成) の問い合わせフォールQRを表示。未生成時はURL文字列で代替。一定時間で idle 復帰。
- **complete（歓迎画面「お待ちしておりました」）**: 氏名と「様」を同サイズでインライン表示。予約情報を拡大表示。QR受付で行き先（会議室）が確定し、かつその会議室に `map_image_url` が登録されている場合のみ館内マップを表示（`go("calling"/"complete", { name, staff, room, scheduledAt, method })` でデータを伝搬）。
- **キオスク設定（スタッフ専用・`showKioskSettings`）**: 画面**左上＋右上の同時タッチ**（または `Ctrl+Shift+M`）で開く。上部の**タブで「設定」/「デバイスチェック」を切替**（統合済み）。
  - **設定タブ**: 音量スライダー＋サウンドON/OFF（タップ音/チャイム/音声ガイダンス, `/device/volume`）、Wi-Fi（`/device/wifi/networks|connect|toggle`）、ロッカーの鍵 全解除（`/proxy/lockers/open-all`）、フッター端末名の**5連タップで再登録**。
  - **デバイスチェックタブ**: `getUserMedia` による**カメラ・ライブプレビュー**、Web Audio(AnalyserNode) の**マイク音量レベルメーター**、`GET /device/status`（1.2s ポーリング）に基づく **PIR/ドア/電子錠を緑(ON/正常)・赤(OFF/異常)のトグル表示**（電子錠トグルは `POST /device/locker/{id}/state`、開錠テストは `/pulse`。委譲クリックで捕捉）。旧 device-control の「DEVICE」情報パネルは非表示。カメラ/マイクのストリーム・AudioContext・rAF・ポーリングは画面離脱/タブ切替で確実に停止（**世代トークン `dcGen`** で teardown 後に解決した in-flight `getUserMedia` も解放）。
  - 旧・独立ページ `static/device-control.html`（`GET /device-control`）はメンテ用に残存（統合により通常運用では不要）。
- `KioskScaler` 相当の `rescale()` が 1920×1080 固定を `transform: scale()` でフィット。`PublicTenantSettings` は `/proxy/settings` 経由で取得。
- Web 版キオスク `frontend/app/[tenant]/kiosk/KioskFlow.tsx` は別実装（簡易フォーム）。本仕様変更は device 版 `kiosk.html` を対象とする。

### 「戻る」ボタンの配置ルール（キオスク・管理画面 共通）

**キオスク (`kiosk.html`)**: 「← 戻る」ボタンは **必ずページ最上部・コンテンツグリッドの外側**に配置する。
- ラッパー: `<div style="padding:28px 80px 0;flex-shrink:0">`
- ボタンスタイル（**タッチ操作用に大型化。全画面で統一すること**）: `display:inline-flex;align-items:center;gap:14px;padding:24px 52px;background:${T.canvas};border:2px solid ${T.borderStrong};border-radius:999px;font-size:32px;font-weight:600;color:${T.sub};cursor:pointer`
- **コンテンツグリッド内（左右どちらの列にも）配置しないこと。**
- キオスクはタッチ操作端末のため、来訪者が押すボタン・文字は指で押しやすい大きさを保つ（戻るボタン=font-size:32px を基準）。

```html
<!-- ✅ 正しい配置 -->
<div style="width:1920px;height:1080px;...display:flex;flex-direction:column">
  <div style="padding:28px 80px 0;flex-shrink:0">
    <button id="xxx-back" style="display:inline-flex;align-items:center;gap:14px;padding:24px 52px;background:${T.canvas};border:2px solid ${T.borderStrong};border-radius:999px;font-size:32px;font-weight:600;color:${T.sub};cursor:pointer">← 戻る</button>
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
- 運用メニューに **問い合わせ**(`inquiries`)を追加（`AdminShell` の `NavId`/`NAV_OPS`/`NAV_PATHS`/`NavIcon` の4箇所を更新済み）。
- **受付設定(`kiosk-settings`)** に「受付電話番号(`kiosk_phone_number`)」「問い合わせフォームURL(外部・任意, `inquiry_form_url`)」を追加。

### 秘密情報の暗号化
- Slack/Chatwork Webhook URL は `services/crypto.py` (Fernet) で暗号化して DB 保存。
- `ENCRYPTION_KEY` 環境変数が必須。

### Slack OAuth 連携（「Slackに追加」= Bot Token + chat.postMessage）
顧客が Bot Token を手入力せず、Slack を認可して mokuture 側で通知先チャンネルを選ぶだけで連携できる方式。SPA(Netlify)+API(Render) 分離構成に合わせ、仕様書の `/admin/slack/*` を `/api/notifications/slack/*` に読み替えて実装。**Incoming Webhook ではなく Bot Token で `chat.postMessage` 送信する**（チャンネルは認可画面ではなく連携後に mokuture 側で選ぶ）。

- **フロー**: 管理画面「通知設定」の **[Slackに追加]** → `GET /notifications/slack/oauth/url`(JWT) が署名state付き認可URLを返す(scope=`chat:write,channels:read,groups:read,channels:join`) → SPA が `window.location` で Slack へ遷移 → 顧客が許可 → Slack が `GET /notifications/slack/callback`(未認証) へリダイレクト → `SlackNotifier.exchange_code`(`oauth.v2.access`) で **Bot Token(`bot_access_token`,`bot_user_id`,`team`)** を取得・暗号化保存(チャンネル未確定) → `{web}/{slug}/admin/notify?slack=connected` へ302で戻す。管理画面はマウント時に `?slack=` を読んでバナー表示＋`GET /notifications/slack` で状態再取得。
- **チャンネル選択(連携後)**: `connected && !channel_configured` なら管理画面がチャンネル選択UIを表示 → `GET /notifications/slack/channels`(`conversations.list`) → 選択 → `POST /notifications/slack/channel {channel_id}`(公開ch未参加なら`conversations.join`)→ `channel_id/channel_name` 保存。「チャンネル変更」で再選択可。
- **state = 署名JWT(`services/auth.create_slack_state_token`, type=`slack_oauth`, TTL10分, tenant_id + 乱数jti)**。サーバ側セッション保存は不要（state自体がtenant紐付を担保）。callback は未認証だが `verify_slack_state_token` で tenant を特定するためテナント越境不可。無効/期限切れstateは何も更新せず error リダイレクト。
- **保存先は既存 `notification_settings`(type=`slack`) を拡張**（専用テーブルは作らない＝マイグレーション不要）。再連携は上書き（`_upsert_setting`）。旧・手入力 `{webhook_url}` の row も送信は後方互換で動く。
- **送信は `SlackNotifier.send_to_config(config, text)` に集約** — `{bot_access_token, channel_id}` があれば `chat.postMessage`(未参加の公開chは`not_in_channel`時にjoinして1回リトライ)、無ければ旧 `{webhook_url}` にフォールバック。受付(`kiosk._notify_slack`)・配達(`_notify_slack_text`)・テストの全経路が同関数を通る。将来の DM・複数チャンネル・テンプレート・Teams/LINE WORKS 拡張の継ぎ目。
- **セキュリティ**: `bot_access_token` / Client Secret / Webhook URL は**ログ出力・画面表示・APIレスポンス一切なし**。`GET /notifications/slack` は team_name/channel_name 等の非機密のみ返す。**env(SLACK_CLIENT_ID/SECRET/REDIRECT_URI)未設定時は機能無効**(`slack_oauth_enabled`)＝ oauth/url は `{enabled:false}`、callback/channels/channel は 404/400。
- **エラー**: Slack送信失敗でも受付は止めない(best-effort)。失敗は `logger.warning` で残すが**秘密情報は出さない**(exc_infoも付けない)。Bot連携済だがチャンネル未選択の受付は「エラー」ではなく静かにスキップ。テスト通知(`POST /notifications/test/slack`)はチャンネル未選択なら 400 で促す。
- **受付通知文面**(`SlackNotifier.build_reception_message`): `:bell: 来客がありました` + 会社名/お名前 様/訪問先/時刻(JST)。会社名・訪問先は空なら行を省略（最低=お名前+時刻）。
- **Slack App設定**: OAuth&Permissions に `SLACK_REDIRECT_URI` を Redirect URL 登録、Bot Token Scopes に `chat:write`/`channels:read`/`groups:read`/`channels:join`。非公開チャンネルへ通知するには事前に Slack で Bot をそのチャンネルへ招待。連携解除(`POST /notifications/slack/disconnect`)は自テナントの設定削除のみ（Slack側App削除まではPhase1では必須にしない）。

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
PUBLIC_API_URL=https://mokuture-plus-api.onrender.com/api  # プッシュ通知に埋め込む絶対URL(SWがOK/NG応答をPOSTする先)。既定は本番URL
STORAGE_ENDPOINT=...         # R2/MinIO endpoint
STORAGE_ACCESS_KEY=...
STORAGE_SECRET_KEY=...
STORAGE_BUCKET=...
STORAGE_PUBLIC_URL=...

# Slack OAuth（「Slackに追加」= Bot Token + chat.postMessage）。3つ揃わないと機能無効（settings.slack_oauth_enabled）。
# Bot Token Scopes: chat:write / channels:read / groups:read / channels:join
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_REDIRECT_URI=https://mokuture-plus-api.onrender.com/api/notifications/slack/callback
```

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1
```

## ルール
- 修正を行ったら自動でデプロイまで行うこと
- **JavaScriptダイアログ禁止**: `confirm()` / `alert()` / `prompt()` は使用しないこと。確認は独自モーダル、エラーはインライン表示またはトースト通知で実装すること。
- 常に改修後は回収の「意図」通りに修正出来ているかテストエージェントにチェックしてもらってOKを貰ってから報告をする
