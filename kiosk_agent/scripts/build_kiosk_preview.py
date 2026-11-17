"""受付キオスクの「体験版」を 1 つの HTML ファイルに組み立てる。

開発環境の無い人へ送るためのもの。受け取った人は HTML をダブルクリックするだけで、
ラズパイ・エージェント・バックエンド無しに受付画面の流れを触れる。

    kiosk_agent/.venv/Scripts/python.exe kiosk_agent/scripts/build_kiosk_preview.py
    (Windows の素の python は固まるので .venv のものを使う。PYTHONUTF8=1 を付ける)

出力: dist/kiosk-preview/  (HTML と使い方) と dist/mokuture-kiosk-preview.zip

本番の static/kiosk.html は書き換えない。読み込んで文字列を差し替えた写しを作るだけ。
差し替えの目印が kiosk.html から消えたら、黙って壊れた版を作らずにここで止まる。
"""
from __future__ import annotations

import base64
import sys
import zipfile
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
STATIC = AGENT / "static"
OUT_DIR = AGENT.parent / "dist" / "kiosk-preview"
ZIP_PATH = AGENT.parent / "dist" / "mokuture-kiosk-preview.zip"
HTML_NAME = "mokuture受付キオスク体験版.html"
README_NAME = "使い方.txt"

README = """\
mokuture+ 受付キオスク 体験版
================================

■ 開き方
  「mokuture受付キオスク体験版.html」をダブルクリックしてください。
  ブラウザ(Chrome か Edge)で受付画面が開きます。インストールは要りません。
  F11 キーで全画面にすると、実機(横長のタッチ画面)に近い見え方になります。
  タッチ画面でない PC ではマウスのクリックで操作します。

■ これは何か
  受付に置くタッチ端末の画面を、パソコンのブラウザだけで再現したものです。
  表示される会社名・担当者・会議室などはすべて見本のデータで、
  どこにも送信されません(担当者への通知も飛びません)。

■ 試せること
  1. 最初の暗い画面(待機画面)をクリックすると、受付が始まります。
     ※実機では人が近づくとセンサーで自動的に始まります。
  2. 予約QRをお持ちの方の流れ
     カメラの使用を聞かれたら「許可」「ブロック」どちらでも構いません。
     (カメラが無い・ブロックした場合は赤い案内が出ますが、そのまま進めます)
     右下の点線のボタン「（体験版）予約QRを読み取ったことにする」を押すと、
     「お待ちください」の数秒後に、お迎えの画面と館内マップへ進みます。
  3. 予約のない方の流れ
     「画面で入力して受付する」→「ご訪問」→ 右のキーボードでお名前を入力 →「受付する」。
     担当者の返事は数秒で自動的に返ります。受付するたびに
       1回目: 担当者が参ります / 2回目: お電話ください / 3回目: お断り
     の順に切り替わるので、続けて3回試すとすべての結果画面を見られます。
     (ブラウザを再読み込みすると 1回目に戻ります)
     ※「変換」で漢字になるのは、体験版では次の読みだけです:
       やまだ / たろう / さとう / すずき / いその / かぶしきがいしゃ
       (実機は約13万語の辞書で変換します)
  4. ロッカー
     「画面で入力して受付する」→「ロッカー」→「手荷物一時保管」で、
     空いている口に暗証番号を決めて預けます。
     「荷物受け取り」では、B のロッカーが最初から利用中です(暗証番号 1234)。
  5. 荷物の配達
     「画面で入力して受付する」→「荷物の配達」→ 置き配(ロッカーへ入れる) / 呼び出し(担当者を呼ぶ)。
     ※置き配で入れた口の暗証番号は、実機では担当者にだけ通知されます。
       体験版では取り出せないので、空きに戻すには再読み込み(F5)してください。
  6. 画面下の「EN」で、日本語と英語のどちらを大きく表示するかを切り替えられます。

  どの画面でも、しばらく操作しないと最初の画面へ戻ります。
  はじめからやり直すときは、ブラウザの再読み込み(F5)を押してください。

■ 実機と違うところ
  ・名刺の読み取り、声での操作、受付後のアンケートは、この体験版には入っていません。
  ・ロッカーの扉は実際には開きません(画面の流れだけ進みます)。
  ・文言・ロゴ・担当者の一覧などは、実際は管理画面で自由に変えられます。
  ・スマートフォンでは画面が小さくなります。パソコンでご覧ください。
"""


# 待機画面のあいだだけ画面下に出す案内。操作のじゃまをしない(pointer-events:none)。
PREVIEW_HINT = """<script>
(function () {
  var h = document.createElement("div");
  h.textContent = "画面をクリックすると受付が始まります（実機では、人が近づくと自動で始まります）";
  h.style.cssText = "position:fixed;left:50%;bottom:5vh;transform:translateX(-50%);z-index:2147483646;" +
    "pointer-events:none;background:rgba(255,254,251,.94);color:#1d1a15;font-family:'Noto Sans JP',Inter,system-ui,sans-serif;" +
    "font-size:clamp(14px,1.5vw,22px);font-weight:600;padding:.7em 1.6em;border-radius:999px;white-space:nowrap;" +
    "box-shadow:0 4px 18px rgba(0,0,0,.4);display:none";
  document.body.appendChild(h);
  setInterval(function () {
    var idle = false;
    try { idle = CURRENT_SCREEN === "idle"; } catch (e) {}
    h.style.display = idle ? "block" : "none";
  }, 300);
})();
</script>
"""


