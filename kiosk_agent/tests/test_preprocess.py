"""画像補正（§6）: 台形補正・向きの正規化・拡大・前処理バリアント。"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from card import settings
from card.detect import detect_card
from card.preprocess import (
    VARIANT_LABELS,
    decode_image,
    limit_width,
    make_variant,
    median_text_height,
    normalize_orientation,
    rectify,
    rotate_180,
    to_jpeg,
    upscale_if_small,
    variants,
)


def test_台形補正で名刺の比率に戻る(scene):
    bgr, _truth, _spec = scene("skewed")
    det = detect_card(bgr)
    assert det is not None
    card, angle, factor = rectify(bgr, det.quad)
    assert card is not None
    # 設定の幅にそろえたあと、文字が小さければ factor 倍に拡大される
    assert card.shape[1] == pytest.approx(
        int(settings.get("preprocess.output_width")) * factor, abs=2)
    assert 1.45 <= card.shape[1] / card.shape[0] <= 1.95


def test_四隅が無いときは画像全体を名刺として扱う(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    card, _angle, _factor = rectify(bgr, None)
    assert card is not None
    assert card.shape[1] > 0


def test_横書きの縦型名刺は回さない(scene):
    """縦長の名刺でも文字が横書きなら、そのままの向きが正しい。"""
    bgr, _truth, _spec = scene("portrait_ja")
    det = detect_card(bgr)
    assert det is not None
    _card, angle, _factor = rectify(bgr, det.quad)
    assert angle == 0


def test_90度倒れた名刺は起こす(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    assert det is not None
    card, _angle, _factor = rectify(bgr, det.quad)
    sideways = cv2.rotate(card, cv2.ROTATE_90_CLOCKWISE)
    fixed, angle = normalize_orientation(sideways)
    assert angle == 90
    # 起こした結果は元と同じく横長になる
    assert fixed.shape[1] > fixed.shape[0]


def test_180度回転は形を変えない(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    flipped = rotate_180(bgr)
    assert flipped.shape == bgr.shape
    assert np.array_equal(rotate_180(flipped), bgr)


def test_文字が小さいときだけ拡大する(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    card, _a, _f = rectify(bgr, det.quad)

    small = cv2.resize(card, (card.shape[1] // 3, card.shape[0] // 3))
    _out, factor = upscale_if_small(small)
    assert factor > 1.0

    big = cv2.resize(card, (card.shape[1] * 2, card.shape[0] * 2))
    _out2, factor2 = upscale_if_small(big)
    assert factor2 == 1.0


def test_拡大率には上限がある(scene, monkeypatch):
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    card, _a, _f = rectify(bgr, det.quad)
    tiny = cv2.resize(card, (card.shape[1] // 8, card.shape[0] // 8))
    monkeypatch.setenv("CARD_PREPROCESS__UPSCALE_MAX", "1.5")
    settings.reload()
    _out, factor = upscale_if_small(tiny)
    assert factor <= 1.5


def test_文字高の推定は文字のある画像で正の値になる(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    card, _a, _f = rectify(bgr, det.quad)
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    assert median_text_height(gray) > 0
    blank = np.full((400, 700), 240, dtype=np.uint8)
    assert median_text_height(blank) == 0


@pytest.mark.parametrize("name", ["raw", "color", "gray", "binary", "sharp"])
def test_各バリアントは3チャンネルの同じ大きさで返る(scene, name):
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    card, _a, _f = rectify(bgr, det.quad)
    out = make_variant(card, name)
    assert out.shape[:2] == card.shape[:2]
    assert out.ndim == 3 and out.shape[2] == 3
    assert name in VARIANT_LABELS


def test_知らないバリアント名は拒否する(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    card, _a, _f = rectify(bgr, detect_card(bgr).quad)
    with pytest.raises(ValueError):
        make_variant(card, "nosuch")


def test_二値化は白黒だけになる(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    card, _a, _f = rectify(bgr, detect_card(bgr).quad)
    binary = make_variant(card, "binary")
    assert set(np.unique(binary)).issubset({0, 255})


def test_バリアントは設定の順に生成される(scene, monkeypatch):
    bgr, _truth, _spec = scene("landscape_ja")
    card, _a, _f = rectify(bgr, detect_card(bgr).quad)
    monkeypatch.setenv("CARD_PREPROCESS__VARIANTS", "gray,binary")
    settings.reload()
    names = [name for name, _img in variants(card)]
    assert names == ["gray", "binary"]


def test_JPEGへの変換と読み戻し(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    data = to_jpeg(bgr)
    assert data[:2] == b"\xff\xd8"          # JPEG のマジックナンバー
    back = decode_image(data)
    assert back is not None
    assert back.shape == bgr.shape


def test_読めないバイト列はNoneになる():
    assert decode_image(b"") is None
    assert decode_image(b"not an image at all") is None


def test_幅の上限は縮小だけで拡大はしない(scene):
    bgr, _truth, _spec = scene("landscape_ja")
    small, scale = limit_width(bgr, 320)
    assert small.shape[1] == 320 and scale < 1.0
    same, scale2 = limit_width(bgr, 99999)
    assert same.shape == bgr.shape and scale2 == 1.0
