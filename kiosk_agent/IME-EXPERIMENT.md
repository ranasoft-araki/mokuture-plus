# 受付フォームの漢字変換入力（実験）

> 発端ブランチ: `experiment/kanji-ime` ／ 本文書は仕様・確認手順・撤退方法のメモ。
> **採用済み: master へマージ済み(CLAUDE.md `showReception` に仕様反映済み)。** 本文書は詳細リファレンスとして残す。

## 何をしたか

受付フォーム（device 版 `kiosk_agent/static/kiosk.html` の `showReception`）の
**五十音ソフトキーボードはそのまま残し**、末尾の「読み（かな）」を漢字に変換する
**変換候補バー**を足した。IME のスペース変換に相当する「変換」ボタンをキーボードに追加。

- 来訪者の操作は今まで通り：五十音を直接タップして「やまだ」と打つ。
- 「変換」を押すと**フローティングの候補パネル**が開き、`山田 / やまだ / ヤマダ …` を
  折り返しグリッドで一括表示。候補をタップで確定＆パネルを閉じる（背景タップ／「閉じる」でも閉じる）。
  ※候補数が多い読み（例「ひ」）でも横スクロールにならず、大きなボタンで選べる。
- 段階変換に対応：`やまだ`→[変換]→`山田`、続けて`たろう`→[変換]→`山田太郎`。
- **OS 側の変更は一切不要**（fcitx5 / mozc / squeekboard / onboard は入れない）。
  → device 版・web 版どちらのキオスクでも、X11/Wayland どちらの Pi でも動く。

## なぜこの方式にしたか（fcitx5+mozc+squeekboard を採らなかった理由）

- 実機のキオスク自動起動は `/etc/xdg/lxsession/LXDE-pi/autostart` の `@chromium-browser`
  ＝ **X11/LXDE**。squeekboard は Wayland 専用なので実機では動かない。
- OS の IME 経路にすると来訪者の入力が「五十音タップ」→「onboard の QWERTY ローマ字」に
  変わる。木工所の受付で高齢者も使うことを考え、五十音タップの体験を壊さない方を選んだ。
- OS 構成に依存しない＝端末ごとの環境差・OTA 更新で壊れるリスクが無い。

## 構成（追加・変更ファイル）

| ファイル | 役割 |
|---|---|
| `kiosk_agent/kana_kanji.py` | かな→漢字 変換ロジック。辞書ルックアップ＋貪欲（最長一致）分割。依存なし・オフライン。 |
| `kiosk_agent/kana_dict.tsv` | 同梱辞書（読み\t候補,候補…）。姓・名・会社/受付語彙 約160語。 |
| `kiosk_agent/main.py` | `GET /device/convert?kana=…` を追加（`{reading, candidates}` を返す）。 |
| `kiosk_agent/static/kiosk.html` | 受付フォームに候補バー＋「変換」ボタン。fetch ヘルパ `deviceConvert` と MOCK スタブ。 |

## 変換の仕組み（`kana_kanji.convert`）

1. 読みを正規化（カタカナ→ひらがな、スペース除去）。
2. **読み全体の完全一致**候補（最優先）。
3. **貪欲分割の連結**候補：辞書で最長一致しながら区切り、各区間の第1候補を連結
   （例 `やまだ`+`たろう`→`山田太郎`）。先頭区間の別候補も1つ提示。
4. 常に**ひらがな・カタカナ**をフォールキャンディデートとして付ける。
5. 重複除去して最大12件。

mozc のような文節解析ほどの精度は無いが、受付で必要な語彙は辞書で確実に拾える。

### 全面辞書 SKK-JISYO.L（推奨・既定）

