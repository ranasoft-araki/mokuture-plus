"""一文の名乗りから受付項目を取り出すところ。

実際の受付は「磯野木工所の荒木と申します、本日服部様と打ち合わせのお約束で参りました」
のように一続きで話される。ここはその文から会社名・氏名・訪問先・用件を取り出す。

**LLM は使わない。** 小型 LLM と比べた実測で規則の方が良かった(担当者の照合 8/10 →
9/10、誤照合 1 → 0)。理由は voice/extract.py の冒頭にある。ここではその規則が、
文字起こしの崩れ方に対して壊れないことを確かめる。

氏名・会社名は架空か利用者の自社名のみ。実在の個人情報は使わない。
"""
from __future__ import annotations

import pytest

from voice import extract, settings

# 同姓が 2 人いる名簿。「1 人に絞れない」が正常に起きる形にしてある。
BOOK = [
    extract.Staff("服部 太郎", "はっとりたろう", "営業部"),
    extract.Staff("服部 健一", "はっとりけんいち", "製造部"),
    extract.Staff("田中 一郎", "たなかいちろう", "総務部"),
    extract.Staff("佐藤 花子", "さとうはなこ", "総務部"),
]
PURPOSES = ["打ち合わせ", "商談", "納品", "面接", "点検・工事", "その他"]


def names(result) -> list[str]:
    return [n.replace(" ", "") for n in result.host_candidates]


# ── 一文から全部取れること ────────────────────────────────────────────────────

def test_一文から4項目が取れる():
    r = extract.extract(
        "磯野木工所の荒木と申します。本日、服部様と打ち合わせのお約束で参りました",
        BOOK, PURPOSES)
    assert r.visitor_company == "磯野木工所"
    assert r.visitor_name == "荒木"
    assert names(r) == ["服部太郎", "服部健一"]
    assert r.purpose == "打ち合わせ"
    assert r.has_appointment is True


def test_語順が違っても取れる():
    """「用件が先、名乗りが後」も普通に言われる。"""
    r = extract.extract("服部様との打ち合わせで参りました、磯野木工所の荒木です", BOOK, PURPOSES)
    assert r.visitor_company == "磯野木工所"
    assert r.visitor_name == "荒木"
    assert names(r) == ["服部太郎", "服部健一"]


def test_同姓が複数なら絞らない():
    """1 人に決め打つと別の人へ通知が飛ぶ。絞れないことを画面へ返すのが正しい(§4)。"""
    r = extract.extract("服部様との約束で来ました", BOOK, PURPOSES)
    assert len(r.host_candidates) == 2
    assert r.host_name_spoken is None, "絞れていないのに 1 人に確定している"


def test_1人に絞れたときだけ名前が入る():
    r = extract.extract("総務の佐藤さんお願いします", BOOK, PURPOSES)
    assert names(r) == ["佐藤花子"]
    assert r.host_name_spoken == "佐藤 花子"


# ── 名乗りの位置を優先すること(取り違えると別人へ通知が飛ぶ) ─────────────────

def test_名乗りに出た人は来訪者であって担当者ではない():
    """「山田運送の田中です」の田中は、名簿に田中一郎がいても来訪者。

    ここを間違えると配達員あての通知が社員へ飛ぶ。田中・佐藤のような姓では
    実運用で必ず起きる。**LLM 版はこの発話で田中を担当者として通していた。**
    """
    r = extract.extract("山田運送の田中です。総務部に荷物を届けに来ました", BOOK, PURPOSES)
    assert r.visitor_name == "田中"
    assert r.host_candidates == [], f"来訪者を担当者にしている: {r.host_candidates}"
    assert r.purpose == "納品"


def test_名乗りの手前は担当者を探す範囲に残る():
    """名乗りだけを切り落とす。前の文まで巻き込むと担当者を探せなくなる。"""
    r = extract.extract("服部様との打ち合わせで参りました、磯野木工所の荒木です", BOOK, PURPOSES)
    assert names(r) == ["服部太郎", "服部健一"]


# ── 読みで照合すること(文字起こしは同じ人を毎回違う字で返す) ─────────────────

@pytest.mark.parametrize("spoken", [
    "はっとりさま", "はっとりさん", "ハットリ様", "ハッドリ", "アットリ様",
    "ハトリサマット", "ハッドリソマト",
])
def test_表記が揺れても読みで当たる(spoken):
    """実際に whisper が返した表記。文字列一致では 1 件しか当たらなかった。"""
    assert [s.name for s in extract.match_one(spoken, BOOK)], f"{spoken} が当たらない"


def test_漢字が正しく出たらそのまま当たる():
    """読みが分からなくても、名簿と同じ字で出れば突き合う。"""
    assert [s.name for s in extract.match_one("田中", BOOK)] == ["田中 一郎"]


