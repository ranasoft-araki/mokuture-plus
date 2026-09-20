# 音声入力（実験導入）

QR コードを持たない来訪者の受付フォームを、声で埋められるようにする実験機能。
**端末の中だけで完結**し、クラウドの音声認識 API・Web Speech API・外部の生成 AI は
一切使わない。インターネットが切れていても動く。

- 対象画面は **QR無し来訪者の受付フォーム（`showReception`）だけ**。QR 受付・ロッカー・
  配達など他のフローには一切手を入れていない。
- **音声だけで受付は確定しない。** 認識結果は受付フォームの入力欄に入るだけで、送信は
  従来どおり利用者が「受付する」を押したとき。
- 使えない端末（マイク未接続・モデル未取得・サービス停止）では「音声で入力」ボタンが
  **表示されない**。受付は従来のタッチ操作だけで完了できる。

---

## 1. 構成

```
ブラウザ (kiosk.html)              画面表示・入力項目の管理・確認
   │  http://127.0.0.1:8181        ← localhost 限定
   ▼
音声サービス (mokuture-voice)       マイク制御・VAD・音声認識      ← 別プロセス
   │                                127.0.0.1 にのみ bind
   ├─ arecord (ALSA)                USB マイクから 16kHz/モノラル/16bit
   └─ whisper-cli (whisper.cpp)     ggml 量子化モデル
```

キオスク本体（`main.py` / port 8080 / 0.0.0.0）とは**別プロセス・別ポート・別 systemd**。
名刺読み取り（`card/`）が本体に相乗りしているのと違う方針を採った理由:

| 理由 | 内容 |
|---|---|
| 外部から触らせない | 本体は端末管理のため `0.0.0.0` で待ち受けている。相乗りすると音声 API が LAN から見えてしまう。別プロセスなら `127.0.0.1` に bind でき、**ソケットの時点**で閉じられる |
| 巻き込まない | 実験機能が落ちても受付本体（GPIO・ロッカー・扉）は動き続ける。画面から「音声で入力」が消えるだけ |
| 切り分け | whisper.cpp は CPU を数秒占有する。本体と分けておくと影響が読みやすい |

**言語は Python**。既存のキオスクエージェントと同じ言語・同じ venv で、FastAPI /
pydantic / uvicorn の作法をそのまま流用できる。whisper.cpp は C++ だが実体はサブプロセス
なので、呼び出し側の言語を揃えないメリットは無い。Node.js にすると venv が二重になり、
現場での運用（`systemctl` とログの見方）も二系統になる。

コードは `kiosk_agent/voice/` にあるので **OTA で配信できる**。本体の再起動では別プロセスの
音声サービスは入れ替わらないため、音声サービスが自分のソースのハッシュ変化を検知して
自ら終了し、systemd に起こし直してもらう（`voice/server.py` の `_watch_sources`）。

---

## 2. インストール手順

### 2-1. 前提

- Raspberry Pi 4 (4GB) 以上 / Raspberry Pi OS 64bit
- **USB マイクを接続済み**（本体にマイク入力は無い）
- キオスクエージェント（`install.sh`）が導入済み＝ `kiosk_agent/.venv` がある
- **導入時だけ**ネットワークに繋がること（apt と、LFS を引いていない場合のモデル取得）

### 2-2. モデルを取り出す

モデルの実体はリポジトリに **Git LFS** で入っている。clone しただけではポインタ
（中身が数行のテキスト）のままなので、実体を取り出す必要がある。

**`git lfs` は git 本体とは別のプログラム**で、Raspberry Pi OS には既定で入っていない。
入っていないと `git: 'lfs' is not a git command` と言われる（`lfs` は小文字のエル、
Large File Storage の略）。

```bash
git lfs version                # 入っているか確認
sudo apt install git-lfs       # 入っていなければ（Raspberry Pi OS / Debian）

cd ~/mokuture                  # リポジトリのルート
git lfs install                # 利用者ごとに1回
git lfs pull
```

**git-lfs を入れたくない・入れられない場合は、取得元から直接落とせる。**
SHA-256 を記録してあるので、壊れたものは弾かれる。

