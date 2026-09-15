# ログデータ収集（実証実験・製品改善分析）— 設計書

> mokuture+ の受付操作ログ（匿名）と端末稼働ログの設計。実装は本書に従う。
> 変更したらこのファイルと `CLAUDE.md` の該当箇所も更新すること。

---

## 0. 何のためのログか

| 目的 | 取るもの |
|---|---|
| 受付1回ごとの連続した行動履歴 | 匿名セッション + 時系列イベント（画面・操作・滞在時間・エラー・結果） |
| Raspberry Pi 受付端末の稼働実績 | 端末イベント（起動/停止/断/復旧）+ 定期メトリクス（CPU/温度/メモリ/接続） |

画面別アクセス数ではなく **1回の受付を後から時系列で再現できること** を最優先にする。
分析画面の作り込みより **後から集計できる正しいデータ構造** を優先する。

---

## 1. 個人情報を保存しない（絶対条件）

分析ログには以下を **一切** 保存しない。

氏名 / 会社名 / 部署 / 電話番号 / メールアドレス / 訪問先担当者名・担当者ID /
入力された文字列 / 検索文字列 / かな漢字変換の読み・候補 / 名刺画像 / 名刺OCR結果 /
音声・音声認識テキスト / カメラ画像 / 顔情報 / QRのトークン / IPアドレス /
Cookie 等の継続的な訪問者識別子 / APIトークン・認証情報・HTTPヘッダ /
個人情報を含むリクエスト・レスポンス本文・スタックトレース

### 保存できるのは「ホワイトリストの列」だけ

`metadata` のような自由入力 JSON 欄は **作らない**。
イベントは §5 に列挙した **固定カラムのみ** を持ち、
サーバ側の Pydantic スキーマが `extra="forbid"` で未知フィールドを **拒否** する。

入力項目については、値ではなく次だけを記録する。

```json
{ "field_id": "visitor_name", "event_name": "validation_error", "error_code": "required" }
```

### キオスク側の追加防御

- ソフトキーボードのキー（`[data-pk]`）と漢字変換候補（`.kb-cand` / `#kb-cand-pop`）は
  **クリックロギングの対象外**（打鍵列から入力値が復元できてしまうため）。
- `<input>` / `<textarea>` / `<select>` の **value は一切読まない**。
  長さも文字種も記録しない（`input_completed` は「入力が終わった」事実のみ）。
- スタッフ専用の `kiosk_settings` 画面は **画面遷移すら記録しない**
  （Wi-Fi パスワード入力などを含むため、丸ごと対象外）。
- 名刺読み取り・QR・音声は「使った / 成功した / 失敗した」だけを記録し、
  読み取り結果は一切送らない。

---

## 2. 匿名セッション（「人」ではなく「受付1回」の識別）

- 受付開始時に **ランダム UUIDv4** を発行する（`crypto.randomUUID()`）。
- 用途は「その1回の操作を時系列でつなぐ」ことだけ。
- **やらないこと**: 同じ人の別日の訪問と結び付けない / 受付情報（`reception_logs`）と結び付けない /
  氏名・会社名・担当者から逆引きできるようにしない / 受付終了後に再利用しない /
  永続的な訪問者IDを発行しない。
- セッションIDは `sessionStorage`（+ 再読込復元用に `localStorage` へ TTL 付きで保持）にのみ置く。
  **Cookie は使わない。**

### 受付ログ（個人情報）との「非結合」をどう守るか

通知の成否は **サーバ側でしか分からない** が、`reception_logs.id ↔ session_id` の
対応表を DB に持つと逆引きが可能になってしまう。そこで:

- `reception_events` / `reception_sessions` に **`reception_log_id` 列は作らない**。
- サーバは `app/services/analytics_link.py` の **プロセス内 TTL マップ（既定2時間・永続化しない）**
  だけで `reception_log_id → (session_id, tenant_id, device_id, ...)` を保持し、
  `notification_*` イベントの発行にのみ使う。プロセス再起動で消える（＝取りこぼすだけ）。
  in-memory 前提は既存の SSE pub/sub（`services/events.py`・単一ワーカー）と同じ。