def replace_once(text: str, old: str, new: str, what: str) -> str:
    """ちょうど 1 か所だけ差し替える。0 か所・複数か所なら止める。"""
    n = text.count(old)
    if n != 1:
        sys.exit(f"[build_kiosk_preview] {what}: 目印が {n} か所ありました(1 か所のはず)。"
                 f"kiosk.html が変わったので、このスクリプトの目印を直してください。\n  目印: {old!r}")
    return text.replace(old, new)


def build() -> str:
    html = (STATIC / "kiosk.html").read_text(encoding="utf-8")
    jsqr = (STATIC / "jsqr.min.js").read_text(encoding="utf-8")
    tap_b64 = base64.b64encode((STATIC / "tap.mp3").read_bytes()).decode("ascii")
    if "</script" in jsqr.lower():
        sys.exit("[build_kiosk_preview] jsqr.min.js に </script が含まれるため埋め込めません。")

    # 1) 外部ファイルを埋め込む(ダブルクリック=file:// では /xxx の絶対パスを読めない)
    html = replace_once(html, '<script src="/jsqr.min.js"></script>',
                        "<script>" + jsqr + "</script>", "QR 読み取りライブラリ")
    # 行動ログは体験版では取らない(読み込まなければ AN が何もしない版に落ちる)
    html = replace_once(html, '<script src="/kiosk-oplog.js"></script>', "", "行動ログ")
    html = replace_once(html, 'fetch("/tap.mp3")',
                        'fetch("data:audio/mpeg;base64,' + tap_b64 + '")', "タップ音")

    # 2) 常にダミーデータで動かす(URL に ?mock=1 を付けなくてよい)
    html = replace_once(html, "let MOCK = (() => {", "let MOCK = true || (() => {", "MOCK の既定")
    # 3) 通知も本物を試さない(開発用の MOCK は通知だけ実経路を試すが、体験版はどこにも送らない)
    html = replace_once(html, "    if (_isRealNotifyPath(path)) {", "    if (false) {", "通知の実経路")

    # 4) 受け取った人向けの表示
    html = replace_once(html, "<title>mokuture+</title>",
                        "<title>mokuture+ 受付キオスク 体験版</title>", "タイトル")
    html = replace_once(html, "MOCK モード · 表示はダミー（通知のみ実送信） · 解除は ?mock=0",
                        "体験版 · 表示は見本のデータです（どこにも送信されません）", "バッジ")
    html = replace_once(html, "（MOCK）予約QRを読み取ったことにする",
                        "（体験版）予約QRを読み取ったことにする", "QR の代用ボタン")
    html = replace_once(html, "（MOCK）商談ルーム A", "商談ルーム A", "見本の会議室名")
    # 結果画面の順番(受付→電話→お断り)はフォーム受付だけで数える。元は予約 QR・配達の呼び出しも
    # 同じ数を進めるので、QR のあとにフォームを試すと「1回目=参ります」が外れ、予約のお客様に
    # お断りが出ることもあった(実物は予約にお断りの選択肢が無い)。予約 QR は常に「受付」にする。
    html = replace_once(
        html,
        '_mockDecisionState = ["accepted", "phone", "declined"][_mockCreateCount++ % 3];',
        '_mockDecisionState = (body && body.method === "appointment") ? "accepted" '
        ': ["accepted", "phone", "declined"][_mockCreateCount++ % 3];',
        "結果の順番(受付)")
    html = replace_once(
        html,
        '_mockDecisionState = ["accepted", "phone"][_mockCreateCount++ % 2];',
        '_mockDecisionState = ["accepted", "phone"][(window._pvCallCount = (window._pvCallCount || 0) + 1, '
        'window._pvCallCount - 1) % 2];',
        "結果の順番(呼び出し)")
    # QR の代用ボタンは開発用に薄く小さい。体験版ではこれが予約 QR の流れの入口なので読める大きさにする
    html = replace_once(
        html,
        "padding:12px;background:transparent;border:1.5px dashed ${T.muted};border-radius:12px;font-size:16px;color:${T.muted}",
        "padding:16px;background:transparent;border:2px dashed ${T.sub};border-radius:12px;font-size:24px;font-weight:600;color:${T.sub}",
        "QR の代用ボタンの見た目")
    if "MOCK-KIOSK" not in html:
        sys.exit("[build_kiosk_preview] 端末名 MOCK-KIOSK が見つかりません。")
    html = html.replace("MOCK-KIOSK", "体験版")
    # 待機画面は実機だと人感センサーで始まる。体験版では「クリックで始まる」と分かるように添える
    html = replace_once(html, "</body>", PREVIEW_HINT + "</body>", "待機画面の案内")
    # 仕上がりの確認: 外のファイルを読みに行く書き方が残っていたら配らない
    for bad in ('<script src=', '<link ', 'fetch("http', "fetch('http"):
        if bad in html:
            sys.exit(f"[build_kiosk_preview] 外部参照が残っています: {bad}")
    return html


def main() -> None:
    html = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / HTML_NAME).write_text(html, encoding="utf-8", newline="\n")
    # メモ帳で開く人向けに BOM 付き UTF-8・CRLF
    (OUT_DIR / README_NAME).write_text(README, encoding="utf-8-sig", newline="\r\n")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for name in (HTML_NAME, README_NAME):
            z.write(OUT_DIR / name, name)
    print(f"HTML : {OUT_DIR / HTML_NAME} ({(OUT_DIR / HTML_NAME).stat().st_size // 1024} KB)")
    print(f"ZIP  : {ZIP_PATH} ({ZIP_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
