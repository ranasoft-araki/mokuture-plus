"""項目抽出（§8）と信頼度（§9）。

OCR は通さず、OCR が返す行を直接組み立てて検証する。抽出規則だけを切り離して
試せるようにしておくと、モデルが無い環境でも回せるし、失敗したときに
「読めなかったのか」「読めたが取り違えたのか」が一目で分かる。

出てくる会社名・氏名・連絡先はすべて架空。ドメインは予約済みの example.jp 等。
"""
from __future__ import annotations

import pytest

from card import settings
from card.extract import extract, overall_confidence
from card.types import OcrLine


def line(text: str, order: int, *, height: float = 26.0, y: float | None = None,
         x: float = 40.0, conf: float = 0.97) -> OcrLine:
    """1 行の OCR 結果を組み立てる。y を省略すると order から等間隔で割り振る。"""
    top = (order * 60.0) if y is None else y
    width = max(20.0, len(text) * height * 0.95)
    box = ((x, top), (x + width, top), (x + width, top + height), (x, top + height))
    return OcrLine(text=text, box=box, conf=conf, order=order)


def standard_card(**over) -> list[OcrLine]:
    """よくある横型の日本語名刺。個々のテストで一部だけ差し替えて使う。"""
    company = over.get("company", "株式会社サンプル商会")
    dept_title = over.get("dept_title", "営業部 部長")
    name = over.get("name", "山田 太郎")
    email = over.get("email", "taro.yamada@example.jp")
    return [
        line(company, 0, height=34),
        line(dept_title, 1, height=26),
        line(name, 2, height=64),
        line("〒100-0001 東京都千代田区千代田1-2-3 サンプルビル5F", 3, height=22),
        line("TEL 03-1234-5678  FAX 03-1234-5679", 4, height=22),
        line("携帯 090-1234-5678", 5, height=22),
        line(email, 6, height=22),
        line("https://www.example.jp", 7, height=22),
    ]


CARD_SIZE = (1024, 620)


# ── 会社名 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("company", [
    "株式会社サンプル商会",
    "（株）サンプル商会",
    "(株)サンプル商会",
    "有限会社きらめき工房",
    "合同会社ミライデザイン",
    "一般社団法人サンプル協会",
    "医療法人社団さくら会",
    "社会福祉法人あおぞら福祉会",
    "学校法人サンプル学園",
    "特定非営利活動法人サンプルネット",
])
def test_法人格から会社名を取る(company):
    """法人格が書いてあれば、その行を会社名として取る。

    **確信度は「そのまま入れてよい」帯(confidence.ok)まで上げない。** 法人格の一致は
    「この行は社名だ」の証拠であって「社名の文字が正しく読めた」証拠ではないため。
    実機で社名の漢字 1 文字を読み違えた「株式会社暖野木工所」が 0.857 で通り、
    受付フォームへ無警告で入った（正しくは磯野木工所）。裏付けの取り方は
    test_ドメインが社名を裏付ければ確信度を下げない を参照。
    """
    ok = float(settings.get("confidence.ok"))
    fields = extract(standard_card(company=company), CARD_SIZE)
    assert fields.company_name.value == company
    assert float(settings.get("confidence.fill_min")) <= fields.company_name.confidence < ok


