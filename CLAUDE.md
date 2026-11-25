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
| DB 本番 | Neon PostgreSQL (Project ID: `bitter-firefly-65136362` = mokuture-plus-usw2, **us-west-2** / Render(oregon)と同居しレイテンシ最小化。2026-07-19 に us-east-1 の旧 `broad-moon-06415649` から pg_dump/restore で移行。旧プロジェクトは切戻し用に当面保持) |

---

## 技術スタック

| レイヤー | 技術 |
|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind CSS |
| Backend | Python 3.11 + FastAPI + SQLAlchemy (async) + asyncpg |
| DB | Neon PostgreSQL (本番) / SQLite (ローカル開発) |
| Storage | Cloudflare R2 / MinIO (S3 互換、Presigned URL) |
| 認証 | JWT HS256 (access + refresh) + bcrypt |
| デプロイ | Frontend → Netlify、Backend → Render (starter・oregon。リポジトリ直下の `Dockerfile` を使う) |

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

**Windows 開発機でキオスクをまとめて起動**: リポジトリ直下の `kiosk-local.bat` をダブルクリック。
音声サービス(8181)→キオスク本体(8080)→ブラウザの順に立ち上げる(起動済みのものは飛ばす)。
終了は「mokuture voice」「mokuture kiosk」の2つの窓を閉じる。`kiosk-local.bat nobrowser` でブラウザを開かない。
本体は `127.0.0.1` で待ち受ける(同じ PC からだけ開ける)。`uv run` ではなく `.venv` の python を直接使う。
`.bat` は **CRLF・UTF-8(BOM なし)** で保存する(LF だと `goto` のラベルが効かなくなる)。

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
├── ANALYTICS.md               ← 分析ログ(実証実験・製品改善)の設計書。イベント一覧・語彙・稼働率の定義
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
│       │   ├── events.py      ← /events/stream (SSE: 管理画面の受付/ロッカー ニアリアルタイム連動)
│       │   ├── analytics.py   ← /analytics/* (分析ログ: 端末からの投入 + 運営の参照/CSV出力)
│       │   ├── notifications.py ← /notifications (Slack/Chatwork 設定)
│       │   ├── staff_routes.py ← /notifications/staff-routes (担当者ごとの通知先・代理通知の設定)
│       │   ├── calendar_integration.py ← /integrations/google-calendar (Google カレンダー連携: OAuth・カレンダー一覧・設定・今すぐ同期・解除)
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
│       │   ├── analytics.py   ← ReceptionSession/ReceptionEvent/DeviceEvent/DeviceMetric (匿名・個人情報の列は無い)
│       │   ├── notification.py ← NotificationSetting, PushSubscription
│       │   ├── staff_route.py  ← StaffNotificationRoute (担当者ごとの通知先・代理通知先)
│       │   └── calendar_integration.py ← CalendarIntegration (Google カレンダー連携・テナントに1行) / CalendarEventTombstone (削除の後始末)
│       ├── middleware/
│       │   └── tenant.py      ← JWT 検証・テナント分離 (get_current_user)
│       └── services/
│           ├── auth.py        ← JWT 生成・検証
│           ├── crypto.py      ← Fernet 暗号化 (Slack URL 等の秘密情報)
│           ├── storage.py     ← R2/MinIO Presigned URL 生成
│           ├── slack.py       ← SlackNotifier(OAuth認可URL/code交換→Bot Token/chat.postMessage送信/チャンネル列挙・参加/受付文面生成)。旧Webhook送信も後方互換で残置
│           ├── events.py      ← テナント単位の in-memory pub/sub (SSE 管理画面ニアリアルタイム連動)。単一ワーカー前提
│           ├── analytics.py   ← 分析ログの受信・集計・未終了セッションのスイープ
│           ├── analytics_vocab.py ← 分析ログの固定語彙(イベント名/画面ID/エラーコード)。analytics.js と一致させる
│           ├── analytics_link.py  ← 受付ログID→匿名セッションID の**プロセス内 TTL マップ**(永続化しない)
│           ├── webpush.py     ← Web Push 送信
│           ├── google_calendar.py ← Google カレンダー連携(OAuth・トークン更新・来社予定の書き出し/取り込み・定期同期ループ)。httpx で REST を直接呼ぶ(SDK 不使用)
│           ├── teams.py       ← Microsoft Teams 通知(「ワークフロー」の Webhook へ Adaptive Card を POST・URL の確認・来訪者の入力の無害化 `escape_md`)
│           ├── decision_link.py ← ログイン無しで返事できるリンク(メール・Teams 用。`/{slug}/respond#token=…`)
│           └── email.py       ← SMTP メール送信(aiosmtplib, best-effort)。来社予定QRのメール送信(segno で QR PNG 生成→CIDインライン画像+添付)。SMTP未設定なら送信APIが 503
│
├── frontend/                  ← Next.js フロントエンド
│   ├── app/
│   │   ├── layout.tsx         ← ルートレイアウト (Google Fonts 等)
│   │   ├── page.tsx           ← / → /login リダイレクト
│   │   ├── login/page.tsx     ← ログイン画面
│   │   ├── ops-console/page.tsx ← 運営ログイン（隠しURL）
│   │   ├── partner-portal/page.tsx ← 代理店ログイン（隠しURL）
│   │   ├── google-calendar/callback/page.tsx ← Google カレンダー連携の戻り先(GOOGLE_REDIRECT_URI)。ログイン中の管理者の JWT でコードを API へ渡して連携を仕上げる
│   │   ├── privacy/page.tsx   ← プライバシーポリシー(公開・ログイン不要。Google の OAuth 同意画面の「プライバシー ポリシー」リンク先。運営者=株式会社ラナソフト)
│   │   ├── terms/page.tsx     ← 利用規約(公開。同意画面の「利用規約」リンク先)。2つの枠は components/LegalPage.tsx
│   │   ├── operator/          ← 運営画面 (operator JWT 必須)
│   │   │   ├── page.tsx       ← 運営ダッシュボード
│   │   │   ├── reception/page.tsx ← 受付ログ（クロステナント）
│   │   │   └── analytics/page.tsx ← 実証実験ログ（匿名セッション一覧・時系列・主要指標・端末稼働率・CSV/JSON出力）
│   │   └── [tenant]/          ← テナント別ルート (slug でテナント識別)
│   │       ├── layout.tsx     ← テナントレイアウト
│   │       ├── admin/         ← 管理画面 (JWT 必須)
│   │       │   ├── page.tsx           ← ダッシュボード (KPI・デバイス状態・受付ログ)
│   │       │   ├── media/page.tsx     ← メディア管理 (アップロード・一覧)
│   │       │   ├── playlists/page.tsx ← プレイリスト管理
│   │       │   ├── schedules/page.tsx ← スケジュール管理
│   │       │   ├── kiosk/page.tsx     ← キオスク端末管理・承認待ち端末の承認・端末名/場所の変更(鉛筆ボタン or ダブルクリック)
│   │       │   ├── reception/page.tsx ← 受付ログ一覧・フィルター・受付/電話/お断り応答ボタン。**一覧は全件を取らず `GET /reception/page` で選んだ期間・条件の1ページぶん(10件)と件数だけを取る**(期間=今日/今週(月曜から)/今月(1日から)/全期間/期間を指定。境目はブラウザの時刻で決めて UTC の時刻で送り、取りに行くたびに計算し直す)。「この条件でCSV出力」も同じ条件(`buildQuery`)
│   │       │   ├── inquiries/page.tsx ← 共通問い合わせフォーム受信の閲覧・状態更新・削除
│   │       │   ├── appointments/page.tsx ← 来社予定管理・QRコード発行 (qrcode.react)。QRは印刷＋PNG画像DL＋メール送信可(表示は鮮明なSVG、DLは非表示の高解像度Canvas1024pxから toDataURL、メールは QRモーダルの「メールで送信」欄に宛先を都度入力→POST /appointments/{id}/send-email)。日付/ステータスフィルタ + 会議室紐付け。審査用デモモード(is_demo)では①〜⑤のQR発行ガイドバルーン(QrGuideBalloon)を表示し、既定会議室=「商談ルーム」を自動選択
│   │       │   ├── meeting-rooms/page.tsx ← 会議室管理 (CRUD・カラー・定員・場所)
│   │       │   ├── calendar/page.tsx  ← カレンダー連携 (Google アカウント1つ・方向=mokuture→Google / Google→mokuture のどちらか・カレンダー選択(マイカレンダー/他のカレンダー)・取り込み条件・同期の状況)
│   │       │   ├── kiosk-settings/page.tsx ← 受付設定 (実機準拠の5画面WYSIWYGプレビュー: 待機/ようこそ/受付メニュー/呼び出し中/完了。文言はプレビュー上を直接クリックしてインライン編集=Canva風、ロゴは受付メニュー画面でドラッグ配置・リサイズ)
│   │       │   ├── settings/page.tsx  ← 基本設定 (ブランディング: ロゴ・カラー・フォント)
│   │       │   ├── notify/page.tsx    ← 通知設定 (Slack=OAuth「Slackに追加」/Chatwork/**Microsoft Teams**/PWA/カスタムWebhook + 配達専用通知先: Slack=共通連携のチャンネル上書き/Webhook/プッシュON-OFF。Chatworkの配達宛先は共通カードのルームそのもの)
│   │       │   ├── locker/page.tsx    ← ロッカー管理
│   │       │   ├── users/page.tsx     ← テナント内ユーザー管理。「メールで招待」=複数アドレスを貼り付けて一括で招待メール(区切りは改行/,/;/、/タブ/空白・「名前 <addr>」可。解析は lib/inviteEmails.ts)＋「招待中」一覧(送り直す/取り消す)。「パスワードを決めて追加」=従来の直接追加
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
│   │       ├── respond/page.tsx ← メール・Teams の受付通知の「受付/電話/お断り」から開く返事の画面(公開・ログイン不要)。`#token=…&via=…&d=…` を読み、開いただけでは何もせず、押したときだけ返事を確定する。→「Microsoft Teams 通知とログイン無しの返事」節
│   │       ├── invite/page.tsx  ← 招待メールのリンク先(公開・認証不要)。`#token=` を読み、パスワードを決めて登録→そのままログインして管理画面へ
│   │       └── kiosk/         ← キオスク受付画面 (デバイストークン必須)
│   │           ├── page.tsx           ← KioskFlow マウント
│   │           ├── KioskFlow.tsx      ← メインキオスクコンポーネント (全画面遷移管理)
│   │           ├── setup/page.tsx     ← 旧PIN入力画面(廃止)。/kiosk へリダイレクトするだけ
│   │           └── top|reception|qr|calling|complete/page.tsx ← 各画面 (KioskFlow へリダイレクト)
│   ├── components/
│   │   ├── AdminShell.tsx     ← 管理画面レイアウト・サイドバーナビ・共通 UI コンポーネント。審査用デモモード時はサイドバー「来社予定」にQR発行ガイド①バルーンを出す(is_demoを自前fetch+mk_isdemo_{tenant}キャッシュ)。汎用 QrGuideBalloon(createPortal+position:fixedで親overflow非依存に任意要素へ吹き出しを固定)をexport
│   │   └── PWAInit.tsx        ← PWA Service Worker 登録
│   └── lib/
│       ├── api.ts             ← API クライアント・全型定義 (TenantSettings 等)。ensureFreshToken/API_BASE を export(SSE 接続用)
│       ├── realtime.ts        ← SSE 購読(EventSource)。受付/ロッカー変化の push を受けて該当リストを即再取得
│       ├── auth.ts            ← JWT トークン管理 (localStorage)
│       └── push.ts            ← Web Push 購読ユーティリティ
│
└── kiosk_agent/               ← Raspberry Pi エージェント (Phase 1)
    ├── main.py                ← メインループ (API ポーリング・GPIO 制御)
    ├── analytics.py           ← 分析ログ: スプール(JSONL)・アップローダ・端末稼働イベント/メトリクス
    ├── sysinfo.py             ← CPU/温度/メモリ/ストレージ/タッチ の取得(標準ライブラリのみ・Linux 実測)
    ├── watchdog.py            ← systemd watchdog + ブラウザ生存確認(分析ログの app_crashed 判定にも使う)
    ├── static/analytics.js    ← キオスク画面の行動ロガー(匿名・IndexedDB 一時保存 + 指数バックオフ再送)
    ├── gpio.py                ← GPIO モック / 実機切り替え
    ├── sync.py                ← バックエンドとのデータ同期
    ├── state.py               ← デバイス状態管理
    ├── kana_kanji.py          ← かな→漢字 変換(辞書ルックアップ+貪欲分割。GET /device/convert)
    ├── kana_dict.tsv          ← 同梱かな漢字辞書(受付語彙, SKKより優先)。kana_kanji.py とともに OTA の配信対象(2026-11-12 追加。SKK-JISYO.L は配らない)
    └── SKK-JISYO.L            ← 全面かな漢字辞書 約13万語(資産として同梱, .gitattributesでバイナリ扱い)
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
- `/operator/analytics` — 実証実験ログ（匿名セッション・端末稼働率。→ [`ANALYTICS.md`](ANALYTICS.md)）
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
- `PATCH /operator/tenants/{id}/suspend` — テナント停止/再開
- `PATCH /operator/tenants/{id}/monitor` — モニター(受付完了後のアンケートを出すテナント)の ON/OFF。body `{monitor: bool}`
- `POST /devices/{id}/force-refresh` — デバイス強制更新
- `GET /reception/export.csv` — 受付ログCSVエクスポート（管理者）。`since`/`until`(UTC の時刻・until は含まない)/`state`/`q`/`method` で一覧と同じ絞り込み(条件なし=全件)。日時の列は日本時間
- `GET /operator/reception/export.csv` — 受付ログCSVエクスポート（運営）
- `GET /reseller/reception/export.csv` — 受付ログCSVエクスポート（代理店）
- `GET /reseller/reception` — 代理店クロステナント受付ログ
- `PATCH /reception/{id}` — 受付ログのステータス・スタッフメモ更新 (body: `{ state?, staff_notes? }`)
- `POST /reception/{id}/decision` — 受付応答 (JWT)。body `{ decision: accept|phone|decline }` → state を `accepted`/`phone`/`declined` に更新。管理画面「受付ログ」のアプリ内3ボタン(受付/電話/お断り)用（iOS PWA は通知アクション非対応のためのフォールバック兼・全端末共通経路）
- `POST /reception/decision/lookup` — 返事用の画面(`/{slug}/respond`)が受付の内容を読む (**認証なし・署名トークン・読むだけ**)。body `{ token }` → `{id, tenant_name, tenant_slug, visitor_name, company, staff, department, purpose, method, created_at, state, decided, decided_by_name, decision_expired, actions}`。**何も書き換えない**(メール・Teams のセキュリティ機能がリンクを勝手に開くため)
- `POST /reception/decision` — 受付応答 (**認証なし・署名トークン**)。body `{ token, decision: accept|phone|decline, via? }`(`via`=`push`(既定)/`email`/`teams`。`decided_via` に残る。それ以外は `push` 扱い)。スタッフPWAの Service Worker が通知アクションボタン（受付/電話/お断り）から、JWTを持たずに応答するための経路。token は `services/auth.create_decision_token`（JWT HS256, type=decision, 2h）
- `POST /inquiries/public/{slug}` — mokuture共通問い合わせフォーム送信 (**認証なし**, rate-limit 10/min)。body `{ name, company?, email?, phone?, message }`。キオスク「営業お断り」画面が案内する共通フォームの受け皿
- `GET /inquiries` — 問い合わせ一覧 (JWT, `state`/`date_from`/`date_to` フィルタ)。`PATCH /inquiries/{id}`(state 更新)・`DELETE /inquiries/{id}` も管理者用
- `GET /kiosk/reception/{id}` — 受付のスタッフ応答結果(state) 取得 (デバイストークン)。キオスク「お待ちください」画面が 2.5s 間隔でポーリングして OK/NG 画面へ切替する
- `_apply_decision` は冪等：既に accepted/declined の受付は上書きしない（通知ボタン＋アプリ内ボタンの二重タップでも安全）
- `GET/POST /users/invitations` — 招待の一覧(+`smtp_enabled`/残り通数)・複数アドレスへ一括招待(管理者のみ)。`POST /users/invitations/{id}/resend`・`DELETE /users/invitations/{id}`
- `POST /auth/invitations/lookup|accept` — 招待リンクの照会・登録(認証なし・トークンは本文)
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
- 受付ログ自動更新（Auto-refresh）: 管理画面 `/reception` および運営画面 `/operator/reception` に ON/OFF トグル付き自動更新機能を実装。**管理画面 `/reception`・`/locker` は SSE push でニアリアルタイム連動**(トグル ON 時は `subscribeRealtime` で即再取得＋30秒フォールバックポーリング。詳細は「管理画面のニアリアルタイム連動（SSE push）」節)。`/operator/reception` は従来どおり `setInterval` ポーリング
- 受付OK/NG応答: 管理画面「受付ログ」の未応答行(received/notified)に「すぐ伺います」「只今対応できません」ボタン(`DecisionButtons`)を表示し `api.decideReception` を呼ぶ。ステータス `accepted`(対応中)/`declined`(対応不可) を `STATUS_LABEL`/`STATUS_COLOR`・フィルタに追加。
- 来訪回数(「N回目の来訪」): 受付ログ詳細モーダルは `getVisitorHistory(visitor_name)` で来訪回数を表示するが、**配達(delivery)・置き配(dropoff)は visitor_name が総称ラベル(「配達」「置き配」)に潰れる**ため取得・表示しない(宅配業者に「4回目の来訪」等の無意味表示を避ける)。
- Web Push: スタッフPWAの Service Worker(`public/sw.js`)は受付プッシュ(`kind==="reception_decision"`)に 受付/電話/お断り アクションボタンを表示し、通知タップ(`accept`/`phone`/`decline`)で署名トークン付き `POST /reception/decision` を送る。iOS PWA は通知アクション非対応のため上記アプリ内ボタンがフォールバック。
- Web Push 通知本体タップ→対応モーダル直起動: プッシュ payload の `data.url` は `/{tenant_id}/admin/reception?respond={log.id}`(`build_decision_push_extras`)。通知**本体**をタップすると受付ログ画面が該当受付の対応モーダル(`RespondModal`: 大型の 受付/電話/お断り ボタン)を自動で開く。SW `notificationclick` は既に受付ログ画面が開いていれば `/admin/reception` サフィックスで捕捉して focus + `postMessage({type:'FOCUS_RECEPTION', logId})`、無ければ `?respond=` 付きURLで `openWindow`。受付ログ画面は マウント時の `?respond=` 読取＋SW message 購読の両経路で `respondId` を立て、その受付を一覧とは別に手元(`focusLogs`)に持ってモーダルを表示(いまのページ・期間に無ければ `GET /reception/{id}` で1件だけ読む。一覧の条件から外れてもモーダルは消えない)。通知アクション非対応端末(iOS PWA)の主要導線。
- Web Push 置き配通知タップ→**詳細モーダル**直起動: 置き配(dropoff)は応答不要なので対応ボタンは付けず、通知タップで**受付詳細モーダル(`ReceptionDetailModal`)を開き解錠PINを大きく表示**する(受付応答通知が `RespondModal` を開くのと同じ導線)。置き配プッシュの payload は `kind="delivery_dropoff"`/`logId`/`url=/{tenant_id}/admin/reception?detail={log.id}`(`_fire_delivery_notifications` の `dropoff_log_id` 経由。`_log_delivery_dropoff` が受付ログ id を返す)。SW `notificationclick` は `delivery_dropoff` も `/admin/reception` サフィックスで既存タブを捕捉し `postMessage({type:'FOCUS_DETAIL', logId})`、無ければ `?detail=` 付きURLで `openWindow`。受付ログ画面は マウント時の `?detail=` 読取＋SW `FOCUS_DETAIL` 購読で `detailId` を立て、`ReceptionDetailModal` を表示(行クリックの `selectedLog` と同じモーダル。`method==="dropoff"` のとき `purpose` の「解錠PIN: XXXX」を正規表現で抜き出し上部に大きく表示)。
- ログイン(`login`/`partner-portal`/`ops-console`): 全入力欄に `name`/`id`/`autoComplete`(username / current-password、新規登録時は new-password) を付与し Chrome のパスワード保存/自動入力に対応。`login` の「ログイン状態を保持」チェックは既定ON(localStorage 保存)。アクセストークンは60分(`jwt_access_expire_minutes`)、JWT refresh は 30日(`jwt_refresh_expire_days`)＝この期間ログイン維持。**起動高速化**: `lib/api.ts` はアクセストークンの `exp` を**ローカルで先読み**し、失効(間近)なら叩く前に先に refresh する（ホーム画面ショートカット起動時の「叩く→401→refresh→再叩き」の無駄な往復を削減。米国サーバーへの1往復≈140ms×余分回数を消す）。先読みで漏れた場合は従来どおり401で自動更新。**セッション切れの扱いは `lib/api.ts` に集約**: refresh トークンが無い、または `/auth/refresh` が 401/403 のときだけ「セッションが切れた」と確定し、保存情報を消して役割に合ったログイン画面(`/login`・運営 `/ops-console`・代理店 `/partner-portal`)へ `location.replace` で移る（その通信の Promise は解決させない＝エラーを一瞬も出さない）。通信断・デプロイ中の 5xx ではログアウトさせず「サーバーに接続できません。…」を投げる（**この文言に「セッション」を入れない**＝ダッシュボードはこの語でログアウトさせる）。各画面の catch で `clearTokens()`＋`/login` へ飛ばさないこと（ここに来るのは一時的な失敗だけ）。**ダッシュボード(`admin/page.tsx`)は前回統計を `mk_stats_{tenant}` にキャッシュし stale-while-revalidate で即描画**（起動時の空白待ちを体感ゼロに）。ネットワーク一時失敗ではログアウトせずキャッシュ表示を維持し、真のセッション切れ時のみ `/login` へ。**起動ゲート(`app/page.tsx`=`/`)**: PWAショートカット起動が約10秒かかっていた主因は、ログイン済みでも `/ → /login(Reactをhydrate) → window.location.assign(ハード遷移) → /{tenant}/admin` と「アプリを2回フル起動」していたこと。対策として `/` を **hydration 前に走るインラインscriptの軽量ゲート**(`export const dynamic="force-static"`)にし、localStorageを同期読みしてログイン済みなら **/login を素通りして直接** `/{tenant}/admin`(operator=`/operator`/reseller=`/{slug}/reseller`)へ `location.replace`。**判定分岐は `lib/auth.ts` の `getHomeUrl` と一致させること**(変更時は両方直す)。`/login` の自動リダイレクトも `window.location.assign`→`router.replace`(ソフト遷移)に変更（ハード遷移=iOSパスワード保存目的はログインsubmit直後のみ）。SW(`public/sw.js`)は起動ゲート `/` のみ **cache-first+背景更新**(ゲートはチャンクを実行せず即離脱するので stale でも安全＝起動時のネット往復を消す)、遷移先ページは network-first 維持でチャンク不整合を防ぐ。
- 問い合わせ管理: 管理画面「問い合わせ」(`/{tenant}/admin/inquiries`)で共通フォーム受信を閲覧・既読/対応済み/削除。公開入力ページは `/{tenant}/inquiry`(認証不要, `app/[tenant]/inquiry/page.tsx`)。

---

## セキュリティ設計

### ログインURL隠蔽
- 運営・代理店のログインページURLは `/login` に表示しない
- 運営: `/ops-console`（推測困難な内部URL）
- 代理店: `/partner-portal`

### 代理ログイン（Proxy Login）
- 運営は `POST /operator/tenants/{id}/proxy-login` で対象テナントの管理者JWTを取得
- 発行されるJWTの有効期限は15分（通常の60分より短い）
- 代理店の代理ログイン（`POST /reseller/customers/{id}/proxy-login`）も同じ（15分・refresh なし。応答の `refresh_token` は空文字）
- **代理ログインの画面は、開いたタブの中だけで完結する**（`lib/auth.ts`）。開く側は受け渡し用の一時キー（`mk_proxy_access` / `mk_proxy_tenant` / `mk_proxy_expires`＝60秒）を localStorage に置き、新しいタブ（`?proxy=1`）の `ProxyLoginHandler` が**子を描画する前に**それを消費して sessionStorage へ移す（`mk_proxy_session=1`）。代理のトークンを localStorage に書かないので、運営・代理店自身のログインは上書きされない。15分で切れたらそのタブに「有効時間が切れました」と出すだけで、ログイン画面へは飛ばさない
- 別タブはクリック直後に（通信の前に）開いておく。通信のあとに開くとブラウザに止められ、一時キーが残る
- 代理ログイン中は、顧客の管理者のパスワードを変えられない（トークンの `proxy` クレームで判定・403）

### 権限・認証・通知まわりの決まり（2026-11-13 に一括で入れた。崩さないこと）

