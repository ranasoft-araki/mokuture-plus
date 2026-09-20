"""自動確定してよいかの判定(§7)。

whisper.cpp は自信の無さを教えてくれないので、複数の手がかりを合わせて決める。
ここでは「弾くべきものを弾けるか」と「まともな入力を弾いていないか」の両方を見る。
"""
from __future__ import annotations

import pytest

from voice import quality, settings
from voice.types import AudioSegment, Transcript


def seg(*, speech_ms=1200, total_ms=1800, stop_reason="silence", peak=-18.0):
    return AudioSegment(
        pcm=b"\x00" * 100, sample_rate=16000, total_ms=total_ms, speech_ms=speech_ms,
        stop_reason=stop_reason, peak_db=peak, noise_floor_db=-55.0,
    )


def tr(text="株式会社ラナソフト", prob=0.85, no_speech=None, ms=900):
    return Transcript(text=text, engine="whisper", model_name="whisper-base-q5",
                      recognition_ms=ms, avg_token_prob=prob, no_speech_prob=no_speech)


# ── 弾くべきもの ──────────────────────────────────────────────────────────────

def test_no_speech_is_rejected():
    v = quality.judge(seg(speech_ms=0, stop_reason="no_speech"), tr(), "株式会社ラナソフト")
    assert not v.accepted and v.code == "no_speech"


def test_too_short_is_rejected():
    """「音声が短すぎる」(§7)。"""
    v = quality.judge(seg(speech_ms=120, total_ms=600), tr(), "あ")
    assert not v.accepted and v.code == "too_short"


def test_empty_result_is_rejected():
    """認識結果が空(§7)。"""
    v = quality.judge(seg(), tr(text=""), "")
    assert not v.accepted and v.code == "empty_result"


def test_repetition_is_rejected():
    """同じ文字や不自然な文字列の繰り返し(§7)。whisper の典型的な幻聴。"""
    hallucination = "ご視聴ありがとうございましたご視聴ありがとうございました"
    v = quality.judge(seg(speech_ms=3000, total_ms=3500), tr(text=hallucination), hallucination)
    assert not v.accepted and v.code == "repetition"


def test_implausible_length_for_duration_is_rejected():
    """発話時間に対して認識結果が長すぎる(§7)。"""
    long_text = "本日はお忙しいところ誠にありがとうございます私は株式会社" * 2
    v = quality.judge(seg(speech_ms=600, total_ms=900), tr(text=long_text), long_text)
    assert not v.accepted and v.code in ("low_confidence", "repetition")


def test_low_token_probability_is_rejected():
    """平均トークン確率が低い(§7)。"""
    v = quality.judge(seg(), tr(prob=0.20), "株式会社ラナソフト")
    assert not v.accepted and v.code == "low_confidence"


def test_high_no_speech_probability_is_rejected():
    """no-speech 確率が高い(§7)。whisper.cpp が返したときだけ見る。"""
    v = quality.judge(seg(), tr(prob=0.9, no_speech=0.95), "株式会社ラナソフト")
    assert not v.accepted and v.code == "low_confidence"


def test_mostly_silence_without_confidence_is_rejected():
    """無音率が高く、確信度も取れないときは通さない(§7)。"""
    v = quality.judge(seg(speech_ms=500, total_ms=9000), tr(prob=None), "株式会社ラナソフト")
    assert not v.accepted and v.code == "low_confidence"


# ── 通すべきもの ──────────────────────────────────────────────────────────────

def test_normal_input_is_accepted():
    v = quality.judge(seg(), tr(), "株式会社ラナソフト")
    assert v.accepted and v.code is None and v.tone == "ok"


def test_short_name_is_accepted():
    """「林です」のような短い入力を弾かないこと。"""
    v = quality.judge(seg(speech_ms=700, total_ms=1200), tr(text="林です"), "林")
    assert v.accepted


def test_confidence_between_thresholds_is_accepted_but_flagged():
    """微妙な確信度は通すが、画面で色を変えて注意を促す。"""
    v = quality.judge(seg(), tr(prob=0.55), "株式会社ラナソフト")
    assert v.accepted and v.tone == "warn"


def test_missing_confidence_does_not_block_a_good_recording():
    """確信度が取れなくても、録音がまともなら通す(無理に数値化しない・§7)。"""
    v = quality.judge(seg(speech_ms=1400, total_ms=1800), tr(prob=None), "荒木秀人")
    assert v.accepted


# ── 診断に出す値 ──────────────────────────────────────────────────────────────

def test_signals_carry_numbers_only():
    """判定の根拠は数値だけ。認識したテキストは入れない(§11)。"""
    v = quality.judge(seg(), tr(), "株式会社ラナソフト")
    for key, value in v.signals.items():
        assert not isinstance(value, str) or key == "stop_reason", key
    assert "株式会社ラナソフト" not in str(v.signals)


def test_thresholds_come_from_settings():
    """しきい値は設定で動かせる(現場調整用)。"""
    cfg = settings.cfg()
    cfg["quality"]["avg_token_prob_min"] = 0.95
    v = quality.judge(seg(), tr(prob=0.85), "株式会社ラナソフト")
    assert not v.accepted and v.code == "low_confidence"


@pytest.mark.parametrize("text,expected_high", [
    ("ああああああああ", True),
    ("ありがとうございますありがとうございます", True),
    ("株式会社ラナソフト", False),
    ("荒木秀人", False),
    ("有限会社さくら工房", False),
])
def test_repeat_ratio(text, expected_high):
    limit = float(settings.get("quality.repeat_ratio_max"))
    assert (quality.repeat_ratio(text) > limit) is expected_high