- `staff_responded` は **ブラウザ側** が「待機画面のポーリングで state が確定した」時点で
  自分で発行する（サーバとの対応表が不要・通知送信からの経過時間もクライアント計測）。

---

## 3. セッションの開始と終了

### 開始（`session_started`）

待機画面（idle）から次のいずれかを最初に行った時点。

| 条件 | `entry_method` |
|---|---|
| 画面タッチ（PIR 検知後の最初の操作を含む） | `touch` |
| QR 受付（`welcome` でQRを検出） | `qr` |
| 名刺読み取り開始 | `card` |
| 音声操作開始（将来） | `voice` |
| スマートフォン受付開始（将来） | `smartphone` |

**PIR（人感センサー）だけでは開始しない。** カメラ・視線検出は使わない。

### 終了

| 終了条件 | `outcome` | 発行イベント |
|---|---|---|
| 受付完了（結果画面・歓迎画面・ロッカー/配達の完了） | `completed` | `session_completed` |
| 利用者のキャンセル・トップへ戻る（ホーム/戻るで idle へ） | `cancelled` | `session_cancelled` |
| 画面を離れた（`pagehide` など、以降イベントが来ない） | `abandoned` | `session_abandoned` |
| 無操作タイムアウト | `timeout` | `session_timeout` |
| アプリ異常終了（前回セッションが未終了のまま再起動） | `app_error` | `session_app_error` |
| 端末再起動 | `device_restarted` | `session_device_restarted` |

**タイムアウト時間は既存仕様を優先**する＝テナント設定 `tenants.kiosk_idle_timeout_sec`
（既定 60 秒 / 10〜300 秒・管理画面「受付設定」で変更可）をそのまま使う。新設しない。

未終了セッションの後始末はサーバ側スイーパー（既定5分間隔・`sweep_stale_sessions`）が行う。
最終イベントから `idle_timeout + 120s` を超えて音沙汰がないセッションを、次の順で畳む:

1. その後に同一端末の **端末起動/再起動/エージェント起動** がある → `device_restarted`
2. ブラウザの `app_crashed` が記録されている → `app_error`
3. いずれでもない → `abandoned`

**`timeout` はブラウザ自身が無操作タイマーで申告したときだけ**使う。サーバから見て
「連絡が途絶えた」状態は、無操作だったのか通信が切れたのか区別できないので `abandoned` にする。

---

## 4. イベント一覧と発生条件

`event_source`: `browser`（キオスク画面） / `backend`（API） / `device_agent`（Pi のエージェント）

### 4-1. セッション

| event_name | source | 発生条件 |
|---|---|---|
| `session_started` | browser | idle から最初の操作（タッチ/QR/名刺/音声/スマホ） |
| `session_completed` | browser | 受付が最後まで進んだ（結果画面到達・ロッカー/配達完了） |
| `session_cancelled` | browser | 利用者がホーム/戻るで idle へ戻した |
| `session_abandoned` | browser/backend | `pagehide` でのフラッシュ、またはサーバ側スイーパー |
| `session_timeout` | browser/backend | 無操作タイマー発火、またはサーバ側スイーパー |
| `session_app_error` | backend | ブラウザの異常終了を検出（端末イベント由来） |
| `session_device_restarted` | backend | 未終了セッション中に端末再起動イベントがある |

### 4-2. 画面

| event_name | 必須項目 | 発生条件 |
|---|---|---|
| `screen_viewed` | `screen_id`, `previous_screen_id` | `go()` で画面を描画した直後 |
| `screen_exited` | `screen_id`, `screen_dwell_ms` | 次画面へ遷移する直前（滞在ミリ秒） |

`screen_id` は `go()` の内部名を snake_case に正規化したもの:

`idle` / `welcome` / `top` / `reception` / `locker_mode` / `locker` / `delivery` /
`calling` / `result_ok` / `result_phone` / `result_decline` / `complete` / `feedback` /
`pending` / `suspended`
（`kiosk_settings` は記録しない＝スタッフ専用・秘密情報を含むため）

### 4-3. 操作

| event_name | 発生条件 |
|---|---|
| `action_selected` | `element_id` を持つ操作要素のタップ |
| `back_selected` | 「← 戻る」ボタン |
| `help_opened` | ヘルプ/案内の展開 |
| `retry_selected` | 「もう一度」「やり直す」 |
| `assistance_requested` | 「受付を呼ぶ」等、人を呼ぶ操作 |
| `noninteractive_area_tapped` | 操作要素に当たらなかったタップ（**座標は保存しない**。`screen_id` のみ） |

`element_id` は **表示文字列ではなく固定ID**。解決順序:

1. 要素の `data-ev="..."`（明示指定・最優先）
2. 最寄りの `button` / `[role=button]` の `id`（既存の `lm-back`, `f-submit` 等をそのまま使う）
3. どれも無い操作要素 → `unlabeled`

除外（記録しない）: `[data-pk]`（ソフトキーボードのキー） / `.kb-cand`（変換候補） /
`input`,`textarea`,`select` の値 / `kiosk_settings` 画面のすべて。

### 4-4. 入力・エラー

| event_name | 保存する項目 |
|---|---|
| `input_started` | `field_id`, `input_method` |
| `input_completed` | `field_id`, `input_method`, `duration_ms` |
| `validation_error` | `field_id`, `error_code`, `screen_id`, `retry_count` |
| `error_recovered` | `field_id`, `error_code`, `retry_count`, `duration_ms`（エラー→解消までの時間） |
| `api_error` | `error_code`, `screen_id`, `result="failed"`, `duration_ms`, `retry_count` |
| `network_error` | `error_code`, `screen_id`, `duration_ms`, `retry_count` |
| `unexpected_error` | `error_code`（JS 例外は種別コードのみ）, `screen_id` |

`field_id`: `visitor_name` / `company` / `department` / `staff` / `purpose` /
`locker_pin` / `locker_select` / `delivery_method` / `qr_scan` / `card_capture` / `feedback`

`error_code`（固定語彙・サーバ側でも検証）:
`required` / `too_long` / `invalid_format` / `pin_mismatch` / `pin_invalid` /
`no_locker_available` / `locker_occupied` / `locker_open_failed` /
`network_unreachable` / `api_4xx` / `api_5xx` / `timeout` /
`camera_unavailable` / `qr_unsupported` / `card_unavailable` / `card_not_detected` /
`agent_unreachable` / `unknown`

**エラーメッセージ本文・入力値・通信本文・スタックトレースは保存しない。**
JS 例外は種別を上記語彙にマップし、未知なら `unknown` に丸める。

### 4-5. 通知・取次

| event_name | source | 発生条件 |
|---|---|---|
| `notification_requested` | browser | 受付送信 / 配達呼び出しを POST した時点 |
| `notification_succeeded` | backend | いずれかの宛先へ送信成功（in-memory link 経由） |
| `notification_failed` | backend | 全宛先が失敗 |
| `notification_retried` | backend | 代理通知（エスカレーション）を送った |
| `staff_responded` | browser | 待機画面のポーリングで state が確定（`result` に accepted/phone/declined、`duration_ms` に通知送信からの経過） |

**担当者名・担当者ID・チャンネル名は保存しない。** 経路は `element_id` に
`slack` / `push` / `webhook` / `chatwork` / `email` の固定語で入れる。

### 4-6. アンケート

| event_name | 保存する項目 |
|---|---|
| `feedback_viewed` | `question_id` |
| `feedback_submitted` | `question_id`, `answer_code` |
| `feedback_skipped` | `question_id`（「回答せず終了」/個別スキップ） |
| `feedback_timeout` | `question_id` |