**backend**
- **設定を変える操作は管理者だけ**: 端末（追加・承認・名前変更・強制更新・削除）、基本設定・受付設定・ロゴ、メディア/プレイリスト/スケジュールの書き込み、会議室の書き込み、受付ログの削除と CSV 出力、問い合わせの削除は `require_tenant_admin()`（`middleware/tenant.py`）。スタッフができるのは 閲覧・受付への応答・受付メモ・来社予定の操作・問い合わせの状態変更・自分のプロフィール。**新しい書き込み API を足すときは、スタッフにも許すかを必ず決めてから付ける**
- **端末 API は承認済みの端末だけ**: `get_kiosk_device` は承認前の端末と停止中テナントを 403 で断る。承認前でも要るもの（状態確認・ハートビート・スケジュール・更新の配信・分析ログの取り込み）だけ `get_kiosk_device_any_status` を使う。**401 は「トークンが無効＝登録し直す」の合図なので、ここで 401 を返さないこと**
- **端末の再登録**: 登録済みの端末が `POST /kiosk/register` を呼ぶとき、今のトークンを `X-Kiosk-Token` で添えていれば同じトークンを返す。添えていなければ新しいトークンを発行して**承認待ちに戻す**（管理画面で承認し直す）
- **メールアドレスは全ユーザーで重複不可**（大文字小文字を区別しない。`services/accounts.py`）。DB の一意制約はまだ無い（既存データの確認が先）
- **パスワードを変えると、それより前に発行したトークンは使えなくなる**（`users.password_changed_at` とトークンの `iat` を比べる）。自分で変えたときは応答に新しいトークンが入り、画面がそれを保存する
- **ログインは、同じIDで10分に8回失敗すると10分受け付けない**（`services/login_throttle.py`・プロセス内）。メール送信（来社予定QR・テスト送信）はテナントごとに1時間30通まで（`services/mail_quota.py`）。どちらもプロセス内なので、ワーカーを増やすなら置き場所を変える
- **回数制限の単位にする接続元**は `services/ratelimit.py` の `client_ip` に一本化（Render の背後なので `X-Forwarded-For` を見る。`TRUST_FORWARDED_FOR`）
- **外へ送る URL（カスタム Webhook）は https かつ公開のホストだけ**（`services/url_safety.py`）。保存時と送信直前の両方で確かめ、送信時にだめなら飛ばして「失敗」に数える（受付の通知全体は止めない）。プッシュの購読先は既知のプッシュサービスのホストだけ
- **通知文面に入れる来訪者の入力は必ず通知先ごとに無害化する**: Slack は `slack.escape_mrkdwn`、Chatwork は `chatwork.escape_tags`。同じ文字列を使い回さず、通知先ごとに元の値から作る（二重に変換しない）
- **CSV は `services/csv_safe.py` の `safe_row` を通す**（表計算ソフトで式として解釈される先頭文字を無害化）
- **設定の取得 API は秘密をそのまま返さない**: カスタム Webhook の URL は `***` で返し、`***` のまま保存されたら元の値を保つ
- **SSE は使い捨てのチケットでつなぐ**: `POST /events/ticket` → `GET /events/stream?ticket=…`（60秒）。`?token=` は画面と backend の配備がずれる間の移行用で、いずれ外す
- **本番（SQLite 以外）で JWT・暗号化の鍵が既定値のままなら起動しない**（`main._refuse_insecure_defaults`）
- **テナントの slug に使えない語**: `login` `operator` `ops-console` `partner-portal` `api` `_next` `admin` `kiosk` `inquiry` `static` `google-calendar` `privacy` `terms`
- **保存先の URL**（ロゴ・メディア・会議室の地図）は自分のストレージのものだけ（`storage.is_own_storage_url`）

**端末エージェント・キオスク画面**
- **エージェントは端末自身のブラウザからの要求だけ受ける**（ループバック以外は 403。`mokuture-kiosk.service` も 127.0.0.1 で待つ）。別の機器から叩く必要があるときだけ `KIOSK_ALLOW_REMOTE=1` を付け、待ち受けアドレスも変える（サービスファイルは OTA で届かないので、既設の端末は `install.sh` をやり直すまで待ち受けは 0.0.0.0 のまま。その間もエージェント側で断る）
- **扉が閉まっていない空きロッカーは、預け入れ・置き配で開けない**（一覧では「扉が開いています」と出て選べない・声でも選べない・端末側も 409）。`GET /device/locker-list` の `door_closed` は true=閉 / false=開 / null=分からない。**「開」を信じるのは、その扉で一度でも「閉」を読めたことがあるときだけ**（センサーをつないでいない入力は常に「開」と読めるため。`locker_state.json` の `doors_seen_closed` に覚える。設定画面でロッカーの口数を選び直すと覚えは消える＝センサーが壊れて口が使えなくなったときの戻し方）。受け取り（利用中の口）と全解除は扉の状態にかかわらず開けられる
- **受け取りは、錠を実際に動かせたときだけ空きに戻す**（`POST /device/locker/{id}/release` が 暗証番号の確認→解錠→記録の消去 を1回で行う。動かせなければ 503 で利用中のまま、画面は「担当者を呼ぶ」を案内）。実機で GPIO が模擬に落ちているときも 503。全解除だけは、錠を動かせなくても記録を消す（動かせなかった扉を `failed` で返す）
- **保留中の置き配通知は、送れたと確かめてから1件ずつ外す**（先に取り出して空にしない。暗証番号の平文はこの保留にしか無い）。60秒ごとに再送する
- **暗証番号の数え方**: 10分のうちに5回違えたら、という意味（何日も前の打ち間違いは積み上げない）
- **暗証番号は口ごとに5回続けて違えると5分受け付けない**（429・メモリ上）
- **登録し直しで手元のトークンが使えなくなったら、承認待ち画面でも捨てて登録からやり直す**（握りつぶすと、承認されても抜けられない）
- **錠を「通電のまま」にする操作は30秒で自動的に切れる**
- **更新（OTA）は、配信対象の一覧にあるパスだけ・取り寄せた中身が配信一覧のハッシュと一致したときだけ適用する**。1つでも食い違えばその回は何も適用しない
- スタッフ用設定画面は、3分触らなければ待機画面へ戻る（開くときの PIN はまだ無い）

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
| kiosk_calling_message | VARCHAR(255) | 呼び出し中メッセージ (実配線: `showCalling` 本文) |
| kiosk_complete_message | VARCHAR(255) | 完了画面メッセージ (実配線: `showComplete` の「お待ちしておりました」行) |
| kiosk_menu_title | VARCHAR(255) | 受付メニュー(top)見出し。既定「ご用件をお選びください」 |
| kiosk_welcome_qr_guide | VARCHAR(255) | ようこそ画面のQRカメラ案内文。既定「ご予約QRをお持ちの方はカメラへかざしてください」 |
| kiosk_welcome_form_label | VARCHAR(255) | ようこそ画面のフォームボタン見出し。既定「QRをお持ちでない方はこちら」 |
| kiosk_idle_timeout_sec | INT | 無操作タイムアウト秒数 (10–300) |
| kiosk_complete_timeout_sec | INT | 完了画面表示秒数 (5–60) |
| logo_pos_x | FLOAT | ロゴ X 位置 (0.0–0.9、画面幅比) |
| logo_pos_y | FLOAT | ロゴ Y 位置 (0.0–0.9、画面高比) |
| logo_width_pct | FLOAT | ロゴ幅 (2.0–30.0、画面幅に対する %) |
| kiosk_style | VARCHAR(32) | （廃止予定・常に `default`）旧・業種別テーマID。テーマ機能廃止により UI からは選択不可。`ALLOWED_KIOSK_STYLES = {"default"}` |
| kiosk_default_lang | VARCHAR(8) | キオスクの既定表示言語(`ja`/`en`)。来訪者がタッチで切り替えるまでの既定。`ALLOWED_KIOSK_LANGS = {"ja","en"}`。管理画面「受付設定」で切替 |
| is_suspended | BOOLEAN | テナント停止フラグ |
| is_demo | BOOLEAN | 審査用デモモード（運営パネルで切替） |
| is_monitor | BOOLEAN | モニター（実証実験の協力先）。true のテナントだけキオスクで受付完了後のアンケートを出す。既定 false。**運営パネル「テナント管理」でだけ切り替える**（店舗の管理画面には出さない）。`GET /settings/public/{slug}` の `is_monitor` でキオスクへ渡る（起動時と60秒ごとのスケジュール確認のついでに `is_monitor` だけ読み直す＝1分ほどで反映。起動時に設定を取れなかった端末も後から追いつく）。起動時自動マイグレーションで追加 |
| operator_notes | TEXT | 運営用内部メモ (nullable) |
| kiosk_phone_number | VARCHAR(32) | 受付応答「電話(対応不可)」時にキオスクへ表示する電話番号 (nullable) |
| inquiry_form_url | VARCHAR(512) | 「お断り」時に案内する外部問い合わせフォームURL (nullable、未設定時は共通フォーム `/{slug}/inquiry`) |

> `kiosk_phone_number` / `inquiry_form_url` / `kiosk_menu_title` / `kiosk_welcome_qr_guide` / `kiosk_welcome_form_label` は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS.tenants`)で追加(後者3つは既存行を埋める DEFAULT 付き)。`GET /settings/public/{slug}` は解決済みの `inquiry_url`(外部 or 共通フォーム)＋`inquiry_qr`(SVG data URI, `segno` で生成)＋`kiosk_phone_number` を返す。

### devices (追加カラム)

| カラム | 型 | 説明 |
|---|---|---|
| force_update_at | TIMESTAMP | 強制更新フラグ（NULLでない場合キオスクがリロード）|
| locker_state_json | TEXT | ローカルファースト・ロッカーの占有スナップショット(端末ごと・表示専用)。agent が best-effort でミラーした `[{id,door_number,name,occupied,has_pin,kind}]`。PIN本体は含まない。管理画面 `GET /lockers/status` の表示元 |
| locker_state_at | TIMESTAMP | 上記スナップショットの最終ミラー時刻(UTC naive) |
| current_playlist_id | VARCHAR(36) | 現在配信中のプレイリストID。`GET /kiosk/schedule` が配信解決時に記録(変化時のみ)。管理画面「キオスク端末」詳細の「現在のプレイリスト」に名前解決して表示。停止/承認待ち/スケジュール無しでは NULL にクリア |
| agent_version | VARCHAR(32) | 端末エージェント版数。`POST /kiosk/heartbeat` の body で受信し保存(管理画面詳細の「バージョン」) |
| ip_address | VARCHAR(64) | 端末が報告する LAN IP。heartbeat body で受信(管理画面詳細の「IPアドレス」) |
| os_version | VARCHAR(64) | 端末の OS 版数。分析ログの端末イベント/メトリクスから最新値をミラー |
| ui_version | VARCHAR(32) | キオスク画面(kiosk.html)の版数ラベル。同上 |
| last_boot_at | TIMESTAMP | 直近の端末起動時刻。`device_boot`/`device_restart` 受信時に更新 |
| online_since | TIMESTAMP(UTC naive) | 連続オンライン開始時刻。`get_kiosk_device` が last_seen 更新時に維持(前回接続から3分超の空白でリセット)。管理画面の「連続稼働」= now − online_since(online な端末のみ表示) |

> 上記のうち `current_playlist_id`(当初からモデルに存在)・`agent_version`・`ip_address`・`online_since` は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS.devices`)で追加。**heartbeat は任意 body**(`{version, ip}`)で、旧エージェント(body 無し)とも後方互換(422 にならない)。日時列は本番 Neon で timestamptz として aware に読み戻るため、シリアライズは `iso_z()` で単一 Z 化、`online_since` の差分計算は naive-UTC へ揃えてから行う(→[[naive-timestamp-tz-gotcha]] 相当)。