def test_ドメインが社名を裏付ければ確信度を下げない():
    """メール／URL のドメインが社名本体と一致していれば、頭打ちを外す。

    これが無いと、正しく読めた社名にも常に「ご確認ください」が付いてしまう。
    """
    ok = float(settings.get("confidence.ok"))
    lines = standard_card(company="株式会社ミライデザイン")
    # 社名の読みと同じドメイン（miraidesign）を持つ名刺にする
    lines = [
        OcrLine(text=("miraidesign@miraidesign.co.jp" if "@" in l.text else l.text),
                conf=l.conf, box=l.box, order=l.order)
        for l in lines
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.company_name.value == "株式会社ミライデザイン"
    assert fields.company_name.confidence >= ok


@pytest.mark.parametrize("company", [
    "Northwind Analytics, Inc.",
    "Sample Trading Co., Ltd.",
    "Mirai Design LLC",
    "Example Holdings Corp.",
])
def test_英文の法人格にも対応する(company):
    fields = extract(standard_card(company=company), CARD_SIZE)
    assert fields.company_name.value == company


@pytest.mark.parametrize("tagline", [
    "Since 1998",            # "inc" を含む
    "Province of Sample",    # "inc" を含む
    "Incubation Lab",        # "Inc" で始まる
    "Limitless Design",      # "Limited" ではない
    "Incredible Service",
])
def test_英字のタグラインを会社名にしない(tagline):
    """英文の法人格は「独立した語」として探す。

    単純な部分一致だと "Since 1998" の中の "inc" に当たってしまい、名刺の
    英字タグラインを高い信頼度（＝画面では緑）で会社名に確定してしまう。
    """
    lines = [
        line(tagline, 0, height=22),
        line("あおぞらクリエイティブ", 1, height=34),
        line("伊藤 直樹", 2, height=64),
        line("naoki.ito@aozora-creative.example.jp", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.company_name.value != tagline


@pytest.mark.parametrize("name", [
    "Northwind Analytics, Inc.",
    "Sample Trading Co., Ltd.",
    "Sample Trading Co.,Ltd.",      # 空白が詰まっている
    "Mirai Design LLC",
    "Example Holdings Corp.",
    "Sample K.K.",
    "Beispiel GmbH",
])
def test_英文の法人格は語として認識する(name):
    lines = [
        line(name, 0, height=34),
        line("Alex Morgan", 1, height=60),
        line("alex.morgan@example.com", 2, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.company_name.value == name
    # 欄に入る水準であること。上限は名刺によって変わる —「Example Holdings Corp.」は
    # メール(alex.morgan@example.com)のドメインが社名を裏付けるので頭打ちが外れ、
    # 裏付けの無いものは「ご確認ください」の帯に留まる
    # （test_法人格から会社名を取る / test_ドメインが社名を裏付ければ確信度を下げない）。
    assert fields.company_name.confidence >= float(settings.get("confidence.fill_min"))


def test_法人格が省略された会社名をメールドメインから推定する():
    lines = standard_card(
        company="あおぞらクリエイティブ",
        name="伊藤 直樹",
        email="naoki.ito@aozora-creative.example.jp",
    )
    fields = extract(lines, CARD_SIZE)
    assert fields.company_name.value == "あおぞらクリエイティブ"
    # 推定なので、法人格がある場合より低い信頼度で返す（画面では黄色になる）
    assert 0.3 <= fields.company_name.confidence < 0.85


def test_会社名が読めないときに氏名を会社名にしない():
    lines = [
        line("山田 太郎", 0, height=64),
        line("taro.yamada@example.jp", 1, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "山田 太郎"
    assert fields.company_name.value != "山田 太郎"


# ── 電話・FAX・携帯 ───────────────────────────────────────────────────────────

def test_TELとFAXと携帯を区別する():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.phone.value == "03-1234-5678"
    assert fields.fax.value == "03-1234-5679"
    assert fields.mobile.value == "090-1234-5678"


def test_区切りが無くても1行の中でラベルごとに分ける():
    lines = [line("TEL03-1234-5678FAX03-1234-5679", 0)]
    fields = extract(lines, CARD_SIZE)
    assert fields.phone.value == "03-1234-5678"
    assert fields.fax.value == "03-1234-5679"


def test_ラベルが無ければ番号の頭で携帯と固定を見分ける():
    fields = extract([line("090-1234-5678", 0), line("03-1234-5678", 1)], CARD_SIZE)
    assert fields.mobile.value == "090-1234-5678"
    assert fields.phone.value == "03-1234-5678"


def test_国際表記は国内表記に直す():
    lines = [line("TEL +81-3-1234-5678", 0), line("Mobile +81-90-1234-5678", 1)]
    fields = extract(lines, CARD_SIZE)
    assert fields.phone.value == "03-1234-5678"
    assert fields.mobile.value == "090-1234-5678"


def test_ラベルのOと0の取り違えを吸収する():
    # OCR が "Mobile" を "M0bile" と読んだ場合
    fields = extract([line("M0bile 090-1234-5678", 0)], CARD_SIZE)
    assert fields.mobile.value == "090-1234-5678"


def test_番号の中のOや1の取り違えを直す():
    # "03-1234-5678" の 0 が O、1 が I になったケース
    fields = extract([line("TEL O3-I234-5678", 0)], CARD_SIZE)
    assert fields.phone.value is not None
    assert fields.phone.value.replace("-", "") == "0312345678"
    # 補正した分は信頼度を下げる
    assert fields.phone.confidence < 0.95


def test_電話番号が複数あっても先に書かれているものを採る():
    lines = [
        line("TEL 03-1234-5678 / 03-1234-5670", 0),
        line("直通 03-1234-5671", 1),
        line("携帯 080-9876-5432", 2),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.phone.value == "03-1234-5678"
    assert fields.mobile.value == "080-9876-5432"


def test_桁数が合わない数字は電話番号にしない():
    fields = extract([line("受付番号 12345", 0), line("整理番号 987-6543", 1)], CARD_SIZE)
    assert fields.phone.value is None
    assert fields.mobile.value is None
    assert fields.fax.value is None


def test_郵便番号を電話番号と取り違えない():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.postal_code.value == "100-0001"
    assert fields.phone.value != "100-0001"


# ── メール・URL ───────────────────────────────────────────────────────────────

def test_メールアドレスを取る():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.email.value == "taro.yamada@example.jp"
    assert fields.email.confidence >= 0.9


def test_アットマークが落ちたメールを復元する():
    """日本語認識モデルの文字セットに "@" が無い端末向けの復元経路。"""
    lines = standard_card(email="taro.yamadaQexample.jp")
    fields = extract(lines, CARD_SIZE)
    assert fields.email.value == "taro.yamada@example.jp"
    # 復元したものは信頼度を下げる（画面では要確認になる）
    assert fields.email.confidence < 0.85


def test_ドメインだけの行をメールに仕立てない():
    lines = [line("株式会社サンプル商会", 0, height=34), line("www.example.jp", 1)]
    fields = extract(lines, CARD_SIZE)
    assert fields.email.value is None
    assert fields.website.value == "www.example.jp"


def test_URLを取りメール行と混同しない():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.website.value == "https://www.example.jp"
    assert "@" not in (fields.website.value or "")


# ── 郵便番号・住所 ────────────────────────────────────────────────────────────

def test_郵便番号と住所を分ける():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.postal_code.value == "100-0001"
    assert fields.address.value.startswith("東京都千代田区")


def test_郵便マークが別の字に化けても拾える():
    """〒 は認識モデルの文字セットに無いことがあり "テ" や "1" に化ける。"""
    for broken in ("テ100-0001東京都千代田区千代田1-2-3", "1100-0001東京都千代田区千代田1-2-3"):
        fields = extract([line("株式会社サンプル商会", 0, height=34), line(broken, 1)], CARD_SIZE)
        assert fields.postal_code.value == "100-0001", broken
        assert fields.address.value.startswith("東京都"), broken


def test_英文住所も拾う():
    lines = [
        line("Northwind Analytics, Inc.", 0, height=34),
        line("Alex Morgan", 1, height=60),
        line("1200 Example Street, Springfield", 2),
        line("alex.morgan@example.com", 3),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.address.value == "1200 Example Street, Springfield"


# ── 部署・役職 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,dept,title", [
    ("営業部 部長", "営業部", "部長"),
    ("総務課 課長", "総務課", "課長"),
    ("開発本部 マネージャー", "開発本部", "マネージャー"),
    ("制作課 主任", "制作課", "主任"),
    ("経営企画部 代表取締役", "経営企画部", "代表取締役"),
    ("Sales Division Director", "Sales Division", "Director"),
])
def test_部署と役職を辞書で切り分ける(text, dept, title):
    fields = extract(standard_card(dept_title=text), CARD_SIZE)
    assert fields.title.value == title
    assert fields.department.value == dept


def test_辞書に無い部署も接尾辞で拾う():
    fields = extract(standard_card(dept_title="次世代モビリティ推進室 室長"), CARD_SIZE)
    assert fields.title.value == "室長"
    assert fields.department.value == "次世代モビリティ推進室"


def test_小書き文字の取り違えを吸収して役職を当てる():
    """OCR は "ャ" を "ヤ" と読みやすい。辞書照合だけこれを吸収する。"""
    fields = extract(standard_card(dept_title="開発本部 マネージヤー"), CARD_SIZE)
    assert fields.title.value == "マネージャー"   # 表示は辞書の正しい表記
    assert fields.department.value == "開発本部"
    # 補正を通したので、そのまま一致した場合より信頼度は低い
    assert fields.title.confidence < 0.92


def test_辞書は外部ファイルから読まれる():
    from card import dicts
    assert "株式会社" in dicts.company_suffixes()
    assert "部長" in dicts.titles()
    assert "営業部" in dicts.departments()
    assert dicts.summary()["titles"] > 50


# ── 氏名 ──────────────────────────────────────────────────────────────────────

def test_大きい文字と姓辞書から氏名を決める():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.person_name.value == "山田 太郎"
    assert fields.person_name.confidence >= 0.6


def test_文字が小さい氏名もメールアドレスとの一致で拾う():
    lines = [
        line("株式会社サンプル商会", 0, height=34),
        line("営業部 部長", 1, height=26),
        line("渡辺 三郎", 2, height=26),          # 会社名より小さい
        line("saburo.watanabe@example.jp", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "渡辺 三郎"


def test_ローマ字表記とメールのローカル部が符合すると確信度が上がる():
    lines = [
        line("株式会社サンプル商会", 0, height=34),
        line("佐藤 健一", 1, height=60),
        line("KENICHI SATO", 2, height=22),
        line("k.sato@example.com", 3, height=22),
    ]
    with_romaji = extract(lines, CARD_SIZE)
    without = extract([l for l in lines if l.text != "KENICHI SATO"], CARD_SIZE)
    assert with_romaji.person_name.value == "佐藤 健一"
    assert with_romaji.person_name.confidence > without.person_name.confidence


def test_英文氏名を拾う():
    lines = [
        line("Northwind Analytics, Inc.", 0, height=34),
        line("Sales Division Director", 1, height=26),
        line("Alex Morgan", 2, height=60),
        line("alex.morgan@example.com", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "Alex Morgan"


def test_氏名が定まらないときは確定せず候補を返す(monkeypatch):
    from card import settings
    monkeypatch.setenv("CARD_EXTRACTION__NAME_MIN_CONF", "0.99")
    settings.reload()
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.person_name.value is None
    assert fields.person_name.candidates          # 候補は出す
    assert "山田 太郎" in fields.person_name.candidates


def test_電話番号や住所を氏名にしない():
    fields = extract(standard_card(), CARD_SIZE)
    name = fields.person_name.value or ""
    assert "03-" not in name and "東京都" not in name and "@" not in name


def test_カタカナ書きの氏名を拾う():
    """外国籍の方の名刺では氏名をカタカナで書くことがある。

    「かなだけの行は読み仮名」と決め打ちすると、この名刺の氏名は候補にすら
    挙がらず**永久に空欄**になる（実機で空欄のまま確認画面まで進んだ）。
    読みかどうかは、隣に「自分より大きい漢字の氏名」があるかで決める。
    """
    lines = [
        line("LUMI株式会社", 0, height=60),
        line("代表取締役", 1, height=22),
        line("レミン ハイ", 2, height=58),
        line("hai@lumi.co.jp", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "レミン ハイ"
    # かな書きの氏名はそれ自体が読みでもある（受付のふりがな欄を打ち直させない）
    assert fields.person_name_kana.value == "レミン ハイ"


def test_姓辞書にもメールにも根拠が無い氏名を確定できる():
    """外国籍の方の名刺。姓の辞書に載らず、メールのローカル部とも符合しない。

    ロゴが大きい名刺では氏名が相対的に小さくなり、「大きい文字」の加点が効かない。
    実機ではこれで 0.42 となり、しきい値 0.45 に届かず**候補のまま空欄**で確認画面へ
    出ていた（利用者からは「名前は読めているのに入らない」と見える）。
    名刺らしさ（連絡先がある）と、残った行の中でいちばん大きいこと、役職の隣で
    あることを根拠にして確定させる。
    """
    lines = [
        line("LUMI株式会社", 0, height=60),          # ロゴ。氏名より大きい
        line("代表取締役", 1, height=22),
        line("レミン ハイ", 2, height=38),
        line("0565-42-8382", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "レミン ハイ"
    assert fields.person_name.confidence >= 0.45


def test_漢字の氏名があるときはカタカナ行を氏名にしない():
    """社名や商品名のカタカナが氏名を押しのけないこと。"""
    lines = [
        line("株式会社サンプル商会", 0, height=34),
        line("アオゾラ クリエイティブ", 1, height=30),   # ブランド名
        line("山田 太郎", 2, height=64),
        line("taro.yamada@example.jp", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "山田 太郎"


def test_ふりがなを氏名の近くから拾う():
    lines = [
        line("株式会社サンプル商会", 0, height=34),
        line("営業部 部長", 1, height=26),
        line("なかむら ゆうこ", 2, height=20),
        line("中村 優子", 3, height=64),
        line("yuko.nakamura@example.jp", 4, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name.value == "中村 優子"
    assert fields.person_name_kana.value == "なかむら ゆうこ"


def test_カタカナの社名をふりがなにしない():
    lines = [
        line("あおぞらクリエイティブ", 0, height=38),
        line("企画部 リーダー", 1, height=26),
        line("伊藤 直樹", 2, height=64),
        line("naoki.ito@aozora-creative.example.jp", 3, height=22),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.person_name_kana.value is None
    assert fields.company_name.value == "あおぞらクリエイティブ"


def test_ふりがなが無ければ空のままにする():
    fields = extract(standard_card(), CARD_SIZE)
    assert fields.person_name_kana.value is None


# ── 信頼度・でっちあげ防止 ────────────────────────────────────────────────────

def test_全項目の信頼度は0から1に収まる():
    fields = extract(standard_card(), CARD_SIZE)
    from card.types import FIELD_NAMES
    for name in FIELD_NAMES:
        f = fields.get(name)
        assert 0.0 <= f.confidence <= 1.0, name


def test_OCRの確信度が低いと項目の信頼度も下がる():
    high = extract(standard_card(), CARD_SIZE)
    low = extract([OcrLine(l.text, l.box, 0.5, l.order) for l in standard_card()], CARD_SIZE)
    assert low.company_name.confidence < high.company_name.confidence
    assert low.email.confidence < high.email.confidence


def test_読み取れなかった項目は空欄にする():
    fields = extract([line("株式会社サンプル商会", 0, height=34)], CARD_SIZE)
    assert fields.email.value is None
    assert fields.phone.value is None
    assert fields.address.value is None
    assert fields.email.confidence == 0.0


def test_空のOCR結果でも落ちない():
    fields = extract([], CARD_SIZE)
    assert fields.filled_count() == 0
    assert overall_confidence(fields) == 0.0


def test_名刺ではない文字列から項目をでっちあげない():
    lines = [
        line("ご案内 サンプル文書", 0, height=30),
        line("本日の予定について", 1, height=24),
        line("会議室は3階です", 2, height=24),
    ]
    fields = extract(lines, CARD_SIZE)
    assert fields.email.value is None
    assert fields.phone.value is None
    assert fields.company_name.value is None or fields.company_name.confidence < 0.6


def test_全体の信頼度は受付で使う項目を重く見る():
    full = extract(standard_card(), CARD_SIZE)
    # 会社名と氏名が読めていない名刺は、連絡先が揃っていても全体が下がる
    partial = extract([
        line("〒100-0001 東京都千代田区千代田1-2-3", 0),
        line("TEL 03-1234-5678", 1),
        line("taro.yamada@example.jp", 2),
    ], CARD_SIZE)
    assert overall_confidence(full) > overall_confidence(partial)


def test_抽出結果はJSONにできる形で返る():
    fields = extract(standard_card(), CARD_SIZE)
    payload = fields.as_dict()
    assert payload["company_name"]["value"] == "株式会社サンプル商会"
    assert isinstance(payload["company_name"]["confidence"], float)
    from card.types import FIELD_NAMES
    assert set(payload) == set(FIELD_NAMES)
