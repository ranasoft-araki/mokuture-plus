"""撮影 1 枚の読み取り全体（検出 → 補正 → バリアント比較 → 抽出）。"""
from __future__ import annotations

import time

import numpy as np
import pytest

from card import settings
from card.detect import detect_card
from card.extract import extract
from card.pipeline import evaluate_acceptance, lines_payload, read_card, score_result
from card.types import OcrLine

pytestmark = pytest.mark.ocr


def _read(scene, pattern):
    bgr, _truth, _spec = scene(pattern)
    det = detect_card(bgr)
    return read_card(bgr, det.quad if det else None)


def test_横型の日本語名刺を読み切る(ocr_engine, scene):
    result = _read(scene, "landscape_ja")
    assert result is not None
    f = result.fields
    assert f.company_name.value == "株式会社サンプル商会"
    assert (f.person_name.value or "").replace(" ", "") == "山田太郎"
    assert f.email.value == "taro.yamada@example.jp"
    assert f.phone.value == "03-1234-5678"
    assert result.overall > 0.8


def test_縦型名刺も読める(ocr_engine, scene):
    result = _read(scene, "portrait_ja")
    assert result is not None
    assert result.fields.company_name.value == "有限会社きらめき工房"
    assert (result.fields.person_name.value or "").replace(" ", "") == "鈴木花子"


def test_斜めに置いた名刺も読める(ocr_engine, scene):
    result = _read(scene, "skewed")
    assert result is not None
    assert result.fields.company_name.value == "株式会社サンプル商会"


def test_木目の机に置いても読める(ocr_engine, scene):
    result = _read(scene, "wood_background")
    assert result is not None
    assert result.fields.company_name.value == "株式会社サンプル商会"


def test_色付きの名刺も読める(ocr_engine, scene):
    result = _read(scene, "colored_card")
    assert result is not None
    assert result.fields.company_name.value == "株式会社あおば技研"


def test_英語のみの名刺も読める(ocr_engine, scene):
    result = _read(scene, "english_only")
    assert result is not None
    assert result.fields.person_name.value == "Alex Morgan"
    assert result.fields.email.value == "alex.morgan@example.com"


def test_電話番号が複数ある名刺を種別ごとに分ける(ocr_engine, scene):
    result = _read(scene, "multi_phone")
    assert result is not None
    assert result.fields.phone.value == "03-1234-5678"
    assert result.fields.mobile.value == "080-9876-5432"
    assert result.fields.fax.value == "03-1234-5679"


def test_四隅が無くても画像全体から読める(ocr_engine, scene):
    """手動撮影で検出に失敗した場合の経路。"""
    bgr, _truth, _spec = scene("landscape_ja")
    result = read_card(bgr, None)
    assert result is not None
    assert result.fields.company_name.value == "株式会社サンプル商会"


def test_結果には確認画面に必要なものが揃っている(ocr_engine, scene):
    result = _read(scene, "landscape_ja")
    assert result is not None
    assert result.card_jpeg[:2] == b"\xff\xd8"        # 補正後の名刺画像
    assert result.card_size[0] > 0 and result.card_size[1] > 0
    assert result.variant in result.tried
    assert result.engine
    assert set(result.timings_ms) >= {"preprocess", "ocr", "extract"}


def test_良い結果が出たら残りのバリアントは省く(ocr_engine, scene, monkeypatch):
    monkeypatch.setenv("CARD_PREPROCESS__VARIANTS", "color,gray,binary,sharp")
    monkeypatch.setenv("CARD_PREPROCESS__EARLY_ACCEPT_SCORE", "0.5")
    settings.reload()
    result = _read(scene, "landscape_ja")
    assert result is not None
    assert result.tried == ["color"], result.tried


def test_早期採用をやめると全バリアントを試す(ocr_engine, scene, monkeypatch):
    monkeypatch.setenv("CARD_PREPROCESS__VARIANTS", "color,gray")
    monkeypatch.setenv("CARD_PREPROCESS__EARLY_ACCEPT_SCORE", "1.1")
    settings.reload()
    result = _read(scene, "landscape_ja")
    assert result is not None
    assert result.tried == ["color", "gray"]