### その他テーブル
- **users** — email / password_hash / role / tenant_id
- **user_invitations** — 管理画面から送った招待(tenant_id, email, role, **token_hash**=リンクのトークンの sha256・平文は持たない, invited_by, sent_at, expires_at=送ってから7日, accepted_at)。`accepted_at IS NULL` が「招待中」。起動時 `create_all` で作成。→「ユーザー招待」節
- **media** — アップロードファイル (URL, mime_type, duration_sec)
- **playlists / playlist_items** — メディアのプレイリスト（transition_type: fade/slide/zoom/wipe/random）
- **schedules** — 曜日・時間帯ごとのプレイリスト割当
- **devices** — キオスク端末 (token, **status**=`pending`承認待ち/`active`承認済み, **hardware_id**=物理端末の安定ID(冪等な再登録用) nullable, last_seen_at, force_update_at)。PIN列は廃止。status/hardware_id は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS`)で追加。既存端末は `active` で埋まる
- **kiosk_bundle_releases** — OTA で配ったキオスクの中身ごとの版番号(全テナント共通。version=manifest の中身ハッシュ PK, label=`YYMMDD-NNN` unique, first_served_at UTC naive)。起動時の create_all で作成。→「キオスク OTA 配信」節
- **lockers** — ロッカー (door_number=gpio_pin, state, **name**=表示ラベル, **pin_hash**=bcrypt(4桁PIN) nullable, **occupied**=利用中フラグ, **occupied_at**)
- **reception_logs** — 受付ログ (visitor_name, company, staff, **department**(訪問先部署), purpose, method, **state**, staff_notes, appointment_id, **decided_at**)。`department` は来訪者が受付フォームで選んだ訪問先部署(管理画面「受付設定」の `department_list` から選択)。カラム追加は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS.reception_logs`)。受付ログ一覧/詳細・CSV・Slack/Push/Webhook 通知にも `部署` を出す。`state`: `received | notified | accepted(受付=参ります) | phone(電話=対応不可・電話番号案内) | declined(お断り=営業お断り+フォーム案内) | completed | cancelled`。`decided_at`=スタッフが応答した時刻(nullable)。**`escalated_at`**=代理通知(エスカレーション)を送った時刻(nullable)。`escalated_at` は二重送信の防止も兼ねる＝スイーパーが**送信前に先に確定・commit** する。state/decided_at は素の型でDB制約なし＝カラム追加は `main.py` の起動時自動マイグレーション(`_ENSURE_COLUMNS`)で対応済み。`method`: `form | qr | calendar | delivery(配達呼出) | dropoff(置き配)`。**置き配(dropoff)** は `notify-delivery`/`occupy-delivery` が `visitor_name="置き配"`/`company=ロッカーラベル`/`purpose="解錠PIN: XXXX（受付端末: …）"`/`state="completed"` で記録する＝**スタッフが通知を見逃しても管理画面の受付ログから解錠PINを後追いできる**。一時的PIN(受取で端末が破棄し無効化)のため通知本文と同じく平文で載せる(`_log_delivery_dropoff`)。誰かの応答を待つ受付ではないので受付/電話ボタンは出さない
- **inquiries** — mokuture 共通問い合わせフォーム受信 (tenant_id, name, company, email, phone, message, **state**=`new|read|archived`, created_at)。公開送信 `POST /inquiries/public/{slug}`、管理閲覧 `GET /inquiries`。キオスク「営業お断り」画面が案内する共通フォーム(`/{slug}/inquiry`)の受け皿。テーブルは起動時 `create_all` で自動作成
- **visitor_appointments** — 来社予定 (visitor_name, company, staff, purpose, scheduled_at, token, status: pending|received|expired, meeting_room_id FK nullable)。**`scheduled_at` は JST の壁時計(naive)**(管理画面のブラウザ時刻のまま保存。naive-UTC で統一している他の列の例外)。Google カレンダー連携の列: `gcal_event_id`/`gcal_calendar_id`(結び付いたイベント。`(tenant_id, gcal_event_id)` で一意 = `main._ensure_schema` の `ix_appointments_tenant_gcal_event`)、`gcal_origin`("google"=取り込んだ予定 / NULL=mokuture で登録)、`gcal_updated`(イベントの `updated`)、`gcal_sync_state`(pending/synced/error)。起動時自動マイグレーションで追加
- **calendar_integrations** — Google カレンダー連携(テナントに1行 = 連携できるアカウントは1つ)。`credentials_json`(Fernet 暗号化の refresh/access token。**API・ログに出さない**)、`account_email`、`status`(active/reauth_required/disconnected)、`direction`(to_google/from_google)、`calendar_id`/`calendar_name`、`import_keyword`、`import_colors`(取り込む予定の色。`"default,5,11"`・空=色で絞らない。起動時自動マイグレーションで追加)、`default_staff`、`last_synced_at`/`last_error`/`last_error_at`。起動時 `create_all` で作成
- **calendar_event_tombstones** — 来社予定を消したときの Google 側の後始末。`kind="delete"`=書き出し中に消した予定のイベントを消す(消せるまで残る・定期同期が拾い直す)、`kind="ignore"`=取り込んだ予定を mokuture で消した(次から取り込まない。日時を過ぎたら掃除)
- **meeting_rooms** — 会議室 (name, location, capacity, color, description, is_active, **map_image_url**=館内マップ画像URL nullable)
- **notification_settings** — 通知先設定 (Fernet 暗号化, `type` で種別)。受付: `slack`/`chatwork`/`webhook`/**`teams`**(`{webhook_url}`=Teams の「ワークフロー」の URL。受付と配達の両方の宛先。GET では `***`)。**VAPID 鍵は全テナント共通の1組(Render の `VAPID_PRIVATE_KEY`/`VAPID_PUBLIC_KEY`)で、DB には持たない。2026-10-24 にテナントごとの `vapid`/`webpush` 行・鍵の生成/再生成 API とボタン・旧鍵の購読を全廃した。共通鍵を作り直すと全テナントの全購読が無効になる**。配達専用: `slack_delivery`/`webhook_delivery`(未設定時は受付用にフォールバック)、`push_delivery`(`{enabled}` プッシュ通知ON/OFF, 既定ON)。**`slack`(受付)は OAuth 連携で `{team_id, team_name, bot_access_token, bot_user_id, channel_id, channel_name, auth_method:"bot", created_at, updated_at}` を暗号化保存**(専用テーブルは作らず既存 row を拡張＝マイグレーション不要)。`bot_access_token` は API レスポンス・ログに一切出さない。旧・手入力 `{webhook_url}` の row も送信は後方互換で動く(`SlackNotifier.send_to_config` が bot/webhook を自動判別)。**2026-10-24: 配達専用に別のSlack/Chatwork連携を結ばせる仕組みを廃止した**（通常の通知先と配達の通知先で、それぞれSlack/Chatworkに二重で連携させるのが無駄だったため）。`slack_delivery` は配達専用の**チャンネル上書きのみ**(`{channel_id, channel_name, updated_at}`、Bot Token は複製せず共通の `slack` 連携を使い回す。`POST /notifications/slack/channel` に `target="slack_delivery"` を渡して設定。未設定/解除時は受付と同じ共通チャンネルへ。`SlackNotifier.resolve_delivery_config(base, override)` が合成)。旧形式(`slack_delivery` が自前の `webhook_url` を持つ行)はそのまま後方互換で動く。Chatworkは元から共通 `chatwork` 行のルームが配達専用の宛先だった(受付通知には使われない)ので、専用の `chatwork_delivery` 書き込み/テストendpointを削除しただけ(読み取りのフォールバックは残置し、既存の旧形式データも動き続ける)
- **staff_notification_routes** — **訪問先担当者ごとの通知先と代理通知設定**。`(tenant_id, staff_name)` で一意(`main.py` の起動時に `CREATE UNIQUE INDEX IF NOT EXISTS ix_staff_routes_tenant_staff`)。`staff_name` は `tenants.staff_list`(キオスクの訪問先ドロップダウン) の1件＝`reception_logs.staff` と突き合わせる。宛先は `config_json`(Fernet 暗号化)に `{slack_channel_id, slack_channel_name, chatwork_room_id, email, webhook_url, teams_webhook_url}` と、列 `push_user_id`(→`users.id`。Web Push を届ける管理ユーザー。購読はブラウザ＝ユーザーに紐づくため、担当者(ただの名前)とここで結びつける。NULL=従来どおり共通の購読へ)。**`webhook_url`・`teams_webhook_url` は API レスポンスに出さない**(`webhook_configured`/`teams_configured` の真偽だけ)＝CLAUDE.md「秘密情報」方針。`include_default`(既定 true)=テナント共通の通知先(Slack/Webhook/**プッシュ**)へも送るか、`fallback_staff_name`=応答が無いときに転送する代理担当者(**1段のみ・連鎖しない**)、`escalate_after_sec`(既定 60、0=代理通知しない、30〜3600)。**行が無い担当者は従来どおり共通の通知先だけ**(後方互換)。テーブルは起動時 `create_all` で自動作成
- **push_subscriptions** — Web Push 購読情報

### 分析ログ（実証実験・製品改善）— 詳細は [`ANALYTICS.md`](ANALYTICS.md)

**個人情報の列を持たない**（氏名・会社名・担当者・入力値・IPアドレス等の置き場が存在しない）。
自由入力の `metadata` 欄も意図的に作っていない＝保存できる項目はカラム定義がホワイトリスト。
テーブルは起動時 `create_all` で自動作成。

- **reception_sessions** — 受付1回ぶんの匿名セッション。`id`=端末が発行する UUIDv4。
  `outcome`(`completed|cancelled|abandoned|timeout|app_error|device_restarted`、NULL=進行中)、
  `entry_method`(`touch|qr|card|voice|smartphone`)、`duration_ms`、`event_count`/`error_count`/
  `screen_count`/`back_count`、`staff_response`(accepted/phone/declined)+`staff_response_ms`、
  アンケート回答 `answer_clarity`/`answer_confidence`/`answer_assistance`(未回答は NULL=unknown)。
  **`reception_logs` とは結び付けない**（`reception_log_id` に相当する列は無い）
- **reception_events** — 行動イベント。**`event_id` が主キー＝再送されても二重登録されない**。
  `sequence_no`(セッション内1始まりの連番)・`client_occurred_at`(端末時刻)・`server_received_at`
  (サーバ受信時刻)を両方持ち、並べ替えは **受信順ではなく** `client_occurred_at, sequence_no`。
  バックエンド発(通知の成否)は `event_source="backend"` / `sequence_no=0`
- **device_events** — 端末稼働イベント(`device_boot`/`device_shutdown`/`device_restart`/
  `agent_started`/`agent_stopped`/`browser_started`/`app_started`/`page_reloaded`/`app_crashed`/
  `online`/`offline`/`network_recovered`/`log_dropped`)。`id` が主キー＝冪等
- **device_metrics** — 端末の定期メトリクス。ハートビート(既定60秒)ごとに1行、5分ごとに
  CPU/温度/メモリ/ストレージも載せる。`app_healthy`/`online`/`interval_sec` が **稼働率の計算元**

---

## API エンドポイント概要

全エンドポイントは `/api` プレフィックス（`config.py` の `api_prefix`。`/v1` は付かない）。

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
| POST | /appointments/{id}/send-email | JWT | 来社予定QRを指定メールへ送信 (body `{email}`・**宛先は保存しない**)。`segno` で `appt:<token>` の QR PNG を生成し CID インライン画像+添付でHTMLメール送信。SMTP未設定(`smtp_enabled=false`)は 503、送信失敗は 502。閲覧専用アカウントも `/appointments/*` は許可 |
| GET | /integrations/google-calendar | JWT(スタッフ可) | Google カレンダー連携の状態 `{enabled, connected, status, account_email, direction, calendar_id, calendar_name, import_keyword, import_colors, event_colors, default_staff, active, last_synced_at, last_error, last_error_at, unsynced_count, staff_list}`。**トークンは返さない** |
| GET | /integrations/google-calendar/oauth/url | JWT(管理者) | Google の認可 URL `{enabled, authorize_url?}`(署名 state・TTL10分・`access_type=offline`+`prompt=consent`)。env 未設定は `{enabled:false}`。**閲覧専用アカウントは 403**(`readonly._RO_BLOCKED_GET`) |
| POST | /integrations/google-calendar/oauth/complete | JWT(管理者) | Google から戻った画面 `/google-calendar/callback`(=GOOGLE_REDIRECT_URI)が `{code, state, error}` を渡して連携を仕上げる → `{result: connected\|denied\|scope\|error\|mismatch}`(画面は `/{slug}/admin/calendar?google=<result>` へ移る)。**state の利用者(連携を始めた管理者)と JWT の利用者が違えば `mismatch` で何もしない**。スコープが欠けていたら保存せず `scope`。アカウントの確認に失敗したら何も変えず `error` |
| GET | /integrations/google-calendar/calendars | JWT(管理者) | 選べるカレンダー `{calendars:[{id,name,primary,access_role,writable,group:"mine"\|"other"}]}`(メイン→マイカレンダー→他のカレンダー順) |
| PUT | /integrations/google-calendar/settings | JWT(管理者) | `{direction, calendar_id, import_keyword?, import_colors?, default_staff?}` を保存して裏で1回同期。`import_colors` は `event_colors` の id だけ(それ以外は 422・全部選ぶと空=絞らない)。書き出しに閲覧だけのカレンダーは 422、担当者は担当者リストの名前だけ。応答に `removed_imports`(取り込み元を変えて消した予定の数) |
| POST | /integrations/google-calendar/sync | JWT(管理者) | 今すぐ同期(終わるまで待つ) → `{result:{pushed,imported,updated,removed,failed,error}, ...状態}` |
| POST | /integrations/google-calendar/disconnect | JWT(管理者) | 解除(Google の revoke を best-effort・トークン破棄・`status=disconnected`)。**カレンダーの予定も来社予定も消さない**。同じアカウントで結び直せば設定を引き継ぐ |
| GET | /meeting-rooms | JWT | 会議室一覧 (active_only フィルタ) |
| POST | /meeting-rooms | JWT | 会議室作成 (map_image_url 対応) |
| POST | /meeting-rooms/map-upload-url | JWT | 館内マップ画像 Presigned URL 取得 (logo-upload と同形式) |
| PATCH | /meeting-rooms/{id} | JWT | 会議室更新 (map_image_url 対応) |
| DELETE | /meeting-rooms/{id} | JWT | 会議室削除 |
| GET | /reception | JWT | 受付ログ一覧(全件。管理画面はもう使っていない・後方互換で残置) |
| GET | /reception/page | JWT | 管理画面「受付ログ」の1ページぶん。`since`/`until`(UTC の時刻)・`q`(氏名/会社名・大文字小文字区別なし)・`method`・`state`・`offset`・`limit`(≤200)・`today_since` → `{items, total(条件に合う件数), all_total, waiting_count(受付済みのまま15分超), unread_today}` |
| GET | /reception/{id} | JWT | 受付ログ1件(自テナントのみ)。**固定パスの GET より後に定義すること** |
| GET | /events/stream | クエリ`token`(access JWT) | **管理画面ニアリアルタイム連動の SSE ストリーム**。受付/ロッカーが変化すると `data: {"type":"reception"\|"locker"}` を push。EventSource はヘッダを送れないため token はクエリで受け接続時に一度だけ検証。ストリームは秘密情報を運ばない(再取得対象の型マーカーのみ)。保持中は DB 接続を握らない・20秒ごとに keepalive コメント |
| POST | /inquiries/public/{slug} | なし | 共通問い合わせフォーム送信 (rate-limit 10/min) |
| GET/PATCH/DELETE | /inquiries | JWT | 問い合わせ閲覧・状態更新・削除 |
| GET/PATCH | /notifications | JWT | 通知設定 |
| GET | /notifications/slack | JWT | Slack連携状態 `{enabled, connected, channel_configured, team_name, channel_name, channel_id, auth_method, connected_at}`。**bot_access_token は返さない** |
| GET | /notifications/slack/oauth/url | JWT | Slack認可URLを返す `{enabled, authorize_url?}`。SPAが `window.location` で遷移。署名state(tenant紐付, TTL10分)を埋め込む。env未設定時 `{enabled:false}` |
| GET | /notifications/slack/callback | なし | Slackのリダイレクト受け口(SLACK_REDIRECT_URI)。**未認証＝tenantは署名stateで特定**。code交換→**Bot Token**を暗号化保存(チャンネルは未確定)→`{web}/{slug}/admin/notify?slack=connected\|denied\|error` へ302リダイレクト |
| GET | /notifications/slack/channels | JWT | 通知先候補チャンネル一覧 `{channels:[{id,name,is_private,is_member}]}`(`conversations.list`, 公開=channels:read/非公開=groups:read)。管理画面のチャンネル選択用 |
| GET | /notifications/slack/users | JWT | **DM先候補の一覧**(issue #1 追記分) `{users:[{id,name}]}`(`users.list`, scope `users:read`)。bot/deleted/Slackbotは除外。旧スコープのトークンは `missing_scope` → 400(「再連携してください」) |
| POST | /notifications/slack/channel | JWT | 通知先を確定。チャンネル=`{channel_id}`(`conversations.info`で名称取得＋公開ch未参加なら`conversations.join`)。**DM=`{user_id, display_name?}`**(`conversations.open`, scope `im:write`。issue #1 追記分)。どちらも`{channel_id, channel_name}`保存→`{ok, channel_name}`(DMは`channel_name="DM: <display_name>"`)。**`target`省略時は`"slack"`(受付の共通チャンネル)。`target="slack_delivery"`は配達専用のチャンネル上書き**(Bot Tokenは複製せず共通連携を使い回す。channel_id/user_idを両方省略すると上書きを解除し受付と同じ共通チャンネルに戻る。2026-10-24追記) |
| POST | /notifications/slack/disconnect | JWT | Slack連携解除(type=slack の row 削除。Bot Token 破棄) |
| POST | /notifications/chatwork/rooms | JWT | **ルーム選択の一覧**(issue #1 2026-10-23 追記分) `{api_token?}`→`{rooms:[{room_id,name,type}]}`(`GET /v2/rooms`)。`api_token`省略時は保存済みの共通トークンを使う。1:1の会話は`type="direct"` |
| GET | /notifications/staff-routes | JWT | **担当者ごとの通知先の一覧**。`{staff_list, routes:[{id,staff_name,slack_channel_id,slack_channel_name,chatwork_room_id,chatwork_room_name,email,webhook_configured,teams_configured,include_default,fallback_staff_name,escalate_after_sec,orphan,updated_at}], slack:{bot_connected,default_channel_name}, chatwork:{connected}, smtp_enabled, default_escalate_sec, min/max_escalate_sec}`。`orphan`=受付設定の担当者リストから消えた担当者(UIで注意表示) |
| PUT | /notifications/staff-routes | JWT | **担当者1人ぶんの通知先を upsert**(担当者名がキー)。`{staff_name, slack_channel_id?, slack_user_id?, slack_display_name?, chatwork_room_id?, chatwork_room_name?, email?, webhook_url?, include_default?, fallback_staff_name?, escalate_after_sec?}`。**`slack_user_id` 指定時は `slack_channel_id` を無視し `conversations.open` でDM先を解決する**(issue #1 追記分)。チャンネル指定は `conversations.info` で名称解決＋公開ch未参加なら `conversations.join`(best-effort)。**`slack_channel_id` が保存済みの値と同じならSlack APIを呼び直さない**(DM先の名称がIDへ戻って壊れるのを防ぐ)。**`webhook_url` は3状態**: 未指定/`null`=変更しない(既存を維持)・`""`=解除・URL=差し替え（**URL は GET で返さない**ので画面が値を持てないため）。**それ以外の項目は省略すると既定値に戻る**(フル置換。画面は常に全項目を送る)。メールはカンマ区切り最大5件で**1件でも形式不正なら 422**(`staff_routing.validate_emails`。保存済みを読む `parse_emails` は寛容)、Webhookは http(s) 必須、`escalate_after_sec` は 0 または 30〜3600、代理に自分自身を指定すると 422。同一担当者への同時 PUT は一意制約違反を拾って既存行の更新にフォールバック |
| DELETE | /notifications/staff-routes/{route_id} | JWT | 担当者ごとの設定を解除(以後は共通の通知先だけに送られる) |
| PUT | /notifications/settings/teams | JWT(管理者) | **Teams の「ワークフロー」の URL(テナント共通)**を保存 `{webhook_url}`(`***`=変更しない・空=解除)。旧方式の Incoming Webhook(`*.webhook.office.com`)とワークフロー以外のホスト(`logic.azure.com`/`powerplatform.com`/`powerautomate.com` 以外)は 400。担当者ごとの URL は `PUT /notifications/staff-routes` の `teams_webhook_url`(`webhook_url` と同じ3状態) |
| POST | /notifications/test/teams | JWT(管理者) | 「Teams」カードの URL へテストのカードを送る → `{ok}`。**ok=ワークフローが受け取った(202)まで**。チャネルに出たかは分からない |
| POST | /notifications/staff-routes/test | JWT | **宛先ごとのテスト送信**。`{staff_name, stage:"primary"|"fallback"}` → `{ok, results:[{channel,target,ok,error?}]}`。**受付ログは作らない**(保存しない `ReceptionLog` で文面だけ実運用と揃える)・応答ボタンは付けない。代理未設定で `stage="fallback"` は 400 |
| POST | /notifications/slack/interactions | なし(署名検証) | **受付通知の対応ボタン(受付/電話/お断り)押下の受け口**。Slack が Block Kit ボタン押下時にPOSTする。`X-Slack-Signature`(v0, `SLACK_SIGNING_SECRET`)＋5分リプレイ防止で検証→ボタン`value`の署名トークン(`create_decision_token`)で受付ログ→テナント特定→`_apply_decision`(冪等)→`response_url`で元メッセージを「対応済み」に置換(ボタン除去)、即200。`SLACK_SIGNING_SECRET`未設定時は404 |
| GET/POST | /lockers | JWT | ロッカー管理 (name 永続化, occupied/has_pin 返却)。旧DB台帳CRUD・後方互換で残置 |
| GET | /lockers/status | JWT | **ロッカー状況(表示専用)**。ローカルファースト化で端末が真実の源＝各端末が best-effort でミラーした占有スナップショット(`devices.locker_state_json`)を**端末ごとに集計**して返す `{devices:[{device_id,device_name,location,updated_at,lockers:[{id,door_number,name,occupied,has_pin,kind}],total,occupied_count,available_count}]}`。管理画面「ロッカー」メニューの表示元。管理・解錠操作は行わない(端末側で完結) |
| GET | /kiosk/lockers | デバイストークン | ロッカー一覧 `{lockers:[{id,name,door_number,occupied,has_pin}], available_count}`。**台帳ローカル権威化(案A)後は agent から未使用**（台帳は端末のドア構成から生成。管理画面表示用に残置）。キオスクUIは agent の `GET /device/locker-list` を使う |
| POST | /kiosk/lockers/{id}/occupy | デバイストークン | 空き→PIN設定 `{pin:4桁}`→`{ok}`。409/422。**後方互換で残置**（現行キオスクは agent `POST /device/locker/{id}/occupy` を使い、PINは端末ローカルで管理） |
| POST | /kiosk/lockers/{id}/release | デバイストークン | 利用中→PIN照合 `{pin}`→`{ok,door_number}`。403/409。**後方互換で残置**（現行キオスクは agent `POST /device/locker/{id}/release` でローカル照合＝オフライン可） |
| POST | /kiosk/lockers/{id}/occupy-delivery | デバイストークン | 置き配(旧経路・**後方互換**): 空き→**サーバでランダム4桁PIN生成**して施錠(occupied, pin_hash=bcrypt)→**受付ログに置き配記録(`_log_delivery_dropoff`)**→担当者へ通知→`{ok}`。**通知は `BackgroundTasks` で非ブロック送信**(`_fire_delivery_notifications`)。現行キオスクは agent 経由(`/device/locker/{id}/occupy-delivery`→PINローカル生成→backend `notify-delivery`)を使う |
| POST | /kiosk/lockers/{id}/notify-delivery | デバイストークン | **ローカルファースト置き配の通知＋受付ログ記録**を発火 `{pin, locker_label, device_name}`→`{ok}`。ロッカー占有状態は変更しない（占有は agent が権威）。**DB の lockers 行に依存しない(案A)**＝管理画面でロッカーを作っていなくても発火する（`{id}` は端末側の door_number、`locker_label` は agent が渡す）。①**受付ログに置き配を記録**(`_log_delivery_dropoff`: visitor="置き配"/company=ロッカーラベル/purpose="解錠PIN: XXXX"/method="dropoff"/state="completed"。**記録した受付ログの id を返す**)＝通知を見逃してもPINを後追いできる。②「どのロッカーにこのPINで置き配」を担当者へ通知(`_fire_delivery_notifications(dropoff_log_id=…)`, best-effort)。**Web Push は `kind="delivery_dropoff"`/`logId`/`url=?detail={id}` を載せ、タップで受付詳細モーダル(解錠PIN表示)を開く**(応答ボタンは付けない)。オフライン時は agent がキューし再接続で再送 |
| POST | /kiosk/lockers/mirror | デバイストークン | agent からの占有状態ミラー `{lockers:[{id,occupied,has_pin,name?,door_number?,kind?}]}`→`{ok,updated}`（管理画面の表示専用、**PINは受けない**）。**DBの lockers 台帳には書かず、送信端末の `devices.locker_state_json` に端末ごとの全件スナップショットとして保存**(冪等に丸ごと置換)。旧agent(メタ無し)は id から door_number/name を補完。管理画面は `GET /lockers/status` で端末ごとに表示 |
| POST | /kiosk/call-staff | デバイストークン | 配達の呼び出し: **受付ログ(ReceptionLog: visitor="配達"/company=device.name/method="delivery"/state="received")を作成**し、担当者へ「どの端末(device.name)から呼び出し」を通知 `{message?}`→`{ok, id}`。id はキオスクの待機画面が `GET /kiosk/reception/{id}` をポーリングして 受付(accepted)/電話(phone) 応答を結果画面へ反映するのに使う(受付フローと同じ仕組み。配達は お断り 無し)。**通知には受付/電話の対応ボタンを付ける**(`_fire_delivery_notifications(decision_log=log)`)＝来客受付と同じ Slack Block Kit(署名シークレット＋Bot Token時)＋Web Push アクション(`decision_actions`/`build_decision_push_extras`, 配達は accept/phone の2択)。スタッフが**通知から直接「受付」を押す**→`_apply_decision`で accepted→キオスクがポーリングで拾い「参ります」へ遷移。WebPush は `push_delivery` 設定 (`{enabled}`, 既定ON) で ON/OFF 可、通知本体タップ先は `?respond={id}` 付きで対応モーダル(受付/電話)を直接開く。Slack/WebPush/Webhook/Chatwork (best-effort)。**通知は非ブロック(BackgroundTasks)** |
| POST | /lockers/{id}/open | JWT | ロッカー開錠 |
| POST | /analytics/events | デバイストークン | **行動イベントの投入**(バッチ・最大200件)。1件の不正で全体を落とさず `{accepted, duplicate, rejected}` を返す。tenant/site/device はトークンから確定し本文の申告値は使わない |
| POST | /analytics/device-events | デバイストークン | 端末稼働イベントの投入(同上) |
| POST | /analytics/device-metrics | デバイストークン | 端末メトリクス(ハートビート)の投入(同上) |
| GET | /analytics/sessions | **運営JWT** | 匿名セッション一覧(テナント/端末/日付(JST)/結果/入力方法で絞り込み) |
| GET | /analytics/sessions/{id} | **運営JWT** | 1セッションの時系列イベント(`client_occurred_at, sequence_no` 順) |
| GET | /analytics/summary | **運営JWT** | 主要指標(完了率・離脱率・エラー率・回復率・所要時間の中央値/90%タイル・自己申告非介助率(回答率併記)) |
| GET | /analytics/uptime | **運営JWT** | 端末稼働率・通信障害時間・再起動回数・CPU/温度/空き容量 |
| GET | /analytics/export | **運営JWT** | CSV/JSON 出力(`kind=sessions\|events`, `fmt=csv\|json`) |

> `/analytics/*` の参照系は **運営(operator)のみ**。テナント管理画面には出さない（実証実験・製品改善は自社側の分析のため）。
> 受付送信(`POST /kiosk/reception`)と配達呼び出し(`POST /kiosk/call-staff`)は任意の `analytics_session_id` を受け取るが、**受付ログには保存しない**（通知の成否を匿名セッションへ書き戻すためだけにプロセス内 TTL マップへ渡す）。

---

## 管理画面のニアリアルタイム連動（SSE push）

管理画面の「受付ログ」「ロッカー状況」を、キオスク操作と**ほぼリアルタイム(<1秒)**で連動させる仕組み。
キオスク→backend(DB反映)は元々ほぼ即時で、遅延は「DB→管理画面」の最後の1ホップ(旧: 受付30秒/ロッカー15秒ポーリング)だった。ここを **Server-Sent Events の push** に置き換えた。

- **in-memory pub/sub (`backend/app/services/events.py`)**: `publish(tenant_id, {"type": ...})` / `subscribe` / `unsubscribe`。テナント単位で接続中の管理画面へファンアウトする。本番は **uvicorn `--workers 1`**(Dockerfile) ＝単一プロセス単一ループなのでプロセス内メモリで全接続に届く（Redis 等不要）。**複数ワーカー化する場合はプロセス跨ぎのブローカーに差し替えること**。`publish` はノンブロッキング(`put_nowait`)で**リクエスト経路に例外を投げない**。遅い/固まったクライアントは上限超過分を捨てる(メモリ無限増加防止)＝取りこぼしてもフロントは次イベントかフォールバックで再取得するので状態は失われない。
- **SSE エンドポイント (`backend/app/api/events.py` = `GET /events/stream`)**: 認証は EventSource がヘッダを送れないため **access token をクエリ**で受け接続時に一度だけ検証(get_current_user と同判定)。**DB セッションはユーザー解決の短命のみで、ストリーム保持中は握らない**(`Depends(get_db)` は使わない＝長時間 DB 接続を占有しない)。20秒ごとに `: keepalive` コメントを流しプロキシのアイドル切断を防ぐ＋切断を検出して `unsubscribe`。ペイロードは再取得対象を示す `{"type":"reception"|"locker"}` のみで**秘密情報・PIN・本文は一切載せない**。
- **publish する箇所**:
  - 受付(`type:"reception"`): `reception.create_reception`・`reception._apply_decision`(応答が実際に確定した時のみ＝冪等early-returnでは出さない。JWT/署名トークン/Slackインタラクション/デモ自動応答の全経路がここを通る単一ポイント)・`reception.update_reception`(PATCH)・`bulk_delete`/`delete`、および `kiosk.kiosk_reception`・`kiosk.kiosk_call_staff`(配達呼出)・`kiosk._log_delivery_dropoff`(置き配)。
  - ロッカー(`type:"locker"`): `kiosk.kiosk_mirror_lockers`。ミラーは操作時＋heartbeat(60秒)で届くので、**占有スナップショットが実際に変わった時だけ** publish(文字列比較)＝アイドルの定期ミラーではストリームを静かに保つ。
- **フロント (`frontend/lib/realtime.ts` `subscribeRealtime`)**: `/reception` と `/locker` ページが各1本 EventSource を張る。イベント受信で該当リスト(受付一覧/ロッカー状況)だけ 300ms デバウンスで即再取得。**「自動更新 OFF」時は SSE もポーリングも張らない**(更新を止めた意図を尊重)。EventSource は一時切断で自動再接続するが**トークン失効時は 401 ループに陥る**ため、`onerror` で一度閉じ `ensureFreshToken()`(lib/api.ts, 先読みrefresh再利用)でトークンを更新してから張り直す。**フォールバックの低頻度ポーリング(30秒)を併用**し、SSE が恒久的に切れても更新は続く。
- **デプロイ上の注意**: SSE は接続を張りっぱなしで uvicorn `--limit-concurrency` 枠を1つ占有する。通常リクエストと取り合って枯渇しないよう Dockerfile で **50→300** に引き上げた(天井であり予約ではない/アイドルSSEはDB接続を握らず軽量)。単一ワーカー維持が in-memory pub/sub の前提。

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
- `kioskStyles.ts` はどこからも読まれていなかったため 2026-11-12 に削除した。

### キオスク 日英バイリンガル表示（2026-10-03）

**常に日本語・英語の両方を表示し、タッチでどちらを大きく見せるかを入れ替えるだけ**（非表示にはしない）。
画面の再描画はしない（かざす面のカメラ・呼び出し中のポーリング・受付フォームの入力中の値を壊すため）。

- `kiosk.html` に `LANG`（既定 `"ja"`）と、常に両言語を描画するヘルパー `bi(ja, en, opts)` がある。
  生成した `<span class="bi-ja">`/`<span class="bi-en">` の大小・順序は CSS の `html[data-lang]` だけで
  切り替える(`document.documentElement.dataset.lang`)。`biDefault(value, key, opts)`/`biPurpose(ja, opts)`は
  管理画面の自由入力文言(待機メッセージ・来訪目的リスト等)用——**既定値のままなら組み込みの英訳を添え、
  テナントが文言を変えていたら英語行を出さず日本語のみ**にする(完全一致判定。`BI_DEFAULTS`/`BI_PURPOSE_EN`)。
  部署リストは既定が無い(テナント固有の組織名)ので常に日本語のみ。
- 下部帯(`bottomBandHtml`)に「EN⇄日本語」トグルを常設。下部帯を出す画面(受付フォーム・
  ロッカー暗証番号含む)なら出る。下部帯を使わない画面(待機・呼び出し中・結果・完了・
  アンケート・キオスク設定。角の「やめる」だけの画面)には元から出ない。
  押すと `LANG` を反転するだけで、`vcRelang()`(後述)が聞き取り中の音声語彙も合わせて差し替える
  (切り替えた先の言語で声が使えない端末では、聞き取り中でもそこで声を抜ける)。
  来訪者ごとに `go("idle")` でテナント既定(`ST.kiosk_default_lang`)へリセットする。
- 既定言語は管理画面「受付設定」で設定(`tenants.kiosk_default_lang`・`backend/app/api/settings.py`の
  `ALLOWED_KIOSK_LANGS = {"ja","en"}`)。`GET /settings/public/{slug}`経由でキオスクへ渡る。
- 対象は主要な来客導線一式(待機〜アンケートの全画面・共通の帯)。音声認識の英語対応は次節。

### 端末セットアップ（承認フロー・PIN 廃止）

**PIN は廃止。** キオスク端末は接続時に自己登録し、管理画面での承認で起動する。

- **device 版 (`kiosk.html` / agent)**: boot 時にトークンが無ければ agent `POST /register`（backend `POST /kiosk/register` へ `tenant_slug`+ホスト名+`hardware_id` を送信）→ トークンを `device_state.json` と localStorage に保存。status=pending なら `showPending()`（承認待ち画面）を表示し `GET /proxy/status`(→`/kiosk/status`) を **4s間隔でポーリング**、active になったら `location.reload()` で通常起動。agent の `/register` は既にトークンがあれば再登録せず現在の status を返す（冪等）。
- **Web 版 (`frontend/app/[tenant]/kiosk/page.tsx`)**: トークンが無ければ `api.registerKioskDevice({tenant_slug, hardware_id})`（hardware_id は localStorage に保存する `web-<uuid>`）。pending なら承認待ち画面＋`api.getKioskStatus` を 4s ポーリング、active で `KioskFlow` を描画。`setup/page.tsx`（旧PIN入力）は `/kiosk` へリダイレクトするだけ。
- **管理画面 (`admin/kiosk/page.tsx`)**: 端末一覧を 15s ごとに自動更新。`status==="pending"` の端末を「承認待ちの端末」セクションに表示し「承認する」(`api.approveDevice`→`POST /devices/{id}/approve`)で active に。不要な端末は「削除」で消す（拒否ボタンは無し）。端末名/場所は承認後に鉛筆ボタンで編集。
- **仮名**: 自己登録時の端末名はホスト名（Web版は「新しい端末」）。承認後に鉛筆ボタンで正式名称に変更する。

### 分析ログ（実証実験・製品改善）

**設計書は [`ANALYTICS.md`](ANALYTICS.md)。イベントや項目を足すときは必ずそちらも更新すること。**

- **個人情報は保存しない。** 氏名・会社名・担当者・入力値・QRトークン・名刺/カメラ画像・
  音声・IPアドレス・Cookie は **列そのものが存在しない**。自由入力の `metadata` 欄も作らない。
  受信 API は `extra="forbid"` のスキーマ＋固定語彙(`services/analytics_vocab.py`)で
  **ホワイトリスト外を1件単位で reject** する（残りは通る＝1件の不正で全体を落とさない）。
- **キオスク側の追加防御**: ソフトキーボードのキー(`[data-pk]`)と漢字変換候補(`.kb-cand`)は
  クリック記録の対象外（打鍵列から入力値が復元できるため）。`<input>` の value は読まない。
  スタッフ専用の `kiosk-settings` 画面は **画面遷移すら記録しない**（Wi-Fiパスワードを含むため）。
  `element_id` は ASCII 識別子のみ許可＝日本語の表示ラベルはサーバ側で弾かれる。
- **匿名セッションと受付ログ(個人情報)は結び付けない。** 対応表は
  `services/analytics_link.py` の **プロセス内 TTL マップ(既定2時間・永続化しない)** だけ。
  通知の成否(`notification_succeeded`/`failed`/`retried`)を匿名セッションへ書き戻すためだけに使う。
  単一ワーカー前提は SSE pub/sub と同じ（複数ワーカー化するならここも要検討。**永続化はしない**）。
- **経路**: ブラウザ(`static/analytics.js`。画面は `/kiosk-oplog.js` として読む) → **IndexedDB に先に保存** → エージェント
  `POST /device/oplog` → **ディスクスプール(JSONL)へ書いてから ack** →
  ブラウザは ack されたものだけ削除 → エージェントが `X-Kiosk-Token` を付けて backend へ
  指数バックオフでアップロード → 200 を受けてスプールから削除。
  **デバイストークンはブラウザのコードに持たせない**（エージェントが中継する）。
- **ブラウザが叩く URL に analytics / track / telemetry / beacon / collect / pixel を入れない**。
  Raspberry Pi OS の Chromium には **uBlock Origin Lite が最初から入っている**。旧名
  `/device/analytics/events` は EasyPrivacy の `/analytics/event` に当たって送信がブラウザ内で止められ、
  **2026-09-16 の導入から 10-02 の修正まで Pi からは行動ログが 1 件も届いていなかった**（匿名セッションは
  全部開発機の Chrome から。受付は普通に動くので気づけない）。旧名もエージェントに残してある。
  `kiosk_agent/tests/test_oplog_paths.py` が語を見張る。
- **通信断でも失われない**: IndexedDB は再読込・端末再起動をまたいで残り、スプールは
  順番(FIFO)を維持したまま復旧後に再送する。`event_id` が主キーなので二重登録されない。
- **稼働率の分母は「ラズパイの電源が入っていた時間」**（メトリクス行が存在する時間）。
  電源OFF中は行が無いので夜間・休日・計画停止は自動的に分母から外れる。通信断中は
  ローカルに溜まって後から届くので **分母に入り分子(app_healthy)から外れる**＝通信障害時間になる。
- **失敗しても受付を止めない**: ブラウザ側は全公開APIを try/catch で包み、`/kiosk-oplog.js` が
  404（OTA 未着）でも `AN` が no-op に落ちて通常どおり動く。エージェント/バックエンドが
  落ちていてもキオスク操作には影響しない。
- **`?mock=1` のプレビューでは送信しない**（本番データを汚さない）。
- **語彙は2か所にある**: `backend/app/services/analytics_vocab.py` と
  `kiosk_agent/static/analytics.js` の `VOCAB`。**片方だけ増やすとそのイベントが reject される**ので
  必ず両方に足すこと（`backend/tests/test_analytics_vocab_sync.py` がズレを検出する）。

### キオスク OTA 配信（`kiosk.html`・agent の自己更新）

キオスク端末(agent)は `updater.py` で backend の `GET /kiosk/bundle/manifest`(version＋各ファイル `sha256(bytes)[:16]`)を定期ポーリングし、version が変われば変更ファイルだけを `GET /kiosk/bundle/file/{path}` からDL→idle時に適用する。対象は `BUNDLE_FILES`(kiosk.html/**analytics.js**/tap.mp3/main.py/updater.py/gpio.py/sync.py/state.py/config.py/locker_store.py/**analytics.py**/**sysinfo.py**/**watchdog.py**＋`card/**.py` 17ファイル)。
**`main.py` が import する Python は必ず同じリストに入れること**（main.py だけ新しくなると import 失敗でエージェントが起動しなくなる）。デバイス側 `_local_hash` と backend の hash は同一算法(`sha256(bytes)[:16]`)＝一致すれば再DLしない。

**バイナリ・大きいファイルも配れる**（声の英語モデル、130MB・`voice_models/vosk-model-en-us-0.22-lgraph.zip`、Git LFS 管理の唯一の例）。ファイルサイズに応じて端末側のDLタイムアウトを伸ばし(`updater._download`)、適用(`apply()`)は一時ファイル経由 + `os.replace`(同じディレクトリ内なら atomic)にしてある——直接上書きだと、適用中に電源が落ちる・プロセスが落ちると壊れたファイルが残る。大きいファイルほど適用にかかる時間が延びて途中で切れる確率も上がるため。**Git LFS 管理ファイルは `raw.githubusercontent.com` だとポインタ文字列(約130バイト)しか返らない**ので、`_read_bundle_bytes` は該当パス(`_LFS_BUNDLE_PATHS`)だけ `media.githubusercontent.com` 経由にし、ポインタ文字列を検知したら(ローカル・GitHubどちらでも)配信・キャッシュしない(`_is_lfs_pointer`)。新しい LFS 管理ファイルを OTA 対象に追加するときは、`BUNDLE_FILES`/`MANAGED_FILES` に足すのと同時に `_LFS_BUNDLE_PATHS` にも追記すること。

- **配信元は「ローカルの kiosk_agent が有ればそれ、無ければ GitHub public raw(master)」**(`backend/app/api/kiosk.py` の `_read_bundle_bytes`/`_collect_bundle`)。**本番 Render のイメージはビルドコンテキストが `backend/` のみで `kiosk_agent/` を含まないため**、以前は配信元パスが存在せず manifest が空(`files:[]`)＝**全キオスクにOTAが一切届いていなかった**。対策として、ローカルに無い場合は公開リポジトリ `raw.githubusercontent.com/ranasoft-araki/mokuture-plus/master/kiosk_agent/<rel>` から取得(120s バイトキャッシュ)。これで **Dockerfile/コンテキストを触らず**、push→backend再デプロイ→GitHub master の最新 kiosk.html を配信、で更新が実機に届く。env `KIOSK_BUNDLE_DIR`/`KIOSK_BUNDLE_GITHUB_RAW` で上書き可。
- **GitHub からの取り寄せは「Render がデプロイしたコミット」に固定**(`_BUNDLE_REF` = env `RENDER_GIT_COMMIT`、`KIOSK_BUNDLE_REF` で上書き、どちらも無ければ従来どおり master)。バックエンドとキオスクのコードが同じコミットで揃い、中身が不変なのでバイトはプロセス存続中ずっと再利用する。manifest には **`source`** を載せる:
  - **`label`=版番号 `YYMMDD-NNN`**(例 `261002-001`。画面はこれを表示)。**配信サーバーがその中身(version)を初めて配った日(日本時間)＋その日に配り始めた何番目の中身か**を `kiosk_bundle_releases` テーブルに記録して振る(`_bundle_label`)。GitHub に頼らない・再デプロイしても同じ中身は同じ番号・前の中身に戻せば前の番号。master 追従/ローカル配信でも付く。
  - `commit/date/subject` = kiosk_agent に触れた最後のコミット(コミット固定時のみ。GitHub API をデプロイごとに1回)。**Render の外向き IP は共有で、未認証 GitHub API(60回/時/IP)は他の利用者に使い切られて通らないことがある**(2026-10-02 本番で発生)ので、失敗時はデプロイ SHA のみで10分後に引き直す。件名が無くても版番号は出る。
- **端末側の届いたかどうかの確認**: updater は**記録した版(`.bundle_version`)ではなくディスク上の中身を manifest と突き合わせる**(`_diff`)。git で巻き戻された Pi も「未反映」と分かり取り寄せ直す。いまの版の名前と適用時刻は `.bundle_info.json`(gitignore)。agent の `GET /update-status` が状態一式(enabled/checked_at/error/local/remote/mismatch/pending)を返し、`POST /update-check` で即時確認。キオスク設定の**デバイスチェックタブ「ソフトウェア更新」**に表示(最新です/更新あり[今すぐ更新]/未反映/再読み込みが必要/確認できません[理由]/自動更新オフ=開発機)。フッターの版表示も同じ名前。テスト: `kiosk_agent/tests/test_ota_status.py`・`backend/tests/test_kiosk_bundle.py`。
- **注意**: 配信は GitHub のデプロイ済みコミット(=master)＝**push していない変更は実機に届かない**(Render のデプロイ完了後に届く)。kiosk.html を直したら commit＋push すること。Windows開発機のローカル配信は CRLF、GitHub/Linux は LF で hash が変わるが、実機(Linux Pi)は常に LF なので manifest と一致し再DLループにならない。

### システム更新（OS の設定・パッケージ・ライブラリを配信で届ける。2026-11-17）

OTA（上の節）はエージェントの利用者権限でファイルを置き換えるだけで、**OS の設定変更・apt のパッケージ・pip のライブラリ・systemd の定義は届けられない**。それを受け持つのが `kiosk_agent/system/`。**配信されたものを管理者権限で実行する仕組みなので、次の決まりを崩さないこと。**

- **端末が管理者権限で実行するのは、署名を確かめられた版だけ**。署名は開発機の秘密鍵（`~/.ssh/mokuture_sysupdate`・リポジトリの外）でしか作れない＝GitHub や配信サーバー、端末のエージェントが乗っ取られても、管理者権限の処理は流せない。**秘密鍵をリポジトリ・Render・端末に置かない。無くすとシステム更新を配れなくなる**（端末を回って install.sh で公開鍵を入れ直すことになる）ので、利用者が控えを取っておくこと。
- **`system/` のファイル（`apply.sh`・`sysupdate-root.sh`・unit）を書き換えたら、commit の前に必ず `bash kiosk_agent/scripts/sign_system.sh`**。署名した一覧 `SYSTEM_MANIFEST`（`ハッシュ  パス` の行）と `SYSTEM_MANIFEST.sig` が更新され、中身が変わっていれば連番 `SERIAL` が上がる。署名し忘れると `tests/test_system_update.py` が落ち、端末側は「ハッシュが合わない」で実行しない。`system/**` は `.gitattributes` で LF 固定（CRLF だと署名と合わない）。
- **端末側の流れ**（`system/sysupdate-root.sh`。`/usr/local/lib/mokuture/` に置いた写しが root で動く。`mokuture-sysupdate.timer` が起動3分後と10分ごと）: ①一覧と署名を管理者しか書けない場所へ写す ②`ssh-keygen -Y verify` で署名を確かめる（公開鍵は `/etc/mokuture/allowed_signers`） ③一覧のファイルを写してハッシュを照合（確かめた写しのほうを実行＝あとから差し替えられない） ④連番が、これまでに確かめた中でいちばん新しい版（`floor.serial`）より進んでいるか確かめる（古い署名済みの版を流されない。**下限は実行の前に進める**＝わざと失敗させ続けて連番を止め、古い版を流し直す手を塞ぐ。同じ連番を通すのは同じ版のやり直しだけ） ⑤写した `apply.sh` を実行。**エージェントの置き場所にあるファイルは管理者として開かない**（エージェントの利用者として・1MB と30秒の上限つきで読む。リンクの先を読まされる・終わらない読み込みで止められる・ディスクを埋められる、を避ける）。確かめに失敗したら何も実行しない（`rejected`）。`apply.sh` が失敗した版は1時間後にやり直す（`failed`）。
- **`apply.sh` は「OS 側をいまの版が求める状態にそろえる」手順**で、何度動かしても同じ結果になるように書く。いまの中身: apt（swig / liblgpio-dev / python3-dev / i2c-tools）・I2C の有効化・エージェントの利用者を i2c グループへ・pip（本体 / `rpi` / `tof`。**pip はエージェントの利用者として動かす**＝`pyproject.toml` は署名の対象外なので管理者権限では読ませない）・この仕組み自身の更新。**`mokuture-kiosk.service` はまだ書き換えていない**（全端末の起動に関わるので、実機で確かめてから足す）。
- **エージェントの再起動は頼むだけ**（`/var/lib/mokuture/restart-requested`）。`apply.sh` が何かを実際に変えたときだけ印を置き、`sysupdate.py` がそれを読んで `/update-status` の `ready` を立て、キオスクが待機画面に戻ったときに再起動する（OTA の適用と同じ流れ。受付の途中では止めない）。変えていないのに頼むと、直らない端末が1時間ごとに再起動し続ける。印は中身（頼むたびに変わる値）で比べ、時刻では比べない（時計を持たない Pi は起動直後の時刻が戻るので、時刻で比べると再起動を繰り返す）。
- **端末への導入は `install.sh` を一度だけ**（公開鍵・設定・写し・timer を置く）。**既設の端末はこの1回が済むまでシステム更新を受け取れない**。デバイスチェックの「ソフトウェア更新」カードの「OS の設定・部品」の行に状態を出す（最新 / 適用待ち / 失敗した手順 / 署名を確認できない / まだ受け取れない＝install.sh 未実行）。端末では `cat /var/lib/mokuture/sysupdate.status`・`journalctl -u mokuture-sysupdate`・`/var/lib/mokuture/sysupdate.log`。
- **公開鍵（`system/allowed_signers`）と `install.sh` は OTA で配らない**（どちらも人が管理者として使うもので署名が無い。配信で差し替えられたら署名で守る意味が無い）。`install.sh` を実行する前は必ず `git fetch && git reset --hard origin/master`。`install.sh` は、端末に入っている公開鍵がリポジトリのものと違うときは差し替えない（鍵を作り直したときだけ `SYSUPDATE_REPLACE_KEY=1`）。sudo を付けて実行すると断る（エージェントまで管理者で動く設定になるため）。
- **`pyproject.toml` は OTA で配るが署名しない**（pip はエージェントの利用者として動かす）。代わりにそのハッシュ `system/PYPROJECT_SHA` を署名の対象に入れてある＝**`pyproject.toml` を変えたら `sign_system.sh` を動かす**（版が変わり、端末が pip をやり直す。忘れるとテストが落ちる）。
- **守れる範囲**: 署名で防げるのは「配信元（GitHub・配信サーバー）や端末のエージェントを乗っ取った者が、人手を介さずに管理者権限を得ること」。**エージェントを動かす利用者（いまは install.sh を実行した人＝sudo できる利用者）を乗っ取られると、その人が次に sudo を使うときに管理者権限を奪われうる**のは、この仕組みの有無に関係なく残る。そこまで塞ぐには、エージェントを sudo できない専用の利用者で動かす必要がある（未対応）。
- テスト: `kiosk_agent/tests/test_system_update.py`。確かめる手順そのもの（署名なし・別の鍵・あとから差し替え・一覧の書き換え・連番の巻き戻し）は、`SYSUPDATE_TEST_ROOT`（管理者でない利用者のときだけ効く試験用の根）で実際に `sysupdate-root.sh` を動かして確かめている。**`apply.sh` の中身（apt / raspi-config / pip）は開発機では動かせない＝2026-11-17 時点で実機では未確認**。

### 遠隔ログイン（運営が、問題の起きた端末へ必要なときだけ SSH で入る。2026-11-18）

端末は顧客のネットワークの内側にあって外から届かないので、**端末のほうから**自前の踏み台サーバー（VPS・OpenSSH を 443 番で待受）へ外向きに SSH をつなぎ、逆向きの転送口を開く。運営は踏み台を経由（`ssh -J`）して、端末の中だけで待つ受け口へ入る。踏み台の作り方と使い方は [`bastion/README.md`](bastion/README.md)。**2026-11-18 時点で、踏み台も実機も未確認**（開発機にあるのは単体テストだけ）。

- **流れ**: 運営パネル「デバイス管理」の「開く…」（理由と時間が必須）→ `tunnel_sessions` に `requested` で記録 → 端末の常駐（`kiosk_agent/tunnel_agent.py`・`mokuture-tunnel.service`）が次に `POST /kiosk/tunnel/poll` で聞きに来たとき受け取る（要求が無いあいだは 60 秒ごと・あるあいだは 5 秒ごと）→ 端末が踏み台へ `ssh -N -R 127.0.0.1:<転送口>:127.0.0.1:2222` → ssh が転送口を開けたと記録してから端末が `open` を報告（動き続けているだけでは報告しない） → 運営が入る → 「終了する」か時間切れで `closing` → 端末が閉じたと報告して `closed`。
- **閉じる経路は 3 つあり、どれか 1 つが働けば閉じる**: ①運営の「終了する」②端末が、サーバーから受け取った残り秒数を**経過時間で**数えて自分で閉じる（サーバー・回線が落ちて終了が届かなくても開きっぱなしにならない。時計を持たない端末があるので時刻では比べない）③踏み台の見回り（1 分ごと・`GET /bastion/active-ports` に無い転送口を切る）。端末を再起動したら必ず閉じた状態から始まる。
- **鍵は 2 つに分かれている。これを崩さないこと**: API が握るのは「どの端末を、いつまで、つながせてよいか」だけ。端末へ入る鍵は運営それぞれの PC にしかなく、公開鍵を ①踏み台（`bastion/add-operator.sh`）②端末（`kiosk_agent/system/operator_keys`＝**署名つきのシステム更新で配る**）の両方に登録する。**API が乗っ取られても、この遠隔ログインの経路からは端末の中へ入れない**（できるのは端末を踏み台へつながせることまで）。API に SSH の鍵・パスワードを持たせたり、API から端末へコマンドを流す口を足したりしない。**ただし、これは「遠隔ログインが新しい穴にならない」という意味で、端末全体が守られているという意味ではない**: OTA（`updater.py`）は署名が無く、配信サーバー（API）か GitHub を乗っ取った者は、遠隔ログインを使わなくても `main.py` などを差し替えて端末の中でコードを動かせる（この機能より前からある弱点。塞ぐには OTA にも署名が要る＝未対応）。同じ理由で、つなぎ先（踏み台のホスト・番号・公開鍵）も API の返事をそのまま使っている（API を乗っ取った者は端末を別のサーバーへつながせられるが、運営の鍵が無いので受け口には入れない）。OTA に署名を入れるときは、つなぎ先も署名つきの `system/` に固定すること。
- **踏み台は鍵を持たない**。端末がつなぎに来るたびに sshd の `AuthorizedKeysCommand` が `GET /bastion/authorized-keys`（合言葉 `TUNNEL_BASTION_SECRET`）へ聞き、**いま `requested`/`open` で期限内の端末の鍵だけ**が `restrict,port-forwarding,permitlisten="127.0.0.1:<転送口>"` 付きで返る。端末用の利用者にできるのは、決まった転送口を 1 つ開くことだけ（シェル・ほかへの転送なし）。運営用の利用者も踏み台にシェルは無く、踏み台の 127.0.0.1 へ中継してもらえるだけ。
- **端末の受け口は OS の sshd とは別物**（`system/mokuture-tunnel-sshd.socket` ＝ `127.0.0.1:2222` だけで待つ・接続ごとに `sshd -i`・設定は `system/tunnel_sshd_config`）。パスワード不可、見る鍵は `/etc/mokuture/tunnel_sshd/authorized_keys`（＝`operator_keys` の写し）だけで、端末の利用者の `~/.ssh` は見ない。**OS の sshd の設定は変えない**。`openssh-server` が入っていなかった端末では、入れた直後に OS の sshd（22 番・LAN 向け）を止め直す（顧客の LAN に新しい入口を作らない）。置くのは `system/apply.sh` の「5. 遠隔ログイン」（管理者権限・署名済み）。
- **常駐はキオスク本体に頼らない**（本体が起動しなくなった端末にこそ入りたい）。別の systemd 単位・システムの `python3`・標準ライブラリだけ（`tests/test_tunnel_agent.py` が import を見張る）。`RESTART_FILES` には入れない＝配信で `tunnel_agent.py` が変わったら、**開いていないときに**自分で終了して systemd に起こし直してもらう。聞きに来ても端末の `last_seen_at` は動かさない（本体が止まっているのに「オンライン」に見えるため）。
- **遠隔ログインの待ち受けは、手で `systemctl stop` されても 10 分以内に戻る**（`system/sysupdate-root.sh` の先頭が、enabled なのに止まっている `mokuture-tunnel-sshd.socket` / `mokuture-tunnel.service` を毎回起こす。`Restart=always` は落ちたときだけで、人が止めたものは戻さないため）。**キオスク本体（`mokuture-kiosk`）は戻さない**（現地・遠隔の作業で止めておきたい。2026-11-20 利用者の指示）。本体を止めても遠隔ログインは使える（別サービス）。遠隔ログインを本当に止めたままにするなら `systemctl disable --now`（ただし次にシステム更新の版が変わると `apply.sh` が enable し直す）。
- **サーバーが返す値（つなぎ先のホスト・利用者・踏み台の公開鍵・番号）は、端末が形を確かめてから ssh に渡す**（`parse_want`。ssh のオプションに化ける値を通さない）。端末が届ける公開鍵も、API が ed25519 の形に厳密に合うものだけ受け取る（踏み台の authorized_keys の行としてそのまま出すため）。**開いている最中は、端末の鍵の差し替えを受け付けない**（転送口の横取りを防ぐ）。
- **記録（`tunnel_sessions`）の書き換えは必ず `svc.move`**（読んだときの状態のままのときだけ書く条件つき UPDATE）。端末の問い合わせ（5 秒ごと）と運営の操作は同時に届くので、読んだ値をそのまま書き戻すと「終了」を「接続中」で上書きし、画面は終了待ちなのに踏み台が鍵を通し続ける（2026-11-18 の検証で実際に再現した）。片づいていない記録は端末ごとに 1 件だけ（部分一意インデックス `ix_tunnel_sessions_one_pending`。「開く」が同時に届いても 2 件目は 409）。
- **状態の表示は端末の報告を元にする**（ボタンを押した事実ではなく）。`tunnel_reach`（端末から踏み台へ届くか・起動時と 6 時間ごとに端末が確かめる）が `blocked` の端末は「踏み台へ届かない」と出す＝443 番の SSH を通さない設置先。その端末は遠隔ログインの対象外（決定済み）。
- **記録**: `tunnel_sessions` が、誰が・いつ・どの端末を・何のために開け、誰がどう閉じたかの記録を兼ねる（端末やテナントを消しても残るよう外部キーは張らず、そのときの名前を写す）。延長は同じ行の `expires_at` を延ばし、`reason` に「延長（誰）: 理由」を足す。顧客への都度の通知はしない（契約での包括同意。決定済み）。
- **設定が無ければ機能ごと無効**（`TUNNEL_BASTION_HOST` / `_HOST_KEY` / `_SECRET` の 3 つ。`settings.tunnel_enabled`）。無効のあいだ端末は 10 分ごとに聞きに来るだけで何もつながない。
- **転送口の番号は端末ごとに固定**（`devices.tunnel_port`・初めて開くときに 20000 番から割り当て）。`bastion/setup.sh` の `PORT_FROM`/`PORT_TO` と `TUNNEL_PORT_BASE`/`_COUNT` を変えるときは両方そろえる。
- **既設の端末に届く条件**: システム更新の仕組みが入っていること（「システム更新」節。未導入の端末は `install.sh` を一度）。届くまでは運営パネルに「端末が未対応」と出る。
- **未対応（次の候補）**: シェルに入らずに済む決まった操作（ログの取得・サービスの再起動・端末の再起動・更新のやり直し）。443 番の SSH が通らない設置先ではこれだけが手段になる。足すときも「API から任意のコマンドを流せる口」にはしないこと（決まった操作の名前だけを受け取る）。
- テスト: `backend/tests/test_tunnel.py`・`kiosk_agent/tests/test_tunnel_agent.py`。API: `GET /operator/tunnel/status?device_ids=`・`POST /operator/tunnel/{device_id}/open|close`・`GET /operator/tunnel/sessions`（運営のみ）、`POST /kiosk/tunnel/poll`（デバイストークン）、`GET /bastion/authorized-keys|active-ports`（合言葉）。実装: `backend/app/api/tunnel.py`・`services/tunnel.py`・`models/tunnel.py`、画面は `frontend/app/operator/devices/RemoteLogin.tsx`。

### 名刺読み取り（QR無し来訪者の受付フォーム自動入力）

受付フォーム(`showReception`)の「名刺で入力」から、カメラにかざした名刺を読み取って
**お名前・会社名・部署**を自動入力する。**端末内で完結**し、外部 OCR/生成AI/外部APIは一切使わない。
詳細は [`kiosk_agent/CARD_READER.md`](kiosk_agent/CARD_READER.md)（セットアップ/API仕様/しきい値/トラブルシュート）。

- **かざす面(`showWelcome`)で QR と名刺を同時に待ち受ける**。同じ `getUserMedia` の映像を
  QR 検出(毎フレーム)と `POST /card/frame`(探索中 320ms / 名刺を掴んだら端末設定の間隔)へ
  交互に回す。名刺が読めたら**確認画面を挟まず**受付フォームへ値を入れる(同じ 3 項目を
  直せる画面を 2 枚続けて見せない)。「名刺で入力」からの従来経路も残る。
  - **jsQR は同期実行でメインスレッドを止める**。映像のまま(1280x720)を 120ms ごとに回すと
    1 回 689ms かかってフレームが 2 秒に 1 枚しか流れず、静止 3 連続に永久に届かなかった。
    480px へ落とし(96ms)、名刺を掴んでいる間は QR を見ない。
  - カメラは **1920x1080 を要求**する。1280x720 だと会社名の漢字が 16〜18px しかなく、
    磯→暖 のような 1 文字誤りが出る。
- **確からしさの帯で扱いを変える**(`/card/status` の `confidence`)。`fill_min`(0.45)未満は欄に
  入れない、`ok`(0.85)未満は入れて「ご確認ください」、以上はそのまま入れる。`fill_min` は
  抽出側の `extraction.name_min_conf` と揃える(二重に線を引くと正しく読めた値まで捨てる)。
  確定API(`/card/session/{id}/confirm`)が**項目ごとの信頼度**を返す。
- **会社名は法人格の一致だけでは `ok` 帯へ上げない**。「株式会社」が読めたことは
  「この行は社名だ」の証拠であって「文字が正しい」証拠ではない(実機で「株式会社暖野木工所」が
  0.857 で無警告入力された)。メール/URL のドメインが社名本体を裏付けたときだけ頭打ちを外す。
- **縁で見つけた四角形は、中に印字があるか確かめてから確定する**(`_has_print`)。顔が偶然
  名刺の縦横比(1.69)の四角形になり、名刺を無視して顔を読んで 0 行になった。枠内の文字成分が
  画面全体に占める割合で見る(実測: 顔 9% / 名刺 48〜71%)。
- **撮影画像は OCR の前にピントを見る**(`quality.capture_focus_min`)。検出フレームで合焦と
  判定しても、ブラウザが実際に撮るのは別の瞬間の別フレーム。OCR は 1 枚 4.5〜5.8 秒なので
  読む前に弾く。測るのは**検出できた名刺の中**(画像全体だと名刺の無い絵まで弾いて行き止まりになる)。
- **法人格の頭 1 文字が欠けた行も社名として拾い、その 1 文字を書き戻す**。「株式会社◯◯」が
  「式会社◯◯」と読まれて候補から外れ、背景のゴミが会社名になっていた（株は画数が多く
  行頭にあるので落ちやすい）。「式会社」で終わる法人格は株式会社しかない＝推測ではなく
  確定なので補正する（辞書 33 件のうち 25 件が 1 対 1。業協同組合 は農業/事業のどちらか
  決まらないので補正しない）。補正した値は確信度を下げて「ご確認ください」を出す。
- **惹句は氏名に採らない**。氏名は「漢字で始まる」か「全部かな」で、ひらがなが漢字を
  挟む形にはならない。①漢字→かな→漢字（難しいほど面白い）②かな→漢字→かな
  （しいまとい白い＝①が崩れて読まれ漢字が 1 つしか残らない形）の両方を落とす。
  「小野ゆかり」「あき子」のような氏名は通る。
- **踊り字「々」を氏名の文字範囲に含める**。々(U+3005) は漢字の範囲にもかなの範囲にも
  入らないため、佐々木・野々村といった姓が一度も氏名候補にならなかった。
- **姓辞書は約 2 万件**(`card/dictionaries/surnames.tsv`、出典 SKK-JISYO.jinmei / GPL)。113 件だった
  頃は実機で読めた氏名(諫山綾音・磯野敏寛)が裏付けを得られず確定線に 0.001 届かず空欄になった。
  **辞書は OTA 配信対象**。現場で足す語は `*.local.*`(例 `surnames.local.tsv`)に書く＝配信で消えない。
- **実機調整用のフレーム保存**(`card.debug.dump_dir`、既定は無効)。撮影画像・検出範囲・補正後の
  名刺画像・読み取り結果を書き出す。画面録画では OCR 精度を測れないため。個人情報そのものなので
  有効な間は保存のたびに警告ログを出し、`.gitignore` で `kiosk_agent/card_dump/` を除外している。

- **実装場所は `kiosk_agent/card/`**（別サービス・別ポート・別systemdは作らない）。キオスクエージェントに
  `APIRouter(prefix="/card")` をマウントする。`main.py` の import は try/except で包んであり、
  依存(opencv/onnxruntime)やモデルが無い端末では**ルーターを生やさずキオスク本体は従来どおり起動**する。
  画面側は boot 時に `GET /card/status` を見て、使えなければ「名刺で入力」を描画しない。
- **カメラはブラウザが握る**(`getUserMedia`)。サーバ側で `/dev/video0` を開くと QR スキャンと排他になるため。
  検出ループは 640px の JPEG を 120ms ごとに `POST /card/frame`、撮影時だけ 2048px を `POST /card/capture`。
- **縦型・縦書きの名刺**: 縦型は横型と同等に扱える。①四隅は多角形近似のあと辺ごとの
  直線当てはめで取り直す(`refine_quad`。近似のままだと縦型で 44px ずれた→5px)。
  ②エッジのしきい値はノイズ床(勾配の90%点)に追従させる(固定値では白い名刺と暗所を
  両立できない)。③大きさの判定は面積比ではなく「その向きで写せる最大の何割か」
  (`fill_ratio`)。横長カメラでは縦型の面積比は最大34%にしかならず、面積で測ると縦型だけ
  不利になる。④**縦型を90度回さない**。射影では「縦書き」と「横倒しの横書き」を区別できず、
  縦書きを回すと全文字が横倒しになる(8行→3行に落ちた)。縦長の行は OCR 側が
  「起こして1行」「1文字ずつ」の両方を試し確からしい方を採る。縦書きの小さい部署・
  連絡先は取りこぼす（CARD_READER.md に精度表あり）。
- **認識したら自動で読み取りに入り、項目が取れたときだけ確認画面へ進む**。取れなければ
  「失敗」を見せずそのまま撮り直す(`accept.*` / `evaluate_acceptance`)。判定は会社名か氏名が
  取れていること＋項目数＋全体精度。上限(`accept.max_attempts`=5)に達したら取れた分で進む
  （手入力できるように。無限ループにしない）。手動「撮影する」は `force=1` で常に進む。
  自動撮影は `quality.stable_frames`=3（≒0.4秒）と短め — 失敗しても撮り直すので慎重にしすぎない。
- **保存しない**。SQLite も一時ファイルも持たない。画像はプロセスメモリ上のセッションのみで、
  確定/取り消し/TTL(180s)のいずれでも破棄。受付に送るのは氏名/会社名/部署だけで、
  メール・電話・住所は確認画面に出すだけで捨てる。ログにも値を出さない。
- **`/card/*` は既定でループバック限定**(`bind_loopback_only`)。agent 自体もループバック限定になった(2026-11-13)が、名刺だけ絞る。
- **しきい値はコードに直書きしない**。`card/defaults.py` が唯一の定義で、`card_reader.yaml`(端末ごと・gitignore)
  と環境変数 `CARD_<SECTION>__<KEY>` で上書きする。`card_reader.yaml.example` は既定値と完全一致し、
  ズレると `tests/test_config.py` が落ちる。
- **OCR は2系統**。第一候補 `paddle_onnx`(PP-OCRv4 の det/rec を ONNX Runtime で直接実行)、
  第二候補 `tesseract`(コマンド直叩き)。`card/ocr/base.py` の `OcrEngine` を実装し、設定 `ocr.engine` の一語で入替。
  **日本語モデルの文字セットに `@`/`_`/`〒` が無い**ため、英数字専用モデル(`rec_en.onnx`)で
  CJK を含まない行だけ読み直している。無い場合は復元を試み、特定できなければ**空欄で返す**（作らない）。
- **モデル(約23MB)と依存パッケージは OTA では配らない**。`install.sh` → `scripts/fetch_ocr_models.py`
  (SHA-256 照合つき)の担当。OTA が配るのは `card/**.py` と辞書(`card/dictionaries/`)。**辞書も OTA で上書きされる**ので、
  現場で語を足すときは `*.local.*`（例: `surnames.local.tsv`）に書く（そちらは配信しないので消えない）。
- **辞書は再起動不要**。`card/dictionaries/*.txt|tsv` は mtime を見て読み直す。
- OTA 対象は agent(`updater.MANAGED_FILES`) と backend(`kiosk.BUNDLE_FILES`) の2箇所にあり、
  ズレると「その端末だけ古いコード」になる。`tests/test_ota_list.py` が並び順まで一致を検証する。
- テストは `kiosk_agent/tests/`（268件）。**実在の名刺は使わない**。`tests/make_fixtures.py` が
  架空の社名・氏名と予約済みドメインで名刺画像を生成する（横型/縦型/日英混在/白/色付き/木目/斜め/
  反射/ぼけ/暗所/名刺でない紙/スマホ画面 等19パターン）。モデル未取得なら `-m ocr` のテストが自動 skip。

### 声で操作する（画面操作のキーワード / 実験導入 / Doc/kiosk-voice-touchless.html 段階2）

**語彙を持つ画面が出たら押さなくても音声モードに入る**(`command.auto_start`・既定 true、`/voice/status` の
`command.auto_start` で画面へ渡す。false なら下部帯の「声で操作する」を押したときだけ)。**画面が選択を待っている間だけ**
マイクを開けて、その画面の言葉だけ(「ほうもん」「ロッカー」「にばん」「もどる」…)を受け付ける。待機画面へ戻ると抜け、
**待機画面ではマイクを開けない**。「声の操作をやめる」を押した来訪者には待機画面へ戻るまで自動で入らない(`VCMD.optOut`)。
自動で入ったときは開始音を鳴らさず、分析セッションは最初に声で操作した時点(`vcFire`)で始める。
**端末内で完結**し、クラウド音声認識API・Web Speech API・外部生成AIは使わない。詳細は
[`kiosk_agent/VOICE_COMMAND.md`](kiosk_agent/VOICE_COMMAND.md)。

**英語対応(2026-10-03)**: 表示言語の切替え(上の「キオスク 日英バイリンガル表示」節)に声も追従する。
発話での言語自動判定はしない(タッチが正)。`vosk_engine.py` の関数は全部 `lang="ja"` 既定の引数を取り、
英語は別設定節 `vosk_en.*`(既存の `vosk.*` はネストせず触らない)。**英語の小型 Vosk モデルは
語彙外(OOV)を表す `[unk]` が無く、語彙を絞ると周りの雑談まで信頼度1.0で誤爆する**実測があり、
`[unk]` を持つ `vosk-model-en-us-0.22-lgraph`(130MB)を既定にした。**日本語モデルとは違いこの
英語モデルは OTA 配信対象**(Git LFS 管理・`backend`の`BUNDLE_FILES`/`updater.py`の`MANAGED_FILES`)。
zip のまま配り、`voice/server.py` の `_watch_models` が端末側で初回だけ展開する(手動導入も
`scripts/install_voice.sh --english` / Windows は `install_voice_windows.ps1 -English` で可能)。
LFS 管理ファイルは `raw.githubusercontent.com` だとポインタ文字列しか返らないため、
`_read_bundle_bytes` は該当パスだけ `media.githubusercontent.com` 経由にし、ポインタ検知
(`_is_lfs_pointer`)で誤って配信・キャッシュしないようにしてある。詳細・実測は VOICE_COMMAND.md §12。
**以前の「音声で入力」(受付フォームを声で埋める・一文の名乗り・whisper.cpp・AmiVoice 中継・staff_readings.yaml)
は 2026-09-29 に利用者の指示で削除した。** テナントの `voice_cloud_enabled/opt_out` 列だけは DB 互換のため
モデルに定義を残してある(読み書きするコードは無い)。

- **実装場所は `kiosk_agent/voice/` だが、名刺と違って別プロセス・別ポート・別systemd**
  (`mokuture-voice.service` / `127.0.0.1:8181`)。①本体は 0.0.0.0 で待つので相乗りすると音声APIがLANから
  見える ②実験機能のクラッシュで受付本体(GPIO/ロッカー/扉)を巻き込まない。**マイクを握るのはサービス側**
  (`arecord` / Windows は `sounddevice`)。ブラウザが送るのは「いまの画面の言葉」だけ。
- **画面のボタンはほぼすべて声でも押せる**(2026-10-02 利用者の指示で「遷移と選択まで」から広げた)。
  **人が動く・物が動くもの(下部帯の「担当者を呼ぶ」・配達の「呼び出し」・受付の「受付する」・ロッカーの空きの口・
  解錠ガイドの「扉を閉めました」)は、声で選んだときだけ確認(`vcConfirm`「〜しますか？ はい/いいえ」)を挟む**
  (タッチは従来どおり即実行)。「受付する」の確認には入力内容を並べる(設計案 §08 の復唱)。
  **暗証番号も声で入れられる**(2026-11-06 利用者の指示。以前はマイクを開けなかった)。**画面の案内は「1桁ずつ、丸が付くのを待って」**(2026-11-17 利用者の指示。続けて言うと頭の桁が `[unk]` に吸われてほぼ入らないため、続けて言う例はやめた / VOICE_COMMAND.md)。数字は 1 つずつでも続けてでも
  言え(`sequence`・サービスは言われた順に id を返す `vosk_engine.match_sequence`)、**1 語でも怪しければ発話ごと捨てる**
  (拾える桁だけ拾うと桁が黙って抜ける)。**声で入れた桁だけ丸に数字を出し、4 桁そろったら「この番号でよいか」を確かめる**
  (設定で聞き違えると荷物を取り出せない)。**どの数字かはログに残さない**(`secret`。メトリクスは `"secret"`・
  ログは `matched` だけ)。画面に「番号は周りの人にも聞こえます」と出す。キーボード・変換候補は対象外。
  重なり(確認・担当者を呼んだ案内・名刺の読み取り)は `voiceCommandsLayer(画面名, 要素)` で語彙を差し替え、
  要素が描き直しで消えたら語彙も外す。ご用件・部署・アンケートは管理画面で変わる文言なので `spare` 扱いにし、
  `vcFit` がサービスの上限(言い回し16文字・選択肢24個。**1つでも超えると422で画面ごと声が使えなくなる**)からはみ出すぶんを外す。
- API は `POST /voice/session/{id}/command`(`vosk_engine.recognize_command`)。画面が渡す語彙だけで Vosk の
  語彙制限(`Gr.fst`)decode。**認識した言葉は画面にも実験ログにも出さない**(返すのは選択肢 id と信頼度)。
  前の画面の聞き取り中に新しい語彙が来たら畳んで開け直す。
- 語彙は kiosk.html の `VOICE_VOCAB`(**JSON として書く**。テストと `scripts/voice_command_eval.py` が読む)。
  各画面は描画後に `voiceCommands(画面名, [vcItem(キー, 押す要素)], {onActivity: resetIdle})` を呼ぶだけで、
  当たると**その要素を click() する**(タッチと同じ経路)。要素には「言う言葉」の札が付く。
  **札は押す前から薄く出す**(声で操作したことの無い人に伝わるように。押す手段がある画面だけ)。
  札の言葉(`label`)は**読み仮名(ひらがな)**。帯は `#bb-voice-slot`(下部帯の差し込み口。不足幅は
  flex-shrink:1000 でここだけが縮む)、帯の無い画面・確認の上は上端中央に浮かせる。
- Vosk の語彙制限の性質(実測): ①句でなく**語**で絞られる(句が続けて現れたかはこちらで照合)
  ②**同じ読み・近い音の表記を並べると信頼度が割れて両方外れる**(「戻る」と「もどる」、「受け取る」と「受け取り」)
  ③短い数字は発話頭の雑音に吸われる(語彙を絞ると「にばん」は「番」だけ) → **番号で選ぶロッカーの画面だけ
  語彙を絞らない認識で聞き直す**(`opts.fallback`。7口の番号で 11/21 → 25/28) ④**雑談に紛れたキーワードは
  信頼度1.0で当たる** → 後ろに語彙外の発話が 0.25 秒以上続いたら捨てる(`command.trailing_unk_sec`)。
  合成音声で当たり 218/222・取り違え 0、雑談の誤爆 31→7。**ロビーの実音と Pi 実機での値は未計測**。
  ⑤**数字の語は信頼度が低めに出る**(実機で「にばん」だけ反応しなかった。静かな所でも「二」が 0.75〜0.85 に
  落ちて 0.85 に届かないことがある) → **数字の語だけ合格ラインを 0.75**(`command.number_min_conf`)、「二」がある画面では
  同じ音の言い添え「に」を語彙から外す。
- **録音の始まり(VAD・`voice/vad.py`)**: 暗騒音は**話し始める前の直近 2 秒の中央値**で見積もり、窓をまたいで
  持ち回る。**固定の初期値(-55dBFS)から判定を始めてはいけない**: それより 9dB うるさい場所では窓を開けた
  瞬間に話し始めと判定され、声と関係なく 3 秒(`max_record_sec`)で切れていた(実機の「話している最中に
  認識が始まる」)。話し始めは直近 0.2 秒のうち 0.1 秒が「暗騒音＋5dB」で、そのどこかで＋9dB を越えたとき(`vad.onset_ms`。
  ＋9dB が 0.1 秒だと実機で「かなり近づかないと認識しない」になった)。声らしいコマは暗騒音に入れず、話している
  最中も＋5dB 未満のコマだけで暗騒音を追い、**話し終わりも＋5dB の線**で見る(始まりは高い線・終わりは低い線。
  小さめの声で語尾の前に切れない。引き換えに雑談の中では 3 秒の上限まで録る回数が増える)。頭は最初に声と判定したコマの
  0.25 秒前から、そのコマを 1 回重ねる(`vad.onset_repeat_frames`。1 拍の数字が頭の雑音に吸われにくい)。
  履歴が無いときは本物の音を 0.1 秒測ってから判定(0 埋めは数えない)。**ノイズゲートのマイク**(無音を 0 で
  返す)は「音のあとに 0 が 0.3 秒」を一度見たら覚え、以後 0 が 0.3 秒続いた窓は履歴があっても初期値以下で判定
  (**窓の頭の 0 だけでは決めない**: 開いた直後だけ 0 の機材でうるさい部屋だと元の打ち切りに戻る)。
  履歴は Lock 付き(`_NoiseHistory`。セッションは最大 4 つ)。
  **近くの雑談は音の大きさでは区別できない**(残る課題。詳細と実測は VOICE_COMMAND.md §4)。
  **0 埋めは中身が全部 0 のコマだけ**(音量の線で切ると、入力の小さいマイクの本物の静けさまで 0 扱いになる)。
- **マイクの入力レベルがいちばん効く**(実地試験・`scripts/voice_fieldtest.py`): 安い USB マイクは声の山でも
  -52〜-65 dBFS で、Vosk が何も返さなかった(46 回中 1 回)。認識の前に声の大きさをそろえる
  (`vosk_engine._leveled`・`command.level_target_db` -20・最大 +30dB → 32 回)。それでも語尾が崩れるので、
  本筋は OS の録音レベル(Pi は alsamixer の録音側)を上げること。
- **OTA は `voice/*.py` を配るが `_RESTART_DIRS` には入れない**。音声サービスが自分のソースのハッシュ変化を
  60秒ごとに見て自ら終了し、systemd(`Restart=always`)に起こし直してもらう(`voice/server.py` の `_watch_sources`)。
  配信リストは agent(`updater.MANAGED_FILES`) と backend(`kiosk.py` の `BUNDLE_FILES`)の2か所を並び順まで一致させる。
- **分析ログは「書ける項目を列挙する」方式**(`voice/metrics.py` の `_ALLOWED`)。画面名・選択肢 id・外れた理由・時間だけ。
- Vosk モデル(zip)は Git LFS。`install_voice.sh` が SHA-256 固定で自力取得するので git-lfs 無しでも導入できる。
- **Windows で画面から試すとき**: キオスク本体(`main.py`)は非Linuxでは OTA を止めてあるので起動してよい
  (以前は master の版で未コミットの kiosk.html/voice/*.py を上書きしていた)。本体なしなら
  `http.server --directory static` ＋ `?mock=1&voice=1`(MOCK のまま音声サービスだけ本物)。
- テストは `kiosk_agent/tests/voice_input/`(172件)。実マイクも実モデルも使わない(`voice_fakes.py` の偽 Vosk・
  `capture.BufferStream` のフェイクマイク)。実モデルがある環境では語彙表が発音辞書で書けるかも確かめる。

### キオスク画面（device 版 `kiosk_agent/static/kiosk.html`）
画面遷移フロー（`go(screen, data)` で管理）:

```
idle ──(人感センサー PIR / タップ)──▶ welcome(統合QR画面: 左=QRカメラ常時 / 右=案内＋「ご予約のない方はこちら」)
  welcome: QR検出(予約) → calling,  「こちら」ボタン → top(受付メニュー 3タイル)
  top: ご訪問 → reception(フォーム),  荷物の配達 → delivery,  ロッカー → lockerMode(保管/受取) → locker
  reception(フォーム・用件5択) → calling(お待ちください)
  calling ──(スタッフ応答)──▶ resultOk(受付) / resultPhone(電話) / resultDecline(お断り) / complete(予約マップ)
  各結果 ──▶ feedback(任意アンケート3問。お断りのときは出さない) ──▶ idle
```
※旧・独立QR画面(`showQr`)は `showWelcome` に統合して**廃止**。QR専用画面 `go("qr")` は無い。

**受付応答フロー（受付/電話/お断り）**（`showCalling` @ kiosk.html）— スタッフ側の3択応答をキオスクに反映:
- 受付送信で受け取った `receptionId` を `go("calling", {receptionId})` に渡す。`calling`(=「お待ちください」画面)は `GET /proxy/reception/{id}`(→backend `GET /kiosk/reception/{id}`) を **2.5s間隔でポーリング**する。
- **応答は来訪者ではなく「通知を受けたスタッフ」が押す**。プッシュ通知アクション or 管理画面「受付ログ」の3ボタン(`DecisionButtons`)。backend `_normalize_decision`/`_apply_decision` が state を `accepted`/`phone`/`declined` に更新(いずれも確定＝冪等、上書き不可)。
  - **受付(accepted)** → `showResultOk`「参りますので少々お待ちください」。予約(QR)で会議室マップがある場合は歓迎画面(`showComplete`)で案内。
  - **電話(phone)** → `showResultPhone`。管理画面設定の電話番号(`ST.kiosk_phone_number`)を大きく表示し「対応不可のため、こちらへお電話ください」。
  - **お断り(declined)** → `showResultDecline`「営業・セールス等のご訪問はご遠慮…」＋問い合わせフォールQR(`ST.inquiry_qr`)を表示。
- **通知ボタンは method 別**: QR予約(`method="appointment"`)は 受付/電話 の2択、非QR(form/qr)は 受付/電話/お断り の3択(`build_decision_push_extras`)。push は `sw.js` が `accept`/`phone`/`decline` を署名トークンで `POST /reception/decision`。
- **無応答フォールバック（全パターン共通＝時間切れは電話案内へ）**: スタッフ通知の応答が時間切れになった場合は**どの受付パターンでも `showResultPhone`(電話番号表示)へ流す**→自動で idle 復帰。`showCalling`(来客: form/qr/appointment)は 90s、`showDelivery` の呼び出しwaitも 90s(受付ID無しの旧経路も一定時間後に `resultPhone`)。**`showComplete`(歓迎/会議室マップ)はスタッフが「受付」を押した成功時のみ**(QR予約で `room.map_image_url` がある場合、`showResultOk`→`showComplete`)＝時間切れでは出さない。電話番号未設定時の `showResultPhone` は「受付までお声がけください」を表示。
- MOCK: `mockFetch` は受付ごとに `accepted`→`phone`→`declined` を巡回して返し、3つの結果画面をオフラインで確認できる。

- **idle**: 人感センサー（`GET /device/pir` を 700ms ポーリング）で来訪検知 → `welcome`(統合QR画面) へ自動遷移。タッチCTAは非表示（PIR非搭載/開発環境向けに画面タップでも遷移可）。画面は屋号(ロゴ/welcome_message)・タグラインのみ。signage メディアがあれば再生。
  - **来訪を検知するセンサーは端末ごとに選べる**（`.env` の `PRESENCE_SENSOR`。`gpio.make_presence_sensor`）。`auto`(既定)=起動時に I2C の 0x29 を読んで距離センサーがいればそれを、いなければ人感センサーを使う(`gpio.detect_tof_model`。ライブラリ無しで OS の I2C を直接読み、機種番号で VL53L0X / VL53L1X を見分ける＝**センサーを付け替えた端末で `.env` を書かなくてよい**。見つけるのは起動時だけ) / `pir`=人感センサーに固定(GPIO4) / `vl53l0x`・`vl53l1x`=I2C の距離センサーに固定(`gpio.TofSensor`。VIN(VCC)→3.3V・GND・SDA→GPIO2・SCL→GPIO3、アドレス 0x29)。画面から見える形はどちらも `/device/pir` の `motion_detected` で、kiosk.html は機種を知らない。距離センサーは `TOF_THRESHOLD_MM`(既定1000)以内の読みが `TOF_CONFIRM_READS`(既定3)回続いたら検知。**距離センサーは「物があるだけ」で近いと読み続ける**ので、近いままが `TOF_STALE_SEC`(既定60秒)続いたら離れるまで検知を止める(置かれた物・向かいの壁で待機画面が起き続けない。判定は `gpio.TofPresence`)。読めないときは黙って「検知なし」にせず `/device/status` の `pir.error`(`no_library`/`no_device`/`wrong_model`/`read_failed`/`mock`)に理由を返し(読めないと分かった時点で検知も外す)、デバイスチェックの「人感センサー」カードに、いまの距離と合わせて出す。ライブラリ(pyproject の `tof` extra=Adafruit Blinka)と I2C の有効化は**システム更新(「システム更新」節)が配信で行う**(その仕組みを入れる前の端末は install.sh を一度実行する)。テスト: `tests/test_tof_presence.py`(実機の I2C には触れない)。**2026-11-17 時点で実機では未確認**。
- **welcome（統合QRようこそ画面・`showWelcome`）**: 待機解除後の最初の画面。**左=QRカメラ常時スキャン**(BarcodeDetector→jsQR fallback、`parseQR`で `appt:<token>`/`name`付きURLのみ受付、未対応/エラーは `pauseScan`でクールダウン)、**右=案内＋「ご予約のない方はこちら →」ボタン**。QR検出→`/proxy/reception`送信して `calling` へ。「こちら」→ `top`。カメラは `disposed`/`stopStream` で離脱時に確実に解放。旧・独立QR画面(`showQr`)はここに統合済み。
- **top（受付メニュー）**: `ご訪問 / 荷物の配達 / ロッカー` の3タイル（日英併記・大型）。`welcome` の「こちら」から到達。ご訪問→`reception`、配達→`delivery`、ロッカー→`lockerMode`。
- **delivery（荷物の配達・Phase3実装済み）**: `showDelivery`。配達方法を選択 — **置き配**(空きロッカーへ施錠。空きが無ければ選択不可。空きロッカー選択→`pulseLocker`でGPIO開錠→「扉を閉めました」→**agent `POST /device/locker/{id}/occupy-delivery`**。**agentがローカルでランダム4桁PINを生成・pbkdf2ハッシュ保存して施錠状態にし、backend `notify-delivery` 経由で「どのロッカーにこのPINで置き配された」を担当者へ通知＋受付ログに記録(`method="dropoff"`)**(オフライン時はキュー→再接続で再送)。配達員にはPINを表示しない。**通知を見逃してもスタッフは管理画面「受付ログ」の置き配行でPINを確認できる**(一時PIN＝受取で無効化のため平文表示)) / **呼び出し**(`/proxy/call-staff`→担当者へ「どの端末から呼び出しか(device.name)」をSlack/WebPush/Webhook/Chatwork通知＋受付ログに記録。**通知に受付/電話ボタンを付け、スタッフが通知から直接「受付」を押すと参ますに遷移できる**。返る `id` で「お待ちください」画面(`showDelivery`内蔵の`wait`ビュー)が `GET /proxy/reception/{id}` を2.5s間隔でポーリングし、スタッフの 受付→`showResultOk`/電話→`showResultPhone` に遷移。90s無応答は電話案内へフォールバック=`showResultPhone`)。置き配ロッカーはPIN付き(`has_pin:true`)＝通常の「利用中」ロッカーとして扱われ、スタッフが通知で受け取ったPINでロッカー画面から解錠して受取。
- **lockerMode（ロッカー入口・`showLockerMode`）**: ロッカータイルの直後。**手荷物一時保管**(store: 空き=PIN未設定ロッカーのみ→`showLocker("store")`) / **荷物受け取り**(pickup: PIN設定済ロッカーのみ→`showLocker("pickup")`) を選ぶ。戻る→`top`。
- **locker（ロッカー・`showLocker(mode)`）**: モードでグリッドを絞り込む(一覧は agent `GET /device/locker-list`)。store=`!occupied` のみ表示→`openEmpty`→4桁PIN設定(**agent `POST /device/locker/{id}/occupy`**)。pickup=`occupied && has_pin` のみ表示→4桁PIN入力(**agent `POST /device/locker/{id}/release`**)→照合OKでGPIO開錠。クリックは**絞込後の `shownLockers`** をインデックスする。該当0件は空状態メッセージ。戻る→`lockerMode`(mode時)。**PINは端末(agent)がローカルで pbkdf2 ハッシュ保存・照合＝クラウド往復なし・オフラインでも解錠可**（ローカルファースト。backend へは占有状態を best-effort ミラー）。扉開閉センサーが無いため閉扉は手動ボタン（センサー導入時は自動化可）。
  - **GPIO設定の注意**: kiosk は `POST /device/locker/{door_number}/open` を叩くため、kiosk_agent の `LOCKER_PINS_JSON` は **door_number(口の番号 1〜)をキー、GPIOピン(BCM)を値**にすること。既定: `{"1": 14, "2": 15, "3": 18}`(`config.py`・`.env.example`・`install.sh` で同じ)。**`{}` にすると、一覧は口数の設定から作られるので口は表示されるのに、どの口も `/open` が 404 で開けられない**(昔の `.env.example` は `{}` だったので、古い写しの `.env` に残っていることがある)。
  - **ドアセンサー連動の自動施錠 (`main.py` `_open_with_autolock`)**: 電気ストライク(通電ON=解錠 / 無通電OFF=施錠位置)向け。`/device/locker/{id}/open` は該当ロッカーに**ドアセンサーが設定されていれば**、解錠通電→**扉が開いたら即無通電化**(以後は閉扉でラッチが自動施錠)する経路(`{state:"opening", autolock:true}` を即返す=非ブロック)に入る。開錠パルス長や「扉を閉めました」操作のタイミングに依存せず確実に施錠できる。**有効化には `DOOR_PINS_JSON` のキーを door_number(=`LOCKER_PINS_JSON` のキー)と一致**させること。ドアセンサー未設定のロッカーは従来の固定パルス(`LOCKER_PULSE_SEC`)にフォールバック。開錠通電の保持上限は `LOCKER_OPEN_WINDOW_SEC`(既定12s)。
- **モック方針（実機ハードのみ最小スタブ／バックエンドは常に実経路）**: MOCKは「処理ルートごと本番と分ける」のではなく、**実機でしか動かないハードだけ**を最小限スタブする。バックエンド通信（`/proxy/*`）は開発機でも常に実経路を通す。
  - **ハードのモック（agent 層）**: GPIO(ロッカーリレー/PIR/ドア)・カメラ/マイク状態・音量・WiFi は agent が自動モックする。`main.py` の `_MOCK_DEVICE`(=**非Linux で自動 True**、`MOCK_GPIO=true` でも)と `gpio.py`(`gpiozero` 不在時 `_MOCK=True`)が担当。→ Windows開発機でも `/device/*` は落ちずモック値を返す。
  - **ブラウザは常に実経路**: `kiosk.html` は `/proxy/*`=実バックエンド、`/device/*`=agent(ハード or モック)を叩く。`/config` の旧 `mock` フラグ／`config.kiosk_mock` は**廃止**（ブラウザ全スタブの自動有効化はしない）。
  - **開発機での確認手順**: `kiosk_agent/.env` に `TENANT_SLUG` と到達可能な `REMOTE_API_URL`(既定=本番) を設定 → `uvicorn main:app` → `http://localhost:8080` → 自己登録 → 管理画面で承認。**これで管理画面の実データ(会議室 `map_image_url` 等)がそのまま表示される**。QRはWebカメラがあれば読取（PIRはタップで代替可）。
  - **ロッカーはローカルファースト（`kiosk_agent/locker_store.py`）**: ロッカーは各端末のGPIOに直結＝**端末が台帳・占有状態・PINすべての真実の源**。占有/PINは agent が `locker_state.json` に永続化（pbkdf2ハッシュ、平文不保持）。キオスクUIのロッカー状態系は agent 直叩き＝`GET /device/locker-list`・`POST /device/locker/{id}/occupy|occupy-delivery|release`・`POST /device/lockers/open-all`。**解錠のPIN照合は端末ローカルで完結（クラウド往復なし・オフライン可）**。
    - **台帳(何口あるか)は「設置者が選んだ口数」から生成する（案A・backend 非依存）**: 商品は3口/7口の2パターンで**増設分の配線は標準化＝ピンマップは既知の定数**。GPIOの物理検出では口数を自動判定できない（リードスイッチは pull_up で「未接続」と「開扉」が同じHIGH、リレーは出力でフィードバック無し）ため、**口数は設置者がキオスク設定画面のタッチUIで 3口↔7口 を選び**、`locker_store` に永続化する（`locker_count`、JSON編集不要）。**未選択(初回/既存端末)は env のピン構成から既定口数を推定**（`_env_default_locker_count`＝後方互換で、7口ぶんの env を持つ既存端末を勝手に 3口 へ縮小しない）。`_configured_door_numbers()` は選択口数を `[1..N]` の door_number 台帳にし、`locker_store.ensure_local_roster()` が生成。既存の占有/PINは保持し、構成外の**未占有**ロッカーのみ掃除。**縮小(7→3)で外れる口に利用中があれば `POST /device/locker-config` は 409 で拒否**（GPIOを落とすと解錠不能で中身が取り出せなくなるため。先に解錠が必要）。ピンマップは main.py の `LOCKER_PRESETS` 相当（`_locker_pins_for`/`_door_pins_for`）で決まり、1〜3口のベースは env(`LOCKER_PINS_JSON`/`DOOR_PINS_JSON`)を優先、7口の増設4口は既定ピン `_EXTRA_LOCKER_PINS`/`_EXTRA_DOOR_PINS`（**実機ハーネスに合わせ確定要**。env に7口ぶん書けば上書き可）。口数切替は agent `GET/POST /device/locker-config`（POSTで GPIO 再構築＋台帳再生成＋backend へ best-effort ミラー）。**backend `/kiosk/lockers` は台帳ソースにしない**（管理画面のロッカー管理メニュー廃止で lockers 行が空でも置き配が成立する）。
    - 占有状態は backend `/kiosk/lockers/mirror` へ best-effort ミラー（管理画面の表示専用・失敗しても解錠に影響なし）。ミラーは**DBの lockers 台帳ではなく送信端末の `devices.locker_state_json` に端末ごとのスナップショットとして保存**され、管理画面「ロッカー」メニュー(`GET /lockers/status`)が端末ごとに読み取り専用で表示する（ロッカー行がDBに無くても状況が見える）。**ミラーの発火は2経路**: ①占有/解錠/口数変更/全解除などの**操作時に即時**(`main.py` の `_spawn(_mirror_locker_state())`)、②**heartbeat で60秒ごとに定期**(`sync.py` の `heartbeat_loop`→`_mirror_lockers`)。②により**無操作の端末や再起動/デプロイ直後でも**管理画面がロッカーを表示できる（操作を待たずに埋まる）。`locker_store.py` は OTA 配布対象(`MANAGED_FILES`/backend `BUNDLE_FILES`、変更時は再起動)に含める。置き配通知は backend `/kiosk/lockers/{id}/notify-delivery` 経由（**DB非依存で発火**・オフライン時はキュー→再接続で再送）。GPIO開閉(`pulseLocker`/`forceLockLocker`=`/device/locker/{door}/open`・`/state`)は従来どおり。
  - **通知だけは MOCK でも実経路（`_isRealNotifyPath`）**: mock でも「通知を発火する呼び出し」＝`/proxy/reception`（受付通知）・`/proxy/reception/{id}`（OK/NG応答ポーリング）・`/proxy/call-staff`（配達呼び出し）は**実バックエンドを叩く**（`apiFetch` が `_realFetch` を優先）。（※置き配通知はローカルファースト化で `/device` 経路へ移行）実トークンが無ければ `_ensureRealToken` が agent 経由で `/register` して取得。到達可能な agent/バックエンドが無い（完全オフライン）場合のみ mock にフォールバックしてUIプレビューを維持。→ **mock で見た目を確認しつつ、スマホへの実プッシュ通知もテストできる**。`bootMock` は既存の実トークンを温存する。MOCKバッジは「通知のみ実送信」と明記。
  - **完全オフラインプレビュー（`?mock=1`・明示オプトイン＋記憶）**: `kiosk.html?mock=1` で `mockFetch` が（上記の通知系を除く）APIをスタブし、バックエンド/agent 無しで全画面フローを確認できる。**一度 `?mock=1` を付けると localStorage(`mokuture_kiosk_mock`) に記憶し、以降はパラメータ無しでもモックのまま起動**（ローカルUIプレビューで毎回付けなくてよい）。解除は `?mock=0`。**環境(ホスト名等)による自動有効化はしない**（＝過去の「mockが実データを握りつぶす」不具合を回避）—あくまで明示オプトインの記憶で、常時表示のMOCKバッジで状態が一目で分かる。この時のみ有効:
    - MOCKロッカー: A/C=空き、B=利用中(解錠PIN `1234`)。QR画面の「（MOCK）予約QRを読み取ったことにする」で歓迎画面＋館内マップを確認可。
    - **固定ダミーデータ**: `mockFetch` は管理画面設定を参照せず固定値を返す。`/proxy/appointment/*` は常に「（MOCK）商談ルーム A / 2階」＋組み込みSVG地図＝**管理画面の地図とは一致しない**（仕様。実データ確認は上記の実経路手順で）。
    - **MOCKバッジ**: `showMockBadge()`(`bootMock` で呼ぶ)が上部中央に固定の「MOCK モード…」バッジを常時表示し、ダミー表示だと一目で分かる（`body`直下・`pointer-events:none`で操作を妨げない）。通常起動(実経路)では出ない。
  - **体験版（開発環境の無い人へ送る用・`kiosk_agent/scripts/build_kiosk_preview.py`）**: `kiosk.html` を読み、jsQR とタップ音を埋め込んだ **1 ファイルの HTML** と `使い方.txt` を `dist/kiosk-preview/`・`dist/mokuture-kiosk-preview.zip`(gitignore 済み)に作る。受け取った人はダブルクリック(file://)で開くだけ。`?mock=1` と違い **MOCK を常に有効・通知も実経路を試さない(どこにも送らない)**。待機画面に「クリックで始まる」案内、QR 代用ボタンを読める大きさに、バッジを「体験版」にする。**`kiosk.html` 本体は書き換えない**(文字列の目印を差し替えた写しを作るだけ)。目印が `kiosk.html` から消える・増えるとスクリプトが止まるので、そのときはスクリプト側の目印を直す。`kiosk.html` を変えたら作り直して送り直す。
- **reception（フォーム・`showReception`）**: 左=入力フォーム / 右=**画面内蔵の五十音ソフトキーボード**の1画面(OS標準キーボードは使わない)。お名前(必須)/会社名/**部署**/担当者名。**部署**は管理画面「受付設定」の `department_list`(公開設定 `department_list` 配列)が登録されているときだけドロップダウン(`f-dept` select)で表示し、`form.department` にセット。未登録なら部署欄は出さない。担当者とは独立の選択項目で、送信ペイロード `department` と `showCalling` の「部署：」表示に伝搬。キーボードは**列＝行(あ/か/さ…)の五十音表**(`HIRA_ROWS`, null=や・わ行の空きマス)＋コントロール行(撥音**ん**・濁点**゛**・半濁点**゜**・**小**文字・長音**ー**・スペース)。濁点/半濁点/小文字は`modifyLast()`で直前1文字をトグル(ひら・カナ両対応の`DAKUTEN`/`HANDAKU`/`SMALL`マップ)。ひらがな/カタカナ(表を変換)/ABC(`ABC_ROWS`, A→Z)を切替＋「株式会社」「⌫」。**ご用件は5択の選択形式**(チップ: 管理画面 `purpose_list` があればそれ、無ければ既定「ご予約のあるお客様/お打ち合わせ/納品/採用面接/その他」)＋注記「※営業・セールス・勧誘等のご訪問はお受けしておりません」。チップ選択は `form.purpose` 更新＋チップのスタイルのみ差し替え（テキスト入力を再描画しない）。送信→`method:"form"` で `calling`。
  - **漢字変換(かな→漢字)**: 五十音キーボードに「変換」ボタンがあり、入力欄末尾の「読み(かなの連続 `KANA_RUN`)」を漢字候補に変換する。候補は**フローティングの候補パネル**(`kb-cand-pop`)に折り返しグリッドで一括表示(横スクロールにしない。件数表示・太めスクロールバー・背景/「閉じる」/候補タップで確定)。段階変換対応(`やまだ`→山田、続けて`たろう`→太郎=山田太郎)。変換は**agentローカルの `GET /device/convert?kana=…&limit=`**(`kiosk_agent/kana_kanji.py`)で、同梱 `kana_dict.tsv`(約160語:姓名/会社/受付語彙。SKKより優先)＋全面辞書 `SKK-JISYO.L`(約13万語, **資産としてリポジトリ同梱**=commit済み。`.gitattributes` でバイナリ扱い。万一欠けていれば agent 起動時に自動DLする自己修復付き)を辞書ルックアップ＋貪欲分割。**オフライン・OS IME不要**(fcitx5/mozc/squeekboard を入れない。approachがOS非依存)。**本実装は device版 `kiosk.html` のみ**(web版 `KioskFlow.tsx`/`JapaneseKeyboard.tsx` は別実装で未対応)。agent不通時は かな/カナ にフォールバック。上限は API 既定60/最大100、フロントは100要求。実装メモ: `kiosk_agent/IME-EXPERIMENT.md`。