```bash
cd ~/mokuture/kiosk_agent
.venv/bin/python scripts/fetch_voice_models.py        # 足りないものだけ落とす
```

揃っているかの確認:

```bash
cd ~/mokuture/kiosk_agent
.venv/bin/python scripts/fetch_voice_models.py --check

# 一文の受付だけ試すなら Vosk のモデルだけあればよい
.venv/bin/python scripts/fetch_voice_models.py --check --only vosk-model-small-ja-0.22.zip
```

| ファイル | サイズ | 用途 |
|---|---|---|
| `voice_models/vosk-model-small-ja-0.22.zip` | 50MB | **一文の名乗り（受付の既定の入口）** |
| `voice_models/ggml-base-q5_1.bin` | 60MB | 項目ごとに言う従来の入口 |
| `voice_models/ggml-small-q5_1.bin` | 190MB | 比較用（Pi では遅すぎて実用にならない） |
| `vendor/whisper.cpp-1.9.3.tar.gz` | 9MB | whisper.cpp のソース（固定版） |

壊れていた場合だけ、記録してある SHA-256 付きの取得元から落とし直す:

```bash
.venv/bin/python scripts/fetch_voice_models.py
```

### 2-3. セットアップ

**まず動かして測りたいだけなら `--vosk-only` が速い。** 一文の名乗り（受付の既定の
入口）は Vosk だけで動き、whisper.cpp のビルド（Pi 4 で 10 分以上）を飛ばせる。

```bash
cd ~/mokuture/kiosk_agent
bash scripts/install_voice.sh --vosk-only     # 一文の受付だけ。数分で終わる
bash scripts/install_voice.sh                 # 一式（whisper もビルドする）
```

やること:

1. モデルの検証（ポインタのまま・壊れている場合はここで止まる）
2. `alsa-utils` を apt で導入（`--vosk-only` でなければ `cmake` / `build-essential` も）
3. whisper-cli をビルド（Pi 5 で 3〜6 分、Pi 4 で 10 分以上。`--vosk-only` なら飛ばす）
4. `vosk` を venv へ導入し、Vosk のモデル zip を展開
5. `voice_input.yaml` と `staff_readings.yaml` を雛形から作成、`~/.mokuture-voice/` を作成
6. 実行ユーザーを `audio` グループへ追加
7. `mokuture-voice.service` を登録して起動

### 2-4. 担当者の読み仮名を書く（必須）

社員マスターに読み仮名の欄が無いので、端末側で補う。**ここに載っていない担当者は
音声で指名できない**（読みの推測は禁止）。

```bash
nano ~/mokuture/kiosk_agent/staff_readings.yaml
```

`name` は管理画面「受付設定」の担当者一覧と**完全に同じ文字列**にすること。

```yaml
staff:
  - name: 服部 太郎        # 管理画面の表記そのまま
    kana: はっとりたろう    # 必須
    department: 営業部      # 任意
    aliases:                # 任意（社内での呼ばれ方・旧姓）
      - はっとりさん
```

書き換えたら再起動:

```bash
sudo systemctl restart mokuture-voice
curl -s http://127.0.0.1:8181/voice/status | grep -o '"staff_readings":[^}]*}'
```

### 2-5. 動いているか確かめる

```bash
curl -s http://127.0.0.1:8181/voice/status
```

見るところ:

| 項目 | 期待する値 |
|---|---|
| `available` | `true` |
| `microphone.available` | `true`（false なら USB マイクを認識していない） |
| `engines.vosk.available` | `true` |
| `fields.reception.engine_used` | `vosk` |
| `staff_readings.registered` | 1 以上 |

`available: true` になっていれば、受付フォームに「音声で入力」が出る。
`false` のときは `detail` に理由が入っている。

### 2-6. 速さを測る

```bash
.venv/bin/python scripts/voice_bench.py --models vosk --field reception --repeat 4
```

マイクに向かって一息で名乗ると、機械の素性・モデルのメモリ・認識時間・実時間比が出る。
**`--repeat` は 2 以上にすること。** 1 回目だけ大きく遅く（Kaldi が最初に実デコードを
する費用。Windows で 3.8 秒 → 2 回目以降 0.58 秒）、平均に混ぜると実態を見誤る。

