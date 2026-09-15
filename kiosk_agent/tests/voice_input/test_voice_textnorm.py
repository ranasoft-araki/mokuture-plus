"""認識結果の整形(§4)。

いちばん大事なのは「法人格を消さないこと」と「削りすぎないこと」。
"""
from __future__ import annotations

import pytest

from voice import textnorm


# ── 会社名 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said,expected", [
    ("株式会社ラナソフト", "株式会社ラナソフト"),
    ("株式会社ラナソフトです", "株式会社ラナソフト"),
    ("株式会社ラナソフトから来ました", "株式会社ラナソフト"),
    ("株式会社ラナソフトから参りました", "株式会社ラナソフト"),
    ("ラナソフトです", "ラナソフト"),
    ("ラナソフトの者です", "ラナソフト"),
    ("えーと、株式会社ラナソフトです", "株式会社ラナソフト"),
    ("私は株式会社ラナソフトから来ました", "株式会社ラナソフト"),
    ("有限会社さくら工房でございます", "有限会社さくら工房"),
    ("合同会社みどり", "合同会社みどり"),
])
def test_company(said, expected):
    assert textnorm.normalize_company(said) == expected


@pytest.mark.parametrize("legal", [
    "株式会社", "有限会社", "合同会社", "合資会社", "一般社団法人", "医療法人",
])
def test_company_keeps_legal_form(legal):
    """法人格は定型表現ではない。消したら別の会社になってしまう(§4)。"""
    assert textnorm.normalize_company(f"{legal}あおぞらです").startswith(legal)


def test_company_suffix_only_at_end():
    """社名の途中にある「です」相当の文字列は消さない。"""
    # 「デスク」の「デス」を消してしまわないこと
    assert textnorm.normalize_company("株式会社デスクトップ") == "株式会社デスクトップ"


def test_company_empty_and_noise():
    assert textnorm.normalize_company("") == ""
    assert textnorm.normalize_company("。、") == ""


# ── 氏名 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said,expected", [
    ("荒木です", "荒木"),
    ("荒木秀人です", "荒木秀人"),
    ("荒木秀人と申します", "荒木秀人"),
    ("荒木秀人といいます", "荒木秀人"),
    ("荒木秀人と言います", "荒木秀人"),
    ("私は荒木秀人です", "荒木秀人"),
    ("名前は荒木です", "荒木"),
    ("荒木 秀人", "荒木秀人"),
    ("荒木秀人。", "荒木秀人"),
])
def test_person(said, expected):
    assert textnorm.normalize_person(said) == expected


def test_person_keeps_short_name():
    """短い姓を定型表現ごと消してしまわないこと。"""
    assert textnorm.normalize_person("林です") == "林"
    assert textnorm.normalize_person("原です") == "原"


def test_person_does_not_strip_when_it_is_the_whole_name():
    """全部が定型表現なら、空にせず元を残す判断はしない(空は空として扱う)。"""
    assert textnorm.normalize_person("です") == ""


# ── 担当者(第3段階の下準備) ─────────────────────────────────────────────────

@pytest.mark.parametrize("said,dept,name", [
    ("営業部の田中さん", "営業部", "田中"),
    ("営業の田中さん", "営業", "田中"),
    ("田中太郎さん", "", "田中太郎"),
    ("田中さん", "", "田中"),
    ("総務部の佐藤", "総務部", "佐藤"),
])
def test_split_department(said, dept, name):
    assert textnorm.split_department(said) == (dept, name)


@pytest.mark.parametrize("a,b", [
    ("タナカ", "たなか"),          # カタカナ / ひらがな
    ("さとう さん", "サトウ"),      # 敬称・空白
    ("こうの", "コーノ"),          # 長音の綴り違い
    ("さとう", "サトー"),
    ("せいじ", "セージ"),
    ("はっとり", "ハットリ"),       # 促音
    ("しょうじ", "ショージ"),       # 拗音 + 長音
])
def test_normalize_reading_absorbs_variants(a, b):
    """読み比べのキーは、カナ・長音・促音・敬称・空白の揺れを吸収する。"""
    assert textnorm.normalize_reading(a) == textnorm.normalize_reading(b)


def test_normalize_reading_keeps_different_names_apart():
    """揺れを吸収しすぎて別人が同じキーになっていないこと(よくある姓で確認)。"""
    keys = {textnorm.normalize_reading(n) for n in
            ("たなか", "なかた", "やまだ", "やまた", "さいとう", "さとう", "すずき")}
    assert len(keys) == 7


def test_department_stem():
    assert textnorm.department_stem("営業部") == textnorm.department_stem("営業")


# ── 共通の掃除 ────────────────────────────────────────────────────────────────

def test_normalize_common_squashes_spaces_between_japanese():
    assert textnorm.normalize_common("株式 会社 ラナ ソフト") == "株式会社ラナソフト"


def test_normalize_common_keeps_latin_spacing():
    assert textnorm.normalize_common("Rana Soft Inc") == "Rana Soft Inc"


def test_normalize_common_halfwidth():
    assert textnorm.normalize_common("ＡＢＣ１２３") == "ABC123"