質問と回答コードは §8 参照。**自由記述は無い。**

---

## 5. イベント共通項目（このリスト以外は保存しない）

```json
{
  "event_id": "5f0d…（クライアント生成 UUIDv4・重複排除キー）",
  "session_id": "受付1回ごとの匿名 UUID",
  "sequence_no": 5,
  "client_occurred_at": "2026-11-10T01:15:32.120Z",
  "client_tz_offset_min": 540,
  "server_received_at": "2026-11-10T01:15:32.380Z",
  "event_source": "browser",
  "site_id": "拠点ID",
  "device_id": "受付端末ID",
  "app_version": "1.0.3",
  "ui_version": "default",
  "flow_version": "visitor-v1",
  "event_name": "validation_error",
  "screen_id": "reception",
  "previous_screen_id": "top",
  "element_id": null,
  "field_id": "visitor_name",
  "input_method": "touch",
  "result": "failed",
  "error_code": "required",
  "screen_dwell_ms": null,
  "duration_ms": null,
  "retry_count": 1,
  "recovered": null,
  "question_id": null,
  "answer_code": null
}
```

- 未使用項目は `null`。
- `client_occurred_at` は **UTC の ISO8601（末尾 Z）** で送る。端末のローカル時刻は
  `client_tz_offset_min`（分）で復元する。DB は naive-UTC で保存（既存方針と同じ）。
- `site_id` / `device_id` / `tenant_id` は **サーバがデバイストークンから確定させ、
  クライアントの申告値を上書きする**（詐称防止）。
- `site_id` は現状 **テナントID と同値**（1顧客＝1拠点の運用）。将来 `sites` テーブルを
  足す場合も列はそのまま使える。
- `ui_version` / `flow_version` は A/B 比較用のラベル。既定は `default` / `visitor-v1`。

---

## 6. 順番の保証と重複排除

- `sequence_no` はセッション内で **1 から連番**。ブラウザが採番し `sessionStorage` に永続化する。
- `event_id` は UUIDv4。DB の **主キー**なので同じイベントが再送されても二重登録されない。
- **端末発生時刻（`client_occurred_at`）とサーバ受信時刻（`server_received_at`）を両方保存**する。
- **サーバは受信順を操作順として扱わない。** 並べ替えは常に
  `ORDER BY client_occurred_at, sequence_no`（端末時刻が同一ミリ秒でも連番で決まる）。
  バックエンド発のイベント（通知の成否）はブラウザの連番と別系統なので `sequence_no = 0` を持ち、
  端末時刻で正しい位置に挟まる。
- 画面再読込後は `sessionStorage` の `session_id`/`sequence_no` を復元し、
  それも失われた場合は `localStorage` の TTL 付きスナップショットから復元する。
  復元できたら続行、できなければ前セッションを `abandoned` として畳んでから新規発行する。

---

## 7. 通信断でログを失わない

```
イベント発生
  → ① ブラウザ IndexedDB(outbox) へ先に保存
  → ② エージェント(localhost)へ POST /device/analytics/events
  → ③ エージェントがディスクスプール(JSONL)へ追記して ack
  → ④ ack された event_id だけ IndexedDB から削除
  → ⑤ エージェントがバックエンドへアップロード（指数バックオフ）
  → ⑥ バックエンドが 200 を返したらスプールから削除
```

- **ブラウザにデバイストークンを持たせない**。ログ送信先は同一オリジンの
  エージェント（`http://localhost:8080`）で、エージェントが `X-Kiosk-Token` を付けて中継する。
- ②が失敗（エージェント停止・アプリ異常）→ IndexedDB に残し、指数バックオフで再試行。
  IndexedDB は Chromium のプロファイルに永続化されるので **再読込・再起動をまたいで残る**。
- ⑤が失敗（顧客ネットワーク断）→ スプールに残す。**順番を維持したまま**（FIFO）復旧後に再送。
- 再送間隔は指数バックオフ: 2s → 4s → 8s … 上限 5 分（±20% のジッタ付き）。
  短時間に大量リクエストを出さない。