whisper と比べるなら（`--vosk-only` で入れた場合は whisper は測れない）:

```bash
.venv/bin/python scripts/voice_bench.py --models vosk,base --field reception --repeat 4
```

> **ビルドだけやり直す**（whisper.cpp のバージョンを上げた等）:
> `bash scripts/install_voice.sh --build`
> **apt を触らない**（オフライン端末）: `--no-apt`

---

## 2-7. Windows 開発機での動作試験

本番は Raspberry Pi ですが、**Windows でも同じコードで一通り試せます**。Pi を用意しなくても、
録音 → VAD → whisper.cpp → 整形 → 採否判定 の経路と、キオスク画面の導線を確認できます。

違いは 2 つだけで、設定ファイルは同じものが使えます。

| | Raspberry Pi（本番） | Windows（動作試験） |
|---|---|---|
| 録音 | `arecord`（alsa-utils） | `sounddevice`（PortAudio） |
| whisper-cli | ソースから自前ビルド | 上流の配布バイナリ（同じ v1.9.3） |

### セットアップ

```powershell
cd kiosk_agent
powershell -ExecutionPolicy Bypass -File scripts\install_voice_windows.ps1
```

やること: モデルの確認 → whisper.cpp の Windows x64 バイナリを取得（SHA-256 照合つき）→
`sounddevice` を venv へ導入 → `voice_input.yaml` を作成。マイクを使わないなら `-NoMic`。

### 試し方

```powershell
# 1) 状態を見る（マイク・バイナリ・モデルが揃っているか）
.venv\Scripts\python scripts\voice_selftest.py --status

# 2) 読み上げ音で1往復（マイク不要。Windows の音声合成で音源を作る）
.venv\Scripts\python scripts\voice_selftest.py --say "株式会社ラナソフトです" --show-text

# 3) 実際にマイクへ話しかけて1往復
.venv\Scripts\python scripts\voice_selftest.py --mic --show-text

# 4) 手元の WAV で1往復（16bit なら何 Hz・何chでも可。読み込み時に 16kHz モノラルへ直す）
.venv\Scripts\python scripts\voice_selftest.py --wav sample.wav --show-text

# 入力デバイスの一覧（voice_input.yaml の audio.device に書く値）
.venv\Scripts\python scripts\voice_selftest.py --devices
```

出力例:

```
== 会社名をお話しください ==
  （発話を検出）
  音声 2562ms / うち発話 1620ms / 終了理由 silence
  認識 6093ms / 発話終了から表示まで 6093ms / モデル whisper-base-q5
  生の認識  : 株式会社はラナソフトです
  入力欄の値: 株式会社はラナソフト
  判定      : 採用（色=ok）
  手がかり  : 平均トークン確率=0.782 / 無音率=0.37 / 1秒あたり文字数=6.17 / 繰り返し=0.1
```

### 画面から試す

```powershell
# 1) 音声サービス（別ウィンドウで）
.venv\Scripts\python -m voice.server

# 2) キオスク本体
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

ブラウザで `http://localhost:8080` を開き、QR無し来訪者の受付フォームで「音声で入力」を押します。
`curl http://127.0.0.1:8181/voice/status` が `available: true` ならボタンが出ます。

### マイクを使わずに繰り返し試す

`voice_input.yaml` で音源を固定すると、マイク無しでも毎回同じ音で経路を通せます。
しきい値を触ったときの比較に便利です。

```yaml
audio:
  backend: file
  file_path: samples/company.wav
```

### スクリプトを直すときの注意（PowerShell の罠）

`install_voice_windows.ps1` を編集するときは 2 点。テストで固定してあります。

- **UTF-8 BOM 付きで保存する。** Windows PowerShell 5.1 は BOM が無い `.ps1` をシステムの
  ANSI コードページ（日本語環境は cp932）として読むため、日本語コメントが化けて
  **構文エラーで起動すらしません**。pwsh 7 は BOM 無しでも UTF-8 として読むので、
  7 でだけ確認していると気づけません。検証は `powershell.exe`（5.1）で行ってください。