def test_スコアは項目が埋まっているほど高い():
    good_lines = [
        OcrLine("株式会社サンプル商会", ((0, 0), (300, 0), (300, 30), (0, 30)), 0.98, 0),
        OcrLine("山田 太郎", ((0, 60), (200, 60), (200, 120), (0, 120)), 0.99, 1),
        OcrLine("taro.yamada@example.jp", ((0, 150), (300, 150), (300, 170), (0, 170)), 0.97, 2),
    ]
    noise_lines = [
        OcrLine("あいう", ((0, 0), (100, 0), (100, 20), (0, 20)), 0.98, 0),
        OcrLine("かきく", ((0, 40), (100, 40), (100, 60), (0, 60)), 0.98, 1),
    ]
    good = score_result(good_lines, extract(good_lines, (400, 200)))
    noise = score_result(noise_lines, extract(noise_lines, (400, 200)))
    assert good > noise


def test_名刺ではない紙からは項目が埋まらない(ocr_engine, scene):
    bgr, _truth, _spec = scene("not_a_card_paper")
    result = read_card(bgr, None)
    assert result is not None
    f = result.fields
    assert f.email.value is None
    assert f.phone.value is None
    assert f.person_name.value is None or f.person_name.confidence < 0.6


def test_行ごとの情報をAPIで返せる形にできる(ocr_engine, scene):
    result = _read(scene, "landscape_ja")
    payload = lines_payload(result.lines)
    assert payload
    first = payload[0]
    assert set(first) == {"order", "text", "confidence", "box", "height", "width"}
    assert len(first["box"]) == 4


@pytest.mark.slow
def test_撮影からの処理時間を記録する(ocr_engine, scene, capsys):
    """性能目標(§15)の確認。この機械での実測値を出す。

    Pi 実機の値は scripts/bench.py で測る。ここでは「妥当な時間で終わること」と
    「内訳が取れること」だけを見る。
    """
    bgr, _truth, _spec = scene("landscape_ja")
    det = detect_card(bgr)
    started = time.perf_counter()
    result = read_card(bgr, det.quad)
    elapsed = (time.perf_counter() - started) * 1000
    assert result is not None
    with capsys.disabled():
        print(f"\n  read_card: {elapsed:.0f}ms  内訳={result.timings_ms}")
    assert elapsed < 30000      # 明らかに詰まっていないこと（実機の目標は README 参照）


# ── 受理判定（確認画面へ進んでよいか） ──────────────────────────────────────────

def _fields(**values):
    from card.types import CardFields, Field
    f = CardFields()
    for name, value in values.items():
        setattr(f, name, Field(value=value, confidence=0.9))
    return f


def test_会社名か氏名が取れていれば受理する():
    ok, reason = evaluate_acceptance(_fields(company_name="株式会社サンプル商会",
                                             email="taro.yamada@example.jp"), 0.9)
    assert ok and reason == "ok"


def test_会社名も氏名も無ければ受理しない():
    """連絡先だけ取れていても受付フォームには使えないので撮り直す。"""
    ok, reason = evaluate_acceptance(_fields(email="taro.yamada@example.jp",
                                             phone="03-1234-5678"), 0.9)
    assert not ok
    assert "person_name" in reason


def test_項目が少なすぎれば受理しない():
    ok, reason = evaluate_acceptance(_fields(company_name="株式会社サンプル商会"), 0.9)
    assert not ok
    assert "field" in reason


def test_全体の精度が低ければ受理しない():
    ok, reason = evaluate_acceptance(
        _fields(company_name="株式会社サンプル商会", person_name="山田 太郎"), 0.1)
    assert not ok
    assert "confidence" in reason


def test_何も取れていなければ受理しない():
    ok, _reason = evaluate_acceptance(_fields(), 0.0)
    assert not ok


def test_受理条件は設定から変えられる(monkeypatch):
    from card import settings as st
    only_contact = _fields(email="taro.yamada@example.jp", phone="03-1234-5678")
    assert not evaluate_acceptance(only_contact, 0.9)[0]

    monkeypatch.setenv("CARD_ACCEPT__REQUIRE_ANY", "email")
    st.reload()
    assert evaluate_acceptance(only_contact, 0.9)[0]
