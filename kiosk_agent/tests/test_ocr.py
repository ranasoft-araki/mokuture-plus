"""OCR エンジン（§7）: 共通インターフェース・切り替え・実画像での読み取り。

モデルが未取得の端末では、実画像を読むテストだけが skip される。
"""
from __future__ import annotations

import numpy as np
import pytest

from card import settings
from card.detect import detect_card
from card.ocr import ENGINE_NAMES, describe_all, get_engine, reset
from card.ocr.base import OcrEngine, sort_reading_order
from card.preprocess import make_variant, rectify
from card.types import OcrLine


# ── インターフェース ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ENGINE_NAMES)
def test_全エンジンが共通インターフェースを実装している(name):
    engine = get_engine(name)
    assert isinstance(engine, OcrEngine)
    assert engine.name == name
    ok, reason = engine.available()
    assert isinstance(ok, bool) and isinstance(reason, str) and reason


def test_設定でエンジンを切り替えられる(monkeypatch):
    reset()
    assert get_engine().name == "paddle_onnx"
    monkeypatch.setenv("CARD_OCR__ENGINE", "tesseract")
    settings.reload()
    reset()
    assert get_engine().name == "tesseract"
    monkeypatch.delenv("CARD_OCR__ENGINE")
    settings.reload()
    reset()


def test_知らないエンジン名は第一候補に落とす():
    assert get_engine("nosuch").name == "paddle_onnx"


def test_利用可否の一覧に理由が付く():
    described = describe_all()
    assert {d["engine"] for d in described} == set(ENGINE_NAMES)
    for d in described:
        assert isinstance(d["available"], bool)
        assert d["detail"]


def test_モデルが無ければ理由が分かる形で使えないと言う(monkeypatch):
    monkeypatch.setenv("CARD_OCR__PADDLE_ONNX__DET_MODEL", "models/nosuch.onnx")
    settings.reload()
    reset()
    ok, reason = get_engine("paddle_onnx").available()
    assert ok is False
    assert "nosuch.onnx" in reason
    reset()


# ── 読み取り順 ────────────────────────────────────────────────────────────────

def _line(text, x, y, h=20, w=None):
    w = w if w is not None else len(text) * h
    return OcrLine(text=text, box=((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
                   conf=0.9, order=0)


def test_読み取り順は上から下_同じ高さなら左から右():
    lines = sort_reading_order([
        _line("right", 300, 100),
        _line("left", 10, 104),        # 同じ行とみなす程度のずれ
        _line("top", 10, 10),
        _line("bottom", 10, 300),
    ])
    assert [l.text for l in lines] == ["top", "left", "right", "bottom"]
    assert [l.order for l in lines] == [0, 1, 2, 3]


def test_空の入力でも落ちない():
    assert sort_reading_order([]) == []


# ── 実画像 ────────────────────────────────────────────────────────────────────

@pytest.mark.ocr
@pytest.mark.parametrize("pattern,must_include", [
    ("landscape_ja", ["株式会社サンプル商会", "山田", "taro.yamada@example.jp"]),
    ("english_only", ["Alex Morgan", "alex.morgan@example.com"]),
    # ローマ字表記は 1 文字だけ揺れることがある（KENICHI/KENICHL）。氏名の裏付けに
    # 使うだけで表示には使わないので、姓が読めていることを見る。
    ("mixed_ja_en", ["佐藤", "SATO"]),
    ("colored_card", ["株式会社あおば技研", "高橋"]),
])
def test_名刺の主要な文字列が読める(ocr_engine, scene, pattern, must_include):
    bgr, _truth, _spec = scene(pattern)
    det = detect_card(bgr)
    assert det is not None
    card, _angle, _factor = rectify(bgr, det.quad)
    lines = ocr_engine.run(make_variant(card, "color"))
    text = "\n".join(l.text for l in lines)
    # 語間の空白の有無は名刺の組み方と OCR で揺れるので、比較時は両方から落とす
    packed = text.replace(" ", "")
    for needle in must_include:
        assert needle.replace(" ", "") in packed, \
            f"{pattern}: 「{needle}」が読めていない\n{text}"


@pytest.mark.ocr
def test_行ごとに座標と大きさと信頼度が付く(ocr_engine, scene):
    bgr, _truth, _spec = scene("landscape_ja")
    card, _a, _f = rectify(bgr, detect_card(bgr).quad)
    lines = ocr_engine.run(make_variant(card, "color"))
    assert lines
    for l in lines:
        assert len(l.box) == 4 and all(len(p) == 2 for p in l.box)
        assert 0.0 <= l.conf <= 1.0
        assert l.height > 0 and l.width > 0
    # 読み取り順は連番
    assert [l.order for l in lines] == list(range(len(lines)))
    # 氏名は他より大きい文字で書かれている
    name_line = next(l for l in lines if "山田" in l.text.replace(" ", ""))
    assert name_line.height > sum(l.height for l in lines) / len(lines)


@pytest.mark.ocr
def test_ロゴや地紋を文字として拾いすぎない(ocr_engine, scene):
    """名刺の右上にはロゴ（円と四角）だけを描いてある。"""
    bgr, _truth, _spec = scene("landscape_ja")
    card, _a, _f = rectify(bgr, detect_card(bgr).quad)
    lines = ocr_engine.run(make_variant(card, "color"))
    # 図形しかない領域から 3 文字以上の行が出てこないこと
    width = card.shape[1]
    logo_lines = [l for l in lines if l.center[0] > width * 0.8 and l.center[1] < card.shape[0] * 0.25]
    assert all(len(l.text) <= 2 for l in logo_lines), [l.text for l in logo_lines]


@pytest.mark.ocr
def test_白紙を読ませても何も出ない(ocr_engine):
    blank = np.full((400, 700, 3), 238, dtype=np.uint8)
    assert ocr_engine.run(blank) == []


@pytest.mark.ocr
def test_空画像でも落ちない(ocr_engine):
    assert ocr_engine.run(np.zeros((0, 0, 3), dtype=np.uint8)) == []
