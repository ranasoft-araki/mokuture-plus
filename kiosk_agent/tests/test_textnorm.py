"""文字列の正規化・OCR 誤認の補正・かな→ローマ字（項目抽出の下ごしらえ）。"""
from __future__ import annotations

import pytest

from card.textnorm import (
    canon,
    digits_only,
    fix_digits,
    has_cjk,
    is_all_kana,
    kana_to_romaji,
    kata_to_hira,
    normalize_hyphens,
    normalize_line,
    prefix_overlap,
    romaji_key,
    to_halfwidth,
)


def test_行の正規化は空白だけを整える():
    assert normalize_line("  株式会社　サンプル商会 ") == "株式会社 サンプル商会"
    assert normalize_line("・営業部") == "営業部"


def test_行の正規化は全角記号を半角にしない():
    """会社名の「（株）」は名刺の印字どおりに残す。"""
    assert normalize_line("（株）サンプル商会") == "（株）サンプル商会"


def test_半角化は解析用に別途かける():
    assert to_halfwidth("ＴＥＬ　０３－１２３４") == "TEL 03-1234"


@pytest.mark.parametrize("raw,expected", [
    ("03‐1234‑5678", "03-1234-5678"),   # 別種のハイフン
    ("03−1234−5678", "03-1234-5678"),   # 全角マイナス
    ("03ー1234ー5678", "03-1234-5678"),  # 長音記号
])
def test_ハイフンの種類を揃える(raw, expected):
    assert normalize_hyphens(raw) == expected


def test_数字の取り違えを直す():
    assert fix_digits("O3-I234-56S8") == "03-1234-5658"


def test_数字だけ取り出す():
    assert digits_only("TEL 03-1234-5678") == "0312345678"


@pytest.mark.parametrize("text,expected", [
    ("株式会社", True), ("サンプル", True), ("やまだ", True),
    ("example.jp", False), ("ABC123", False), ("", False),
])
def test_日本語を含むかの判定(text, expected):
    assert has_cjk(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("なかむら ゆうこ", True),
    ("ナカムラ ユウコ", True),
    ("サンプル・商会", False),      # 漢字が混じる
    ("YUKO", False),
    ("", False),
])
def test_かなだけかの判定(text, expected):
    assert is_all_kana(text) is expected


def test_カタカナをひらがなにする():
    assert kata_to_hira("ナカムラ") == "なかむら"


@pytest.mark.parametrize("kana,romaji", [
    ("やまだ", "yamada"),
    ("わたなべ", "watanabe"),
    ("なかむら", "nakamura"),
    ("ささき", "sasaki"),
    ("しんぱち", "shimpachi"),        # ん + p は m（ヘボン式）
    ("きょうと", "kyouto"),
    ("サンプル", "sampuru"),
    ("クリエイティブ", "kurieitibu"),
])
def test_かなをローマ字にする(kana, romaji):
    assert kana_to_romaji(kana) == romaji


def test_比較用のキーは英字だけを残す():
    assert romaji_key("Alex Morgan") == "alexmorgan"
    assert romaji_key("aozora-creative") == "aozoracreative"


def test_先頭一致の長さ():
    assert prefix_overlap("aozorakurieitibu", "aozoracreative") == 6
    assert prefix_overlap("abc", "xyz") == 0


# ── 辞書照合用の正規化（OCR の字形取り違えを吸収する） ────────────────────────

@pytest.mark.parametrize("misread,correct", [
    ("マネージヤー", "マネージャー"),   # 小書き文字を大書きに読む
    ("サソプル", "サンプル"),           # ソ と ン
    ("システム", "システム"),
    ("代表取締役", "代表取締役"),
])
def test_字形の取り違えを吸収して辞書と突き合わせる(misread, correct):
    assert canon(misread) == canon(correct)


def test_照合用の正規化は空白と記号を落とす():
    assert canon("営業部 / 部長") == canon("営業部部長")


def test_照合用の正規化は英字を小文字に寄せる():
    assert canon("Director") == canon("director")


def test_無関係な語まで同一視しない():
    assert canon("営業部") != canon("総務部")
    assert canon("部長") != canon("課長")
