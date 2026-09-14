# 名刺読み取り（QR無し来訪者の受付フォーム自動入力）

キオスクの受付画面で名刺をカメラにかざすと、名刺を自動で検出・撮影し、
会社名・氏名・部署・役職・連絡先を読み取って受付フォームに入力する。

**読み取りはこの端末の中だけで完結する。** 外部の OCR API も生成 AI も使わない。
名刺の画像も抽出した文字列も、端末の外へ出ないし、端末にもサーバにも保存しない。

---

## 目次

- [できること / できないこと](#できること--できないこと)
- [縦型・縦書きの名刺について](#縦型縦書きの名刺について)
- [必要機材](#必要機材)
- [OS セットアップ](#os-セットアップ)
- [カメラ設定](#カメラ設定)
- [インストール](#インストール)
- [起動・停止・自動起動](#起動停止自動起動)
- [使い方（画面の流れ）](#使い方画面の流れ)
- [OCR エンジンの切り替え](#ocr-エンジンの切り替え)
- [認識しきい値の変更](#認識しきい値の変更)
- [個人情報の保存・削除仕様](#個人情報の保存削除仕様)
- [完全オフラインであることの確認](#完全オフラインであることの確認)
- [API 仕様](#api-仕様)
- [処理時間の計測方法](#処理時間の計測方法)
- [OCR エンジンの比較](#ocr-エンジンの比較)
- [テスト](#テスト)
- [トラブルシューティング](#トラブルシューティング)
- [設計メモ](#設計メモ)

---

## できること / できないこと

読み取る項目（`/card/status` の `fields` と同じ順）:

| 項目 | 内容 | 受付フォームへ |
|---|---|---|
| `company_name` | 会社名 | ○ 会社名 |
| `person_name` | 氏名 | ○ お名前 |
| `person_name_kana` | ふりがな（名刺に書かれている場合のみ） | − |
| `department` | 部署 | ○ 部署（管理画面で登録済みのものと一致した場合のみ） |
| `title` | 役職 | − |
| `email` | メールアドレス | − |
| `phone` / `mobile` / `fax` | 固定電話 / 携帯 / FAX | − |
| `postal_code` / `address` | 郵便番号 / 住所 | − |
| `website` | Web サイト | − |

受付フォームへ渡すのは**お名前・会社名・部署の 3 つだけ**。それ以外は確認画面に
表示するだけで、確定と同時に破棄する（受付ログにも残らない）。

### 縦型・縦書きの名刺について

| 種類 | 会社名・氏名 | 部署・役職 | 連絡先 |
|---|---|---|---|
| 横型・横書き | ◎ | ◎ | ◎ |
| **縦型・横書き** | ◎ | ◎ | ◎ |
| **縦型・縦書き** | ○ | △ | △ |

縦型の名刺は横型と同じように扱える。縦書き（文字が縦に並ぶ組み方）の場合、
受付フォームに入る**会社名と氏名は読める**が、小さく組まれた部署・役職や
縦一列の電話番号は取りこぼすことがある。確認画面で手入力してもらう前提。

縦書きで気をつけている点:

- **名刺を 90 度回さない。** 射影だけでは「縦書きの名刺」と「横書きの名刺が
  横倒し」を区別できず、縦書きを回すと全部の文字が横倒しになって読めなくなる
  （実測で 8 行中 3 行まで落ちた）。縦のまま OCR に渡す
- 縦長の行は「起こして 1 行として読む」「1 文字ずつ切って読む」の両方を試し、
  確からしいほうを採る。行ごとに判断するので、横倒しの名刺でも取りこぼさない

### 名刺の位置の決め方（縁 → 文字の 2 段構え）

名刺の位置は**まず紙の縁**で決める。取れないときは**文字の並び**から決める。

実機で 2 段目が要る理由。手に持って差し出すと、名刺の縁は指に隠れるか、逆光の
窓や白いシャツと同系色になって明暗差が消えるか、画面の外へ少しはみ出す。実際に
読み取れなかった画面 3 枚を調べたところ、**4 つのエッジ抽出すべてで候補が 1 つも
面積の条件を通らず、名刺の輪郭が一度も組み上がっていなかった**。「四角形を
見つける」こと自体が成立していない。

一方、名刺には必ず文字が密に並んでいる。文字は紙との明暗差が大きいので、縁が
消える条件でも確実に出る。そこで

1. 文字らしい連結成分を画面全体から拾う（大きさ・縦横比・塗りつぶし率で絞る）
2. 近いものをつないで、いちばん数の多いかたまりを取る
3. そのかたまりを字の高さぶん外側へ広げた矩形を「読み取る範囲」とする

切り出す範囲は名刺の縁とぴったりではない。だが OCR は渡された画像の中から自分で
行を探すので、文字が全部入っていれば読める。**縁に合わせようとして検出できない
より、多少ずれても読めるほうが利用者の役に立つ。**

読み取れなかった実機の画面 3 枚での効果:

| | 従来（縁だけ） | 文字の並びも使う |
|---|---|---|
| 名刺A（横型・逆光） | 検出できず | **7 項目**（社名・住所・電話ほか） |
| 名刺B（横型・逆光） | 検出できず | **4 項目**（氏名・役職ほか） |
| 名刺C（縦型・顔の前） | 検出できず | **4 項目**（社名・氏名ほか） |

以前の録画（縦型を手に持った 72 秒）でも:

| | 検出率 | 撮影に進めたフレーム | 自動撮影 |
|---|---|---|---|
| 縁だけ | 27.2% | 251 | 15 回 |
| **文字の並びも使う（既定）** | **82.1%** | **709** | **28 回** |

**誤検出を止める仕組み。** 文字だけを見ると、A4 の書類やスマートフォンの画面を
名刺と取り違える。どちらも外形がはっきり測れていて、その形が名刺ではない。
そこで「名刺の形ではないが外形がはっきりしている物体」が写っていたら、その上の
文字は名刺と見ない（`detection.text_veto_support`）。実測では書類 0.78 /
スマホ 1.00 の裏付けに対し、本当に困っている実機の画面は 0.56〜0.62 だった
（名刺の縁が壊れているので外形が測れない）。

**「近づいてください」の判定が変わる。** 文字から決めた四隅は名刺の縁ではないので
占有率では大きさを測れない。代わりに「字が読める大きさか」を見る
（`quality.text_height_min`）。

### 手に持った名刺について

キオスクでは名刺を机に置かず、**手に持って差し出す**のがいちばん多い持ち方に
なる。この状態は輝度だけを見るエッジ抽出では壊れる。指が名刺の縁をまたぐと、
そこだけ「名刺 → 指 → 背景」になり、指は紙に近い明るさなので名刺と指の間に
強いエッジが立たない。輪郭は指の外側を回って閉じ、「名刺 ∪ 手」の形になって
長方形ではなくなる。

そこで**肌の色の境目もエッジとして足している**（`detection.use_skin_boundary`）。
明暗の差が無くても色の境目は確実に線になるので、指は名刺の縁で切れて長方形に
戻る。実機の録画（縦型名刺を手に持って差し出した 72 秒）で測ると:

| | 検出率 | 撮影に進めたフレーム | 自動撮影 |
|---|---|---|---|
| 肌の境目を使わない | 15.1% | 137 | 13 回 |
| **肌の境目を使う（既定）** | **27.2%** | **251** | **15 回** |

**足す順番が重要**で、輝度のエッジで取れなかったときの予備に回している。全部の
戦略に足すと、手が紙より暗くて輝度だけで縁が出ているとき（＝本来うまくいく場合）
にまで余計な線が入り、かえって検出率が落ちる。合成画像の総当たり 180 通り（横型・
回転・傾き・大きさ・肌の明るさ・背景を振ったもの）での実測:

| 手の明るさ | 全戦略に足す | 予備に回す（現在） | 足さない |
|---|---|---|---|
| 紙と同程度 | 42/60 | 43/60 | 22/60 |
| 中間 | 38/60 | **48/60** | 47/60 |
| 紙より暗い | 34/60 | **58/60** | 58/60 |

予備は 1 本だけにしてある。2 本にすると検出率は 27.2%→31.3% と上がるが、
1 フレームの処理時間の中央値が 51ms→128ms になって送信間隔 120ms に間に合わなく
なる（そのわりに自動撮影の回数は 15→16 でほとんど変わらない）。上の表のとおり
合成画像では予備を 2 本にしても 1 件も増えないので、1 本で足りると判断した。

実機の録画での 1 フレームあたりの検出時間（640x360・送信間隔 120ms）:

```
中央値 51ms / 90 パーセンタイル 61ms / 99 パーセンタイル 79ms
```

肌の境目を使わない場合は中央値 34ms なので、手が写っているフレームでは
予備の戦略のぶんだけ遅くなる。それでも送信間隔には収まっている。

肌色の範囲は `detection.skin_cr_min` ほかで調整できる。**明るさの上限は用途ごとに
2 つある**ので注意する。

| 設定 | 使う場所 | 既定 | 取り違えたときの害 |
|---|---|---|---|
| `skin_luma_max` | 肌の境目をエッジとして足す | 225 | エッジが 1 本増えるだけ（小） |
| `skin_reject_luma_max` | 候補を「肌だから名刺ではない」と落とす | 165 | **その名刺が読めなくなる（大）** |

落とす側を厳しくしてあるのは、取り違えの損得が非対称だからである。顔を名刺と
誤検出しても撮影後の受理判定で弾かれて撮り直すだけで済むが、本物の名刺を肌と
誤判定するとその名刺は永久に読み取れない。

暖色の紙は**色だけでは肌と分けられない**（生成り・クラフト紙で Cr−Cb=24〜33、
肌は 30〜40）。分かれるのは明るさで、紙のほうが明るい:

```
生成り・クラフト紙の名刺   Y=170〜225
実機の録画での肌           Y 中央値 53 / 95 パーセンタイル 110
```

既定の 165 はこの間に置いてある。

できないこと:

- 縦書きの名刺の、小さく組まれた部署・役職と縦一列の連絡先（上表の △）
- **名刺の縁を四辺とも指で覆ってしまうと検出できない**（長方形が残らない）。
  片手で下辺か横辺を持つ分には問題ない
- **茶色〜濃いベージュの名刺**（輝度 165 未満で赤寄りの紙）は肌と区別が付かず
  落ちることがある。その場合は `detection.skin_reject_luma_max` を下げる
- **上辺を親指でまたいで持つと、いちばん上に印刷された項目を落とすことがある。**
  上辺の輪郭が切れるため、検出がその下の罫線を上辺と取り違える。合成画像では
  社名が読めなくなった（罫線が名刺の高さの 9.9% にある名刺）。氏名が取れていれば
  確認画面へは進むので、社名は手入力してもらう。縁をつまむ持ち方なら起きない
- 手書きの名刺は読めない
- **極端に暗い場所では名刺の輪郭自体が拾えない**（枠線は出ない）。この場合は
  画面全体の明るさから「もう少し明るい場所でお願いします」を出す。撮影には
  進めないので、設置場所の照明を確保すること
- **確認せずに受付が確定することはない。** 必ず利用者が画面で内容を確認する

---

## 必要機材

| | 推奨 | 最低 |
|---|---|---|
| 本体 | Raspberry Pi 5 / メモリ 8GB | Raspberry Pi 4 / メモリ 4GB |
| カメラ | Raspberry Pi Camera Module 3、または UVC 対応 USB カメラ（720p 以上） | 同左 |
| ストレージ | 32GB 以上の microSD（または NVMe） | 16GB |
| 画面 | 1920×1080 のタッチディスプレイ | 同左 |

Pi 4 でも動くが、撮影後の処理時間が Pi 5 のおよそ 2 倍になる。
実測値は [処理時間の計測方法](#処理時間の計測方法) で自分の機材で確認すること。

追加で必要なディスク容量: OCR モデル約 **23MB**、Python パッケージ約 **250MB**
（opencv-python-headless と onnxruntime）。

---

## OS セットアップ

Raspberry Pi OS **Bookworm 64bit**（`aarch64`）を前提とする。32bit 版では
onnxruntime の wheel が無く、PaddleOCR 系のエンジンが動かない。

```bash
uname -m          # aarch64 であること
python3 -V        # 3.11 以上であること
```

キオスク本体のセットアップは [`README.md`](../README.md) を参照。名刺読み取りは
その上に乗る任意機能で、**入っていなくてもキオスクは従来どおり動く**（受付画面に
「名刺で入力」が出なくなるだけ）。

---

## カメラ設定

名刺の撮影にはキオスクのブラウザ（Chromium）が `getUserMedia` で開くカメラを使う。
QR コードの読み取りと同じカメラで、同じ経路。**サーバ側（Python）はカメラデバイスを
開かない**ので、`/dev/video0` の排他で困ることはない。

1. カメラを認識しているか確認する

   ```bash
   # USB カメラ
   v4l2-ctl --list-devices
   # Camera Module（libcamera 経由）
   libcamera-hello --list-cameras
   ```

2. Camera Module 3 を使う場合は、Chromium から見えるように `libcamerify` 経由で
   起動するか、`bcm2835-v4l2` を有効にして V4L2 デバイスとして見せる。
   キオスク端末の管理画面（`/device-control`）の「カメラ」でも認識状況を確認できる。

3. Chromium にカメラ権限を与える。キオスク起動オプションに以下を足しておくと、
   毎回の許可ダイアログが出ない（キオスクには操作する人がいないため必須）。

   ```
   --use-fake-ui-for-media-stream
   ```

   > この指定は「権限ダイアログを自動で許可する」もので、偽のカメラ映像を使う
   > ものではない。実際のカメラがそのまま使われる。

4. 名刺がはっきり写る距離に固定する。目安は**名刺が画面の 30〜60% を占める**くらい。
   小さすぎると「もう少しカメラに近づけてください」と案内が出る。

---

## インストール

`install.sh` が依存パッケージと OCR モデルまで面倒を見る。

```bash
cd ~/mokuture/kiosk_agent
./install.sh
```

名刺読み取りの依存だけを後から入れる場合:

```bash
cd ~/mokuture/kiosk_agent
.venv/bin/pip install -e ".[card]"
.venv/bin/python scripts/fetch_ocr_models.py
sudo systemctl restart mokuture-kiosk
```

取得状況の確認:

```bash
.venv/bin/python scripts/fetch_ocr_models.py --check
curl -s http://localhost:8080/card/status | python3 -m json.tool | head -20
```

`available: true` になれば受付画面に「名刺で入力」が出る。

### 取得されるモデル

| ファイル | 役割 | サイズ | 必須 |
|---|---|---|---|
| `det.onnx` | 文字領域の検出（PP-OCRv4 mobile det / DB） | 4.7MB | ○ |
| `rec_japan.onnx` | 日本語の認識（japan PP-OCRv4 mobile rec） | 9.7MB | ○ |
| `japan_dict.txt` | 日本語モデルの文字セット（4399 字） | 22KB | ○ |
| `rec_en.onnx` | 英数字の認識（メールアドレス用） | 7.7MB | − |
| `en_dict.txt` | 英数字モデルの文字セット（95 字） | 285B | − |
| `cls.onnx` | 行の向き（180 度の上下逆）の判定 | 0.6MB | − |

ダウンロード後に SHA-256 を照合し、一致しないファイルは残さない。
`scripts/fetch_ocr_models.py` に取得元 URL とハッシュが書いてある。

> **なぜ英数字モデルが要るのか**
> 日本語モデルの文字セットに `@` と `_` が入っていない。つまりメールアドレスを
> 原理的に出力できない。そこで英数字だけの行（ドメインを含む行）だけを英数字
> モデルで読み直している。このモデルが無い場合は、`@` が別の字に化けた形から
> 復元を試みるが、復元できないときは**空欄で返す**（勝手に作らない）。

インストール時だけネットワークを使う。以後は完全にオフラインで動く。

---

## 起動・停止・自動起動

名刺読み取りはキオスクエージェント（`mokuture-kiosk.service`）の一部として動く。
単独のサービスやポートは持たない。

```bash
sudo systemctl status  mokuture-kiosk     # 状態
sudo systemctl restart mokuture-kiosk     # 再起動（設定変更後はこれ）
sudo systemctl stop    mokuture-kiosk     # 停止
sudo systemctl enable  mokuture-kiosk     # 自動起動（install.sh が実施済み）
journalctl -u mokuture-kiosk -f | grep card   # 名刺関連のログだけ追う
```

機能だけを止めたい場合（サービスは動かしたまま）:

```bash
echo "enabled: false" >> card_reader.yaml
sudo systemctl restart mokuture-kiosk
```

起動時に OCR モデルを読み込んでおくため、最初の 1 枚も待たされない。
ログに次のように出る:

```
[card] ocr warmed up in 820ms (engine=paddle_onnx)
```

---

## 使い方（画面の流れ）

```
待機画面 → ようこそ → ご用件を選ぶ → ご訪問
                                       ↓
                              ご来訪情報（受付フォーム）
                                       ↓  「名刺で入力」を押す
                              ┌──────────────────────┐
                              │ 1) 読み取り画面        │
                              │    カメラ映像＋四隅の枠 │
                              │    自動撮影 or 撮影ボタン│
                              └──────────┬───────────┘
                                         ↓
                              ┌──────────────────────┐
                              │ 2) 確認画面            │
                              │    補正後の名刺画像     │
                              │    項目＋信頼度（色分け）│
                              │    その場で修正できる   │
                              │    確定 / 再撮影 / クリア│
                              └──────────┬───────────┘
                                         ↓
                              受付フォームに反映（氏名・会社名・部署）
                                         ↓
                                    利用者が「受付する」
```

### 自動で読み取りに入り、読めたときだけ次へ進む

名刺を認識したら**利用者は何も押さなくてよい**。条件が整った時点で自動的に撮影し、
OCR まで進む。そして**実際に項目が取れたときだけ確認画面へ遷移する**。
取れなかった場合は「失敗しました」とは出さず、そのまま黙って撮り直す。

```
名刺を認識  →  0.4 秒ほどで自動撮影  →  OCR・項目抽出
                                          ├ 取れた   → 確認画面へ
                                          └ 取れない → そのまま撮り直し
                                                       （上限まで繰り返す）
```

「取れた」と見なす条件は `accept` で決める（既定値）:

| 設定 | 既定 | 意味 |
|---|---|---|
| `accept.require_any` | `[person_name, company_name]` | 氏名か会社名のどちらかは取れていること |
| `accept.min_fields` | `2` | 埋まった項目が 2 つ以上 |
| `accept.min_confidence` | `0.35` | 全体の読み取り精度の下限 |
| `accept.max_attempts` | `5` | 撮り直しの上限。超えたら取れた分で確認画面へ進む |
| `accept.retry_cooldown_sec` | `0.8` | 撮り直しまでの間隔 |

- 連絡先だけ読めても受付フォームには使えないので、既定では撮り直す。
  会社名だけで進めたい現場では `require_any: [company_name]` にする。
- 上限（既定 5 回）に達したら、取れた分だけで確認画面へ進む。無限には繰り返さない
  （利用者が手で入力できるようにするため）。
- **「撮影する」ボタンを押した場合は内容に関わらず確認画面へ進む。** 利用者の明示的な
  操作なので、読めていなくても画面を出して手入力してもらう。
- 撮り直し中の画面には「もう一度読み取ります」「明るい場所で、名刺を枠いっぱいに
  写してください」と出し、右上に `読み取り 2 回目 / 5` のように回数を表示する。

### 自動撮影の条件

以下がすべて満たされた状態が連続 3 フレーム（既定・検出間隔 120ms なのでおよそ
0.4 秒）続くと自動で撮影する。読み取りに失敗しても自動で撮り直すので、ここは
慎重にしすぎず「認識したらすぐ読み取りに入る」ほうを優先している。

- 名刺全体が画面内に入っている
- 名刺が小さすぎない / 大きすぎない
- ピントが合っている
- 白飛び・反射が少ない
- 暗すぎない
- 位置が動いていない

満たされていないときは、直せるものから順に案内が出る:

| 状態 | 画面の案内 |
|---|---|
| 名刺が見つからない | 名刺を枠内に入れてください |
| はみ出している | 名刺全体が入るようにしてください |
| 小さすぎる | もう少しカメラに近づけてください |
| 大きすぎる | 少しカメラから離してください |
| 暗すぎる | もう少し明るい場所でお願いします |
| 反射している | 光の反射を避けてください |
| ピンぼけ | ピントを合わせています |
| 動いている | 名刺を動かさずにお待ちください |
| 撮影中 | 名刺を読み取っています |

自動撮影が働かないときのために「撮影する」ボタンも常に出している。

### 確認画面の色分け

| 信頼度 | 表示 | 意味 |
|---|---|---|
| 0.85 以上 | 通常 | そのまま使ってよい |
| 0.60 以上 0.85 未満 | 黄色「要確認」 | 読めてはいるが確認してほしい |
| 0.60 未満 | 赤「要入力」 | 怪しい。直してほしい |
| 値なし | 空欄（灰色） | 読み取れなかった |

しきい値は `confidence.ok` / `confidence.warn` で変えられる。

氏名が決めきれない場合は**確定せずに候補として出す**（入力欄は空のまま、候補
ボタンが下に並ぶ）。画像に無い文字列を勝手に作ることはしない。

---

## OCR エンジンの切り替え

`card_reader.yaml`（無ければ `card_reader.yaml.example` をコピーして作る）:

```yaml
ocr:
  engine: paddle_onnx     # 第一候補
  # engine: tesseract     # 第二候補
```

環境変数でも切り替えられる（YAML より優先）:

```bash
sudo systemctl edit mokuture-kiosk
# [Service]
# Environment=CARD_OCR__ENGINE=tesseract
sudo systemctl restart mokuture-kiosk
```

### Tesseract を使う場合

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert tesseract-ocr-eng
tesseract --list-langs        # jpn と eng があること
```

`card_reader.yaml` で `ocr.engine: tesseract` にして再起動する。
利用可否は `/card/status` の `engines` で確認できる。

```json
{"engine": "tesseract", "available": true, "detail": "ready"}
```

### ARM64 で PaddleOCR / ONNX Runtime が入らない場合

まずエラーの内容を確認すること。よくある原因:

| 症状 | 原因 | 対処 |
|---|---|---|
| `No matching distribution found for onnxruntime` | 32bit OS（`armv7l`）を使っている | 64bit の Bookworm を入れ直す |
| 同上（`aarch64` なのに出る） | Python が 3.12 より新しく wheel が未提供 | OS 同梱の Python 3.11 を使う |
| `illegal instruction` で落ちる | 古い CPU 向けでない wheel | `pip install onnxruntime==1.17.*` を試す |
| ディスク不足 | 依存だけで約 250MB 要る | 空きを作るか Tesseract に切り替える |

どうしても入らない場合は Tesseract に切り替えて運用できる。
**動いていない機能を「動いている」ように見せる（固定のサンプル結果を返す）ことは
していない。** モデルや依存が無ければ `/card/status` が `available: false` を返し、
受付画面から名刺の導線が消える。

---

## 認識しきい値の変更

しきい値はすべて設定から変えられる。ソースコードに直書きしていない。

```bash
cd ~/mokuture/kiosk_agent
cp card_reader.yaml.example card_reader.yaml
nano card_reader.yaml
sudo systemctl restart mokuture-kiosk
```

よく触る項目:

| 症状 | 設定 | どう変えるか |
|---|---|---|
| なかなか自動撮影されない | `quality.focus_min` | 下げる（60 → 30） |
| ぼけたまま撮影される | `quality.focus_min` | 上げる |
| 「反射を避けて」が出続ける | `quality.glare_max` | 上げる（0.06 → 0.12） |
| 「暗すぎ」が出続ける | `quality.brightness_min` | 下げる（90 → 60） |
| 撮影が早すぎる/手ブレする | `quality.stable_frames` | 増やす（3 → 6） |
| 何度も撮り直して進まない | `accept.min_confidence` | 下げる（0.35 → 0.2） |
| 会社名だけで進めたい | `accept.require_any` | `[company_name]` にする |
| 空の確認画面が出てしまう | `accept.min_fields` | 上げる（2 → 3） |
| 白い名刺を検出しない | `detection.gradient_noise_mult` | 下げる（1.6 → 1.2） |
| 机の木目を名刺と誤検出する | `detection.gradient_noise_mult` | 上げる（1.6 → 2.2） |
| 縦型の名刺だけ「近づけて」が出る | `quality.capture_fill_min` | 下げる（0.50 → 0.40） |
| 手で持つと検出できない | `detection.use_skin_boundary` | `true`（既定）のままか確認する |
| 名刺がまったく検出されない | `detection.text_fallback` | `true`（既定）のままか確認する |
| 遠いのに撮影に進んでしまう | `quality.text_height_min` | 上げる（5.5 → 8.0） |
| 名刺以外の印刷物に反応する | `detection.text_veto_support` | 下げる（0.70 → 0.60） |
| 文字が多い名刺で範囲がずれる | `detection.text_absorb_ratio_y` | 下げる（16.0 → 10.0） |
| 手が明るく写る照明で検出できない | `detection.skin_luma_max` | 上げる（225 → 235） |
| 生成り・クラフト紙の名刺が検出されない | `detection.skin_reject_luma_max` | 下げる（165 → 140） |
| 顔を名刺として検出してしまう | `detection.skin_reject_luma_max` | 上げる（165 → 185）※生成りの名刺が犠牲になる |
| 精度を上げたい（遅くてよい） | `preprocess.early_accept_score` | 上げる（0.86 → 0.95） |
| 速くしたい | `preprocess.variants` | `[color]` だけにする |

**しきい値は現物で測ってから決めること。** カメラと照明で値が大きく変わる。

```bash
# 実機で撮った写真の実測値を出す（写真は保存されない）
.venv/bin/python scripts/bench.py --image /tmp/sample.jpg --metrics
```

```
■ この写真の実測値（card_reader.yaml のしきい値と見比べる）
  判定           steady
  ピント           3134.0   （quality.focus_min = 60.0）
  明るさ(上位5%)    238.0   （quality.brightness_min = 90.0）
  白飛び率          0.000   （quality.glare_max = 0.06）
  占有率            0.646   （quality.capture_fill_min = 0.50）
  面積比            0.392   （参考。向きで変わるので判定には使わない）
```

ぼけた写真と合焦した写真の両方で測り、その間に `focus_min` を置く。

### 辞書の追加

部署・役職・法人格の辞書は `card/dictionaries/` のテキストファイル。
1 行 1 語で、`#` から始まる行はコメント。**保存すれば次の読み取りから反映される**
（再起動不要。ファイルの更新時刻を見て読み直している）。

| ファイル | 内容 |
|---|---|
| `titles.txt` | 役職（代表取締役・部長・マネージャー…） |
| `departments.txt` | 部署（営業部・総務課・開発本部…） |
| `department_suffixes.txt` | 部署の接尾辞（部・課・室・センター…）。辞書に無い部署を拾う |
| `company_suffixes.txt` | 法人種別（株式会社・有限会社・医療法人…） |
| `company_suffixes_en.txt` | 英文の法人種別（Co., Ltd. / Inc. / LLC…） |
| `surnames.tsv` | よくある姓と読み。氏名らしさの加点とメールアドレスとの突き合わせに使う |
| `prefectures.txt` | 都道府県 |
| `address_keywords.txt` | 住所らしさの判定に使う語 |
| `phone_labels.txt` | 電話番号の種別ラベル（TEL / FAX / 携帯…） |

よく来る取引先の部署名を足していくと精度が上がる。

> **辞書は OTA では配られない。** 現場で追記されたものを上書きしないための措置
> （[設計メモ](#構成)参照）。リポジトリ側で辞書を直した場合は、端末で
> `git pull` するか該当ファイルを手で置き換える必要がある。コード（`card/**.py`）
> だけが OTA で更新されるので、「コードは新しいが辞書は古い」状態が起こり得る。

---

## 個人情報の保存・削除仕様

**名刺の画像も抽出した文字列も保存しない。**

| データ | どこにある | いつ消える |
|---|---|---|
| カメラのフレーム | ブラウザのメモリ（canvas） | 次のフレームで上書き |
| 検出用フレーム（サーバ） | プロセスのメモリ | リクエスト処理が終わった時点 |
| 撮影画像（サーバ） | プロセスのメモリ | OCR が終わった時点 |
| 補正後の名刺画像 | セッション（プロセスのメモリ） | 確定・取り消し・タイムアウトのいずれか |
| 抽出した項目 | 同上 | 同上 |
| 確定後の値 | 受付フォームの入力欄 | 受付送信後、画面遷移で破棄 |

- ディスクには**一切書かない**。`/dev/shm` を含め一時ファイルを作らない
  （`tests/test_privacy.py::test_読み取りでファイルを作らない` で検証している）
- SQLite などのデータベースも持たない
- セッションは無操作 180 秒（`session.ttl_sec`）で自動的に破棄される
- 受付としてバックエンドへ送るのは**お名前・会社名・部署**のみ。
  メール・電話番号・住所は画面に出すだけで送信しない
- **ログに氏名・電話番号・メールアドレスを出さない。** 出すのは件数・状態・
  所要時間だけ（`tests/test_privacy.py::test_ログに氏名や連絡先を出さない` で検証）
- `/card/*` は既定で**この端末自身（127.0.0.1）からのリクエストのみ**受け付ける
  （`bind_loopback_only: true`）
- サービスは root では動かない（`mokuture-kiosk.service` の `User=`）

利用者が確認画面で直した値と OCR の元の値は区別して扱う。確定時の応答に
`edited_fields` として「どの項目が人手で直されたか」が入る（値そのものは残さない）。

---

## 完全オフラインであることの確認

### 1. ネットワークを切って動かす

```bash
sudo ip link set eth0 down
sudo nmcli radio wifi off

# キオスクで名刺を読ませる → 確認画面まで出ることを確認する
# 受付の送信だけはバックエンドが要るので失敗する（想定どおり）

sudo nmcli radio wifi on
sudo ip link set eth0 up
```

### 2. 通信を監視する

```bash
# 名刺を読み取っている間、外部への接続が発生しないことを見る
sudo tcpdump -n -i any 'not host 127.0.0.1 and not port 22' -c 50
```

### 3. コードで確認する

```bash
# 名刺モジュールに外部 URL が無いこと
grep -rn "http://\|https://" card/ --include="*.py"
# → scripts/fetch_ocr_models.py 以外には出てこない（導入時専用）

# HTTP クライアントを取り込んでいないこと
grep -rn "import requests\|import httpx\|urllib.request\|aiohttp" card/
# → 何も出ない
```

### 4. テストで確認する

```bash
.venv/bin/python -m pytest tests/test_privacy.py -v
```

`test_ネットワークを切っても撮影から抽出まで動く` が、ソケットを塞いだ状態で
撮影から項目抽出までを通している。

---

## API 仕様

すべて `http://127.0.0.1:8080` のキオスクエージェント上。外部に公開しない。
画像は multipart ではなく本文そのまま（`Content-Type: image/jpeg`）で送る。

### `GET /card/status`

名刺読み取りが使えるか、画面が必要とするしきい値。キオスクは起動時にこれを見て、
使えなければ導線を出さない。

```json
{
  "available": true,
  "enabled": true,
  "engine": "paddle_onnx",
  "detail": "ready",
  "engines": [
    {"engine": "paddle_onnx", "available": true,  "detail": "ready"},
    {"engine": "tesseract",   "available": false, "detail": "tesseract not found in PATH"}
  ],
  "dictionaries": {"titles": 117, "departments": 94, "surnames.tsv": 113},
  "capture": {"detect_interval_ms": 120, "detect_frame_max_width": 640,
              "capture_max_width": 2048, "stable_frames": 6},
  "confidence": {"ok": 0.85, "warn": 0.6},
  "guidance": {"no_card": {"ja": "名刺を枠内に入れてください", "en": "..."}},
  "fields": ["company_name", "person_name", "..."],
  "sessions": 0
}
```

### `POST /card/session`

読み取りセッションを開始する。

```json
{"session_id": "78h2eCawOaDT0BNnP_fvDg", "detect_interval_ms": 120,
 "detect_frame_max_width": 640, "capture_max_width": 2048, "ttl_sec": 180}
```

### `POST /card/frame?session_id=...`

検出用フレーム（低解像度・JPEG）を 1 枚送る。約 120ms ごとに呼ぶ。

```json
{
  "session_id": "…",
  "state": "steady",
  "message": "名刺を動かさずにお待ちください",
  "message_en": "Hold the card still",
  "should_capture": false,
  "steady": 3, "steady_needed": 6,
  "quad": [[0.19,0.16],[0.81,0.16],[0.81,0.83],[0.19,0.83]],
  "metrics": {"focus": 3134.0, "brightness": 238.0, "glare": 0.0,
              "area": 0.392, "aspect": 1.671, "text_regions": 23, "motion": 0.001},
  "elapsed_ms": 18.3
}
```

`quad` は**送ったフレームの幅・高さに対する比**。表示解像度が違っても、そのまま
掛け算で枠を描ける。`should_capture` が `true` になったら撮影フレームを送る。

### `POST /card/capture?session_id=...`

撮影フレーム（高解像度・JPEG）を送る。検出をやり直し、台形補正・OCR・項目抽出まで行う。

```json
{
  "session_id": "…",
  "fields": {
    "company_name": {"value": "株式会社サンプル商会", "confidence": 0.95},
    "person_name":  {"value": "山田太郎", "confidence": 0.97},
    "person_name_kana": {"value": "", "confidence": 0.0},
    "email": {"value": "taro.yamada@example.jp", "confidence": 0.97}
  },
  "ocr_confidence": 0.94,
  "accepted": true,
  "accept_reason": "ok",
  "proceed": true,
  "attempt": 1,
  "max_attempts": 5,
  "retry_cooldown_sec": 0.8,
  "variant": "color",
  "variants_tried": ["color"],
  "engine": "paddle_onnx",
  "rotation": 0,
  "upscale": 1.12,
  "card_size": {"width": 1152, "height": 699},
  "card_image": "data:image/jpeg;base64,…",
  "lines": [
    {"order": 0, "text": "株式会社サンプル商会", "confidence": 0.999,
     "box": [[56,44],[420,44],[420,82],[56,82]], "height": 37.8, "width": 364.0}
  ],
  "timings_ms": {"preprocess": 17.8, "ocr": 919.7, "extract": 4.3,
                 "encode": 3.6, "total": 1165.8}
}
```

確信度が低い項目には `candidates` が付くことがある（氏名など）。

`proceed` が **false** のときは確認画面へ進まず、画面側が `retry_cooldown_sec` だけ
待って検出ループを再開する（＝撮り直す）。`accepted` は `accept` の条件を満たしたか、
`accept_reason` はその理由（`missing person_name/company_name` など。値は含まない）。
`proceed` は `accepted` に加えて「手動撮影だった」「撮り直しの上限に達した」場合も
true になる。

クエリに `force=1` を付けると、読み取れた内容に関わらず `proceed: true` になる
（「撮影する」ボタン用）。

### `GET /card/session/{id}/result`

直前の読み取り結果をもう一度取得する（画面の再描画用）。

### `POST /card/session/{id}/confirm`

利用者が確認・修正した値を確定し、**セッション（＝画像と抽出結果）を破棄する**。

```jsonc
// リクエスト
{"values": {"person_name": "山田 太郎", "company_name": "株式会社サンプル商会"}}
```

```json
{
  "company_name": "株式会社サンプル商会",
  "person_name": "山田 太郎",
  "person_name_kana": "",
  "department": "営業部",
  "title": "部長",
  "postal_code": "100-0001",
  "address": "東京都千代田区千代田1-2-3 サンプルビル5F",
  "phone": "03-1234-5678",
  "mobile": "090-1234-5678",
  "fax": "03-1234-5679",
  "email": "taro.yamada@example.jp",
  "website": "https://www.example.jp",
  "ocr_confidence": 0.941,
  "confirmed_by_user": true,
  "edited_fields": ["person_name"],
  "captured_at": "2026-09-11T03:33:58Z"
}
```

送らなかった項目は OCR の値がそのまま入る。`edited_fields` は人手で直された項目名。

### `DELETE /card/session/{id}`

取り消し。セッションと画像を破棄する。

### エラー

| コード | 意味 |
|---|---|
| 400 | セッション ID の形式が不正 / 画像として読めない / 空の本文 / 知らない項目名 |
| 403 | ループバック以外からのアクセス（`bind_loopback_only`） |
| 404 | 機能が無効 / セッションが無い |
| 409 | 撮影していないのに確定しようとした |
| 413 | 本文が大きすぎる（`session.max_frame_bytes`） |
| 415 | 対応しない Content-Type |
| 422 | 名刺として読み取れなかった |
| 503 | OCR が使えない（モデル未取得など） |
| 504 | OCR がタイムアウトした |

エラー応答に内部パスやスタックトレースは含めない。

---

## 処理時間の計測方法

### 実機での測り方

```bash
cd ~/mokuture/kiosk_agent

# 1) 架空名刺で測る（すぐ試せる）
.venv/bin/python scripts/bench.py --runs 10

# 2) 実機のカメラで撮った写真で測る（こちらが本番に近い）
#    キオスクで名刺を写した状態でブラウザから保存するか、libcamera-jpeg で撮る
libcamera-jpeg -o /tmp/sample.jpg --width 1920 --height 1080
.venv/bin/python scripts/bench.py --image /tmp/sample.jpg --runs 10

# 3) 検出ループだけ（カメラ映像が引っかかる場合はここを見る）
.venv/bin/python scripts/bench.py --frames-only --runs 30

# 4) しきい値調整用の実測値
.venv/bin/python scripts/bench.py --image /tmp/sample.jpg --metrics
```

出力例:

```
■ 検出ループ（640px のフレーム 1 枚あたり・10 回）
  検出           中央値    10.5ms  最小     9.5  最大    21.9  95%    21.9
  品質判定         中央値     1.9ms  最小     1.7  最大     2.3  95%     2.3
  合計の中央値 12.4ms / 送信間隔 120ms → 間に合っている

■ 撮影後（バリアント=color / 10 回）
  画像補正         中央値    27.0ms
  OCR          中央値   885.5ms
  項目抽出         中央値     3.2ms
  合計           中央値   930.2ms
  目標 5000ms に対して 達成
```

`/card/capture` の応答にも `timings_ms` が入っているので、実運用中の値も見られる。

### 目標と現状

| 工程 | 目標（Pi 5） | 開発機での実測 |
|---|---|---|
| 名刺検出（1 フレーム） | 送信間隔 120ms 以内 | 10.5ms |
| 品質判定（1 フレーム） | 同上 | 1.9ms |
| 台形補正＋前処理 | — | 27ms |
| OCR（1 バリアント） | — | 886ms |
| 項目抽出 | — | 3.2ms |
| **撮影後の合計** | **5 秒以内** | **930ms** |

> 上の「開発機での実測」は x86_64 8 コアで測った値で、**Raspberry Pi 5 実機での
> 測定ではない**（手元に実機が無いため）。Pi 5 は ONNX Runtime の CPU 推論で
> おおむね 3〜4 倍の時間がかかるため、撮影後の合計は 3〜4 秒程度と見込んでいる。
> 目標の 5 秒に収まる想定だが、**必ず実機で上のコマンドを流して確認すること。**
> Pi 4 はさらにその 2 倍程度を見込む。

### 目標に届かない場合

処理時間の内訳（`bench.py` の出力）を見て、支配的な工程から手を打つ。
ほぼ必ず OCR が支配的になる。

1. `preprocess.variants` を `[color]` だけにする（複数試すのをやめる）
2. `preprocess.output_width` を下げる（1024 → 800）。小さい文字は読めなくなる
3. `ocr.paddle_onnx.det_limit_side_len` を下げる（960 → 736）
4. `ocr.threads` を CPU コア数 −1 にする（Pi 5 なら 3）
5. `ocr.paddle_onnx.rec_model_en` を空にする（英数字の読み直しをやめる。
   メールアドレスの精度は落ちる）

### OCR 中に画面が固まらないこと

OCR は `asyncio.to_thread` で別スレッドに逃がしてあり、同時実行は 1 件に制限して
いる（`_ocr_gate`）。検出フレームの処理は別の枠（`_frame_gate`、2 並列）で回る。
画面側は OCR の間「名刺を読み取っています」を出したまま応答を待つ。

### メモリ

ONNX セッションは常駐する（プロセス全体で 300〜400MB 程度）。8GB の Pi 5 なら
余裕がある。4GB の Pi 4 で他のプロセスと競合する場合は `ocr.threads` を 2 に
下げると、スレッドごとのアリーナが減る。

---

## OCR エンジンの比較

同じ画像（架空名刺 `landscape_ja`）を同じ前処理で読ませて比較する。

```bash
.venv/bin/python scripts/bench.py --compare-engines --runs 5
```

開発機（x86_64 8 コア）での結果:

| エンジン | 状態 | 処理時間(中央値) | 行数 | 平均信頼度 | 埋まった項目 |
|---|---|---|---|---|---|
| `paddle_onnx` | 利用可能 | 900ms | 8 | 0.982 | 11 / 12 |
| `tesseract` | 使えない（未導入） | — | — | — | — |

> 開発機に Tesseract を入れていないため、この表の Tesseract 行は埋まっていない。
> Pi 実機で `sudo apt install tesseract-ocr tesseract-ocr-jpn` を入れてから上の
> コマンドを流すと両方の行が埋まる。**数字を推測で埋めることはしない。**

### 選定の経緯

**第一候補: PaddleOCR の軽量日本語モデルを ONNX Runtime で実行**

- PaddleOCR 本体（paddlepaddle）は入れない。ARM64 での導入が重く、
  推論に必要なのは検出・認識・方向分類の 3 モデルだけなので、ONNX へ
  変換済みのものを `onnxruntime` で直接動かしている
- 検出は DB（Differentiable Binarization）、認識は CRNN + CTC
- 前処理・後処理は PaddleOCR の推論実装に合わせてある
- DB の unclip は `pyclipper` を使わず、最小外接矩形を外側へオフセットする形で
  実装した（矩形に対しては `pyclipper` と同じ結果になり、依存を 1 つ減らせる）
- 日本語モデルの文字セットに `@` `_` `〒` が無いという制約があり、
  英数字モデルの併用と、抽出側での復元・補正でカバーしている

**第二候補: Tesseract 5**

- ARM64 で onnxruntime が入らない端末向け
- `pytesseract` は使わず `tesseract` コマンドを直接呼ぶ。依存を増やさないのと、
  画像を一時ファイルに書かず標準入力へ渡せる（名刺の画像をディスクに残さない）
- 出力は TSV で受け取り、単語を行にまとめ直している

両者は `card/ocr/base.py` の `OcrEngine` を実装していて、設定 `ocr.engine` の
一語で入れ替わる。`card/pipeline.py` から下はエンジンの違いを知らない。

---

## テスト

```bash
cd ~/mokuture/kiosk_agent
.venv/bin/pip install -e ".[card,dev]"
.venv/bin/python -m pytest tests/ -q                 # 全部
.venv/bin/python -m pytest tests/ -q -m "not ocr"    # モデル不要のものだけ
.venv/bin/python -m pytest tests/ -v -k 検出          # 名前で絞る
```

OCR モデルが無い端末では、モデルを要するテストだけが自動で skip される。

### テストデータ

**実在する個人・法人の名刺は使わない。** `tests/make_fixtures.py` が架空の
会社名・氏名と予約済みドメイン（`example.jp` など）で名刺画像をその場で生成する。
生成物は `tests/fixtures/`（`.gitignore` 済み）。

```bash
.venv/bin/python tests/make_fixtures.py --list    # パターン一覧
.venv/bin/python tests/make_fixtures.py           # 画像として書き出す（目視確認用）
```

用意しているパターン（spec 14 章のケースに対応）:

`landscape_ja`（横型）/ `portrait_ja`（縦型）/ `mixed_ja_en`（日英混在）/
`english_only`（英語のみ）/ `white_card`（白い名刺）/ `colored_card`（色付き）/
`wood_background`（木目背景）/ `skewed`（斜め）/ `glare`（反射）/ `blurry`（ぼけ）/
`dark`（暗所）/ `too_small`（遠すぎ）/ `multi_phone`（電話番号が複数）/
`no_corporate_suffix`（法人格が省略）/ `small_name`（氏名が小さい）/
`with_kana`（ふりがな付き）/ `vertical_writing`（縦書き）/
`no_edges`（名刺と背景が同じ明るさ＝輪郭が絶対に取れない）/
`held_in_hand`（手に持って差し出した状態）/ `not_a_card_paper`（名刺でない紙）/
`not_a_card_phone`（スマートフォン画面）/ `blank_card`（無地の紙）/
`empty_desk`（何も無い）

`held_in_hand` は手を**紙と同じくらいの明るさ**で描いてある。そうしないと
名刺と指の間に輝度の段差ができてしまい、肌の色の境目を使わなくても検出できて
しまって、テストとして意味を持たない。実際にこのパターンは
`detection.use_skin_boundary` を `false` にすると検出できなくなる。

画像は実際のカメラ応答（紙の白は 255 ではなく 238 前後に収まる）をまねて生成して
いる。255 のままだと「白い紙」と「白飛び」が区別できず、反射のテストが成立しない。

### 開発用スクリプト

```bash
.venv/bin/python scripts/eval_detect.py     # 全パターンの検出結果を一覧
.venv/bin/python scripts/eval_pipeline.py   # 全パターンの抽出結果と所要時間を一覧
.venv/bin/python scripts/eval_pipeline.py landscape_ja --show-lines   # OCR の行も出す
.venv/bin/python scripts/eval_api.py --port 8080                      # API を実際に叩く
```

---

## トラブルシューティング

### 受付画面に「名刺で入力」が出ない

```bash
curl -s http://localhost:8080/card/status | python3 -m json.tool
```

| `detail` の内容 | 原因 | 対処 |
|---|---|---|
| `onnxruntime not importable` | 依存が入っていない | `.venv/bin/pip install -e ".[card]"` |
| `missing det_model: det.onnx` | モデルが無い | `.venv/bin/python scripts/fetch_ocr_models.py` |
| `charset size … != model classes …` | モデルと辞書の組み合わせが違う | `fetch_ocr_models.py --force` で取り直す |
| `tesseract not found in PATH` | Tesseract 未導入 | `sudo apt install tesseract-ocr tesseract-ocr-jpn` |
| `available: false, enabled: false` | 設定で無効化されている | `card_reader.yaml` の `enabled` |

`/card/status` 自体が 404 を返す場合は、エージェントが名刺モジュールを読み込めて
いない。ログに理由が出ている:

```bash
journalctl -u mokuture-kiosk -n 50 | grep "\[card\] disabled"
```

### カメラが起動しない / 映像が真っ暗

- Chromium にカメラ権限があるか（`--use-fake-ui-for-media-stream`）
- ようこそ画面の QR スキャンがカメラを掴んだままになっていないか。
  名刺画面へ入る前に必ず解放している（`stopStream()`）が、別のタブや
  アプリがカメラを使っていると開けない
- `v4l2-ctl --list-devices` でデバイスが見えるか
- `/device-control` の「カメラ」で認識状況を確認する

### 自動撮影されない

画面の案内文言がそのまま原因を指している。案内と対処の対応は
[使い方](#自動撮影の条件) の表を参照。

案内が「名刺を枠内に入れてください」のまま変わらない場合は、検出そのものが
できていない。

```bash
# 実機で撮った写真で、どの判定で落ちているか見る
.venv/bin/python scripts/bench.py --image /tmp/sample.jpg --metrics
```

- 占有率が `capture_fill_min`（0.50）より小さい → 名刺をカメラに近づける
- 縦横比が 1.45〜1.92 の外 → カメラの取り付け角度を見直す（極端な斜めは不可）
- 文字領域数が 3 未満 → ピントか解像度が足りない

それでも駄目なら「撮影する」ボタンで手動撮影できる。

### 撮り直しを繰り返して確認画面に進まない

`accept` の条件を満たす読み取りができていない。ログに理由が出る。

```bash
journalctl -u mokuture-kiosk -n 50 | grep "capture done"
# accepted=False reason=missing person_name/company_name proceed=False attempt=2/5
```

- `missing person_name/company_name` … 氏名も会社名も取れていない。撮影品質の問題
  （照明・距離・ピント）か、名刺のレイアウトが辞書と合っていない
- `only N field(s)` … 読めた項目が少ない。`accept.min_fields` を下げるか撮影品質を改善
- `confidence 0.xx` … 全体の精度が低い。`accept.min_confidence` を下げる

上限（`accept.max_attempts`、既定 5 回）に達すれば取れた分で確認画面へ進むので、
永久に止まることはない。すぐ進めたい場合は「撮影する」ボタンを押す。

### 縦型の名刺だけ精度が悪い

まず補正後の画像を確認する。四隅がずれていると、傾いたまま OCR にかかって精度が落ちる。

```bash
.venv/bin/python scripts/bench.py --image /tmp/sample.jpg --metrics
```

- 占有率が `capture_fill_min` を下回る → 名刺をもっとカメラに近づける。
  縦型は横長のカメラでは面積を稼げないので、判定は面積比ではなく
  「その向きで写せる最大の何割か」で見ている（`detection.fill_ratio`）
- 縦書きの名刺なら、上の[縦型・縦書きの名刺について](#縦型縦書きの名刺について)を参照。
  会社名・氏名は読めるが、小さい縦組みの部署・連絡先は取りこぼす

### 会社名や氏名がうまく取れない

1. 確認画面の色を見る。黄色・赤なら読めてはいるが確信が持てていない
2. `scripts/eval_pipeline.py` 相当を実機で試し、OCR の生の行を確認する

   ```bash
   .venv/bin/python -c "
   import sys; sys.path.insert(0,'.')
   import cv2
   from card.detect import detect_card
   from card.preprocess import rectify, make_variant
   from card.ocr import get_engine
   bgr = cv2.imread('/tmp/sample.jpg')
   det = detect_card(bgr)
   card,_,_ = rectify(bgr, det.quad if det else None)
   for l in get_engine().run(make_variant(card,'color')):
       print(f'{l.conf:.3f} {l.text}')
   "
   ```
3. 行としては読めているのに項目に入らない場合は辞書の問題。
   `card/dictionaries/` に語を足す（再起動不要）
4. 行そのものが読めていない場合は撮影品質の問題。照明と距離を見直す

### メールアドレスの `@` が変な字になる

英数字モデル（`rec_en.onnx`）が入っていない。

```bash
.venv/bin/python scripts/fetch_ocr_models.py --check
```

日本語モデルの文字セットに `@` が無いため、これが無いと原理的に出力できない。
抽出側で復元を試みるが、確実に特定できない場合は空欄で返す。

### 撮影後の処理が遅い

[処理時間の計測方法](#目標に届かない場合) を参照。

### 「名刺を読み取っています」から進まない

```bash
journalctl -u mokuture-kiosk -n 100 | grep card
```

- `ocr unavailable` → モデルか依存の問題（上記）
- `ocr timed out` → `ocr.timeout_sec` を延ばすか、処理を軽くする
- 何も出ない → ブラウザ側の問題。Chromium の DevTools（リモートデバッグ）で
  `/card/capture` の応答を確認する

---

## 設計メモ

### 構成

```
kiosk_agent/
├── card/
│   ├── api.py           FastAPI ルーター（/card/*）
│   ├── session.py       セッション（メモリ上の状態）と自動撮影の判定
│   ├── pipeline.py      撮影 1 枚の読み取り全体。バリアントの比較と採用
│   ├── detect.py        名刺検出（OpenCV の長方形検出）
│   ├── quality.py       撮影可否の判定と画面の案内文言
│   ├── preprocess.py    台形補正・向き・拡大・前処理バリアント
│   ├── extract.py       項目抽出と信頼度
│   ├── textnorm.py      文字列正規化・OCR 誤認の補正・かな→ローマ字
│   ├── dicts.py         辞書ファイルの読み込み
│   ├── settings.py      設定の解決（既定値 → YAML → 環境変数）
│   ├── defaults.py      既定値（しきい値の唯一の定義）
│   ├── types.py         受け渡すデータ型
│   ├── ocr/
│   │   ├── base.py        共通インターフェース
│   │   ├── paddle_onnx.py 第一候補
│   │   └── tesseract.py   第二候補
│   └── dictionaries/    部署・役職・法人格などの辞書（運用中に編集可）
├── models/              OCR モデル（fetch_ocr_models.py が取得・gitignore）
├── scripts/             モデル取得・計測・開発用の確認スクリプト
├── tests/               テストと架空名刺の生成
├── card_reader.yaml.example
└── static/kiosk.html    キオスク画面（名刺の読み取り/確認画面を含む）
```

カメラ、名刺検出、画像補正、OCR、項目抽出はそれぞれ独立したモジュールで、
上の層は下の層の実装を知らない。

### なぜカメラをブラウザ側で開くのか

キオスクは QR コードの読み取りで既にブラウザからカメラを使っている。サーバ側でも
カメラデバイスを開くと同じ `/dev/video0` を奪い合うことになる。ブラウザが取得した
フレームを HTTP で渡す形にすれば、排他の問題が起きず、カメラの扱いも 1 か所に
まとまる。

検出ループは 640px の小さいフレーム（約 30KB）を 120ms ごとに、撮影時だけ
2048px の大きいフレームを 1 枚送る。どちらも `127.0.0.1` 宛てなので転送は速い。

### 検出を一定幅で行う理由

エッジのしきい値や連結成分の大きさは画素単位で効く。検出ループ（640px）と撮影時
（1920px）で同じコードを使うと、入力解像度によって挙動が変わってしまう。そこで
`detect_card()` は必ず `detection.work_width`（既定 640px）へ縮小してから処理し、
四隅だけを元の座標へ戻している。処理時間も入力サイズに依存しなくなる。

### 白い名刺を明るい机に置いた場合

境界の輝度差が 10 程度しかなく、固定しきい値の Canny では輪郭が出ない。
エッジ抽出を複数用意し、名刺候補が採れた時点で打ち切っている。

1. 設定値の Canny — 通常のコントラスト。最も速い
2. 輝度を百分位で引き伸ばしてからモルフォロジー勾配 — 低コントラスト・暗所に強い
3. （反射があるときだけ）固定しきい値の勾配
4. 中央値ベースの自動 Canny — 上記で取れないときの保険

2 のしきい値は固定にできない。実測で名刺の境界の勾配は 16（白い名刺×明るい机）
から 130（木目の机）まで開き、背景のノイズ床も 0 から 15（暗所）まで動く。
画面の大半は平坦なので、勾配の 90 パーセンタイルをノイズ床の推定に使い、
その定数倍をしきい値にしている。

### 四隅を直線の当てはめで取り直す

`approxPolyDP` は輪郭のギザつきに引きずられる。名刺が画面内で小さいとき
（縦型を横長のカメラで写した場合）は特に顕著で、4 頂点に落とすために許容誤差を
大きくせざるを得ず、実測で四隅が 44px ずれていた。辺は本来まっすぐなので、
輪郭の点を 4 辺に振り分けて直線を当てはめ、その交点を四隅にしている（誤差 5px）。

### 木目の机との区別

四角形であるだけでは名刺としない。内側に「文字らしい連結成分」が複数あり、
かつそれが複数の行に分かれていることを要求する。木目や布地は細長い縞になるため
縦横比で落ち、無地の紙は領域自体が出ない。

### 明るさを平均で測らない理由

濃紺や黒地の名刺は平均輝度が低く、「暗い場所」と区別できない。知りたいのは
「その場に十分な光があるか」なので、名刺領域の**上位 5% 点**（95 パーセンタイル）
を見る。十分な光があれば紙の白や文字のハイライトが上位側に出る。

### 抽出の順番

確実なもの（正規表現で判定できる連絡先）から先に決めて、その行を「使用済み」に
してから曖昧なもの（会社名・氏名）を残りの行から選ぶ。

```
連絡先（メール / URL / 電話 / 郵便番号 / 住所）
  → 会社名（法人格がある場合）
  → 部署 / 役職（辞書）
  → 氏名（文字サイズ・位置・姓辞書・メールのローカル部との一致）
  → 会社名（法人格が無い場合の推測）
  → ふりがな
```

この順番には理由がある。

- 連絡先を先に取らないと、住所やメールの行が会社名・氏名の候補に混ざる
- 法人格のある会社名は氏名より確実なので先に押さえる
- 法人格が無い会社名の推測を氏名より後にしないと、社名が読めなかった名刺で
  氏名の行を会社名として拾ってしまう
- ふりがなを最後にしないと、カタカナ主体の社名（「あおぞらクリエイティブ」）を
  ふりがなとして消費してしまう

### 値を作らないこと

- 補正するのは「その並びが数字であるべき」と分かっている場所だけ
  （電話番号の中の `O`→`0`、`I`→`1`）。文章中の `O` は触らない
- 補正した値は信頼度を下げて返す（画面で黄色くなる）
- 辞書と突き合わせるときだけ OCR の字形取り違え（`ャ`↔`ヤ`、`ソ`↔`ン`）を吸収し、
  一致した場合は**辞書側の正しい表記**を表示する
- メールアドレスの `@` は、日本語モデルの文字セットに無いため復元を試みるが、
  位置を特定できない場合（小文字の英字に化けた場合など）は**空欄で返す**
- 氏名が決めきれない場合は確定せず候補として出す
- 大きい文字で氏名らしい形をしているだけでは「要確認」の閾値に届かないよう
  配点してある。姓の辞書・近くのローマ字・メールアドレスとの一致といった
  裏付けが必要

### 全体の信頼度

「読めた項目の平均」にはしていない。それだと連絡先しか読めていない名刺が、
全項目そろった名刺より高く出てしまう。受付に必要な会社名・氏名は**欠けていること
自体を減点**として扱い（重み 70%）、その他の項目は取れた分だけ加点する（30%）。
