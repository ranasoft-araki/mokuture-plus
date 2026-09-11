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
    order_quad,
    quad_area,
    quad_aspect,
    quad_angles,
    quad_motion,
    warp_card,
)
from card.quality import GUIDANCE, evaluate, message

# 検出できて、かつ自動撮影に進める（= steady）べきパターン
DETECTABLE = [
    "landscape_ja", "portrait_ja", "mixed_ja_en", "english_only",
    "white_card", "colored_card", "wood_background", "skewed",
    "multi_phone", "no_corporate_suffix", "small_name", "with_kana",
]
# 名刺ではないので検出されてはいけないもの
#   not_a_card_paper : A4 の書類（縦横比が違う）
#   not_a_card_phone : スマートフォンの画面（縦横比が違う）
#   blank_card       : 名刺と同じ大きさの無地の紙（縦横比では弾けない）
#   empty_desk       : 何も置かれていない机
NOT_A_CARD = ["not_a_card_paper", "not_a_card_phone", "blank_card", "empty_desk"]


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