- **外部コマンドは `Invoke-Native` で包む。** `$ErrorActionPreference='Stop'` のまま
  ネイティブコマンドを呼ぶと、stderr へ 1 行書かれただけで `NativeCommandError` になり、
  成功していても止まります（whisper-cli の `load_backend: ...`、uv の進捗表示が該当）。

### Windows で試すときの注意

- **合成音声は人の声より認識しにくい**です。`--say` で多少崩れても実際の精度とは別物と考えてください（経路と整形・判定の確認用です）。
- **処理時間は Pi 5 の目安になりません。** CPU も命令セットも違います。性能の数字は必ず Pi 実機の `voice_bench.py` で取ってください。
- systemd はありません。サービスの常駐・自動起動の確認は Pi 実機でのみ行えます。
- Windows のバイナリは `vendor/whisper.cpp-win-x64/` に展開され、`.gitignore` 済みです（プラットフォーム固有の実行ファイルなのでリポジトリには入れません）。

---

## 3. 起動・停止・再起動

```bash
sudo systemctl start   mokuture-voice     # 起動
sudo systemctl stop    mokuture-voice     # 停止（画面から「音声で入力」が消える）
sudo systemctl restart mokuture-voice     # 再起動（設定を変えたら必ず）
sudo systemctl status  mokuture-voice     # 状態
journalctl -u mokuture-voice -f           # ログを追う
sudo systemctl disable mokuture-voice     # 自動起動をやめる
sudo systemctl enable  mokuture-voice     # 自動起動に戻す
```

- `Restart=always` / `RestartSec=3` なので、異常終了しても自動で復帰する。
- 再起動が繰り返し失敗する場合は 60 秒あたり 10 回で打ち止めになる（CPU を焼かないため）。
  `systemctl reset-failed mokuture-voice` で解除。
- **Pi の再起動後も自動で起動する**（`WantedBy=multi-user.target` + `enable` 済み）。

一時的に音声だけ止めたいとき（サービスは動かしたまま）は `voice_input.yaml` の
`enabled: false` → `systemctl restart mokuture-voice`。

---

## 4. マイク選択・音量調整

### 4-1. どのデバイスか調べる

```bash
arecord -l                                     # カード番号の一覧
arecord -L                                     # ALSA のデバイス名（設定に書くのはこちら）
curl -s http://127.0.0.1:8181/voice/devices    # サービスから見えている一覧
```

USB マイクはたいてい `plughw:1,0` か `sysdefault:CARD=<名前>`。

### 4-2. 設定に書く

```yaml
# voice_input.yaml
audio:
  device: plughw:1,0
```

```bash
sudo systemctl restart mokuture-voice
```

### 4-3. 録れているか確かめる

```bash
# 3 秒録って再生する（本番と同じ 16kHz/モノラル）
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -d 3 /dev/shm/t.wav && aplay /dev/shm/t.wav
rm -f /dev/shm/t.wav
```

### 4-4. 入力音量

```bash
alsamixer -c 1        # F4 で Capture 画面。Mic のゲインを上げる
sudo alsactl store    # 再起動後も保つ
```

`alsamixer` で上げきってもまだ small すぎるときだけ、設定側で持ち上げる:

```yaml
audio:
  input_gain: 2.0     # 上げすぎると歪んで認識が落ちる。3.0 くらいまで
```

### 4-5. 拾いすぎ・拾わなさすぎ

| 症状 | 調整 |
|---|---|
| 周りの話し声で勝手に録音が始まる | `vad.speech_margin_db` を上げる（9 → 12） |
| 小さい声を拾わない | `vad.speech_margin_db` を下げる（9 → 6）／`input_gain` を上げる |
| 言いよどむと途中で切れる | `vad.silence_sec` を上げる（0.7 → 0.8） |
| 話し終えてから待たされる | `vad.silence_sec` を下げる（0.7 → 0.5） |

---

## 5. 性能計測（実機）

```bash
cd ~/mokuture/kiosk_agent

# その場で 1 回話して測る（既定は一文の名乗り＝ Vosk）
.venv/bin/python scripts/voice_bench.py --models vosk --field reception --repeat 4

# whisper と比べる
.venv/bin/python scripts/voice_bench.py --models vosk,base --field reception --repeat 4

# 同じ音声で繰り返してばらつきを見る
.venv/bin/python scripts/voice_bench.py --record-only --out /dev/shm/sample.wav
.venv/bin/python scripts/voice_bench.py --wav /dev/shm/sample.wav --models vosk,base --repeat 5
rm -f /dev/shm/sample.wav        # 計測が終わったら必ず消す
```

