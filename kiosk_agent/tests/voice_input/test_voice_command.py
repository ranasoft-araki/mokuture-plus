"""画面操作のキーワード(声で操作する / Doc/kiosk-voice-touchless.html 段階2)。

Vosk は差し替えて、**言い回しを辞書の語に切る・句として続けて現れたかを確かめる・
2 つ当たったら動かさない・語彙ごとに認識器を使い回す・認識した言葉を画面へ返さない**
ことを確かめる。当たり方そのもの(誤爆・取りこぼし)は scripts/voice_command_eval.py で測る。

最後に kiosk.html の語彙表(VOICE_VOCAB)を読み、形と、実モデルがある環境では
発音辞書の語で書けることを確かめる。画面に書いた言葉が辞書に無いと、その言葉では
選べない(黙って落ちる)。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from voice import metrics, session as session_mod, settings, vosk_engine
from voice.api import router
from voice.types import AudioSegment, CommandMatch
from voice_audio import room, silence, tone
from voice_fakes import FakeRecognizer

AGENT_DIR = Path(__file__).resolve().parents[2]
KIOSK_HTML = AGENT_DIR / "static" / "kiosk.html"

def seg(ms: int = 600) -> AudioSegment:
    return AudioSegment(pcm=b"\x00\x01" * (16 * ms), sample_rate=16000, total_ms=ms, speech_ms=ms,
                        stop_reason="silence", peak_db=-20.0, noise_floor_db=-60.0)


TOP = [("visit", ["ご訪問", "一番"]), ("delivery", ["配達", "二番"]), ("locker", ["ロッカー"]),
       ("back", ["戻る"])]


# ── 言い回しを辞書の語に切る ──────────────────────────────────────────────────

def test_言い回しを辞書の語でいちばん少ない数に切る(fake_vosk):
    t = vosk_engine.phrase_tokens(["ご訪問", "一番", "二番", "最初から"])
    assert t == {"ご訪問": ("ご", "訪問"), "一番": ("一番",), "二番": ("二", "番"), "最初から": ("最初", "から")}


def test_同じ数に切れるなら前の語が長いほうを採る(fake_vosk):
    """「違 います」は辞書にあっても読みが怪しい。"""
    assert vosk_engine.phrase_tokens(["違います"])["違います"] == ("違い", "ます")


def test_空白で区切った言い回しはその区切りのまま(fake_vosk):
    assert vosk_engine.phrase_tokens(["お 願い し ます"])["お 願い し ます"] == ("お", "願い", "し", "ます")


def test_辞書の語で書けない言い回しは使わない(fake_vosk):
    """グラマーに渡すと Vosk がその語だけ黙って落とし、残りの語で当たってしまう。"""
    t = vosk_engine.phrase_tokens(["置き配", "お 願い 致し ます"])
    assert t == {"置き配": None, "お 願い 致し ます": None}


# ── 句として当たったか ────────────────────────────────────────────────────────

def table():
    return vosk_engine.command_table(TOP)[0]


def test_句のすべての語が続けて現れたときだけ当たる(fake_vosk):
    """語で絞られるので「三 いいえ ます」のように句の一部だけが返ることがある(実測)。"""
    assert vosk_engine.match_command([("[unk]", 0.8), ("番", 1.0)], table(), 0.85) == (None, None, "unmatched")
    assert vosk_engine.match_command([("二", 0.9), ("番", 1.0)], table(), 0.85) == ("delivery", 0.9, None)


def test_信頼度が足りない語を含む句は当たりにしない(fake_vosk):
    """「いちどもどってください」が「戻る」0.78 で当たっていた(合成音声の実測)。"""
    assert vosk_engine.match_command([("戻る", 0.78)], table(), 0.85)[0] is None
    assert vosk_engine.match_command([("戻る", 0.95)], table(), 0.85)[0] == "back"


def test_数字の語は少し低い信頼度でも採る(fake_vosk):
    """実機で「にばん」だけ反応しなかった。静かな所でも「二」が 0.83 前後に張り付く(合成音声)。"""
    assert vosk_engine.match_command([("二", 0.83), ("番", 1.0)], table(), 0.85)[0] == "delivery"
    assert vosk_engine.match_command([("一番", 0.8)], table(), 0.85)[0] == "visit"
    # 下げるのは数字の語だけ。句のほかの語・数字でない言葉は 0.85 のまま
    assert vosk_engine.match_command([("二", 0.83), ("番", 0.8)], table(), 0.85)[0] is None
    assert vosk_engine.match_command([("戻る", 0.83)], table(), 0.85)[0] is None
    # 数字にも下限はある
    assert vosk_engine.match_command([("二", 0.7), ("番", 1.0)], table(), 0.85)[0] is None


def test_数字の合格ラインは全体の合格ラインより上げない(fake_vosk):
    """聞き直し(0.4)で数字だけ厳しくなると、聞き直しの意味がなくなる。"""
    assert vosk_engine.match_command([("二", 0.45), ("番", 0.9)], table(), 0.4)[0] == "delivery"


def test_2つの選択肢に当たったら動かさない(fake_vosk):
    """どちらか分からないまま画面を動かすより、言い直してもらうほうが害が小さい。"""
    words = [("配達", 1.0), ("[unk]", 0.9), ("ロッカー", 1.0)]
    assert vosk_engine.match_command(words, table(), 0.85) == (None, None, "ambiguous")


def test_言い添えと同じ言葉の選択肢はほかの言葉に譲る(fake_vosk):
    """ようこそ画面では「お願いします」も選択肢。「やめるでお願いします」は「やめる」。"""
    t = vosk_engine.command_table([("form", ["受付", "お願いします"]), ("home", ["やめる"])])[0]
    words = [("やめる", 1.0), ("で", 1.0), ("お願い", 1.0), ("します", 1.0)]
    assert vosk_engine.match_command(words, t, 0.85)[0] == "home"
    assert vosk_engine.match_command([("お願い", 1.0), ("します", 1.0)], t, 0.85)[0] == "form"


def test_同じ選択肢に2回当たるのは1つと数える(fake_vosk):
    words = [("ロッカー", 1.0), ("ロッカー", 0.9)]
    assert vosk_engine.match_command(words, table(), 0.85) == ("locker", 1.0, None)


def test_文の一部として言われたキーワードでは動かさない(fake_vosk):
    """雑談の「ロッカーの鍵どこだっけ」は信頼度 1.0 で当たる。後ろに語彙外の発話が続く(実測)。"""
    words = [("ロッカー", 1.0, 0.10, 0.55), ("[unk]", 1.0, 0.60, 1.53)]
    assert vosk_engine.match_command(words, table(), 0.85) == (None, None, "embedded")


def test_後ろに続くのが言い添えだけなら動かす(fake_vosk):
    """「ロッカーでお願いします」。言い添えは語彙に入っているので [unk] にならない。"""
    words = [("ロッカー", 1.0, 0.1, 0.58), ("で", 1.0, 0.58, 0.7), ("お", 1.0, 0.7, 0.79),
             ("願い", 1.0, 0.79, 1.12), ("し", 1.0, 1.12, 1.27), ("ます", 1.0, 1.27, 1.63)]
    assert vosk_engine.match_command(words, table(), 0.85)[0] == "locker"


def test_前に付くえーとは許す(fake_vosk):
    """「えーと、ロッカー」の「えーと」は [unk] 0.4 秒ほど(実測)。"""
    words = [("[unk]", 1.0, 0.0, 0.42), ("ロッカー", 1.0, 0.45, 0.99)]
    assert vosk_engine.match_command(words, table(), 0.85)[0] == "locker"


def test_後ろの短い雑音は許す(fake_vosk):
    """息やマイクの擦れが短い [unk] になっても、操作として受ける。"""
    words = [("ロッカー", 1.0, 0.1, 0.58), ("[unk]", 0.9, 0.6, 0.72)]
    assert vosk_engine.match_command(words, table(), 0.85)[0] == "locker"


def test_重なった当たりは長い句を残す(fake_vosk):
    t = vosk_engine.command_table([("visit", ["ご訪問"]), ("other", ["訪問"])])[0]
    assert vosk_engine.match_command([("ご", 1.0), ("訪問", 1.0)], t, 0.85)[0] == "visit"


# ── 認識器と語彙 ──────────────────────────────────────────────────────────────

def test_語彙は選択肢と言い添えと未知語の逃げ場(fake_vosk):
    FakeRecognizer.words = [("ロッカー", 1.0)]
    r = vosk_engine.recognize_command(seg(), TOP)
    assert r.matched == "locker"
    grammar = fake_vosk[0].grammar
    assert {"ご 訪問", "一番", "配達", "二 番", "ロッカー", "戻る"} <= set(grammar)
    assert "お 願い し ます" in grammar and "えっと" in grammar      # 言い添え
    assert grammar[-1] == "[unk]"


def test_選択肢と同じ言葉の言い添えは入れない(fake_vosk):
    """切り方が違うだけの同じ言葉を両方入れると信頼度が割れる(実測 0.79 で取りこぼした)。"""
    FakeRecognizer.words = []
    vosk_engine.recognize_command(seg(), [("form", ["受付", "お願いします"])])
    grammar = fake_vosk[0].grammar
    assert grammar.count("お 願い します") == 1
    assert "お 願い し ます" not in grammar


def test_選択肢の語と同じ音の言い添えは入れない(fake_vosk):
    """「二 番」と言い添えの「に」を並べると、同じ音で信頼度が割れる。"二" の無い画面では残す。"""
    FakeRecognizer.words = []
    vosk_engine.recognize_command(seg(), TOP)
    assert "二 番" in fake_vosk[0].grammar
    assert "に" not in fake_vosk[0].grammar
    vosk_engine.recognize_command(seg(), [("locker", ["ロッカー"]), ("back", ["戻る"])])
    assert "に" in fake_vosk[-1].grammar


def test_小さすぎる声は持ち上げてから認識に渡す(fake_vosk):
    """Vosk は小さすぎる声を言葉として聞き取れない(実機の USB マイクで 46 回中 1 回 → 32 回)。"""
    from voice import vad
    quiet = tone(600, dbfs=-45)
    out = vosk_engine._leveled(quiet)
    level = vad.dbfs(out)
    target = float(settings.get("command.level_target_db"))
    assert target - 2 <= level <= target + 2
    # 上げすぎない(最大 level_max_gain_db)・大きい声は下げない・無音はそのまま
    very_quiet = tone(600, dbfs=-80)
    assert vad.dbfs(vosk_engine._leveled(very_quiet)) <= -80 + float(settings.get("command.level_max_gain_db")) + 1
    loud = tone(600, dbfs=-12)
    assert vosk_engine._leveled(loud) == loud
    assert vosk_engine._leveled(silence(300)) == silence(300)


def test_辞書の切り方が違っても同じ言葉なら当たる(fake_vosk):
    """「お願いします」は「お 願い します」とも「お 願い し ます」とも返る。"""
    t = vosk_engine.command_table([("form", ["お願いします"])])[0]
    words = [("お", 1.0), ("願い", 1.0), ("し", 1.0), ("ます", 1.0)]
    assert vosk_engine.match_command(words, t, 0.85)[0] == "form"


def test_語彙が同じなら認識器を使い回す(fake_vosk):
    """画面を行き来するたびに作り直すと、そのたびに初回のデコード費用を払う。"""
    for _ in range(3):
        vosk_engine.recognize_command(seg(), TOP)
    assert len(fake_vosk) == 1
    assert fake_vosk[0].fed == b"", "認識器の中に音が残っている"


def test_語彙ごとに認識器を持ち古いものから捨てる(fake_vosk):
    settings.cfg()["command"]["cache_size"] = 2
    vocab = [[("a", ["受付"])], [("b", ["配達"])], [("c", ["ロッカー"])]]
    for v in vocab:
        vosk_engine.recognize_command(seg(), v)
    vosk_engine.recognize_command(seg(), vocab[2])     # まだ持っている
    assert len(fake_vosk) == 3
    vosk_engine.recognize_command(seg(), vocab[0])     # 捨てたので作り直す
    assert len(fake_vosk) == 4


def test_書ける言い回しが1つも無ければ認識しない(fake_vosk):
    r = vosk_engine.recognize_command(seg(), [("x", ["置き配"])])
    assert r.reason == "no_vocabulary" and fake_vosk == []


def test_語彙を絞れないモデルでは使えない(fake_vosk):
    """1GB 版(vosk-model-ja-0.22)は HCLG.fst しか無い。"""
    assert vosk_engine.grammar_supported()
    (Path(settings.get("vosk.model_path")) / "graph" / "Gr.fst").unlink()
    assert not vosk_engine.grammar_supported()


# ── 番号の聞き直し(ロッカー) ──────────────────────────────────────────────────
# 語彙を絞ると「にばん」は「番」だけが残る。番号で選ぶ画面だけ通常の認識で聞き直す。

LOCKERS = [("n1", ["一番"]), ("n2", ["二番"]), ("n3", ["三番"]), ("back", ["戻る"])]


def test_語彙を絞って外れたら通常の認識で番号を聞き直す(fake_vosk):
    FakeRecognizer.words = [("[unk]", 0.8, 0.0, 0.2), ("番", 1.0, 0.2, 0.45)]
    FakeRecognizer.free_words = [("二", 0.69, 0.0, 0.2), ("番", 0.65, 0.2, 0.45)]
    r = vosk_engine.recognize_command(seg(), LOCKERS, fallback=True)
    assert r.matched == "n2"
    assert [x.grammar is None for x in fake_vosk] == [False, True]


def test_番号で選ばない画面では聞き直さない(fake_vosk):
    """聞き直しは CPU を使い、雑談の誤爆の母数も増える。番号の画面だけに限る。"""
    FakeRecognizer.words = [("[unk]", 0.8)]
    FakeRecognizer.free_words = [("二", 0.9), ("番", 0.9)]
    r = vosk_engine.recognize_command(seg(), LOCKERS)
    assert r.matched is None
    assert all(x.grammar is not None for x in fake_vosk), "通常の認識器を作っている"


def test_聞き直しでも文の一部なら動かさない(fake_vosk):
    """「にばんせんのでんしゃ」。語彙に無い語は [unk] と見なして同じ物差しで切る。"""
    FakeRecognizer.words = [("[unk]", 0.9, 0.0, 1.2)]
    FakeRecognizer.free_words = [("二", 0.9, 0.0, 0.2), ("番", 0.9, 0.2, 0.4), ("線", 0.9, 0.4, 0.6),
                                 ("の", 0.9, 0.6, 0.7), ("電車", 0.9, 0.7, 1.2)]
    r = vosk_engine.recognize_command(seg(), LOCKERS, fallback=True)
    assert r.matched is None and r.reason == "embedded"


def test_聞き直しは低めのしきい値で採る(fake_vosk):
    """通常の認識は信頼度が低めに出る(「二 番」が 0.65〜0.7)。"""
    FakeRecognizer.words = [("[unk]", 0.8)]
    FakeRecognizer.free_words = [("二", 0.3), ("番", 0.9)]
    assert vosk_engine.recognize_command(seg(), LOCKERS, fallback=True).matched is None
    FakeRecognizer.free_words = [("二", 0.45), ("番", 0.9)]
    assert vosk_engine.recognize_command(seg(), LOCKERS, fallback=True).matched == "n2"


# ── 続けて言う数字(暗証番号) ─────────────────────────────────────────────────
# 「いち に さん よん」を言われた順に返す。1 語でも怪しければ発話ごと捨てる。

PIN = ([(f"d{i}", [d]) for i, d in enumerate(["ゼロ", "一", "二", "三", "四", "五", "六", "七", "八", "九"])]
       + [("del", ["消す"]), ("ok", ["決定"]), ("back", ["戻る"])])


def pin_table():
    return vosk_engine.command_table(PIN)[0]


def test_続けて言った数字を言われた順に返す(fake_vosk):
    words = [("一", 0.9), ("二", 0.8), ("三", 1.0), ("四", 0.95)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85) == (["d1", "d2", "d3", "d4"], 0.8, None)
    # 同じ数字が続いても 1 つにまとめない(「いち いち」は 2 桁)
    words = [("七", 1.0), ("七", 1.0), ("消す", 1.0), ("決定", 0.9)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[0] == ["d7", "d7", "del", "ok"]


def test_数字の合格ラインは続けて言う画面だけ下げる(fake_vosk):
    """語彙が数字だけなので 0.55 まで下げても取り違えが増えなかった(合成音声)。"""
    words = [("一", 0.6), ("二", 0.9)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[0] == ["d1", "d2"]
    assert vosk_engine.match_command(words[:1], pin_table(), 0.85)[0] is None   # ほかの画面の物差しでは落ちる
    # 数字でない言葉は下げない
    assert vosk_engine.match_sequence([("決定", 0.6)], pin_table(), 0.85)[0] is None


def test_1語でも怪しければ発話ごと捨てる(fake_vosk):
    """拾える桁だけ拾うと、桁が黙って抜けたまま番号が入る(「いち に なな ろく」→「なな ろく」の実測)。"""
    # 合格ラインに届かない数字が途中にある
    words = [("一", 0.9), ("二", 0.4), ("三", 0.9)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85) == (None, None, "partial")
    # 頭の桁が [unk] に吸われた
    words = [("[unk]", 0.8, 0.0, 0.5), ("七", 0.9, 0.5, 0.8), ("六", 1.0, 0.8, 1.1)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[2] == "partial"
    # 最後の桁が [unk] に吸われた
    words = [("七", 0.9, 0.0, 0.3), ("六", 1.0, 0.3, 0.6), ("[unk]", 0.8, 0.6, 0.8)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[2] == "partial"
    # 雑談(「三人います」→「[unk] 二 ます」)
    words = [("[unk]", 1.0, 0.0, 0.3), ("二", 0.95, 0.3, 0.5), ("ます", 1.0, 0.5, 0.8)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[2] == "partial"
    assert vosk_engine.match_sequence([("[unk]", 1.0)], pin_table(), 0.85) == (None, None, "unmatched")


def test_続けて言う画面でも言い添えは許す(fake_vosk):
    words = [("五", 0.9), ("で", 1.0), ("お", 1.0), ("願い", 1.0), ("し", 1.0), ("ます", 1.0)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[0] == ["d5"]


def test_言い添えの句のかけらは許さない(fake_vosk):
    """「お 願い し ます」を語にばらして許すと、四を「し」と聞いたときに 4 桁目が黙って消える。"""
    assert vosk_engine.match_sequence([("一", 0.9), ("二", 0.9), ("三", 0.9), ("し", 0.9)],
                                      pin_table(), 0.85)[2] == "partial"
    assert vosk_engine.match_sequence([("一", 0.9), ("ます", 0.9), ("三", 0.9)], pin_table(), 0.85)[2] == "partial"
    # 「二」がある画面では同じ音の言い添え「に」も許さない(語彙にも入れていない)
    assert vosk_engine.match_sequence([("一", 0.9), ("に", 0.9), ("三", 0.9)], pin_table(), 0.85)[2] == "partial"


def test_数字でない言葉の前のえーとは許す(fake_vosk):
    """「えーと、もどる」。頭の [unk] に数字が吸われていても「もどる」の意味は変わらない。"""
    words = [("[unk]", 1.0, 0.0, 0.42), ("戻る", 1.0, 0.45, 0.9)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[0] == ["back"]
    words = [("[unk]", 1.0, 0.0, 0.42), ("一", 1.0, 0.45, 0.9)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[2] == "partial"
    # 数字が後ろにあるときも許さない(頭の [unk] が吸われた数字なら「消す」が消す桁がずれる)
    words = [("[unk]", 1.0, 0.0, 0.42), ("消す", 1.0, 0.45, 0.8), ("一", 1.0, 0.8, 1.0)]
    assert vosk_engine.match_sequence(words, pin_table(), 0.85)[2] == "partial"


def test_続けて言う画面は聞き直さず並びで返す(fake_vosk):
    FakeRecognizer.words = [("一", 0.9), ("二", 0.9)]
    FakeRecognizer.free_words = [("九", 0.9)]
    r = vosk_engine.recognize_command(seg(), PIN, sequence=True, fallback=True)
    assert r.sequence == ["d1", "d2"] and r.matched is None
    assert all(x.grammar is not None for x in fake_vosk), "通常の認識器で聞き直している"


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def heard(monkeypatch, fake_vosk):
    """認識の結果を決め打ちにする(録音ループは本物)。"""
    state = {"match": CommandMatch(matched="locker", confidence=0.97, reason=None, recognition_ms=40,
                                   words=[("ロッカー", 0.97)]),
             "calls": []}

    def fake(segment, choices, min_conf=None, **kw):
        state["calls"].append(choices)
        state.setdefault("kw", []).append(kw)
        m = state["match"]
        return CommandMatch(m.matched, m.confidence, m.reason, m.recognition_ms, list(m.words),
                            sequence=list(m.sequence) if m.sequence else None)

    monkeypatch.setattr(vosk_engine, "recognize_command", fake)
    return state


def wait_for(client, sid, phases=("done", "error", "cancelled"), timeout=15.0):
    deadline = time.monotonic() + timeout
    s = {}
    while time.monotonic() < deadline:
        s = client.get(f"/voice/session/{sid}/state").json()
        if s["phase"] in phases:
            return s
        time.sleep(0.02)
    pytest.fail(f"状態が {phases} にならなかった: {s.get('phase')}")


def start(client):
    return client.post("/voice/session").json()["session_id"]


def body(**kw):
    b = {"screen": "top", "choices": [{"id": cid, "phrases": ps} for cid, ps in TOP]}
    b.update(kw)
    return b


def command_rows():
    return [r for r in metrics._read_rows() if str(r.get("screenId", "")).startswith("command-")]


def test_statusに声で操作できるかが出る(client, fake_vosk, feed):
    feed(silence(100))
    s = client.get("/voice/status").json()
    assert s["features"]["command"] is True and s["command"]["available"] is True


def test_statusに暗証番号を声で入れられる版かが出る(client, fake_vosk, feed):
    """画面だけ OTA で新しくなり、サービスが古い版のままだと secret が効かず数字がログに残る。
    画面はこれが true のときだけ暗証番号の画面でマイクを開ける。"""
    feed(silence(100))
    assert client.get("/voice/status").json()["features"]["sequence"] is True
    settings.cfg()["command"]["enabled"] = False
    assert client.get("/voice/status").json()["features"]["sequence"] is False


def test_voskが無ければ声で操作できない(client, feed, monkeypatch):
    feed(silence(100))
    monkeypatch.setattr(vosk_engine, "available", lambda lang="ja": (False, "無い"))
    s = client.get("/voice/status").json()
    assert s["features"]["command"] is False


def test_設定で止められる(client, fake_vosk, feed):
    feed(silence(100))
    settings.cfg()["command"]["enabled"] = False
    assert client.get("/voice/status").json()["features"]["command"] is False
    sid = start(client)
    assert client.post(f"/voice/session/{sid}/command", json=body()).status_code == 409


def test_言われた選択肢を返し言葉そのものは返さない(client, heard, feed):
    feed(room(200) + tone(500) + silence(900))
    sid = start(client)
    assert client.post(f"/voice/session/{sid}/command", json=body()).status_code == 200
    s = wait_for(client, sid)
    assert s["phase"] == "done"
    assert s["command"]["matched"] == "locker"
    assert "ロッカー" not in json.dumps(s, ensure_ascii=False), "認識した言葉を画面へ返している"
    assert heard["calls"][0][2] == ("locker", ["ロッカー"])


def test_当たらなければ画面を動かさない(client, heard, feed):
    heard["match"] = CommandMatch(None, None, "unmatched", 30)
    feed(room(200) + tone(500) + silence(900))
    sid = start(client)
    client.post(f"/voice/session/{sid}/command", json=body())
    s = wait_for(client, sid)
    assert s["command"]["matched"] is None and s["error_code"] == "unmatched"
    assert s["message"] == "もう一度お願いします"


def test_実験ログには画面と選択肢のidだけを残す(client, heard, feed):
    feed(room(200) + tone(500) + silence(900))
    sid = start(client)
    client.post(f"/voice/session/{sid}/command", json=body())
    wait_for(client, sid)
    rows = command_rows()
    assert len(rows) == 1
    assert rows[0]["screenId"] == "command-top" and rows[0]["choiceId"] == "locker"
    assert "ロッカー" not in json.dumps(rows, ensure_ascii=False)


def pin_body(**kw):
    b = {"screen": "lockerPin", "choices": [{"id": cid, "phrases": ps} for cid, ps in PIN],
         "sequence": True, "secret": True}
    b.update(kw)
    return b


def test_暗証番号の数字は並びで返しログには残さない(client, heard, feed, caplog):
    """選択肢の id が数字そのものなので、実験ログにもサービスのログにも書くと暗証番号が端末に残る。"""
    heard["match"] = CommandMatch(None, 0.9, None, 40, words=[("一", 0.9)], sequence=["d1", "d2", "d3", "d4"])
    feed(room(200) + tone(500) + silence(900))
    sid = start(client)
    with caplog.at_level("INFO"):
        assert client.post(f"/voice/session/{sid}/command", json=pin_body()).status_code == 200
        s = wait_for(client, sid)
    assert s["phase"] == "done" and s["command"]["sequence"] == ["d1", "d2", "d3", "d4"]
    assert heard["kw"][0]["sequence"] is True
    rows = command_rows()
    assert len(rows) == 1 and rows[0]["choiceId"] == "secret" and rows[0]["accepted"] is True
    # サービスのログだけを見る。乱数のセッション id(httpx のログ・sessionId)には「d1」が混ざりうるので外す。
    voice_log = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("voice"))
    assert "lockerPin: matched" in voice_log
    fixed = [{k: v for k, v in r.items() if k not in ("sessionId", "timestamp")} for r in rows]
    dumped = json.dumps(fixed, ensure_ascii=False) + voice_log
    assert not re.search(r"d[0-9]", dumped), "暗証番号の数字がログに残っている"
    assert "一" not in dumped


def test_続けて言う画面は画面がsecretを付け忘れても数字を記録しない(client, heard, feed):
    """続けて言う画面は暗証番号だけ。画面側の付け忘れで暗証番号がログに残らないよう二重にしておく。"""
    heard["match"] = CommandMatch(None, 0.9, None, 40, sequence=["d1", "ok"])
    feed(room(200) + tone(500) + silence(900))
    sid = start(client)
    client.post(f"/voice/session/{sid}/command", json=pin_body(secret=False))
    wait_for(client, sid)
    assert command_rows()[0]["choiceId"] == "secret"


def test_続けて言う画面は録音を長めに取る(client, heard, feed, monkeypatch):
    """4 桁を区切って言うと 3 秒を超え、最後の桁が切れた(合成音声・話速 -3)。"""
    from voice import vad
    seen = []
    real = vad.record_utterance
    monkeypatch.setattr(vad, "record_utterance", lambda *a, **kw: seen.append(kw["max_record_sec"]) or real(*a, **kw))
    for b in (pin_body(), body()):
        feed(room(200) + tone(500) + silence(900))
        sid = start(client)
        client.post(f"/voice/session/{sid}/command", json=b)
        wait_for(client, sid)
    assert seen == [float(settings.get("command.sequence_max_record_sec")), float(settings.get("command.max_record_sec"))]


def test_話しかけられなかった窓は記録しない(client, heard, feed):
    """画面が選択を待つ間は開け直し続けるので、数えるとログが無言で埋まる。"""
    settings.cfg()["command"]["window_sec"] = 1.0
    feed(silence(3000))
    sid = start(client)
    client.post(f"/voice/session/{sid}/command", json=body())
    s = wait_for(client, sid)
    assert s["phase"] == "error" and s["error_code"] == "no_speech"
    assert command_rows() == [] and heard["calls"] == []


def test_画面が変わったら前の語彙の聞き取りを畳んで開け直す(client, heard, feed):
    feed(silence(10000))                     # 誰も話さない = 前の聞き取りは走り続ける
    sid = start(client)
    client.post(f"/voice/session/{sid}/command", json=body())
    wait_for(client, sid, phases=("listening",))
    r = client.post(f"/voice/session/{sid}/command",
                    json=body(screen="lockerMode", choices=[{"id": "store", "phrases": ["預ける"]}]))
    assert r.status_code == 200, "前の画面の聞き取りに阻まれた"
    assert r.json()["phase"] in ("arming", "listening")


@pytest.mark.parametrize("bad", [
    {"choices": []},
    {"choices": [{"id": "Visit", "phrases": ["ご訪問"]}]},              # id は小文字の固定語彙
    {"choices": [{"id": "田中", "phrases": ["田中"]}]},
    {"choices": [{"id": "x", "phrases": []}]},
    {"choices": [{"id": "x", "phrases": ["あ" * 17]}]},
    {"screen": "top page"},
    {"window_sec": 0.2},
])
def test_形の崩れた依頼は受けない(client, fake_vosk, bad):
    sid = start(client)
    assert client.post(f"/voice/session/{sid}/command", json=body(**bad)).status_code == 422


def test_端末の外からは使えない(fake_vosk):
    app = FastAPI()
    app.include_router(router)
    remote = TestClient(app, client=("192.168.1.50", 50000))
    assert remote.post("/voice/session/" + "a" * 22 + "/command", json=body()).status_code == 403


def test_集計は画面ごとの当たりと外れ方():
    """声の操作以外の行(古い一文入力のログなど)は数えない。"""
    metrics.record({"sessionId": "s1", "screenId": "visitor-name-input", "result": "success"})
    metrics.record({"sessionId": "s2", "screenId": "command-top", "result": "success", "choiceId": "visit"})
    metrics.record({"sessionId": "s2", "screenId": "command-top", "result": "error", "errorCode": "unmatched"})
    metrics.record({"sessionId": "s2", "screenId": "command-top", "result": "error", "errorCode": "ambiguous"})
    s = metrics.summary()
    assert s["attempts"] == 3 and s["voice_sessions"] == 1 and s["by_choice"] == {"visit": 1}
    assert s["by_screen"]["top"] == {"attempts": 3, "matched": 1, "unmatched": 1, "ambiguous": 1,
                                     "embedded": 0, "partial": 0, "error": 0,
                                     "matched_rate": 0.3333}


# ── kiosk.html の語彙表 ───────────────────────────────────────────────────────

def load_vocab() -> dict:
    text = KIOSK_HTML.read_text(encoding="utf-8")
    m = re.search(r"/\* VOICE_VOCAB:BEGIN \*/\s*const VOICE_VOCAB = (\{.*?\});\s*/\* VOICE_VOCAB:END \*/", text, re.S)
    assert m, "kiosk.html に VOICE_VOCAB の表が見つからない"
    return json.loads(m.group(1))


def test_語彙表の形():
    vocab = load_vocab()
    for key, v in vocab.items():
        wire_id = key.split(".")[-1].lower()
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,31}", wire_id), key
        assert 1 <= len(v["say"]) <= 8 and v["label"], key
        assert all(1 <= len(p) <= 16 for p in v["say"]), key


def test_語彙表に同じ言い回しを2つの選択肢で使わない():
    """同じ画面に並ぶ選択肢どうしで言い回しが重なると、どちらにも当たって動かない。"""
    vocab = load_vocab()
    common = {k: v for k, v in vocab.items() if k.startswith("common.")}
    groups: dict[str, dict] = {}
    for k, v in vocab.items():
        if not k.startswith("common."):
            groups.setdefault(k.split(".")[0], {})[k] = v
    for screen, items in groups.items():
        # 開ける前の確認は画面の上に重なるので、下の画面の共通語を持たない。
        shared = {} if screen == "confirm" else common
        owner: dict[str, str] = {}
        for k, v in {**items, **shared}.items():
            for p in v["say"]:
                assert p not in owner, f"{screen}: 「{p}」が {owner.get(p)} と {k} の両方にある"
                owner[p] = k


@pytest.mark.skipif(not (AGENT_DIR / "voice_models" / "vosk-model-small-ja-0.22" / "graph" / "words.txt").is_file(),
                    reason="Vosk のモデルが無い環境では発音辞書を確かめられない")
def test_語彙表の言い回しはすべて発音辞書の語で書ける():
    """書けない言い回しはサービスが黙って落とす = 画面に書いてあるのに声では選べない。"""
    settings.cfg()["vosk"]["model_path"] = str(AGENT_DIR / "voice_models" / "vosk-model-small-ja-0.22")
    phrases = [p for v in load_vocab().values() for p in v["say"]]
    tokens = vosk_engine.phrase_tokens(phrases)
    missing = [p for p, t in tokens.items() if not t]
    assert missing == [], f"発音辞書の語で書けない: {missing}"