同梱の `kana_dict.tsv`（約160語）だけだと、載っていない姓名は変換できず
かな/カナのフォールバックしか出ない（例: 当初「あらき」→「荒木」が出なかった）。
そこで **`kiosk_agent/SKK-JISYO.L`（約13万語）を置くと自動マージ**され全面拡張される
（`kana_kanji.py` の `_SKK_CANDIDATES` ／ 環境変数 `KANA_DICT_EXTRA` でパス指定も可）。
EUC-JP/UTF-8 どちらでも読める。送り仮名ありエントリは自動除外。起動時に別スレッドで
事前ロード（`kana_kanji.warmup` を lifespan で呼ぶ）するので初回変換も待たされない。

- **リポジトリに同梱（資産として commit 済み・約4.5MB）**。`.gitattributes` で `-text -diff`
  （EUC-JP を改行変換で壊さない・diff 肥大化防止）のバイナリ扱い。OTA でそのまま Pi に届く。
- **自己修復**: 万一ファイルが欠けている環境では agent 起動時(`ensure_dict`)に自動 DL
  （`skk-dev.github.io/dict/SKK-JISYO.L.gz`）、`install.sh` も未取得なら DL する。取得失敗
  （オフライン）時のみ同梱 `kana_dict.tsv`(約160語)にフォールバック。
- `あらき→荒木` を確認済み。

```bash
# 手動で入れる場合(install.sh を使わないとき)
cd kiosk_agent
curl -fsSL -o SKK-JISYO.L.gz https://skk-dev.github.io/dict/SKK-JISYO.L.gz
gunzip -f SKK-JISYO.L.gz
# 起動中なら再起動で再読込: sudo systemctl restart mokuture-kiosk
```

姓名の第1候補の並びを調整したい語は、同梱 `kana_dict.tsv` に追記すると
SKK より優先される（`読み<TAB>候補,候補`。バンドル辞書を先にマージするため）。

## 動作確認（済み）

開発機（Windows）で以下を実施済み。agent は非Linuxで自動モックのためハード不要。

```bash
# 1. 変換ロジック単体
cd kiosk_agent && python -c "import kana_kanji as k; print(k.convert('やまだたろう'))"
#   -> ['山田太郎', 'やまだたろう', 'ヤマダタロウ']

# 2. エンドポイント（uvicorn 起動 → HTTP）
python -m uvicorn main:app --host 127.0.0.1 --port 8099
curl "http://127.0.0.1:8099/device/convert?kana=いその"
#   -> {"reading":"いその","candidates":["磯野","礒野","いその","イソノ"]}
```

- フロントの候補バー中核ロジック（末尾読み抽出・候補適用・段階変換・フォールバック）は
  Node で 10 ケース PASS。`kiosk.html` の inline JS は `node --check` を通過。
- **ブラウザ実操作での目視確認は未実施**（Pi かローカルブラウザで下記手順を要確認）。

### ブラウザで確認する手順

```bash
cd kiosk_agent && python -m uvicorn main:app --host 0.0.0.0 --port 8080
# ブラウザで http://localhost:8080 → 自己登録 → 管理画面で承認 → 受付メニュー → ご訪問
#   お名前欄にフォーカス → 五十音で「やまだ」→「変換」→ 候補「山田」をタップ
#   続けて「たろう」→「変換」→「太郎」→ 「山田太郎」になることを確認
# UIプレビューだけなら http://localhost:8080/?mock=1（デモ辞書: やまだ/たろう/さとう/すずき/いその/かぶしきがいしゃ）
```

## 撤退（ロールバック）

この実験は独立追加なので、`experiment/kanji-ime` を捨てれば master は無傷。
部分的に無効化したい場合は `kiosk.html` の「変換」ボタン（`convBtn`）をコメントアウトすれば
候補バーは出なくなり、従来の五十音キーボードのみに戻る。

## 採用時のTODO

- [ ] ブラウザ実操作でタッチ確認（Pi 実機推奨）
- [ ] 辞書を SKK-JISYO.L で全面化するか、`kana_dict.tsv` を運用しながら追記するか決める
- [ ] CLAUDE.md の受付フォーム説明（`showReception`）に候補バー仕様を追記
- [ ] （任意）精度を上げるなら将来 mozc 連携に `convert()` を差し替え（フロント無改修）