出るもの（§3-1 の計測項目）: 機械の素性 / 音声の長さ / 認識処理時間 / 発話終了から
結果表示までの時間 / 実時間比（RTF）/ モデルのメモリ / 自動確定の可否。

**`--repeat` は 2 以上にすること。** Vosk は 1 回目だけ大きく遅い（Windows の実測で
3.8 秒 → 2 回目以降 0.58 秒）。モデル読み込みでも認識器の生成でもなく、Kaldi が最初に
実際のデコードをするときに払う費用で、モデルを先読みしても消えなかった。
運用上はサービス起動後の最初の 1 人だけが余分に待つ（OTA の再起動ごとに 1 回）。
ベンチはこれを分けて表示する。

判定の目安は **話し終わってから 3 秒**。Windows（8 コア）での実測値は次のとおりで、
Pi はこれより数倍遅くなる。

| | 読みCER | 定常の認識 | 実時間比 |
|---|---|---|---|
| Vosk small-ja | 0.118 | 0.58 秒 | 0.10 |
| whisper base | 0.217 | 2.86 秒 | 0.48 |
| whisper small | 0.179 | 10.1 秒 | — |

認識したテキストは既定では表示しない。精度を目で確かめたいときだけ `--show-text`
（画面に出るだけで、どこにも保存しない）。

**運用中の実測値は `/voice/metrics` に貯まる**（§12 の指標）:

```bash
curl -s http://127.0.0.1:8181/voice/metrics | python3 -m json.tool
```

| 指標 | キー |
|---|---|
| 音声入力の利用回数 | `voice_sessions` / `attempts` |
| 認識の成功率 | `success_rate` |
| 項目別の再入力率 | `by_screen.<画面>.retry_rate` |
| 音声からタッチへ切り替えた割合 | `fallback_rate` |
| 発話終了から結果表示までの時間 | `end_to_display_ms_p50` / `_p95` |
| モデル別の処理時間 | `by_model.<モデル>.recognition_ms_p50` |
| エラー発生率 | `error_rate` |
| 途中でキャンセルした割合 | `cancel_rate` |
| 結果を利用者が修正したか | `edited_rate` |

---

## 6. 設定

`voice_input.yaml`（雛形は `voice_input.yaml.example`）。優先順位は
**既定値 → YAML → 環境変数 `VOICE_*`** の後勝ち。

### モデルの切り替え

```yaml
whisper:
  model_path: voice_models/ggml-small-q5_1.bin
  model_name: whisper-small-q5      # メトリクスの識別子。必ず一緒に変える
```

環境変数でも:

```bash
VOICE_WHISPER__MODEL_PATH=voice_models/ggml-small-q5_1.bin
VOICE_WHISPER__MODEL_NAME=whisper-small-q5
```

### 時間まわりの初期値（§8）

| 項目 | キー | 初期値 |
|---|---|---|
| 発話開始待ち | `vad.start_timeout_sec` | 5.0 秒 |
| 発話終了と判断する無音 | `vad.silence_sec` | 0.7 秒 |
| 1 項目の最大録音時間 | `vad.max_record_sec` | 10.0 秒 |
| 認識処理のタイムアウト | `whisper.timeout_sec` | 10.0 秒 |

---

## 7. 個人情報の扱い

| 対象 | 扱い |
|---|---|
| 音声 | メモリ上のみ。whisper.cpp へ渡す WAV だけ tmpfs（`/dev/shm`）に置き、**成功・失敗・タイムアウトのいずれでも `finally` で必ず削除**。ディスクには残さない |
| 認識テキスト | セッションのメモリのみ。確定・キャンセル・タイムアウト・TTL のいずれでも破棄 |
| 診断ログ | 項目名・状態・所要時間・エラーコードだけ。氏名・会社名・認識結果は出さない |
| 分析ログ | 個人を特定できない数値と固定語彙だけ（`~/.mokuture-voice/metrics.jsonl`）。**書ける項目を列挙する方式**なので、うっかり本文を渡しても構造的に書かれない |
| 外部送信 | しない。音声サービスは外部へ接続しない（テストで確認済み） |
| セッション ID | 音声入力ごとの使い捨ての乱数。受付ログ（`reception_logs`）とはひも付けない |