- **QR読取**: `welcome`(統合)に統合。`parseQR()` は **`appt:<token>` / `name` パラメータ付きURLのみ受付**、未対応/エラーは `pauseScan()` でメッセージ＋クールダウン。`scanLoop` は ≈8fps 間引き、`getUserMedia` は `disposed` フラグで teardown ガード。
- **resultPhone（電話案内・`showResultPhone`）**: スタッフ「電話(対応不可)」応答時。`ST.kiosk_phone_number` を大きく表示（未設定時は「受付までお声がけください」）。一定時間で idle 復帰。
- **resultDecline（営業お断り・`showResultDecline`）**: スタッフ「お断り」応答時。「営業・セールス等の…ご協力をお願いいたします」＋「お問い合わせフォームよりお願いいたします。受付でのお取次ぎは行っておりません」＋`ST.inquiry_qr`(SVG data URI, backend生成) の問い合わせフォールQRを表示。未生成時はURL文字列で代替。一定時間で idle 復帰。
- **feedback（受付完了後アンケート・`showFeedback`）**: **お断り(resultDecline)以外のすべての終了パターン**の直後に表示する（受付/電話/歓迎画面/ロッカー完了/配達完了）。`goAfterResult()` が1か所で判定する。3問を1問ずつ・大きなボタンで、**すべて任意回答**。常に「回答せず終了」を出し、1問 20 秒（`FEEDBACK_QUESTION_SEC`）で自動終了する。保存されるのは **質問IDと回答コードだけ**（`clarity`/`confidence`/`assistance`。自由記述は無い）。未回答は `unknown` 扱いで、**行動ログからスタッフ支援の有無を推測しない**。**出すのはモニターのテナント(`ST.is_monitor`)だけ**（運営パネルで切替・既定オフ。2026-11-18〜。それまでは全テナントに出ていた）。端末単位で止めるには localStorage `kiosk_feedback="off"`。`?mock=1` では出さない。
- **complete（歓迎画面「お待ちしておりました」）**: 氏名と「様」を同サイズでインライン表示。予約情報を拡大表示。QR受付で行き先（会議室）が確定し、かつその会議室に `map_image_url` が登録されている場合のみ館内マップを表示（`go("calling"/"complete", { name, staff, room, scheduledAt, method })` でデータを伝搬）。
- **キオスク設定（スタッフ専用・`showKioskSettings`）**: 画面**左上＋右上の同時タッチ**（または `Ctrl+Shift+M`）で開く。上部の**タブで「設定」/「デバイスチェック」を切替**（統合済み）。
  - **設定タブ**: 音量スライダー＋サウンドON/OFF（タップ音, `/device/volume`）、Wi-Fi（`/device/wifi/networks|connect|toggle`）、**ロッカーの口数(3口/7口)選択**（`/device/locker-config`。増設時に設置者がタッチで切替＝JSON編集不要）、ロッカーの鍵 全解除（`/device/lockers/open-all`）、フッター端末名の**5連タップで再登録**。
  - **デバイスチェックタブ**: `getUserMedia` による**カメラ・ライブプレビュー**、Web Audio(AnalyserNode) の**マイク音量レベルメーター**、`GET /device/status`（1.2s ポーリング）に基づく **PIR/ドア/電子錠を緑(ON/正常)・赤(OFF/異常)のトグル表示**（電子錠トグルは `POST /device/locker/{id}/state`、開錠テストは `/pulse`。委譲クリックで捕捉）。旧 device-control の「DEVICE」情報パネルは非表示。カメラ/マイクのストリーム・AudioContext・rAF・ポーリングは画面離脱/タブ切替で確実に停止（**世代トークン `dcGen`** で teardown 後に解決した in-flight `getUserMedia` も解放）。右の列の先頭に **「センサー・電子錠の接続」カード**(GPIO が実機か模擬か。`/device/status` の `gpio: {hardware, reason}`、reason=`env`(MOCK_GPIO=true)/`no_library`(gpiozero が入らない)。**gpio.py は gpiozero を import できないと黙って模擬に落ち、ドアは常に「開放中」・電子錠はトグルの表示だけ変わる**ので、それを画面で分かるようにした。`mock_gpio` も env だけでなく実際の状態を返す)。install.sh は本体→card→(Pi なら)rpi を別々に入れ、Pi で GPIO が入らなければ大きく警告する(以前は rpi が失敗しても card が入れば黙って進んでいた)。カメラの下に **「ソフトウェア更新」カード**(OTA の届き具合。開くたびに `POST /update-check`、以降 10s ごとに `/update-status`。→「キオスク OTA 配信」節)。
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