- 上限を超えた古いイベントは捨てる（ブラウザ 5,000 件 / スプール 20,000 行・設定値）。
  捨てた件数は `device_events` の `log_dropped` として記録する（本文は残さない）。

---

## 8. アンケート（受付完了後・任意回答）

表示タイミング: **「お断り（declined）」以外のすべての終了パターン**の直後。
受付(accepted) / 電話案内(phone) / 歓迎画面(complete) / ロッカー保管・受取完了 / 配達完了 で表示する。
**お断り画面の後には出さない。**

1問ずつ・大きなボタン・常に「回答せず終了」を表示する。制限時間（既定 20 秒/問・設定可）で
`feedback_timeout` として打ち切り、待機画面へ戻る。

| question_id | 設問 | answer_code |
|---|---|---|
| `clarity` | 操作方法は分かりやすかったですか？ | `very_clear` / `clear` / `neutral` / `unclear` / `very_unclear` |
| `confidence` | 安心して受付を進められましたか？ | `very_secure` / `secure` / `neutral` / `slightly_anxious` / `very_anxious` |
| `assistance` | 受付操作中にスタッフの手助けを受けましたか？ | `none` / `received` |

- すべて任意。未回答は `unknown` として扱い、**行動ログからスタッフ支援の有無を推測しない**。
- 実証先スタッフ・観察担当者に受付ごとの記録作業は依頼しない。
- 回答は `reception_events`（`feedback_submitted`）に加え、集計しやすいよう
  `reception_sessions.answer_clarity` / `answer_confidence` / `answer_assistance` にも保存する。

---

## 9. 端末稼働実績

ブラウザからは取れない OS/ハード情報は **既存の `kiosk_agent`（systemd サービス）** が担当する。
新しいサービス・新しいポートは作らない（`kiosk_agent/analytics.py` として同居）。

### 9-1. 必須（`device_events` / `device_metrics`）

| event_name | 取得方法 |
|---|---|
| `heartbeat` | エージェントが 60 秒ごと（`device_metrics` 行として記録） |
| `device_boot` | エージェント起動時に `/proc/uptime` が短い（既定 180 秒未満）ことで判定 |
| `device_shutdown` | lifespan 終了時（systemd 停止）に記録＋正常停止マークを書く |
| `device_restart` | 起動時に「前回の正常停止マークが無い」＋ uptime が短い |
| `agent_started` / `agent_stopped` | エージェントの lifespan |
| `browser_started` | ブラウザの kiosk-heartbeat を新しい `page_id` で初めて受けた（＝Chromium がページを開いた） |
| `app_started` | 受付アプリの起動完了。`boot()` 後に `booted:true` 付きのハートビートを1回だけ送る |
| `page_reloaded` | 同一ブラウザで `page_id` が変わった（リロード） |
| `app_crashed` | ブラウザ heartbeat が `browser_stale_sec`（既定45秒）を超えて途切れた |
| `online` / `offline` / `network_recovered` | アップローダのバックエンド到達性が変化した時 |
| `log_dropped` | 保存上限でイベントを捨てた（件数のみ） |

バージョン情報（`agent_version` / `ui_version` / `os_version`）は端末イベント・メトリクスに載せ、
`devices` テーブルにも最新値をミラーする。

### 9-2. 可能であれば（`device_metrics`・Linux のみ実測）

CPU使用率 / CPU温度 / メモリ使用量 / ストレージ残量 / タッチパネル接続 / マイク接続 / カメラ接続。

いずれも **標準ライブラリだけ**で取得する（新しい pip 依存を増やさない）。

| 項目 | 取得元 |
|---|---|
| CPU使用率 | `/proc/stat` の差分 |
| CPU温度 | `/sys/class/thermal/thermal_zone*/temp` |
| メモリ | `/proc/meminfo` |
| ストレージ | `shutil.disk_usage("/")` |
| 稼働秒 | `/proc/uptime` |
| タッチパネル | `/proc/bus/input/devices` に touch 系デバイスがあるか |
| マイク / カメラ | 既存の `_microphone_status()` / `_camera_status()` |