def test_来訪者側の語は当たらない():
    for word in ["あらき", "荒木", "いその", "磯野木工所", "山田運送", "打ち合わせ", "そのもっこうしょ"]:
        assert extract.match_one(word, BOOK) == [], f"{word} が担当者に当たっている"


def test_2文字では1文字の違いを許さない():
    """「はと」と「さと」は 1 文字違い。2 文字で緩めると佐藤にも当たってしまう。

    完全一致なら当たってよい(「はと」は「はっとり」の頭)。許さないのは**違い**の方。
    """
    hit = [s.name for s in extract.match_one("はと", BOOK)]
    assert "佐藤 花子" not in hit, "1 文字違いで別人に当たっている"
    assert hit == ["服部 太郎", "服部 健一"]
    # 3 文字あれば 1 文字の違いまで許す(文字起こしの揺れを吸収するため)。
    assert [s.name for s in extract.match_one("あとり", BOOK)] == ["服部 太郎", "服部 健一"]


def test_読みが無ければ音声では指名できない():
    """読みの推測は禁止(§8)。登録が無い人は漢字一致でしか当たらない。"""
    book = [extract.Staff("服部 太郎")]
    assert extract.match_one("はっとりさま", book) == []
    assert [s.name for s in extract.match_one("服部", book)] == ["服部 太郎"]


def test_別称でも当たる():
    book = [extract.Staff("福部 恵", "ふくべめぐみ", aliases=("ふくべさん",))]
    assert [s.name for s in extract.match_one("ふくべ", book)] == ["福部 恵"]


# ── 実際の言い回し ────────────────────────────────────────────────────────────

def test_言いよどんでも担当者は拾える():
    r = extract.extract("えーと、服部さんだったかな？お約束してるんですけど", BOOK, PURPOSES)
    assert names(r) == ["服部太郎", "服部健一"]
    assert r.has_appointment is True


def test_約束が無いと言われたら約束なしにする():
    """「アポは無い」を約束ありにすると意味が逆になる。"""
    r = extract.extract("アポは無いんですけど服部さんいますか", BOOK, PURPOSES)
    assert r.has_appointment is False
    assert names(r) == ["服部太郎", "服部健一"]
    assert r.visitor_name is None, "「アポは無いん」を氏名にしている"


def test_役割で呼ばれると特定できない():
    """「採用担当の方」は名簿に役割の欄が無いので解けない。

    **取りこぼすのは構わないが、でたらめな氏名を作ってはいけない。**
    """
    r = extract.extract("採用担当の方にお会いしたいのですが", BOOK, PURPOSES)
    assert r.host_candidates == []
    assert r.visitor_name is None


# ── 言っていないことを作らない(§8) ───────────────────────────────────────────

def test_言っていない項目はnullのまま():
    r = extract.extract("打ち合わせで来ました", BOOK, PURPOSES)
    assert r.visitor_company is None
    assert r.visitor_name is None
    assert r.host_candidates == []
    assert r.has_appointment is None, "言っていないのに約束ありにしている"
    assert r.purpose == "打ち合わせ"


def test_空の発話でも落ちない():
    r = extract.extract("", BOOK, PURPOSES)
    assert r.as_dict() == {
        "visitor_company": None, "visitor_name": None, "host_name_spoken": None,
        "host_candidates": [], "purpose": None, "has_appointment": None,
    }


# ── 用件は設定された選択肢から選ぶ ────────────────────────────────────────────

def test_設定に無い用件は返さない():
    r = extract.extract("エアコンの点検に伺いました", BOOK, ["打ち合わせ", "納品"])
    assert r.purpose is None, "選択肢に無い用件を作っている"


def test_用件名と発話の言い方が違っても当たる():
    """管理画面は「お打ち合わせ」「採用面接」。発話は「打ち合わせ」「面接」。"""
    options = ["ご予約のあるお客様", "お打ち合わせ", "納品", "採用面接", "その他"]
    assert extract.purpose_of("打ち合わせで来ました", options) == "お打ち合わせ"
    assert extract.purpose_of("面接に来ました", options) == "採用面接"
    assert extract.purpose_of("荷物をお届けに来ました", options) == "納品"


def test_具体的な用件を優先する():
    """「打ち合わせのお約束」は打ち合わせと予約の両方に当たる。長い方を採る。"""
    options = ["ご予約のあるお客様", "お打ち合わせ"]
    assert extract.purpose_of("打ち合わせのお約束で参りました", options) == "お打ち合わせ"
    assert extract.purpose_of("お約束で参りました", options) == "ご予約のあるお客様"