`staff_readings.yaml`（第3段階で使う担当者の読み仮名）は**実在の社員情報**が入るため
`.gitignore` 済み。コミットしないこと。

---

## 8. 実機確認チェックリスト

### 導入直後

- [ ] `systemctl status mokuture-voice` が `active (running)`
- [ ] `curl -s http://127.0.0.1:8181/voice/status` が `"available": true`
- [ ] **端末の外から繋がらない**: 別の PC から `curl http://<PiのIP>:8181/voice/status` が失敗する
- [ ] 受付フォーム（QR無し来訪）に「音声で入力」ボタンが出る
- [ ] QR 受付・ロッカー・配達の画面が今までどおり

### 会社名・お名前（第1段階）

- [ ] 「音声で入力」→ 開始音が鳴り、**鳴り終わってから**「お話しください」になる
- [ ] 話している間、音量バーが動く／「聞き取り中」に変わる
- [ ] 黙ると自動で止まり、「認識しています」→ 結果が出る
- [ ] 「株式会社ラナソフトから来ました」→ 会社名が `株式会社ラナソフト`（**株式会社が残る**）
- [ ] 「荒木秀人と申します」→ お名前が `荒木秀人`
- [ ] 発話終了から結果表示まで **2.5 秒以内**（base モデル）

### 確認・修正（第2段階）

- [ ] 「この内容で進む」→ 次の項目へ、最後は受付フォームに値が入る
- [ ] 「音声でもう一度入力」→ 録り直せる
- [ ] 「キーボードで修正」→ 受付フォームに戻り、五十音キーボードで直せる
- [ ] 「前の項目に戻る」→ 前の項目をやり直せる
- [ ] 「音声入力をやめる」→ それまでの入力を保ったまま通常操作に戻る
- [ ] **音声だけでは受付が完了しない**（必ず「受付する」を押す必要がある）

### 異常系

- [ ] 何も話さず 5 秒 → 「お声を聞き取れませんでした」→ 再入力かキーボードを選べる
- [ ] 録音中に「キャンセル」→ 止まって最初の画面に戻る
- [ ] 録音中に「入力を終了」→ そこまでで認識される
- [ ] **マイクを抜いて**「音声で入力」→ エラーになるが**受付は続けられる**
- [ ] `sudo systemctl stop mokuture-voice` → 画面を再読込すると「音声で入力」が消え、
      タッチだけで受付できる
- [ ] **LAN ケーブルを抜く／Wi-Fi を切る** → 音声入力はそのまま動く

### 後始末・再起動

- [ ] 受付完了後、`ls /dev/shm` に `mokuture-voice-*` が残っていない
- [ ] `~/.mokuture-voice/metrics.jsonl` に氏名・会社名が入っていない
      （`grep -c 株式会社 ~/.mokuture-voice/metrics.jsonl` が 0）
- [ ] `journalctl -u mokuture-voice --since today | grep 株式会社` が空
- [ ] **Pi を再起動 → 自動で `active (running)` に戻る**

---

## 9. 変更したファイル

### 新規

```
kiosk_agent/voice/                      音声サービス本体（13 ファイル）
  __init__.py  api.py  capture.py  defaults.py  metrics.py  quality.py
  server.py  session.py  settings.py  textnorm.py  types.py  vad.py  whisper_cpp.py
kiosk_agent/voice_models/               モデル実体（Git LFS）
  ggml-base-q5_1.bin  ggml-small-q5_1.bin  vosk-model-small-ja-0.22.zip
kiosk_agent/vendor/
  whisper.cpp-1.9.3.tar.gz              whisper.cpp 固定版ソース（Git LFS）
kiosk_agent/mokuture-voice.service      systemd ユニット
kiosk_agent/voice_input.yaml.example    設定の雛形
kiosk_agent/staff_readings.yaml.example 担当者の読み仮名の雛形（第3段階）
kiosk_agent/scripts/install_voice.sh    セットアップ(Raspberry Pi)
kiosk_agent/scripts/install_voice_windows.ps1  セットアップ(Windows 動作試験)
kiosk_agent/scripts/fetch_voice_models.py  モデルの検証・取得
kiosk_agent/scripts/voice_selftest.py   動作試験(録音→認識→整形→判定を1往復)
kiosk_agent/scripts/voice_bench.py      性能計測
kiosk_agent/tests/voice_input/          テスト（124 件）
kiosk_agent/VOICE_INPUT.md              この文書
```