非 Linux（Windows 開発機）では `null` を返す＝既存のモック方針と同じ。

### 9-3. 取得間隔（すべて設定で変更可）

| 対象 | 既定 | 環境変数 |
|---|---|---|
| ハートビート | 60 秒 | `ANALYTICS_HEARTBEAT_SEC` |
| CPU・メモリ・温度など | 300 秒 | `ANALYTICS_METRICS_SEC` |
| 起動・停止・再起動・切断・復旧 | 発生時 | — |
| スプールのアップロード | 15 秒（失敗時は指数バックオフで最大5分） | `ANALYTICS_FLUSH_SEC` |

---

## 10. 稼働率の定義

```
稼働率 ＝ 正常稼働時間 ÷ 端末の電源が入っていた時間
```

- **分母＝ラズパイ自身の電源が動いていた時間**（実測）。
  エージェントは 60 秒ごとにハートビート行を残し、**通信断中もローカルスプールに書いて
  復旧後に再送する**。したがって
  - 電源OFF・OS停止 → 行が存在しない → **分母に入らない**（夜間・休日・計画停止は自動的に除外）
  - 電源ONだがネット断 → 行は後から届く → **分母に入り、分子からは外れる**（＝通信障害時間）
- **分子＝正常稼働**は「ハートビートがある」だけでは足りず、次を **すべて** 満たすサンプル:
  1. 受付アプリ（ブラウザ）の heartbeat が `browser_stale_sec` 以内に届いている
  2. その時点でバックエンド API へ到達できている（**直近のアップロードが成功している**。
     起動直後でまだ一度も送っていない＝到達性不明のあいだは正常稼働に数えない）
  3. 画面が `pending`（承認待ち）/ `suspended`（停止中）でない
  → メトリクス行の `app_healthy = true`
- 各サンプルは `heartbeat_interval` ぶんの時間を代表する。

```
稼働率      = Σ(app_healthy なサンプル) / Σ(全サンプル)
通信障害時間 = Σ(online = false なサンプル) × heartbeat_interval
```

---

## 11. 保存先（テーブル）

既存の命名規則（スネークケース複数形・`id` は `VARCHAR(36)` UUID・
日時は naive-UTC の `TIMESTAMP`・`tenant_id` FK に `ondelete="CASCADE"`）に合わせる。
マイグレーションは既存どおり `main.py` の起動時 `create_all` + `_ENSURE_COLUMNS`。

| テーブル | 内容 |
|---|---|
| `reception_sessions` | 受付1回ぶんの匿名セッション（結果・所要時間・アンケート回答） |
| `reception_events` | 行動イベント（`event_id` が PK＝重複排除） |
| `devices` | 既存。`os_version` / `ui_version` / `last_boot_at` を追加 |
| `device_events` | 端末稼働イベント（起動/停止/断/復旧など） |
| `device_metrics` | 端末の定期メトリクス（ハートビート 1 行/分 + 5 分ごとに CPU 等） |

### インデックス

- `reception_sessions`: `tenant_id`, `site_id`, `device_id`, `started_at`, `outcome`,
  `app_version`, `ui_version`, `entry_method`
- `reception_events`: `event_id`(PK), `session_id`, `tenant_id`, `site_id`, `device_id`,
  `event_name`, `screen_id`, `client_occurred_at`, `app_version`, `ui_version`,
  `result`, `error_code`、複合 `(session_id, sequence_no)`
- `device_events`: `device_id`, `tenant_id`, `event_name`, `occurred_at`
- `device_metrics`: `device_id`, `measured_at`、複合 `(device_id, measured_at)`

---

## 12. API