# ── 名簿の読みの読み込み ──────────────────────────────────────────────────────

def test_読み仮名ファイルを読む(tmp_path):
    path = tmp_path / "staff_readings.yaml"
    path.write_text(
        "staff:\n"
        "  - name: 服部太郎\n"
        "    kana: はっとりたろう\n"
        "    department: 営業部\n"
        "    aliases:\n"
        "      - はっとりさん\n",
        encoding="utf-8")
    settings.cfg()["staff"]["readings_path"] = str(path)

    book = extract.build_staff(["服部 太郎", "田中 一郎"])
    assert book[0].reading == "はっとりたろう"
    assert book[0].aliases == ("はっとりさん",)
    assert book[0].name == "服部 太郎", "画面から渡された表記のまま返すこと"
    assert book[1].reading == "", "登録が無い人は読みが空"
    assert extract.readings_count(["服部 太郎", "田中 一郎"]) == 1


def test_読み仮名ファイルが無くても動く():
    settings.cfg()["staff"]["readings_path"] = "does-not-exist.yaml"
    assert extract.load_readings() == {}
    book = extract.build_staff(["服部 太郎"])
    assert book[0].reading == ""


def test_壊れたファイルでも落ちない(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("staff: [これは: 壊れて\n  います", encoding="utf-8")
    settings.cfg()["staff"]["readings_path"] = str(path)
    assert extract.load_readings() == {}


# ── API 経由(画面がやるのと同じ順序) ──────────────────────────────────────────

def test_一文モードがAPIから使える(monkeypatch, tmp_path, feed):
    """画面 → 音声サービスの経路。担当者と用件の一覧は**画面から渡す**。

    誰がいるかの出どころは管理画面の社員マスターなので、音声サービスに持たせない。
    端末側は読み仮名だけを補う。
    """
    import time as _time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from voice import whisper_cpp
    from voice.api import router
    from voice.types import Transcript
    from voice_audio import silence, tone

    readings = tmp_path / "readings.yaml"
    readings.write_text(
        "staff:\n  - name: 服部太郎\n    kana: はっとりたろう\n", encoding="utf-8")
    settings.cfg()["staff"]["readings_path"] = str(readings)

    heard = "磯野木工所の荒木と申します。本日、はっとり様と打ち合わせのお約束で参りました"
    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))
    monkeypatch.setattr(whisper_cpp, "transcribe", lambda seg: Transcript(
        text=heard, engine="whisper", model_name="whisper-base-q5",
        recognition_ms=120, avg_token_prob=0.9))

    feed(silence(200) + tone(900) + silence(2000))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, client=("127.0.0.1", 50000))

    assert client.get("/voice/status").json()["features"]["reception"] is True

    sid = client.post("/voice/session").json()["session_id"]
    r = client.post(f"/voice/session/{sid}/listen", json={
        "field": "reception",
        "staff": ["服部 太郎", "田中 一郎"],
        "purposes": ["打ち合わせ", "納品", "その他"],
    })
    assert r.status_code == 200

    deadline = _time.monotonic() + 15.0
    state = {}
    while _time.monotonic() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        if state["phase"] in ("done", "error", "cancelled"):
            break
        _time.sleep(0.02)
    assert state["phase"] == "done", state

    got = state["result"]["extracted"]
    assert got["visitor_company"] == "磯野木工所"
    assert got["visitor_name"] == "荒木"
    assert got["host_candidates"] == ["服部 太郎"], "画面が渡した表記で返すこと"
    assert got["purpose"] == "打ち合わせ"
    assert got["has_appointment"] is True


def test_項目ごとの入力では抽出しない(monkeypatch, feed):
    """会社名だけを言わせる従来の入口では、余計な項目を作らない。"""
    import time as _time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from voice import whisper_cpp
    from voice.api import router
    from voice.types import Transcript
    from voice_audio import silence, tone

    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))
    monkeypatch.setattr(whisper_cpp, "transcribe", lambda seg: Transcript(
        text="株式会社ラナソフトです", engine="whisper", model_name="whisper-base-q5",
        recognition_ms=100, avg_token_prob=0.9))

    feed(silence(200) + tone(900) + silence(2000))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, client=("127.0.0.1", 50000))
    sid = client.post("/voice/session").json()["session_id"]
    client.post(f"/voice/session/{sid}/listen", json={"field": "company"})

    deadline = _time.monotonic() + 15.0
    state = {}
    while _time.monotonic() < deadline:
        state = client.get(f"/voice/session/{sid}/state").json()
        if state["phase"] in ("done", "error", "cancelled"):
            break
        _time.sleep(0.02)
    assert state["phase"] == "done", state
    assert state["result"]["extracted"] is None