### 変更

| ファイル | 変更内容 |
|---|---|
| `kiosk_agent/static/kiosk.html` | `ICO.mic` / `ICO.mic_lg` 追加、音声入力オーバーレイ `openVoiceInput()` 追加、`showReception` に「音声で入力」ボタンと `applyVoiceValues()` 追加、`boot()` で `ensureVoiceStatus()` |
| `kiosk_agent/updater.py` | `MANAGED_FILES` に `voice/*.py` 13 件を追加（OTA 配信対象）。`_RESTART_DIRS` には入れない（別プロセスのため） |
| `kiosk_agent/pyproject.toml` | optional extra `voice` を追加 |
| `kiosk_agent/install.sh` | 音声セットアップの案内を追加 |
| `backend/app/api/kiosk.py` | `BUNDLE_FILES` に `voice/*.py` 13 件を追加（agent 側と並び順まで一致させる） |
| `kiosk_agent/tests/test_ota_list.py` | `voice/` を再起動対象の例外にし、その根拠（自己再起動の仕組み）を検証する test を追加 |
| `.gitignore` | `voice_input.yaml` / `staff_readings.yaml` / `vendor/whisper.cpp/` / `vendor/whisper.cpp-win-x64/` / 展開後の Vosk / metrics を除外 |
| `.gitattributes` | 音声モデルと vendor tarball を Git LFS 管理に |

---

## 10. 既存機能への影響範囲

**コードとして触ったのは `kiosk.html` の受付フォーム画面まわりだけ。** それ以外の既存
ファイルへの変更は、OTA の配信リスト・依存定義・インストール案内・ignore 設定という
「増やすだけ」の変更に限っている。

| 機能 | 影響 |
|---|---|
| QR 受付（`showWelcome` / jsQR / `/proxy/appointment`） | **なし**（触っていない） |
| 名刺読み取り（`card/`） | **なし**。ボタンが 1 つ増えて横に並ぶだけ |
| ロッカー・配達・呼び出し・アイドル | **なし** |
| 受付フォームの通常入力 | **なし**。五十音キーボード・部署チップ・ご用件チップはそのまま |
| バックエンド | OTA の配信リスト（`kiosk.py` の `BUNDLE_FILES`）に `voice/*.py` を足しただけ。配信リストは agent と backend の 2 か所にあり、ズレると「その端末だけ古いコード」になるため両方に足す必要がある（`tests/test_ota_list.py` が一致を検証する） |
| 管理画面 | **なし**（1 行も変更していない） |
| キオスクエージェント本体 | 配信リストが増えるだけ。音声サービスが落ちても本体は無関係 |
| 端末の CPU | 待受時ほぼ 0%。認識中だけ 1〜2 秒間 CPU を使う（同時実行は 1 件に制限） |

想定されるリスクと、その抑え方:

- **受付フォームの描画が壊れる** → `voiceAvailable()` が false のときはボタンの HTML すら
  出さないので、サービス未導入の端末は今までと同一の DOM になる。
- **音声サービスが暴走して受付が重くなる** → 別プロセス。`systemd` の `Restart` と
  同時実行 1 件の制限で抑える。最悪 `systemctl stop mokuture-voice` で即座に切り離せる。
- **OTA で `voice/` が配られたのに古いコードのまま動く** → 音声サービスが自分のソースの
  ハッシュを 60 秒ごとに見て、変わっていたら自分で終了する。

---

## 11. 元に戻す手順

### 一時的に止める（いちばん軽い）

```bash
sudo systemctl stop mokuture-voice
```