| メソッド | パス | 認証 | 説明 |
|---|---|---|---|
| POST | `/analytics/events` | デバイストークン | 行動イベントのバッチ投入 |
| POST | `/analytics/device-events` | デバイストークン | 端末イベントのバッチ投入 |
| POST | `/analytics/device-metrics` | デバイストークン | 端末メトリクスのバッチ投入 |
| GET | `/analytics/sessions` | 運営JWT | 匿名セッション一覧（テナント/端末/日付/結果で絞り込み） |
| GET | `/analytics/sessions/{id}` | 運営JWT | 1セッションの時系列イベント |
| GET | `/analytics/summary` | 運営JWT | 主要指標（完了率・離脱率・エラー率・回復率・所要時間・非介助率） |
| GET | `/analytics/uptime` | 運営JWT | 端末稼働率・通信障害時間・再起動回数 |
| GET | `/analytics/export` | 運営JWT | CSV / JSON 出力（`kind=sessions|events`） |

受付送信（`POST /kiosk/reception`）と配達呼び出し（`POST /kiosk/call-staff`）は
`analytics_session_id` を **任意で**受け取る。通知の成否を匿名セッションへ書き戻すためだけに使い、
**受付ログ（個人情報）には保存しない**（§2 のプロセス内 TTL マップへ渡すだけ）。

投入系のレスポンスは `{"accepted": [...], "duplicate": [...], "rejected": [{id, reason}]}`。
**部分成功を許す**（1件の不正で全体を落とさない）＝端末は accepted+duplicate+rejected を削除する。

### セキュリティ

- HTTPS（既存の Render/Neon 経路をそのまま使う）。
- 端末認証は既存の **デバイストークン（端末ごとに発行済み・`X-Kiosk-Token`）**。
  新しい認証情報は増やさない。**ブラウザのコードにトークンを埋め込まない**（§7）。
- 受信時に `tenant_id` / `site_id` / `device_id` を **トークンから確定**し、本文の申告値は捨てる。
- `event_name` / `screen_id` / `error_code` / `result` / `input_method` / `answer_code` などは
  **固定語彙以外を拒否**（未知はその1件だけ reject）。
- 1バッチ件数上限（既定 200）・本文長上限（512KB）・**レート制限**。
  投入系は **IP ではなく端末ごと**（デバイストークンのハッシュをキーに 120/分）＝同じ拠点で
  複数台が1つのグローバルIPを共有しても互いを枯渇させない。参照系は 60/分/IP。
- SQLAlchemy のパラメータバインドのみ（生 SQL 文字列連結をしない）。
- エラーログに認証情報・個人情報・本文を出さない（`event_id` と理由コードのみ）。
- **外部のアクセス解析・行動分析 SaaS へは一切送信しない。**

---

## 13. 後から分析できる断面（データ構造の裏取り）

| 分析したいこと | 使う列 |
|---|---|
| 受付開始→完了の操作経路 | `reception_events` を `(session_id, sequence_no)` 順に並べる |
| 完了者と離脱者の経路比較 | `reception_sessions.outcome` で分けて上の経路を比較 |
| 離脱直前の画面・操作 | `outcome != 'completed'` の最後の `screen_viewed` / `action_selected` |
| 画面別の平均・中央値・90%タイル滞在時間 | `screen_exited.screen_dwell_ms` を `screen_id` で集計 |
| 戻る操作が多い画面 | `back_selected` を `screen_id` で集計 |
| ヘルプ表示が多い画面 | `help_opened` を `screen_id` で集計 |
| 入力項目別エラー率 | `validation_error` を `field_id` で集計 ÷ `input_started` |
| エラー発生後の回復率 | `error_recovered` / `validation_error`（同一 `session_id`+`field_id`） |
| 再試行回数 | `retry_count` |
| 標準経路から外れた操作パターン | 画面遷移列を文字列化して頻度集計 |
| 入力方法別の受付時間・完了率 | `reception_sessions.entry_method` × `duration_ms` / `outcome` |
| 拠点別・端末別の完了率 | `site_id` / `device_id` × `outcome` |
| 時間帯別・曜日別の利用状況 | `started_at` + `client_tz_offset_min` |
| アプリバージョン別のエラー率 | `app_version` × `error_count` |
| UIバージョン別の完了率・滞在時間 | `ui_version` × `outcome` / `duration_ms` |
| 通知成功率 | `notification_succeeded` / `notification_requested` |
| 担当者応答までの時間 | `staff_responded.duration_ms` |
| 端末稼働率 | `device_metrics.app_healthy`（§10） |
| 通信障害時間 | `device_metrics.online = false` の合計 |
| 端末再起動回数 | `device_events.event_name = 'device_restart'` |
| エラー発生前後の端末負荷 | `reception_events` のエラー時刻 ± 5 分の `device_metrics` |

