"""名刺検出（§4）と自動撮影の判定（§5）。

spec 14 章のテストケース一覧に対応する:
  横型 / 縦型 / 日本語のみ / 日英混在 / 英語のみ / 白い名刺 / 色付き名刺 /
  木目背景 / 斜め / 反射 / 名刺ではない紙 / スマートフォン画面
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from card import settings
from card.detect import (
    detect_card,
    edge_support,
    fill_ratio,
    order_quad,
    quad_area,
    quad_aspect,
    quad_angles,
    quad_motion,
    skin_mask,
    skin_ratio,
    warp_card,
)
from card.quality import GUIDANCE, evaluate, message

# 検出できて、かつ自動撮影に進める（= steady）べきパターン
DETECTABLE = [
    "landscape_ja", "portrait_ja", "mixed_ja_en", "english_only",
    "white_card", "colored_card", "wood_background", "skewed",
    "multi_phone", "no_corporate_suffix", "small_name", "with_kana",
    "vertical_writing", "held_in_hand", "held_in_hand_portrait",
]
# 名刺ではないので検出されてはいけないもの
#   not_a_card_paper : A4 の書類（縦横比が違う）
#   not_a_card_phone : スマートフォンの画面（縦横比が違う）
#   blank_card       : 名刺と同じ大きさの無地の紙（縦横比では弾けない）
#   empty_desk       : 何も置かれていない机
NOT_A_CARD = ["not_a_card_paper", "not_a_card_phone", "receipt",
              "blank_card", "empty_desk"]


def _detect_frame(bgr):
    """ブラウザが送ってくる検出用フレームと同じ大きさに落とす。"""
    width = int(settings.get("camera.detect_frame_max_width"))
    if bgr.shape[1] <= width:
        return bgr
    scale = width / bgr.shape[1]
    return cv2.resize(bgr, (width, int(bgr.shape[0] * scale)), interpolation=cv2.INTER_AREA)


def _iou(a, b, shape) -> float:
    ma = np.zeros(shape[:2], np.uint8)
    mb = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(ma, [np.array(a, np.int32)], 255)
    cv2.fillPoly(mb, [np.array(b, np.int32)], 255)
    inter = int(np.count_nonzero(cv2.bitwise_and(ma, mb)))
    union = int(np.count_nonzero(cv2.bitwise_or(ma, mb)))
    return inter / union if union else 0.0


# ── 幾何ユーティリティ ────────────────────────────────────────────────────────

def test_order_quad_は左上から時計回りに並べる():
    # わざとばらばらの順で渡す
    quad = order_quad(np.array([[100, 60], [10, 10], [100, 10], [10, 60]]))
    assert quad == ((10.0, 10.0), (100.0, 10.0), (100.0, 60.0), (10.0, 60.0))


def test_quad_の面積と縦横比():
    quad = ((0, 0), (91, 0), (91, 55), (0, 55))
    assert quad_area(quad) == pytest.approx(91 * 55)
    assert quad_aspect(quad) == pytest.approx(91 / 55, abs=1e-6)


def test_縦型名刺でも縦横比は同じ値になる():
    yoko = ((0, 0), (91, 0), (91, 55), (0, 55))
    tate = ((0, 0), (55, 0), (55, 91), (0, 91))
    assert quad_aspect(yoko) == pytest.approx(quad_aspect(tate))


def test_quad_angles_は長方形で90度():
    angles = quad_angles(((0, 0), (100, 0), (100, 50), (0, 50)))
    assert all(a == pytest.approx(90.0, abs=0.01) for a in angles)


def test_quad_motion_は移動量を短辺比で返す():
    a = ((0, 0), (100, 0), (100, 50), (0, 50))
    b = ((5, 0), (105, 0), (105, 50), (5, 50))
    assert quad_motion(a, b, 500.0) == pytest.approx(5 / 500)
    assert quad_motion(None, b, 500.0) == 1.0


# ── 検出 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern", DETECTABLE)
def test_名刺を検出して四隅が実際の位置と重なる(scene, pattern):
    bgr, truth, _spec = scene(pattern)
    frame = _detect_frame(bgr)
    scale = frame.shape[1] / bgr.shape[1]

    det = detect_card(frame)
    assert det is not None, f"{pattern}: 名刺が検出できなかった"

    expected = [(x * scale, y * scale) for x, y in truth]
    assert _iou(det.quad, expected, frame.shape) > 0.75, f"{pattern}: 四隅がずれている"
    assert 1.45 <= det.metrics.aspect <= 1.92
    assert det.metrics.text_regions >= 3


@pytest.mark.parametrize("pattern", NOT_A_CARD)
def test_名刺でないものは検出しない(scene, pattern):
    bgr, _truth, _spec = scene(pattern)
    assert detect_card(_detect_frame(bgr)) is None, f"{pattern}: 誤検出した"


def test_検出は入力解像度に依存しない(scene):
    """検出ループ(640px)と撮影時(元解像度)で同じ名刺が取れること。"""
    bgr, _truth, _spec = scene("landscape_ja")
    big = detect_card(bgr)
    small = detect_card(_detect_frame(bgr))
    assert big is not None and small is not None
    scale = bgr.shape[1] / _detect_frame(bgr).shape[1]
    scaled = [(x * scale, y * scale) for x, y in small.quad]
    assert _iou(big.quad, scaled, bgr.shape) > 0.9


def test_台形補正で名刺だけが切り出される(scene):
    bgr, _truth, _spec = scene("skewed")
    det = detect_card(bgr)
    assert det is not None
    card = warp_card(bgr, det.quad, width=800)
    assert card is not None
    assert card.shape[1] == 800
    # 91x55mm の比率に近い形になっている（斜めの台形が正面に起きている）
    assert 1.45 <= card.shape[1] / card.shape[0] <= 1.92


# ── 自動撮影の判定 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern", DETECTABLE)
def test_良好なフレームは撮影条件を満たす(scene, pattern):
    bgr, _truth, _spec = scene(pattern)
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None
    # 同じ位置に静止している状態を作る
    state, metrics = evaluate(frame, det, prev_quad=det.quad)
    assert state == "steady", f"{pattern}: {state} になった ({metrics})"
    assert metrics.motion == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("pattern,expected", [
    ("blurry", "blurry"),        # ピンぼけ
    ("glare", "glare"),          # 反射・白飛び
    ("dark", "dark"),            # 暗すぎる
    ("too_small", "too_small"),  # 小さすぎる
    ("empty_desk", "no_card"),   # 何も置かれていない
])
def test_撮影できない状態は理由が案内される(scene, pattern, expected):
    bgr, _truth, _spec = scene(pattern)
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    state, _metrics = evaluate(frame, det, prev_quad=det.quad if det else None)
    assert state == expected, f"{pattern}: {state} になった"


def test_動いている間は撮影しない(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None
    # 前フレームから大きくずれた位置を渡す
    moved = tuple((x + 40, y + 40) for x, y in det.quad)
    state, metrics = evaluate(frame, det, prev_quad=moved)
    assert state == "moving"
    assert metrics.motion > float(settings.get("quality.motion_max"))


def test_手ぶれの上限は手に持つ前提で決めてある(scene, monkeypatch):
    """机に置く前提の厳しさ（0.012）だと、手に持った名刺が撮影に進まない。

    緩めた副作用として、ブレた画像が OCR に流れてはいけない。上限そのものは
    設定から動かせること、上限を超える動きはきちんと moving になることを見る。
    """
    bgr, _truth, _spec = scene("landscape_ja")
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None

    limit = float(settings.get("quality.motion_max"))
    # 既定値そのものを固定する。実機の録画では、手に持って差し出した名刺の
    # 連続検出中の移動量が中央値 0.010・上side 0.02 台まで振れていた。机置き前提の
    # 0.012 だと「動かさずにお待ちください」が出続けて撮影に進まない。
    assert limit >= 0.02, "手に持った名刺の揺れ（実測で 0.02 台）を通せない"
    assert limit <= 0.05, "これ以上緩めるとブレた画像が OCR に流れる"
    short = min(frame.shape[0], frame.shape[1])
    # 上限の 2 倍だけ四隅をずらした「直前のフレーム」を作れば moving になる
    shifted = [(x + limit * 2 * short, y) for x, y in det.quad]
    state, m = evaluate(frame, det, prev_quad=shifted)
    assert state == "moving"
    assert m.motion > limit

    # 上限の半分なら通る
    small = [(x + limit * 0.5 * short, y) for x, y in det.quad]
    state2, m2 = evaluate(frame, det, prev_quad=small)
    assert m2.motion < limit
    assert state2 == "steady"

    # しきい値は設定から変えられる
    monkeypatch.setenv("CARD_QUALITY__MOTION_MAX", "0.0001")
    settings.reload()
    assert evaluate(frame, det, prev_quad=small)[0] == "moving"


def test_すべての状態に案内文言がある():
    from card.types import CaptureState  # noqa: F401
    for state in ("no_card", "out_of_frame", "too_small", "too_large",
                  "blurry", "glare", "dark", "moving", "steady", "capturing"):
        ja, en = message(state)
        assert ja and en, state
        assert state in GUIDANCE


def test_しきい値は設定から変えられる(scene, monkeypatch):
    """ピント判定の閾値を上げると、鮮明な画像でも blurry と判定される。"""
    bgr, _truth, _spec = scene("landscape_ja")
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None

    monkeypatch.setenv("CARD_QUALITY__FOCUS_MIN", "999999")
    settings.reload()
    state, _m = evaluate(frame, det, prev_quad=det.quad)
    assert state == "blurry"


def test_文字の無い名刺サイズの紙は検出しない(scene):
    """「四角形であること」だけで名刺と判定していないことの確認。

    縦横比・面積・角度はすべて名刺の条件を満たすが、内部に文字が無い紙。
    detection.min_text_regions が効いていないとここで検出されてしまう。
    """
    bgr, _truth, _spec = scene("blank_card")
    assert detect_card(_detect_frame(bgr)) is None


def test_無地の紙は文字領域が数えられない(scene):
    """上のテストが効いている仕組みそのものを確かめる。

    無地の紙の内部では「文字らしい連結成分」がしきい値未満しか見つからない。
    逆に本物の名刺では十分な数が見つかる。この差が木目の机や無地の紙を
    落としている根拠なので、値そのものを確認しておく。
    """
    from card.detect import count_text_regions

    threshold = int(settings.get("detection.min_text_regions"))

    blank, blank_quad, _s = scene("blank_card")
    frame = _detect_frame(blank)
    scale = frame.shape[1] / blank.shape[1]
    quad = tuple((x * scale, y * scale) for x, y in blank_quad)
    regions, rows = count_text_regions(frame, quad)
    assert regions < threshold or rows < 2, f"無地の紙で {regions} 領域 / {rows} 行"

    card, _t2, _s2 = scene("landscape_ja")
    card_frame = _detect_frame(card)
    det = detect_card(card_frame)
    assert det is not None
    card_regions, card_rows = count_text_regions(card_frame, det.quad)
    assert card_regions >= threshold and card_rows >= 2


# ── 手に持った名刺（実機で最初に壊れた条件）──────────────────────────────────

def test_手に持った名刺は肌の境目が無いと検出できない(scene, monkeypatch):
    """実機の録画で「端を指で持つと検出できない」が起きた仕組みそのもの。

    指は紙に近い明るさなので、名刺と指の間には強いエッジが立たない。
    輪郭は指の外側を回って閉じ、「名刺 ∪ 手」の形になって長方形ではなくなる。
    肌と肌でないものの境目をエッジとして足すと、指が名刺の縁で切れて
    長方形に戻る。この差が出ていることを両方向で確かめる。
    """
    bgr, truth, _spec = scene("held_in_hand")
    frame = _detect_frame(bgr)
    scale = frame.shape[1] / bgr.shape[1]
    want = [(x * scale, y * scale) for x, y in truth]

    det = detect_card(frame)
    assert det is not None
    assert _iou(det.quad, want, frame.shape) > 0.85

    # 肌の境目だけを切り分けたいので、文字ベースの予備も止める
    monkeypatch.setenv("CARD_DETECTION__USE_SKIN_BOUNDARY", "false")
    monkeypatch.setenv("CARD_DETECTION__TEXT_FALLBACK", "false")
    settings.reload()
    assert detect_card(frame) is None


def test_縦型の名刺を手に持った場合も肌の境目で検出できる(scene, monkeypatch):
    """利用者が実際に困った形（縦型を手のひらの前に立てて差し出す）。

    親指が上辺に、指先が右辺にかかる。名刺の右辺と上辺は手に重なるので
    輝度だけでは辺が出ない。
    """
    bgr, truth, _spec = scene("held_in_hand_portrait")
    frame = _detect_frame(bgr)
    scale = frame.shape[1] / bgr.shape[1]
    want = [(x * scale, y * scale) for x, y in truth]

    det = detect_card(frame)
    assert det is not None
    assert _iou(det.quad, want, frame.shape) > 0.80

    # 肌の境目だけを切り分けたいので、文字ベースの予備も止める
    monkeypatch.setenv("CARD_DETECTION__USE_SKIN_BOUNDARY", "false")
    monkeypatch.setenv("CARD_DETECTION__TEXT_FALLBACK", "false")
    settings.reload()
    assert detect_card(frame) is None


def test_生成りやクラフト紙の名刺を肌と間違えない(scene):
    """暖色の紙は色域では肌と分けられないので、明るさで分けている。

    ここを緩めると（＝肌と判定する明るさの上限を上げると）生成りの名刺が
    max_skin_ratio で落ち、その名刺は永久に読み取れなくなる。実際に一度
    そうなったので、紙の色を振って回帰させないようにする。
    """
    import make_fixtures as mf
    papers = [(248, 242, 228), (235, 220, 190), (228, 210, 178),
              (220, 200, 165), (210, 190, 155), (205, 180, 145)]
    for paper in papers:
        card = mf.render_card(mf.CardSpec(bg=paper))
        img, truth = mf.place_on_background(
            card, mf.plain_background(mf.SCENE_W, mf.SCENE_H, (150, 150, 150)))
        bgr = cv2.cvtColor(np.asarray(mf.simulate_camera(img)), cv2.COLOR_RGB2BGR)
        frame = _detect_frame(bgr)
        scale = frame.shape[1] / bgr.shape[1]
        want = [(x * scale, y * scale) for x, y in truth]
        assert skin_ratio(frame, want) < float(settings.get("detection.max_skin_ratio")), (
            f"紙 {paper} が肌と判定されている")
        assert detect_card(frame) is not None, f"紙 {paper} の名刺が検出できない"


def test_肌の色の範囲は設定から変えられる(scene, monkeypatch):
    """肌色のしきい値はハードコードせず設定で動かせること（§13）。"""
    bgr, _truth, _spec = scene("held_in_hand")
    frame = _detect_frame(bgr)
    before = int(np.count_nonzero(skin_mask(frame)))
    assert before > 0

    # 明るさの上限を下げれば、明るい照明下の手は肌と見なされなくなる
    monkeypatch.setenv("CARD_DETECTION__SKIN_LUMA_MAX", "150")
    settings.reload()
    assert int(np.count_nonzero(skin_mask(frame))) < before // 10


def test_名刺の紙は肌と見なさない(scene):
    """肌の判定が紙まで拾うと、名刺そのものが max_skin_ratio で落ちる。"""
    for pattern in ("landscape_ja", "white_card", "colored_card"):
        bgr, _truth, _spec = scene(pattern)
        frame = _detect_frame(bgr)
        assert np.count_nonzero(skin_mask(frame)) / frame[:, :, 0].size < 0.01, pattern


def test_顔のように肌が多い候補は名刺として採らない(scene, monkeypatch):
    """max_skin_ratio が効いていることを、値を絞って逆向きに確かめる。

    実機では名刺を顔の前に持つので、顔が候補として上がってくる。
    """
    bgr, _truth, _spec = scene("landscape_ja")
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None
    assert skin_ratio(frame, det.quad) < float(settings.get("detection.max_skin_ratio"))

    # 名刺の内側の肌率でも落ちる値まで下げれば、検出されなくなる。
    # max_skin_ratio は縁から決めた候補にだけ効くので、文字ベースの予備は止める
    # （文字から決めた範囲の肌色は text_skin_box_ratio が別の測り方で見る）。
    monkeypatch.setenv("CARD_DETECTION__MAX_SKIN_RATIO", "-1")
    monkeypatch.setenv("CARD_DETECTION__TEXT_FALLBACK", "false")
    settings.reload()
    assert detect_card(frame) is None


# ── 候補の絞り込み ────────────────────────────────────────────────────────────

def test_辺の裏付けは本物の縁で高く_でたらめな四角形で低い(scene):
    """edge_support は「その四辺に本当に明暗の段差があるか」を測る。

    木目の机のように四角形がいくらでも取れる背景で、名刺以外を落とす根拠。
    """
    bgr, truth, _spec = scene("wood_background")
    frame = _detect_frame(bgr)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = frame.shape[1] / bgr.shape[1]
    want = [(x * scale, y * scale) for x, y in truth]

    thresh = float(settings.get("detection.gradient_thresh"))
    on_card = edge_support(gray, want, thresh)
    # 名刺の中に完全に収まる小さな四角形。縁ではないので段差が無い
    cx = sum(p[0] for p in want) / 4
    cy = sum(p[1] for p in want) / 4
    inside = [(cx - 20, cy - 12), (cx + 20, cy - 12), (cx + 20, cy + 12), (cx - 20, cy + 12)]
    assert on_card > float(settings.get("detection.min_edge_support"))
    assert on_card > edge_support(gray, inside, thresh)


def test_占有率は向きで変わらない():
    """縦型でも横型でも「画面をどれだけ占めているか」は同じ尺度で測る。

    ここが向き依存だと、縦型名刺だけ「もっと近づけてください」が出続ける。
    """
    w, h = 640, 360
    # 長辺が画面の長辺いっぱいなら、どちらの向きでも 1.0 に近い値になる
    assert fill_ratio([(0, 100), (w - 1, 100), (w - 1, 300), (0, 300)], w, h) > 0.95
    assert fill_ratio([(100, 0), (300, 0), (300, h - 1), (100, h - 1)], w, h) > 0.95
    # 小さければどちらの向きでも小さい
    assert fill_ratio([(0, 0), (100, 0), (100, 60), (0, 60)], w, h) < 0.3
    assert fill_ratio([(0, 0), (60, 0), (60, 100), (0, 100)], w, h) < 0.3


# ── 文字から位置を決める経路（紙の縁が使えないとき）──────────────────────────

def test_縁が見えない名刺は文字の並びから見つける(scene, monkeypatch):
    """名刺と背景が同じ明るさで、輪郭からは四角形が絶対に組めない絵。

    実機では逆光の窓や白いシャツを背にするとこれに近くなる。利用者から
    「外枠の認識自体が難しいので文字を認識したほうが早いのでは」と指摘が
    あり、実際の失敗画面ではエッジ側の候補が 1 つも通っていなかった。
    """
    bgr, truth, _spec = scene("no_edges")
    frame = _detect_frame(bgr)
    scale = frame.shape[1] / bgr.shape[1]
    want = [(x * scale, y * scale) for x, y in truth]

    det = detect_card(frame)
    assert det is not None
    assert det.source == "text"
    # 四隅は名刺の縁ではないので重なり具合ではなく「はみ出していないか」で見る
    own = np.zeros(frame.shape[:2], np.uint8)
    card = np.zeros(frame.shape[:2], np.uint8)
    cv2.fillPoly(own, [np.array(det.quad, np.int32)], 255)
    cv2.fillPoly(card, [np.array(want, np.int32)], 255)
    inside = np.count_nonzero(cv2.bitwise_and(own, card)) / np.count_nonzero(own)
    assert inside > 0.90, "切り出す範囲が名刺からはみ出している"

    monkeypatch.setenv("CARD_DETECTION__TEXT_FALLBACK", "false")
    settings.reload()
    assert detect_card(frame) is None


def test_名刺の中の小さな四角形で確定しない(scene, monkeypatch):
    """縁から取れたのが「撮影に進めない大きさ」なら、文字からも決め直す。

    実機の録画で起きたこと: 氏名の周りの余白が名刺らしい縦横比の四角形として
    取れてしまい、そこで検出が確定していた。画面には「もう少し近づけてください」
    が出続け、名刺をいくら近づけても撮影に進まない（近づけても掴んでいるのは
    名刺の中の一部分なので、占有率は上がらない）。その間、文字からは名刺全体が
    取れていた。小さい候補で確定せず、文字からも決めて広いほうを採ること。
    """
    import card.detect as detect_mod

    bgr, _truth, _spec = scene("no_edges")
    frame = _detect_frame(bgr)
    h, w = frame.shape[:2]

    # 名刺の中に収まる小さな四角形（名刺らしい縦横比）を縁の経路が返す状況を作る
    small = ((0.40 * w, 0.45 * h), (0.53 * w, 0.45 * h),
             (0.53 * w, 0.53 * h), (0.40 * w, 0.53 * h))
    from card.types import Detection, FrameMetrics
    fake = Detection(quad=small, metrics=FrameMetrics(
        area_ratio=quad_area(small) / float(w * h), aspect=quad_aspect(small),
        text_regions=4), score=0.9, source="edge")
    monkeypatch.setattr(detect_mod, "_best_quad", lambda *a, **k: fake)

    det = detect_card(frame)
    assert det is not None
    assert det.source == "text", "小さな四角形のまま確定している"
    assert quad_area(det.quad) > quad_area(small) * 3

    # 文字からは決められない絵（何も写っていない机）では、小さくても縁の候補を残す。
    # ここで None にしてしまうと「近づけてください」の案内自体が出せなくなる。
    bgr, _truth, _spec = scene("empty_desk")
    empty = _detect_frame(bgr)
    det = detect_card(empty)
    assert det is not None and det.source == "edge"


def test_縁の候補が十分な大きさなら文字の経路は使わない(scene, monkeypatch):
    """毎フレーム文字まで走らせると Pi の検出間隔に間に合わない。

    縁で名刺らしい大きさが取れているときは、そのまま使うこと。
    """
    import card.text_detect as text_mod

    bgr, _truth, _spec = scene("landscape_ja")
    frame = _detect_frame(bgr)

    def fail(*a, **k):
        raise AssertionError("縁で足りているのに文字の経路を呼んでいる")

    monkeypatch.setattr(text_mod, "detect_by_text", fail)
    det = detect_card(frame)
    assert det is not None and det.source == "edge"


def test_紙の上の字と顔の造作を肌色で見分ける(scene):
    """文字から決めた範囲の肌色は「広げた四角形の内側」では測れない。

    手に持つと余白ぶん必ず手が入るので、名刺でも顔でも同じくらいの値になる
    （実測 0.16-0.21 と 0.12-0.20 で重なった）。箱の中身で測れば、印刷された字は
    紙の上・目や鼻は肌の上、という違いがそのまま出る。
    """
    from card.text_detect import skin_box_ratio

    h, w = 120, 200
    boxes = [(20 + 30 * i, 40, 18, 24) for i in range(5)]

    paper = np.full((h, w, 3), 235, np.uint8)          # 白い紙
    skin = np.zeros((h, w, 3), np.uint8)
    skin[:] = (95, 120, 175)                           # 肌色(BGR)。Y は上限より暗い
    for img in (paper, skin):
        for x, y, bw, bh in boxes:
            cv2.rectangle(img, (x, y), (x + bw, y + bh), (30, 30, 30), 2)

    assert skin_box_ratio(paper, boxes) < float(settings.get("detection.text_skin_box_ratio"))
    assert skin_box_ratio(skin, boxes) > float(settings.get("detection.text_skin_box_ratio"))


def test_文字から決めたときは字の大きさで近さを見る(scene, monkeypatch):
    """四隅が名刺の縁でないので、占有率では「近づいてください」を判定できない。

    代わりに「字が読める大きさか」を見る。ここが効いていないと、遠くの小さな
    名刺でも撮影に進んで、読めない画像を OCR にかけ続けることになる。

    しきい値は画面幅に対する比で持つ。OCR がかかるのは検出フレームではなく
    撮影画像なので、検出フレームの画素数で決め打ちにすると、実機で「画面から
    はみ出すほど近づけないと認識しない」状態になる（実際になった）。
    """
    bgr, _truth, _spec = scene("no_edges")
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None and det.source == "text"
    assert evaluate(frame, det, det.quad)[0] == "steady"

    monkeypatch.setenv("CARD_QUALITY__TEXT_HEIGHT_MIN_RATIO", "0.5")
    settings.reload()
    assert evaluate(frame, det, det.quad)[0] == "too_small"


def test_名刺でない物体の上の文字は名刺と見ない(scene):
    """A4 の書類やスマートフォンの画面には文字が密に並んでいる。

    どちらも外形がはっきり測れていて、その形が名刺ではない。文字だけを見ると
    取り違えるので、「名刺でない外形がはっきり写っている」ことを根拠に止める。
    """
    for pattern in ("not_a_card_paper", "not_a_card_phone"):
        bgr, _truth, _spec = scene(pattern)
        assert detect_card(_detect_frame(bgr)) is None, pattern


def test_文字の切り出しは罫線やロゴを文字と数えない(scene):
    """中空の図形（飾り罫・枠）を文字として数えると、無地の紙でも反応してしまう。"""
    from card.text_detect import text_boxes, dominant_cluster
    bgr, _truth, _spec = scene("blank_card")
    frame = _detect_frame(bgr)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _core, group = dominant_cluster(text_boxes(gray), gray.shape)
    assert len(group) < int(settings.get("detection.text_min_boxes"))


def test_レシートは文字が多くても名刺と見ない(scene):
    """細長い印刷物。文字だけを見ていると名刺と取り違える。

    縁からは名刺の縦横比にならないので落ちるが、縁が取れないときに文字へ
    落ちてくるため、文字が入る範囲の縦横比にも上限を置いている。
    """
    bgr, _truth, _spec = scene("receipt")
    assert detect_card(_detect_frame(bgr)) is None


def test_見切れた名刺でも写っている範囲は読み取りに進む(scene):
    """名刺が画面から大きくはみ出している状態。

    文字から位置を決めるときは名刺の縁が見えないので、「名刺が切れている」のか
    「画面の端にたまたま文字（ブラインドの桟・襟など）がある」のかを区別できない。
    見切れを理由に止める作りにしたところ、実機の映像では後者で止まって
    まったく読み取れなくなった。誤って止めると利用者は何もできないが、誤って
    撮っても受理判定で弾かれて撮り直しになるだけなので、止めない側に倒す。

    見切れていること自体は text_clipped に記録して、後から判断できるようにする。
    """
    bgr, _truth, _spec = scene("card_half_out")
    frame = _detect_frame(bgr)
    det = detect_card(frame)
    assert det is not None and det.source == "text"
    state, m = evaluate(frame, det, prev_quad=det.quad)
    assert m.text_clipped is True, "見切れていることが記録されていない"
    assert state == "steady"


def test_名刺でない物体が別の場所にあっても名刺は検出できる(scene):
    """「名刺でない外形」を見つけたら一律に止める作りにすると、縁が壊れている
    だけの本物の名刺まで落ちる（実際に落ちた）。拾った文字がその物体の上に
    あるときだけ止めること。
    """
    import make_fixtures as mf
    from PIL import ImageDraw
    spec = mf.CardSpec()
    card = mf.render_card(spec)
    # 縁が取れない名刺（背景と同じ明るさ）の隣に、はっきりした別の四角形を置く
    img, _quad = mf.place_on_background(
        card, mf.plain_background(mf.SCENE_W, mf.SCENE_H, spec.bg),
        scale=0.40, offset=(-0.28, 0.0))
    d = ImageDraw.Draw(img)
    d.rectangle([int(mf.SCENE_W * 0.66), int(mf.SCENE_H * 0.20),
                 int(mf.SCENE_W * 0.97), int(mf.SCENE_H * 0.86)],
                fill=(70, 70, 74))
    bgr = cv2.cvtColor(np.asarray(mf.simulate_camera(img)), cv2.COLOR_RGB2BGR)
    det = detect_card(_detect_frame(bgr))
    assert det is not None, "別の物体に引きずられて名刺を落としている"