キオスク画面を再読込すると「音声で入力」が消え、以降は従来の受付だけになる。
Pi を再起動すると自動起動で戻ってくる。

### 自動起動もやめる

```bash
sudo systemctl disable --now mokuture-voice
```

### 設定だけで無効にする（サービスは動かしたまま）

```yaml
# voice_input.yaml
enabled: false
```
```bash
sudo systemctl restart mokuture-voice
```

### 完全に取り除く

```bash
sudo systemctl disable --now mokuture-voice
sudo rm -f /etc/systemd/system/mokuture-voice.service
sudo systemctl daemon-reload
cd ~/mokuture/kiosk_agent
rm -rf vendor/whisper.cpp voice_models/vosk-model-small-ja-0.22
rm -f voice_input.yaml staff_readings.yaml
rm -rf ~/.mokuture-voice
```

画面側（`kiosk.html`）を元に戻すには、ブランチ `experiment/voice-input` を master に
マージしていない状態へ戻すか、次のコミットを revert する:

```bash
git revert <音声入力の UI コミット>
git push origin master        # OTA で全端末の kiosk.html が戻る
```

> `kiosk.html` は OTA の配信元が **GitHub の master** なので、revert を push すれば
> 端末側は自動で元の画面に戻る（30 分以内、アイドル時に適用）。

---

## 12. トラブルシュート

| 症状 | 見るところ |
|---|---|
| (Windows) `whisper-cli がありません` | `scripts\install_voice_windows.ps1` を実行 |
| (Windows) マイクが見つからない | `uv pip install --python .venv\Scripts\python.exe sounddevice`。入れたあと `voice_selftest.py --devices` で番号を確認し `audio.device` に書く |
| 「音声で入力」が出ない | `curl -s http://127.0.0.1:8181/voice/status` の `available` と `detail`。`microphone.available` が false ならマイク、`engines.whisper.available` が false ならビルドかモデル |
| `whisper-cli がありません` | `bash scripts/install_voice.sh --build` |
| `モデルがありません` | `git lfs pull` → `.venv/bin/python scripts/fetch_voice_models.py --check` |
| `録音デバイスが見つかりません` | USB マイクの接続。`arecord -l` に出るか。`audio` グループに入っているか（`id -nG`）。入れた直後は再ログインか Pi の再起動が要る |
| 認識がいつも「うまく聞き取れませんでした」 | `voice_bench.py --show-text` で実際の認識結果を見る。マイクのゲイン不足が多い（§4-4） |
| 認識が遅い（3 秒以上） | モデルが small になっていないか（`status` の `engines.whisper.model`）。`whisper.threads` が 4 か |
| 開始音を認識してしまう | `audio.start_guard_ms` を上げる（250 → 400） |
| ブラウザのコンソールに CORS エラー | `voice_input.yaml` の `server.allowed_origins` にキオスクのオリジンが入っているか |
| OTA でコードを配ったのに変わらない | `journalctl -u mokuture-voice | grep 再起動`。60 秒待っても出なければ `sudo systemctl restart mokuture-voice` |

---

## 13. 実装の段階

| 段階 | 内容 | 状態 |
|---|---|---|
| 1 | 会社名・訪問者名を項目ごとに録音 → whisper.cpp → 画面表示 | 実装済み（実機未検証） |
| 2 | 再入力・修正・キャンセル・通常入力への切替 | 実装済み（実機未検証） |
| 3 | 担当者名を社員マスターと照合して候補表示（Vosk） | 未着手 |
| 4 | 「はい」「いいえ」「次へ」「戻る」などの基本音声操作 | 未着手 |
| 5 | 匿名の性能ログ・エラー処理・systemd 自動起動 | 実装済み（§5・§8 の確認は実機で） |

第3段階に進む前に決めることが 1 つある。**社員マスターに読み仮名・部署・別称の欄が無い**
（`tenants.staff_list` は表示氏名のカンマ区切りだけ）。いまは端末ローカルの
`staff_readings.yaml` に読みがある担当者だけを音声照合の対象にする設計にしてあるが、
恒久対応としては管理画面の担当者マスターに読み仮名欄を足すべきで、それは別 issue の範囲。