### 確認手段（最低限）

運営画面 `/operator/analytics`:

- 匿名セッション一覧（日付・テナント・端末・完了状態で絞り込み）
- 1セッションの時系列イベント表示
- 主要指標のサマリ・端末稼働率
- CSV / JSON 出力

（テナント管理画面には出さない＝実証実験・製品改善は自社側の分析のため）

---

## 14. 主要指標

| 指標 | 式 |
|---|---|
| 受付完了時間 | `ended_at - started_at`（平均・中央値・90パーセンタイル） |
| 受付完了率 | `outcome='completed'` 件数 ÷ `session_started` 件数 |
| 離脱率 | (`abandoned` + `timeout`) ÷ `session_started` |
| エラー発生率 | エラーが1件以上あったセッション数 ÷ `session_started` |
| エラー回復率 | エラー後に完了したセッション数 ÷ エラーがあったセッション数 |
| 自己申告による非介助率 | `answer_assistance='none'` ÷ 設問3の回答件数 |

非介助率は **回答率と回答者数を必ず併記**する（API のレスポンスにも両方入れる）。

---

## 15. 失敗しても受付を止めない

- ログ処理はすべて `try/catch` で囲み、**失敗しても受付操作は継続**する。
- IndexedDB が使えない環境ではメモリキューへ自動フォールバック（送信できなければ捨てる）。
- エージェントが落ちていてもキオスク画面は通常どおり動く（ログはブラウザに溜まる）。
- ログ API が 5xx を返してもキオスクは何も表示しない（サイレントに再送）。


---

## 16. 環境変数

### backend

分析ログ専用の追加設定は無い（既存の `DATABASE_URL` / デバイストークンをそのまま使う）。

### kiosk_agent（`.env` もしくは systemd の Environment）

| 変数 | 既定 | 説明 |
|---|---|---|
| `ANALYTICS_HEARTBEAT_SEC` | 60 | ハートビート（`device_metrics` 1行）の間隔 |
| `ANALYTICS_METRICS_SEC` | 300 | CPU・温度・メモリ等を載せる間隔 |
| `ANALYTICS_FLUSH_SEC` | 15 | スプールのアップロード間隔（失敗時は指数バックオフ） |
| `ANALYTICS_BROWSER_STALE_SEC` | 45 | ブラウザのハートビートが途切れたと判断する秒数 |
| `ANALYTICS_BOOT_WINDOW_SEC` | 180 | 起動時、OS の uptime がこれ未満なら「端末が起動した」と判定 |
| `ANALYTICS_MAX_SPOOL_LINES` | 20000 | スプールの上限行数（種類ごと・超過分は古い順に破棄） |
| `ANALYTICS_UPLOAD_BATCH` | 200 | 1回のアップロード件数（サーバ上限と揃える） |
| `ANALYTICS_SPOOL_DIR` | `kiosk_agent/analytics_spool/` | スプールの置き場所 |

### キオスク画面（端末ごと・localStorage）

| キー | 値 | 説明 |
|---|---|---|
| `kiosk_feedback` | `off` | 受付完了後アンケートをこの端末だけ止める |
| `mokuture_kiosk_mock` | `1` | `?mock=1` のプレビュー。**この間は分析ログを送らない** |