**キオスク「最初の画面に戻る」ボタン（全画面共通・`kiosk.html`）**: 「← 戻る」(一つ前へ戻る)とは**別に**、どの画面からでも待機画面(`idle`)へ即戻れる導線を**来訪者向け全画面の右上に統一配置**する。共通ヘルパで生成・配線する（個別に書かない）:
- 生成: `homeBtnHtml(id)` … ラベル「最初の画面に戻る」＋`ICO.home`。スタイルは戻るボタンと同系の中立ピル（`padding:24px 44px;font-size:30px;border-radius:999px;background:${T.canvas};border:2px solid ${T.borderStrong};color:${T.sub}`）。
- ヘッダの無い画面（呼び出し中/結果/完了）は `homeBtnCornerHtml(id)`（画面ルートを`position:relative`にし `top:28px;right:80px;z-index:5` で右上に絶対配置）。
- 配線: `render()`/描画直後に `bindHomeBtn(id)` を呼ぶ（`cleanup(); go("idle")`。各画面は自身の後始末を`CLEANUPS`に積むので teardown は cleanup 任せでよい。welcome のカメラ停止等も網羅）。
- 配置済み画面と id: welcome=`wel-home` / top=`top-home` / reception=`rec-home` / lockerMode=`lm-home` / locker(shell)=`lk-home` / delivery(shell)=`dl-home` / calling=`cal-home` / resultOk=`ok-home` / resultPhone=`ph-home` / resultDecline=`dc-home` / complete=`cmp-home`。**新画面を足したら同様に右上へ追加すること。**
- ヘッダのある画面（welcome/top/reception/lockerMode/locker/delivery）は既存のヘッダ行を `display:flex;align-items:center` にして `<div style="flex:1"></div>` のスペーサ後に置く（左＝「← 戻る」、右＝「最初の画面に戻る」）。
- **対象外**: `idle`(=最初の画面自身)・`pending`(承認待ち)・`suspended`(停止中)・`kiosk-settings`(スタッフ設定)。

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
- 現在の設定メニュー: 通知設定 / **カレンダー連携** / **受付設定** / 基本設定
- **通知設定(`notify`)** に「担当者ごとの通知先」カード(`StaffRoutesPanel`)がある。行は「受付設定」の担当者リスト(`staff_list`)から生成するので、**担当者を増減したら両画面が連動する**(消えた担当者の設定は `orphan` として残り、注意表示つきで編集/解除できる)。
- 運用メニューに **ロッカー**(`locker`)を配置。ローカルファースト化後は**読み取り専用の「ロッカー状況」ビュー**(`admin/locker/page.tsx`、`GET /lockers/status`、端末ごとにグルーピング・15s自動更新)。旧DBモデル前提のCRUD(作成/削除/開錠/施錠)は廃止し、施錠・解錠・PINは各キオスク端末で管理(端末が真実の源)。`NavId`/`NAV_OPS`/`NAV_PATHS`/`NavIcon` の4箇所に配線済み
- 運用メニューに **問い合わせ**(`inquiries`)を追加（`AdminShell` の `NavId`/`NAV_OPS`/`NAV_PATHS`/`NavIcon` の4箇所を更新済み）。
- **受付設定(`kiosk-settings`)** に「受付電話番号(`kiosk_phone_number`)」「問い合わせフォームURL(外部・任意, `inquiry_form_url`)」を追加。
- **メニュー遷移中インジケータ**: サイドバーの `NavItem` クリックは `router.push` を `useTransition` でラップし、遷移完了(遷移先ページ描画)まで `isPending` を取得。クリックした項目を即ハイライト＋回転スピナー(`mkNavSpin`)、トップバー直下に不定進捗バー(`mkNavBar`)を表示して「遷移中」を明示する。`AdminShell` は各ページ内でマウントされる(永続レイアウトではない)ため、遷移中は旧ページの `AdminShell` がインジケータを保持し、遷移先で新 `active` の `AdminShell` に差し替わる。同一ページのクリックは `if (id === active) return;` で早期 return(無駄な遷移/スピナー滞留を防止)。モバイルはメニュー選択でドロワーを閉じる。
- **受付設定はCanva風WYSIWYGに刷新**: 実キオスク画面(kiosk.html)を1920×1080で忠実に再現した5画面プレビュー(待機/ようこそ/受付メニュー/呼び出し中/完了)を`ScaledCanvas`で縮小表示し、`Editable`(contentEditable, onBlurでcommit)で文言を画面上から直接編集する。編集対象=`kiosk_welcome_message`/`kiosk_sub_message`/`kiosk_menu_title`/`kiosk_welcome_qr_guide`/`kiosk_welcome_form_label`/`kiosk_calling_message`/`kiosk_complete_message`。ロゴは受付メニュー画面で`logo_pos_x/y`(画面比)・`logo_width_pct`(画面幅%)をドラッグ/ハンドルで調整=kiosk.html `showTop` の絶対配置ロゴに実配線。旧プレビューの誤り(存在しない4タイル「QR受付/配送/その他」)を廃し実機の3タイル(ご訪問/荷物の配達/ロッカー)に一致。数値・電話番号・スタッフ/来訪目的/**部署**リストは下部の補助フォーム(部署リスト=`department_list`。1行1部署のTextareaで登録。空なら受付フォームに部署欄を出さない)。**以前プレビュー限定で実機未使用だった `kiosk_calling_message`/`kiosk_complete_message`/`logo_pos_*` を kiosk.html に配線して同期を回復した。**

### 管理画面のモバイル・レスポンシブ

管理画面(`AdminShell` 配下の全ページ)は幅 320–767px のスマホでも横あふれ・見切れなく表示・操作できるようにする。`AdminShell` はモバイルでサイドバー→ハンバーガー化済み(`adm-sidebar`/`adm-hamburger`/`adm-topbar`/`adm-content`)。**各ページのコンテンツは固定幅/固定列グリッドを直書きせず、`globals.css` の共通ユーティリティを使う**こと:

- `.adm-autofit` / `.adm-autofit-sm` / `.adm-autofit-lg` — カード/KPI/統計/クイックリンク等の自動折返しグリッド(`repeat(auto-fit, minmax(160/120/240px, 1fr))`、gap内蔵)。**インラインの `display:grid`/`gridTemplateColumns`/`gap` の代わりに使う**(併記時は grid 系インラインを削除)。
- `.adm-scroll-x` — 横長のテーブル/タイムライン/カレンダーを**その要素の中だけ横スクロール**させるラッパー(`overflow-x:auto`)。`<table>` は必ずこれで囲み、テーブルに `minWidth`(列数×約90px)を付けて潰れ防止。ページ全体はズレない。
- `.adm-toolbar` — 検索+フィルタ+アクションの行(`flex-wrap`)。中の検索ボックス等は `maxWidth:<元値>, width:"100%", flex:"1 1 220px", minWidth:0` で可変化。
- `.adm-cols-2` — 2カラムのフォーム/詳細グリッド(640px以下で1カラム、gap内蔵)。子の `gridColumn:"span 2"`/`"1 / -1"` は1列化後も破綻しない。
- `.adm-bulkbar` — 画面下部 `position:fixed` のアクションバー(767px以下で折返し+padding調整)。
- `.adm-modal` — ピクセル固定幅モーダルの幅上限(767px以下 `max-width:calc(100vw-24px)`)。個別に `maxWidth:"90vw"` を付けても可。
- 既存の `.adm-grid-2/3/4/5/main/locker/kiosk-settings` も 767px で縮む。

**新しい管理画面ページ/UI を追加するときは、固定 `gridTemplateColumns`・固定幅入力・生の `<table>`・折返さないツールバー/下部バーを避け、上記ユーティリティを使うこと。** ルート `viewport` は `width=device-width` 設定済み(`app/layout.tsx`)。キオスク受付設定の 1920×1080 `ScaledCanvas` プレビューは `transform:scale` でコンテナ幅に縮小されるため**内部は固定サイズのままでよい(触らない)**。

### 秘密情報の暗号化
- Slack/Chatwork Webhook URL は `services/crypto.py` (Fernet) で暗号化して DB 保存。
- `ENCRYPTION_KEY` 環境変数が必須。

### Slack OAuth 連携（「Slackに追加」= Bot Token + chat.postMessage）
顧客が Bot Token を手入力せず、Slack を認可して mokuture 側で通知先チャンネルを選ぶだけで連携できる方式。SPA(Netlify)+API(Render) 分離構成に合わせ、仕様書の `/admin/slack/*` を `/api/notifications/slack/*` に読み替えて実装。**Incoming Webhook ではなく Bot Token で `chat.postMessage` 送信する**（チャンネルは認可画面ではなく連携後に mokuture 側で選ぶ）。

- **フロー**: 管理画面「通知設定」の **[Slackに追加]** → `GET /notifications/slack/oauth/url`(JWT) が署名state付き認可URLを返す(scope=`chat:write,channels:read,groups:read,channels:join,im:write,users:read`) → SPA が `window.location` で Slack へ遷移 → 顧客が許可 → Slack が `GET /notifications/slack/callback`(未認証) へリダイレクト → `SlackNotifier.exchange_code`(`oauth.v2.access`) で **Bot Token(`bot_access_token`,`bot_user_id`,`team`)** を取得・暗号化保存(チャンネル未確定) → `{web}/{slug}/admin/notify?slack=connected` へ302で戻す。管理画面はマウント時に `?slack=` を読んでバナー表示＋`GET /notifications/slack` で状態再取得。
- **チャンネル選択(連携後)**: `connected && !channel_configured` なら管理画面がチャンネル選択UIを表示 → `GET /notifications/slack/channels`(`conversations.list`) → 選択 → `POST /notifications/slack/channel {channel_id}`(公開ch未参加なら`conversations.join`)→ `channel_id/channel_name` 保存。「チャンネル変更」で再選択可。
- **DM(個人)も宛先にできる**（issue #1 追記分）。同じ `<select>` に「ダイレクトメッセージ」optgroupで Slack メンバー(`GET /notifications/slack/users` = `users.list`, scope `users:read`)を並べ、選ぶと `POST /notifications/slack/channel {user_id, display_name}` → `SlackNotifier.open_dm`(`conversations.open`, scope `im:write`)で得たDMチャンネルID(`D...`)を**普通のチャンネルIDと同じ `channel_id` に保存**する。送信は既存の `chat.postMessage` のままで追加スコープ不要（DMを開く一回だけ `im:write` が要る）。担当者ごとのSlack先(`StaffRoutesPanel`)も同じ仕組み(`PUT /notifications/staff-routes` に `slack_user_id`/`slack_display_name`)。
  - **スコープを増やすと既存の連携には後から付与されない**。① Slack App(api.slack.com) の **Bot Token Scopes に `im:write`/`users:read` を追加**(要ユーザー作業)。② 既に連携済みのテナントは、古いBot Tokenにこのスコープが無いため DM関連の呼び出しが `missing_scope` で失敗する → API は 400 で「「Slackに追加」でもう一度連携してください」と返す(`_slack_scope_error`)。**チャンネル指定・既存の受付通知は旧スコープのままでも動き続ける**（影響は新規にDMを選ぶ操作だけ）。
  - DM先の表示名(`channel_name = "DM: <name>"`)はDM作成時に一度だけ解決して保存する。既存のSlack設定を変えずに他の項目だけ保存したときは、`conversations.info` を呼び直さない（呼ぶと `D...` ID は追加スコープ(`im:read`)が無く失敗し、名前が生のIDへ戻ってしまうため）。
- **state = 署名JWT(`services/auth.create_slack_state_token`, type=`slack_oauth`, TTL10分, tenant_id + 乱数jti)**。サーバ側セッション保存は不要（state自体がtenant紐付を担保）。callback は未認証だが `verify_slack_state_token` で tenant を特定するためテナント越境不可。無効/期限切れstateは何も更新せず error リダイレクト。
- **保存先は既存 `notification_settings`(type=`slack`) を拡張**（専用テーブルは作らない＝マイグレーション不要）。再連携は上書き（`_upsert_setting`）。旧・手入力 `{webhook_url}` の row も送信は後方互換で動く。
- **送信は `SlackNotifier.send_to_config(config, text)` に集約** — `{bot_access_token, channel_id}` があれば `chat.postMessage`(未参加の公開chは`not_in_channel`時にjoinして1回リトライ)、無ければ旧 `{webhook_url}` にフォールバック。受付(`kiosk._notify_slack`)・配達(`_notify_slack_text`)・テストの全経路が同関数を通る。将来の DM・複数チャンネル・テンプレート・Teams/LINE WORKS 拡張の継ぎ目。
- **セキュリティ**: `bot_access_token` / Client Secret / Webhook URL は**ログ出力・画面表示・APIレスポンス一切なし**。`GET /notifications/slack` は team_name/channel_name 等の非機密のみ返す。**env(SLACK_CLIENT_ID/SECRET/REDIRECT_URI)未設定時は機能無効**(`slack_oauth_enabled`)＝ oauth/url は `{enabled:false}`、callback/channels/channel は 404/400。
- **エラー**: Slack送信失敗でも受付は止めない(best-effort)。失敗は `logger.warning` で残すが**秘密情報は出さない**(exc_infoも付けない)。Bot連携済だがチャンネル未選択の受付は「エラー」ではなく静かにスキップ。テスト通知(`POST /notifications/test/slack`)はチャンネル未選択なら 400 で促す。
- **受付通知文面**(`SlackNotifier.build_reception_message`): `:bell: 来客がありました` + 会社名/お名前 様/訪問先/時刻(JST)。会社名・訪問先は空なら行を省略（最低=お名前+時刻）。
- **Slack App設定**: OAuth&Permissions に `SLACK_REDIRECT_URI` を Redirect URL 登録、Bot Token Scopes に `chat:write`/`channels:read`/`groups:read`/`channels:join`/`im:write`/`users:read`。非公開チャンネルへ通知するには事前に Slack で Bot をそのチャンネルへ招待。連携解除(`POST /notifications/slack/disconnect`)は自テナントの設定削除のみ（Slack側App削除まではPhase1では必須にしない）。

### Google カレンダー連携（来社予定 ⇔ Google カレンダー。2026-11-19）

管理画面「カレンダー連携」(`/{slug}/admin/calendar`・設定メニュー)で、テナントに **Google アカウントを1つだけ**結び、**同期するカレンダーを1つ**選び、**方向をどちらか一方**選ぶ。実装は `services/google_calendar.py`・`api/calendar_integration.py`・`models/calendar_integration.py`。テストは `backend/tests/test_google_calendar.py`(Google は偽物に差し替え)。

- **OAuth は Slack と違い、戻りを画面で受けてログイン中の管理者が仕上げる**。署名 state(`create_google_state_token(tenant_id, user_id)`・type=`google_calendar_oauth`・10分)を付けて Google へ → Google は **画面の `/google-calendar/callback`**(`GOOGLE_REDIRECT_URI`)へ戻す → 画面が JWT 付きで `POST /oauth/complete` → **state の利用者と JWT の利用者が同じときだけ**コードを交換してトークンを Fernet 暗号化保存。Slack のような未認証の callback で保存すると、他テナントの管理者が作った認可 URL を踏まされた人のカレンダーがそのテナントへつながってしまう(ログイン CSRF)ため。`google-calendar` はテナントの slug に使えない(`accounts.RESERVED_SLUGS`)。認可 URL は `prompt=select_account consent`(「別のアカウントに切り替える」で必ず選択画面を出す)。スコープは `calendar.events`(予定の読み書き)と `calendar.calendarlist.readonly`(カレンダー一覧)だけ。`access_type=offline`+`prompt=consent` で refresh_token を必ず受け取る。Google の同意画面は項目ごとにチェックを外せるので、**どちらかが欠けたら保存せず `?google=scope`**。アカウントのメールはメインのカレンダーの ID(`calendarList/primary`)から取る。**SDK は入れない**(httpx で REST)。
- **「マイカレンダー」**: カレンダー一覧は Google の画面と同じく、連携したアカウントがオーナーのもの(`accessRole=owner`、メインを含む)を「マイカレンダー」、それ以外を「他のカレンダー」に分けて出す。書き出し(to_google)は owner/writer のカレンダーだけ選べる。
- **日時**: 来社予定の `scheduled_at` は **JST の壁時計(naive)**。Google へは `+09:00` 付き・`timeZone=Asia/Tokyo` で送り、Google からは JST に直してから tz を外す(9時間ずれをテストで見張っている)。新しく足した時刻の列(`last_synced_at` 等)は従来どおり naive-UTC。
- **mokuture → Google(`to_google`)**: 来社予定の作成・変更の直後に `BackgroundTasks` で1件送る(`push_appointment`)。**イベント ID は予約の UUID からハイフンを抜いた値**(base32hex の範囲内)＝送り直しても二重にならない。409 なら上書きに回す。イベントには `extendedProperties.private.mokuture_appointment_id` を付ける。**QR の予約コード(token)はイベントに入れない**(カレンダーの共有先へ渡さない)。送れなかった予定は `gcal_sync_state="error"` のまま残り、定期同期が送り直す(再デプロイで BackgroundTasks が消えても取りこぼさない)。削除は `calendar_event_tombstones(kind=delete)` に残してから消す(**作成直後でまだイベント ID を記録していない予定も、予約から決まる ID で消しに行く**＝送信中に消されて Google に孤児が残るのを防ぐ)。書き出すのは**前日以降の予定だけ**。**Google から取り込んだ予定(`gcal_origin="google"`)は書き出さない**(相手の元の予定を書き換えないため)。書き出し先のカレンダーを変えると、前のカレンダーのこれからの予定を消して新しい方へ書き直す。担当者の改名(`staff_routes.rename`)は書き出し済みの予定を `pending` に戻して説明欄を書き直させる(取り込みの既定の担当者 `default_staff` も追随)。
- **Google → mokuture(`from_google`)**: 定期同期(`google_calendar_sync_interval_sec`・既定300秒)と「今すぐ同期」で、**前日〜90日先**のイベントを `singleEvents=true`+`showDeleted=true` で読み、`(tenant_id, gcal_event_id)` で upsert する。**取り込む条件**: 時刻のある予定(**終日は取り込まない**)・`import_keyword` をタイトルに含む(空=全部。画面の初期値は「来社」＝空にすると社内の会議まで来社予定になるため)・**予定の色が `import_colors` のどれか**(2026-11-19 追加。Google カレンダーで予定に付けた色＝イベントの `colorId` 1〜11、付けていない予定は `default`。名前と色は Google の画面に合わせて `services/google_calendar.EVENT_COLORS` に持つ＝API の `/colors` は古い淡い色を返すため。空=色で絞らない。**言葉と色の両方を入れたら両方に合う予定だけ**)・自分が「いいえ」と返事していない。`eventType` が default 以外(不在・集中時間・勤務場所・Gmail からの予定)は取り込まない。タイトルから取り込みの言葉と、それを囲む【】[]「」・区切り記号を外したものが `visitor_name`(`visitor_name_from_title`。キオスク・通知に「【来社】B社 田中様 様」と出さないため。何も残らなければ元のタイトル)、場所に会議室名が含まれればその会議室、説明欄(HTML は素の文字にする)がメモ、担当者は `default_staff`。**Google が元なので Google で変わったら取り込み直すのは「お名前・日時・所要時間」だけ。担当者・会議室・会社名・目的・メモは作るとき以外上書きしない**(上書きすると受付の担当者の割り当てが同期のたびに消える)。Google で消された・条件に合わなくなった予定は、**まだ受付していない(pending)ものだけ**消す(受付済みは記録として残す)。期間の一覧に出てこなかった取り込み済みの予定は個別に取り直す(期間外へ延期された予定に追従)。**mokuture で消した取り込み予定は作り直さない**(`tombstones(kind=ignore)`)。**`mokuture_appointment_id` の付いたイベントは新規には取り込まない**(書き出しから切り替えたとき自分の書いた予定を二重に取り込まないため。元の予定があれば結び付けて日時だけ追従)。取り込み元のカレンダーを変えると、前のカレンダーから取り込んだ未受付のこれからの予定を消す(画面で保存前に予告する)。
- **方向の切り替え**: 書き出し→取り込みにしても、書き出した予定は Google に残る。取り込み→書き出しにしても、取り込んだ予定は来社予定に残る(書き出しはしない)。**別のアカウントで結び直したとき、前に選んでいたカレンダーが新しいアカウントからも見えるなら(共有カレンダー)何も外さない**(イベント ID はカレンダーのもの)。見えなければカレンダーの選択と結び付きを外し、そのとき取り込み済みの未受付のこれからの予定は消す(残すと二度と更新されない孤児になり、同じカレンダーを選び直したときに二重に取り込まれる)。**アカウントの確認(`calendarList`)に失敗したら何も変えない**(確かめられないまま「別のアカウント」とみなさない)。解除は Google 側の許可も取り消すが、カレンダーの予定・来社予定はどちらも消さない。
- **連携が切れたとき**: トークンの取り直しで `invalid_grant` が返ったら `status="reauth_required"` にして同期を止め、「カレンダー連携」と「来社予定」の上部に「もう一度連携してください」を出す(黙って止まり続けない)。**Google Cloud の OAuth 同意画面が「テスト」のままだと、refresh_token が7日で失効してこの状態になる**ので、本番では「本番環境」に公開すること(`calendar.events` は機密スコープのため Google の確認(審査)が要る場合がある)。
- **権限**: 連携・設定・今すぐ同期・解除は管理者だけ(`require_tenant_admin`)。状態の参照だけスタッフも可(来社予定画面の表示用)。**来社予定はスタッフも閲覧専用アカウントも操作できるので、その操作も Google へ反映される**。認可 URL は閲覧専用アカウントには出さない(`readonly._RO_BLOCKED_GET`)。
- **同時実行**: テナントごとの同期は `asyncio.Lock`(`tenant_lock`)で直列(定期同期・今すぐ同期・画面操作直後の送信・設定の保存・連携の仕上げが同じ予定を同時に触らない)。想定外の例外も画面の「最後のエラー」に出す(`UNEXPECTED_MESSAGE`)。単一ワーカー前提(複数ワーカー化するなら担当プロセスを決めるかロックを外へ)。
- **画面**: 「来社予定」の上部に連携中の帯(方向・カレンダー名・未送信の数)、取り込んだ予定に「Googleから」、送れなかった予定に「Google未反映」のバッジ。取り込んだ予定の編集画面には「お名前と日時は上書きされる」旨を出す。削除の確認には Google 側がどうなるかを書く。
- **Google Cloud(2026-11-19 設定済み)**: プロジェクト `mokuture-plus`(Calendar API 有効)・同意画面(アプリ名 mokuture+・外部・サポートメール=作成した Google アカウントのアドレス(mokuture@ranasoft.co.jp へ変えたいが、選べるのはログイン中のアカウントか管理している Google グループだけ)・連絡先 mokuture@ranasoft.co.jp・スコープ2つ)・OAuth クライアント「mokuture+ calendar」(ウェブ)。Render に GOOGLE_* 3つ設定済み。**本番公開にはブランディングにホームページ・`/privacy`・`/terms`・承認済みドメイン `mokuture-plus.netlify.app` が要る**。`calendar.events` は機密スコープなので、公開しても Google の確認(審査)が通るまでは「確認されていないアプリ」の警告が出て、新規に連携できるのは100人まで。
- **残り**: 同意画面は「本番環境」に公開済み(ホームページ・`/privacy`・`/terms`・承認済みドメイン登録済み)だが、Google の確認(審査)は未申請。審査にはサービスを説明するホームページ(いまの `/` はログインへ飛ぶだけ)・ドメイン所有確認・デモ動画が要る見込み。env は3つ揃わないと機能は無効(画面は「この環境では使えません」)。**2026-11-19 時点で本物の Google での連携の通し確認は未実施(テストは偽物のみ)**。

### Slack 受付通知の対応ボタン（Block Kit + Interactivity）
受付通知(`_notify_slack`)を **Block Kit 化**し、Slack メッセージ内の 受付/電話/お断り ボタンでスタッフが応答できる。Web Push・管理画面「受付ログ」と同じ `_apply_decision`(冪等)に集約。
- **有効化条件**: `SLACK_SIGNING_SECRET`(env) が設定され、かつ Bot Token 経路(`bot_access_token`+`channel_id`)のとき**のみ**ボタンを付ける。未設定なら従来のテキスト通知（後方互換・無効化）。Webhook 経路はインタラクション不可のため text のみ。
- **送信**: `SlackNotifier.build_reception_blocks(text, actions, token)` が本文セクション＋`actions`ブロック(ボタン)を生成。ボタン `value` に `"{action}|{token}"`(token=`create_decision_token`)。ボタンの選択肢は `reception.decision_actions(log)`（QR予約=受付/電話の2択、非QR=3択、push と共用）。受付=primary/お断り=danger。
- **押下受け口**: `POST /api/notifications/slack/interactions`（未認証）。`_verify_slack_signature`(v0 HMAC-SHA256, `SLACK_SIGNING_SECRET`, 5分リプレイ防止)→`value`の署名トークン検証→`ReceptionLog`特定(テナント越境不可)→`_apply_decision`→`response_url` で元メッセージを「✅ 対応済み：受付/電話/お断り（押した人）」に置換(ボタン除去)。**Slackの3秒制限のため response_url 更新は `BackgroundTasks` で背後送信し即200**。
- **必要な手動設定**: ① Render env に `SLACK_SIGNING_SECRET`(Slack App の Basic Information → Signing Secret) を設定。② Slack App → **Interactivity & Shortcuts を ON**、Request URL に `https://mokuture-plus-api.onrender.com/api/notifications/slack/interactions` を登録。追加スコープ不要(既存 `chat:write` で更新可)。

### 担当者ごとの通知先と代理通知（エスカレーション）

受付通知の宛先は元々「テナントに1つ」だったが、**来訪者がキオスクで選んだ訪問先担当者ごと**に Slack チャンネル / メール / Webhook を割り当てられる。さらに**応答が無いまま時間切れ**になったら、指定した**代理担当者**の通知先へ自動転送する（GitHub issue #1）。

- **宛先の決定は `services/staff_routing.py` に集約**。`resolve_primary(db, tenant_id, staff_name)` が通常の宛先、`resolve_fallback(...)` が代理の宛先を `Destinations{slack_channels, chatwork_rooms, emails, webhooks, push_user_ids, use_default, routed_to}` で返す。`slack_send_configs(default_config, dest)` が実際に `SlackNotifier.send_to_config` へ渡す設定列を組む。
- **送信は `services/reception_notify.py` に集約**。`notify_reception(db, tenant_id, log, stage="primary"|"fallback")` が Slack / **Chatwork** / Web Push / Webhook / メールへ一括ファンアウトする。**キオスク受付(`kiosk.kiosk_reception`)と管理画面からの手動受付(`reception.create_reception`)の両方がここを通る**（以前は両ファイルに `_notify_slack`/`_notify_push` がほぼ同じ形で重複しており、宛先を担当者別に拡張するとズレる一方だったので統合した）。どちらも `BackgroundTasks` で非ブロック送信（メール20s/Webhook5sのタイムアウトを受付経路に持ち込まない）。
- **統合による意図的な挙動変更**: 管理画面から手動作成した受付(`POST /reception`)も、キオスク受付と同じく Slack の対応ボタン(Block Kit)・Webhook・メールが付く（従来は Slack テキスト＋Web Push のみ）。通知も `BackgroundTasks` 化した。
- **Slack は既存の OAuth 連携(Bot Token)を使い回し、チャンネルだけ差し替える**＝**追加スコープ不要**。担当者チャンネルへ送る config は `{bot_access_token, channel_id}` のみにして `webhook_url` を落とす（旧Webhook設定へフォールバックして共通チャンネルへ二重投稿するのを防ぐ）。Bot Token が無い（旧Webhook連携だけの）テナントでは担当者ごとのチャンネル指定は成立しないので黙って捨てる。共通の通知先と同じチャンネルになる場合は重複送信しない。
- **Chatwork も担当者ごとにルームを割り当てられる**（issue #1 追記分）。Slack と同じで**API トークンはテナント共通のものを使い回し、差し替えるのはルーム ID だけ**（担当者ごとにトークンを発行させない）。送信の実体は `services/chatwork.py` に集約。**トークン未設定なら何も送らない**。ルーム ID だけ指定して保存しようとすると API が 400 で拒む（「設定したのに届かない」を作らない）。
- **共通の `chatwork` 設定はルーム未入力でも「連携済」にできる**（issue #1 2026-10-23 追記分）。以前は新規登録時にルームも必須で、ユーザーから「担当者ごとのルーム指定・テスト送信のためだけに連携したいのにルームを強制される／そのルームが何に使われているのか分からない」という指摘があった。`PUT /notifications/settings/chatwork` は トークンだけで保存できる（`_upsert_chatwork`。室未入力は許すが、室が無ければテスト送信は `GET /v2/me` でのトークン確認に留まる）。ルーム未設定時のテスト送信(`POST /notifications/test/chatwork`)は実送信の代わりに `chatwork.verify_token`(`GET /v2/me`)でトークンの有効性だけ確認する。
- **共通カードのルームは受付通知と配達の呼び出しで共有する**。担当者別ルートが未設定、または「共通の通知先にも送る」が有効な受付は、Chatwork全体スイッチがONなら共通ルームへ送る。配達専用の `chatwork_delivery` 書き込み/テストendpointは削除済みだが、旧形式データの読み取りフォールバックは維持する。
- **ルームは手入力ではなく一覧から選べる**（issue #1 2026-10-23 追記分、「ルーム一覧を取得して選択する形式がよい」という指摘への対応）。`POST /notifications/chatwork/rooms`(`GET /v2/rooms` をラップ)がルーム一覧 `[{room_id, name, type}]` を返す。body に `api_token` を渡すと(まだ保存していない入力中のトークンでも)そのトークンで取得する＝Slackの「OAuth後にチャンネルを選ぶ」と同じ体験。空なら保存済みの共通トークンを使う。フロントの `ChatworkRoomPicker`（共通カード／担当者ごとの編集欄の2箇所で共用。配達専用カードは2026-10-24に削除済み）は一覧取得に失敗したときだけ数字IDの手入力にフォールバックする。選んだルーム名は `chatwork_room_name` として（Slackの `slack_channel_name` と同様に）設定へ一緒に保存し、一覧の概要表示に使う。Chatworkは1:1の会話も `type="direct"` のルームとして返ってくるため、これが実質的にChatwork版のDM選択にもなる。
- 受付通知のChatwork宛先は、担当者個別ルームに加え、`Destinations.use_default` が有効かつChatwork全体スイッチがONなら共通ルームも含む。同じルームIDは重複排除する。個別ルームは担当者のセレクト指定を優先するため、全体スイッチがOFFでも送信対象になる。
- **トークンとルームは別々に読む**（`chatwork.load_api_token()` / `load_config()`）。「両方揃った行だけ返す」実装にすると、トークンだけ登録して共通ルームが空のテナントで**担当者ルームへ1通も届かない**（保存時も「未連携です」と嘘の 400 を返す）。一方 `load_config()` は配達用に**最初に見つかった行をそのまま返す**（不完全な行を飛ばして次の候補へ流すと、配達専用ルームを空にしているテナントの配達通知が受付用ルームへ漏れる）。
- **Chatwork の接続設定(テナント共通)は部分更新**。`PUT /notifications/settings/chatwork` は**空欄の項目を現在値のまま残す**。API トークンはレスポンスで `***` にマスクしていて画面の入力欄には戻らないため、素直に上書きすると「**ルーム ID だけ直したい**」という普通の操作でトークンが空になり、Chatwork 通知が丸ごと止まる（担当者ごとのルームも道連れ）。新規登録のときはトークンが必須（空の設定行を作らない。ルームは任意）。
- **来訪者の入力は Chatwork 記法として無害化する**（`chatwork.escape_tags()`）。氏名・会社名はキオスクで打たれた文字列なので、`[/info]` でカードを閉じたり `[To:id]` でメンションを飛ばしたりできないよう角括弧を全角へ寄せる（Chatwork にエスケープ記法は無い）。
- **Web Push は担当者ごとに割れる**（issue #1 追記分）。購読(`push_subscriptions`)は端末ではなく**ログインした管理ユーザー**に紐づくので、`staff_notification_routes.push_user_id` で「この担当者あては誰の端末へ」を結びつける。宛先は `reception_notify.push_targets()`。
- **プッシュ先を指定したら `include_default` が ON でもその人だけに送る**。Slack/Chatwork は「担当者のチャンネル＋共通チャンネル」と足し算に意味があるが、**プッシュの「共通」はテナント内の全購読＝絞り込みの上位集合**なので、足すと担当者ごとの指定が必ず無意味になる（既定が ON なので、そのままでは機能が死ぬ）。指定した人が**まだプッシュを許可していない**（購読0件）ときだけ `include_default` に従って全購読へ落とす。
- **`include_default`（既定 ON・担当者ごとにOFF可）**でテナント共通の通知先へも送るかを決める。OFF かつ `push_user_id` 未設定なら Web Push は送らない（従来どおり）。**代理通知で宛先が絞れないときは `include_default` に関わらず全購読へ送る**（誰も応答していない状態で誰にも届かないのが一番危ないので安全側へ倒す）。代理通知のプッシュは `tag` を `reception-{id}-esc` にして元の通知を上書きしない。
- **ユーザーを削除したら `push_user_id` を NULL に戻す**（`api/users.delete_user`）。本番の `push_user_id` は `ALTER TABLE ADD COLUMN` で足した列で**外部キー制約が無く `ON DELETE SET NULL` が効かない**。残すと画面は「指定しない」と表示するのに実際は宛先が解決できない、という乖離になる。
- **代理通知は「別の担当者を指定」方式・1段のみ**（`fallback_staff_name`）。代理の代理は辿らないのでループしない。代理担当者にルートが無い/宛先が空のときは**テナント共通の通知先へ落とす**（無言の空振りを避ける）。自分自身を代理には指定できない（API が 422）。
- **発火は「受付ごとのタイマー」ではなく定期スイープ**（`services/escalation.py`、15秒間隔、`main.lifespan` が起動・停止）。受付ごとに `asyncio.sleep` する方式だと Render の再デプロイ/再起動で待機中のタスクが消え、**安全網が一番必要なときに黙って効かなくなる**。スイープなら再起動後も未処理ぶんを拾い直せる。対象は **`staff_notification_routes` との JOIN で「代理通知が設定された担当者宛」に限定**したうえで、`state ∈ (received, notified)` かつ `escalated_at IS NULL` かつ `method ∉ (delivery, dropoff)` かつ直近24時間、1周期あたり最大50件。**JOIN で絞るのが重要**: 代理設定の無い担当者宛や担当者未選択の未応答ログは `escalated_at` が永久に NULL のままなので（来客に直接応対して誰も 受付/電話/お断り を押さない受付はそのまま残る）、絞らないと毎周期そちらが LIMIT の枠を先に埋め、本来送るべき受付が永久に選ばれなくなる。cutoff は **naive-UTC** で渡す（SQLAlchemy はモデルの `DateTime(timezone=False)` から `$1::TIMESTAMP WITHOUT TIME ZONE` にキャストするため、aware を渡すと asyncpg 側で壊れる）。**代理通知を設定しているテナントが1つも無ければ JOIN の結果が0件で終わる**（`staff_notification_routes` が空なら走査するものが無い）。担当者名の突き合わせは `func.trim(reception_logs.staff)` で行う——ルート側(`staff_name`)は保存時に必ず strip されるため、受付側に前後空白が残ると**代理通知だけ静かに落ちる**（1通目は `get_route` が strip して引くので届いてしまい原因に気づけない）。新規受付は `ReceptionCreate.staff` / `AppointmentCreate.staff` の strip バリデータで入口から揃え、過去データは JOIN 側の trim で拾う。
- **冪等性は `reception_logs.escalated_at`**。**「まだ未応答・未エスカレーション」を条件にした `UPDATE` で先に確定・commit** してから送る。条件付きなのは、対象を読んでから送るまでの await の間にスタッフが応答を commit しうるため（単一ワーカーでもリクエストは並行する）。更新件数が0なら送らない。**この順序は意図的に at-most-once**＝commit と送信の間でプロセスが落ちるとその1件は送られない。逆にすると送信成功後の commit 失敗で15秒ごとに鳴り続けうるので、鳴りすぎるより取りこぼす側に倒している（通知は全経路 best-effort）。代理通知後は SSE(`{"type":"reception"}`)を publish し、管理画面「受付ログ」に**「代理通知済」バッジ**が即出る。
- **前提: uvicorn `--workers 1`**（Dockerfile。in-memory pub/sub と同じ前提）。複数ワーカー化する場合は、このスイープが各ワーカーで走らないよう担当プロセスを決めるかロックを入れること。
- **文面**: `SlackNotifier.build_reception_message(..., escalated_from=...)` に元の担当者名を渡すと見出しが `:warning: 受付に応答がありません（代理通知）` になり、末尾が「「{担当者}」宛の受付に応答がありません。代わりに対応をお願いします。」になる。メールは `reception_notify.build_reception_email`（来社予定QRメールと同じ和モダンHTML・`?respond={id}` 付きの受付ログリンク）。JST 表記は `services/timeutil.format_jst`（Slack・メール共通。以前 slack.py にあった `_format_jst` を公開名として timeutil へ移した）。
- **管理画面**: 「通知設定」の**担当者ごとの通知先**カード（`StaffRoutesPanel` @ `admin/notify/page.tsx`）。上部の `StaffMasterEditor` で担当者の追加・改名・削除・並べ替えを行い、その下に担当者ごとの行を並べる。行の「編集」でインライン編集（Slackチャンネル/DM・Chatworkルーム・プッシュ先ユーザー・メール・Webhook・代理通知。SlackチャンネルとDM先の候補は `GET /notifications/slack/channels`/`/slack/users` を**編集を開いた時だけ**取得）。プッシュ先の選択肢には**まだブラウザでプッシュを許可していないユーザーに「（未許可）」を付ける**（選べてしまうが届かないため）。**宛先ごとの成否が出るテスト送信**（通常／代理）付き。Slack未連携・SMTP未設定はカード上部で明示する。「設定を解除」は取り消せないので**2段階確認**にしている（JSダイアログ禁止ルールに従いインライン。Slack連携解除と同じ方式）。
  - **`StaffRoutesPanel` は上の「Slack」「Chatwork」カードとは別フェッチ**（issue #1 2026-10-23 追記分）。以前はこのパネルがマウント時に一度 `GET /notifications/staff-routes` を読んだら、後から上のカードで Chatwork を連携したり Slack を解除したりしても再読込しなかったため、「連携したのにこのパネルには未連携のまま表示される」という食い違いが起きた。親(`AdminNotifyPage`)が `staffRoutesRefresh`（単調増加カウンタ）を持ち、Chatworkのトークン保存・Slack連携解除のたびに増やして `<StaffRoutesPanel refreshSignal={...} />` に渡す。パネルは `refreshSignal` の変化を見て `quiet=true` で読み直す（担当者を編集中でも編集欄が閉じない）。Slackの新規連携・チャンネル変更はこのページへの302リダイレクトを経るため元から再マウントで解決していたが、OAuth連携解除は fetch のみなので同様に漏れていた。
  - **「通知対象」チェックボックス(受付完了/呼び出し中/タイムアウト)は削除した**（issue #1 2026-10-23 追記分）。状態も送信先も無く、見た目だけの死んだUIだった。
- **担当者マスターの編集は「通知設定」に集約**（issue #1 追記分）。実体は `tenants.staff_list`（カンマ区切り）のままで、**キオスク設定（受付設定）側は読み取り専用**にして誘導リンクだけ置く。宛先を決める場所と担当者を足す場所が別画面なのは分かりにくいため。API は `PUT /notifications/staff-routes/staff`（リストを丸ごと置換＝追加・削除・並べ替え）と `POST /notifications/staff-routes/staff/rename`。**名前にカンマは使えない**（保存形式が壊れるので 422）。
  - **削除するとその担当者の通知先設定も一緒に消し、他の担当者の代理通知先参照も外す**。残すと「キオスクでは選べないのに代理先として参照され続ける」状態になる。
  - **改名は通知先設定・代理通知先・まだ応答していない受付・登録済みの来社予定まで追随させる**。進行中の受付を旧名のまま残すと、その受付の代理通知が旧名で設定を探して見つけられず、**安全網が黙って外れる**。来社予定の `staff` はキオスク受付時にそのまま `reception_logs.staff` になるので、こちらも追随させないと同じことが起きる。**過去の完了ログは当時の記録なので書き換えない**。追随させる状態の集合(`PENDING_STATES`)と突き合わせ方(`func.trim`)は**スイープと必ず揃える**。
  - **改名先は担当者リストだけでなく「設定行」も見て重複を弾く**。リストから消えても設定だけ残る担当者(orphan)と同名へ改名すると `(tenant_id, staff_name)` が重複し、以後 `get_route()` の `scalar_one_or_none()` が `MultipleResultsFound` を投げて、**その担当者宛の通知が全経路サイレントに止まる**（例外は `fire_reception_notifications` の except に飲まれる）。
  - **`PATCH /settings` は `staff_list` を受け取っても無視する**。画面を読み取り専用にするだけでは、デプロイ前に開かれていた古いタブが受付設定を保存した瞬間に、その時点の古いリストで巻き戻る（しかもこの経路はルートの後片付けをしない）。
  - **担当者リストの更新は楽観ロックで守る**。`GET` が返す `staff_list_version`（リスト内容の sha256 先頭16桁。並び順も含む）を画面が持ち回り、`PUT /staff` と `POST /staff/rename` に送り返す。食い違えば 409。**リストは全置換**なので、2人の管理者が同じ画面を開いていると、古い版のまま保存した側が**相手の追加した担当者とその通知先設定を巻き込んで消す**。`tenants` に `updated_at` が無いのでカラムは足さず内容から版を作る。版の送信は任意（API 直叩きを塞がない）だが管理画面は必ず送る。409 のときは画面側も読み直して最新を見せる。
  - キオスク設定ページは `staff_list` を**PATCH の対象から外した**。読み取り専用にしたまま送ると、そのページを開いた時点の古いリストで上書きしてしまう。
- **後方互換**: 担当者ごとの設定を1件も作らなければ挙動は従来どおり（共通の通知先だけ・代理通知なし）。担当者リストから名前が消えても設定行は残り、一覧に `orphan`（「受付設定に無い担当者」）として出す。
- **配達の呼び出し・置き配は対象外**（`log.staff` が無いので宛先ルーティングは働かず、スイープも `method` で明示的に除外する。従来どおり `_fire_delivery_notifications`）。
- **メールと Teams の通知の「受付/電話/お断り」はログイン無しで返事できる**(→「Microsoft Teams 通知とログイン無しの返事」節)。
- **Webhook ペイロードの変更**: 受付 Webhook に `reception_id` が増え、`created_at` は `iso_z()` の単一 `Z` 形式に揃えた（従来は naive/aware で `...` と `...+00:00` が混在していた）。代理通知では `event` が `reception_escalated` になり `escalated_from`(元の担当者名) が付く。管理画面「カスタムWebhook」のサンプル表示も同じ形に更新済み。

### Microsoft Teams 通知とログイン無しの返事（2026-11-25）

Teams を使う会社でも、担当者が通知からすぐ返事をしてキオスクの来訪者を待たせないための仕組み。あわせて**メール通知も同じ返事の仕組みにした**（以前はメールのリンクがログインの要る受付ログに飛ぶだけで、スマホではログイン画面で止まっていた）。

- **Teams へは「ワークフロー」の Webhook へ Adaptive Card を POST する**（`services/teams.py`）。Teams 側の準備は利用者が行う(チャネルの「…」→「ワークフロー」→「Webhook 要求を受信するとチャネルに投稿する」で URL を作って管理画面に貼る)。Bot・Azure の登録は要らない。送る形は `{"type":"message","attachments":[{"contentType":"application/vnd.microsoft.card.adaptive","content":{AdaptiveCard v1.4}}]}`。**旧方式の Incoming Webhook(コネクタ・`*.webhook.office.com`)は受け付けない**(Microsoft が廃止を進めている)。受け付けるホストは `logic.azure.com`/`powerplatform.com`/`powerautomate.com`(保存時と送信直前の両方で確かめ、`url_safety` も通す)。**ワークフローは受け取っただけで 202 を返す**＝投稿できたかは mokuture からは分からない(テスト送信の文言もそう伝える)。
- **宛先**: 「Teams」カードの URL(`notification_settings` type=`teams`)＝受付(`include_default` が有効な受付・担当者設定の無い受付)と配達の呼び出し・置き配(Chatwork の共通ルームと同じく受付と配達で共有)。担当者ごとの URL(`staff_notification_routes` の `teams_webhook_url`)は全体スイッチ(`channel_enabled_teams`)に左右されない。代理通知・対応済みのお知らせ(`fire_decision_notifications`)も送る。宛先の決定は `reception_notify.teams_targets`。
- **来訪者の入力は `teams.escape_md` で無害化する**。カードの文字は常にマークダウンとして描かれ、素の文字として出す指定が無いので、`[ ] ( ) * _ ~ # < > { } | \ `` ` `` を全角へ寄せ、行頭の箇条書き・改行も潰す(リンク・見出し・太字を作らせない)。
- **カードのボタンはリンクしか開けない**(Webhook 投稿のカードは Teams の中で返事を受け取れない・あとから書き換えられない)。受付/電話/お断り(予約・配達は お断り なし＝`decision_actions`)は**ログイン無しで返事できる画面 `/{slug}/respond#token=…&via=teams&d=accept`** を開く(`services/decision_link.py`)。トークンは Slack ボタン・プッシュと同じ `create_decision_token`(2時間)。**担当者ごとの宛先へ送るトークンには `actor_name`=担当者名**を入れる(「〇〇さんが対応しました」に出る)。共通の宛先は「担当者」。
- **返事の画面は開いただけでは返事にしない**。メール・Teams のセキュリティ機能(Microsoft Defender の Safe Links など)はリンクの中身を勝手に開くので、開いたときは `POST /reception/decision/lookup`(読むだけ)で受付の内容を出し、**画面のボタンを押したときだけ** `POST /reception/decision`(`via=email|teams`)で確定する。トークンは `#` の後ろ(サーバーのアクセスログに残らない)に置き、画面は読んだらアドレス欄から消して sessionStorage へ移す(招待の画面と同じ)。すでに返事が済んでいる/時間切れ/リンク切れはそれぞれ案内を出す。
- **メール**(担当者ごとのメール)にも同じ 受付/電話/お断り ボタン(返事の画面へのリンク・`via=email`)を付け、「受付ログを開く（ログインが必要です）」は控えのリンクにした。
- **分析ログ**: 通知の経路の固定語に `teams` を足した(`analytics_vocab.NOTIFY_CHANNELS` と `kiosk_agent/static/analytics.js` の `notifyChannels` の両方)。
- **画面**: 通知設定に「Microsoft Teams」カード(URL・通知する/しない・テスト送信・解除(2段階)・URL の作り方)、担当者ごとの編集欄に「Microsoft Teams（ワークフローの URL）」。
- テスト: `backend/tests/test_teams_and_decision_link.py`(Teams への実送信はしない)。**2026-11-25 時点で本物の Teams のワークフローでの通し確認は未実施**(投稿までの遅れも未計測。キオスクは 90 秒で電話案内に切り替わる)。

### ユーザー招待（複数アドレスの一括招待メール）

管理画面「ユーザー管理」の「メールで招待」。招待された人がメールのリンクから自分でパスワードを決めて登録する（管理者がパスワードを決めて伝える従来の「パスワードを決めて追加」も残す。SMTP が無くても使える手段なので）。

- **貼り付けの解析は画面側 `frontend/lib/inviteEmails.ts`**（その場でプレビューを出すため）。区切りは 改行 / `,` `;` / タブ / 全角 `、` `，` `；` / 空白。`名前 <addr>` はかっこの中、`mailto:`・引用符は外す、NFKC で全角を半角へ。「@」を含むのに崩れているものは「形式の誤り」として見せ、「@」の無い語(名前)は「読み飛ばした語」として別に出す（黙って捨てない）。**語の中からアドレスの部分だけを取り出し、ASCII だけの厳しい形で判定する**（`services/invitations.STRICT_EMAIL_RE`/`_EXTRACT_RE` と画面側を同じ正規表現にそろえる）。緩い形（`staff_routing._EMAIL_RE`）だと「E-mail:taro@x.jp」「taro@x.jpまで」が通り、SMTP は taro@x.jp へ届けるのに崩れた文字列がログインIDとして保存され、全ユーザーでの重複確認もすり抜けていた（テストエージェントの指摘）。backend は `parseaddr()` で読み直して同じ値になることも確かめる。
- **backend は受け取った一覧を自分でも判定し直し、アドレスごとに結果を返す**（`sent / resent / already_user / invalid / duplicate / failed`。`api/users.py` `POST /users/invitations`）。重複と登録済みは大文字小文字を区別しない（`accounts.email_in_use`＝全テナントのユーザーと重ねない）。このテナントで招待中のアドレスはリンクを作り直して送り直す（前のリンクは使えなくなる）。
- **回数制限は来社予定QRメールと共有**（`mail_quota`、テナントごと1時間30通）。送る件数が残りを超えるときは **1通も送らず 429**（一部だけ送られた状態にしない）。枠は送る前に一度だけ確保する。送信は同時4本（1通最大20秒なので直列だとプロキシの待ち時間を越える）。送れなかった宛先は招待を作らない（送り直しなら前のリンクを残す）。
- **リンクは `{public_web_url}/{slug}/invite#token=…`**。トークンは `#` の後ろ＝ブラウザがサーバーへ送らない部分に置き、画面が公開 API（`POST /auth/invitations/lookup|accept`）へ**本文で**渡す（パスやクエリに載せると Netlify/Render のアクセスログに残る）。DB には sha256 だけ。有効期限は7日（`services/invitations.EXPIRE_DAYS`）。
- **登録(accept)**: 期限切れ・使用済みは 410、取り消し/作り直し済みは 404、招待のあとで同じアドレスが別経路で登録されていたら 409。同じリンクの同時押しでユーザーを2人作らないよう、`accepted_at` を条件つき UPDATE で先に確定してからユーザーを作る。成功すると通常ログインと同じトークンを返し、画面は `saveTokens`（ログイン状態を保持）して `/{slug}/admin` へ。
- 招待の送信・一覧・送り直し・取り消しは管理者(`admin`/`superadmin`)のみ。送るメールの文面は `services/invitations.build_email`（件名のテナント名から改行を除く・HTML は全部 escape）。
- テスト: `backend/tests/test_user_invitations.py`。

### DB マイグレーション
- Alembic は使っていない。backend の起動時に `app/main.py` が `create_all`（新しいテーブル）と `_ENSURE_COLUMNS`（既存テーブルへの列追加）を自動で流す。列を足すときはモデルに加えて `_ENSURE_COLUMNS` にも書くこと（手作業の `ALTER TABLE` は不要）。
- SQLAlchemy モデルと DB スキーマを常に同期すること。

---

## 環境変数

### Backend (.env)
```
DATABASE_URL=postgresql+asyncpg://...
JWT_SECRET_KEY=...
ENCRYPTION_KEY=...           # Fernet key (base64)
PUBLIC_API_URL=https://mokuture-plus-api.onrender.com/api  # プッシュ通知に埋め込む絶対URL(SWがOK/NG応答をPOSTする先)。既定は本番URL
STORAGE_ENDPOINT_URL=...     # R2/MinIO endpoint
STORAGE_ACCESS_KEY_ID=...
STORAGE_SECRET_ACCESS_KEY=...
STORAGE_BUCKET_NAME=...
STORAGE_PUBLIC_URL=...

# Slack OAuth（「Slackに追加」= Bot Token + chat.postMessage）。3つ揃わないと機能無効（settings.slack_oauth_enabled）。
# Bot Token Scopes: chat:write / channels:read / groups:read / channels:join / im:write / users:read
# im:write/users:read は DM宛先(issue #1 追記分)用。Slack App(api.slack.com)側のBot Token Scopesにも
# 追加登録が必要(要ユーザー作業)。追加前に連携済みのテナントはDM関連だけ missing_scope で失敗するので
# 「Slackに追加」で再連携してもらう（チャンネル宛の既存通知は無停止で動き続ける）。
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_REDIRECT_URI=https://mokuture-plus-api.onrender.com/api/notifications/slack/callback

# Slack 受付通知の対応ボタン(Interactivity)。Slack App の Basic Information → Signing Secret。
# 設定時のみ 受付/電話/お断り ボタンを付け、押下(/notifications/slack/interactions)を署名検証する。
# 未設定ならボタン無し(従来のテキスト通知)。Slack App 側で Interactivity Request URL の登録も必要。
SLACK_SIGNING_SECRET=...

# Google カレンダー連携(管理画面「カレンダー連携」)。3つ揃わないと機能無効(settings.google_calendar_enabled)。
# Google Cloud: OAuth クライアント(ウェブアプリ)の「承認済みのリダイレクト URI」に GOOGLE_REDIRECT_URI を登録、
# Calendar API を有効化、同意画面のスコープに calendar.events / calendar.calendarlist.readonly。
# 同意画面が「テスト」のままだと refresh_token が7日で失効する(=連携が切れる)ので本番では公開すること。
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://mokuture-plus.netlify.app/google-calendar/callback   # API ではなく画面の URL(画面がログイン中の管理者として連携を仕上げる)
GOOGLE_CALENDAR_SYNC_INTERVAL_SEC=300   # 任意。取り込みと送り直しの間隔(秒・最小60)

# SMTP メール送信(来社予定QRのメール送信 = 管理画面「来社予定」QRモーダルの「メールで送信」)。
# HOST/USERNAME/PASSWORD が揃ったときのみ有効(settings.smtp_enabled)。未設定なら送信APIは 503。
# 587=STARTTLS(SMTP_STARTTLS=true) / 465=implicit TLS(SMTP_SSL=true, SMTP_STARTTLS=false)。
# Gmail は 2段階認証+「アプリパスワード」を SMTP_PASSWORD に。差出人表示名は未設定ならテナント名。
# 注意: Render は無料/starter プランで送信SMTPポート(587/465)を塞ぐことがある(本番で送信失敗時は経路/プランを確認)。
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=            # 差出人アドレス(空なら SMTP_USERNAME)
SMTP_FROM_NAME=       # 差出人表示名(空ならテナント名)
SMTP_STARTTLS=true
SMTP_SSL=false
```

遠隔ログイン（→「遠隔ログイン」節・`bastion/README.md`）。**HOST / HOST_KEY / SECRET の 3 つが揃わなければ機能は無効**:
```
TUNNEL_BASTION_HOST=          # 踏み台のホスト名(または IP)
TUNNEL_BASTION_HOST_KEY=      # 踏み台の sshd の公開鍵 "ssh-ed25519 AAAA..."(bastion/setup.sh が表示する)
TUNNEL_BASTION_SECRET=        # 踏み台 → API の合言葉(bastion/setup.sh が作って表示する)
TUNNEL_BASTION_PORT=443       # 以下は任意(既定値)
TUNNEL_BASTION_USER=mokuture-tunnel
TUNNEL_DEFAULT_MINUTES=60     # 開けておく時間の既定
TUNNEL_MAX_MINUTES=240
TUNNEL_IDLE_POLL_SEC=60       # 要求が無いとき、端末が聞きに来る間隔
```

> 分析ログ(ANALYTICS.md)にバックエンド専用の追加設定は無い（既存の DB とデバイストークンを使う）。

### Kiosk Agent (.env) — 分析ログ関連（すべて任意・未設定なら既定値）

```bash
ANALYTICS_HEARTBEAT_SEC=60        # ハートビート(device_metrics 1行)の間隔
ANALYTICS_METRICS_SEC=300         # CPU/温度/メモリ等を載せる間隔
ANALYTICS_FLUSH_SEC=15            # スプールのアップロード間隔(失敗時は指数バックオフで最大5分)
ANALYTICS_BROWSER_STALE_SEC=45    # ブラウザのハートビートが途切れたと見なす秒数(app_crashed 判定)
ANALYTICS_BOOT_WINDOW_SEC=180     # 起動時、OS の uptime がこれ未満なら「端末が起動した」と判定
ANALYTICS_MAX_SPOOL_LINES=20000   # スプールの上限行数(種類ごと・超過分は古い順に破棄→log_dropped)
ANALYTICS_UPLOAD_BATCH=200        # 1回のアップロード件数(サーバ上限と揃える)
ANALYTICS_SPOOL_DIR=              # スプールの置き場所(既定 kiosk_agent/analytics_spool/)
```

端末ごとの切り替え（キオスク画面の localStorage）:
`kiosk_feedback="off"` で受付完了後アンケートをその端末だけ止める（アンケートを出すのは運営パネルでモニターにしたテナントだけ）。

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:8001/api
```

## ルール
- **日時・日付を DB の列と比べるときは必ず naive な `datetime` を渡す**（`services/timeutil.py` の `utcnow_naive()` / `day_start()`）。文字列（`"2026-11-01"`）や tz 付きの値を渡すと、SQLite のテストは通るのに本番の PostgreSQL では 500 になる。2026-11-12、運営・代理店の統計と日付絞り込みがこの形で壊れていたのを直した。
- **キオスク画面が端末エージェント経由で backend へ送る項目は、エージェントの受け口（`kiosk_agent/main.py` の `ReceptionBody` など）にも宣言する**。宣言が無い項目は黙って捨てられる（部署と匿名セッションIDが 2026-07-23 から届いていなかった）。
- 修正を行ったら自動でデプロイまで行うこと（`deploy.sh` / `deploy.bat` は 2026-11-12 に削除した。作業ツリーに他の未コミット作業が混ざっているときは、自分の変更だけをコミットする。master への push は本番と全端末への配信になる）
- **見たら分かる画面にする（画面の文言を書く・直すたびに確認すること）**: 画面上の文言が別の設定を指すときは、**その画面に実際に表示されている名前で指す**こと（例:「上の「Slack」カードで選んだチャンネル（#xxx）」）。「受付と同じ」「通常の通知先」「共通」のように、**画面のどこにも書かれていない内部の呼び名**（コード上の `slack` 行＝受付用、のような実装側の区別）で指してはいけない。指される側の画面にも、それが何に使われるのかを書く（例: Slack カードの値の見出しを「受付通知の送信先」にし、「配達で別を選ばなければ配達もここへ届く」と明記）。初めて見た利用者が、ほかの画面やマニュアルを見なくても「どこの何のことか」「何に使われるのか」が分かるかどうかで判断する。2026-10-24、通知設定の配達カードで「受付と同じチャンネル」と書いたが、Slack カードのどこにも「受付用」と書かれておらず指摘された。
- **JavaScriptダイアログ禁止**: `confirm()` / `alert()` / `prompt()` は使用しないこと。確認は独自モーダル、エラーはインライン表示またはトースト通知で実装すること。
- 常に改修後は回収の「意図」通りに修正出来ているかテストエージェントにチェックしてもらってOKを貰ってから報告をする
- **GitHub issue を起点に対応したら、完了後に必ずその issue へ対応結果をコメントで追記すること。** 書く内容は「何ができるようになったか（利用者目線）／注意点・既存挙動の変更／要ユーザー作業（env 追加など）／commit ハッシュ」。**issue はクローズせず追記まで**（クローズの判断は依頼者に委ねる）。`gh` CLI は未インストールなので GitHub REST API (`POST /repos/ranasoft-araki/mokuture-plus/issues/<番号>/comments`) を使う。認証トークンは `git credential fill` (stdin に `protocol=https` と `host=github.com` の2行＋空行を流す) で Git の資格情報マネージャから取り出し、`Authorization: Bearer <token>` で送る＝**トークンは出力・ログに絶対に出さない**。本文は日本語・改行が壊れないよう **JSON ファイルに包んで `curl --data-binary @file`** で POST する。201 が返れば成功で、レスポンスの `html_url` がコメントの URL。
