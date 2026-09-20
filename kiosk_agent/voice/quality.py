"""認識結果を自動で入力欄へ入れてよいかの判定(§7)。

whisper.cpp は「自信が無い」と言ってくれない。無音や雑音に対しても、それらしい
文を返してしまうことがある(いわゆる幻聴)。確信度を 1 つの数値で受け取れない以上、
複数の手がかりを組み合わせて判断する(§7 の指定):

    無音率 / 認識文字数 / 平均トークン確率 / no-speech 確率 /
    同じ文字や不自然な文字列の繰り返し / 発話時間に対する認識結果の長さ

どれかに引っかかったら `accepted=False` にして、再入力か候補選択を求める。
**引っかかっても認識テキストは画面に出す**。黙って捨てるより「こう聞こえました」と
見せたほうが、利用者は直すか話し直すかを選べる。

判定に使った値は `signals` に入れて画面と診断に返す。ここに入るのは数値と真偽値
だけで、認識したテキストそのものは入れない(§11)。
"""
from __future__ import annotations

from voice import settings
from voice.types import AudioSegment, Judgement, Transcript


def repeat_ratio(text: str) -> float:
    """繰り返しの強さを 0〜1 で返す。1 に近いほど「同じものの繰り返し」。

    3 種類の壊れ方を見る:
      - 同じ文字が続く      「あああああ」
      - 丸ごと二重          「ご視聴ありがとうございましたご視聴ありがとうございました」
      - 同じ並びの重複      「ありがとうございますありがとうございます、ありがとう」

    丸ごと二重は whisper が無音や雑音に対して出す典型的な幻聴で、2-gram の重複率
    だけでは 0.5 前後にしかならず取りこぼす。周期そのものを見て 1.0 と断定する。
    """
    t = "".join(text.split())
    if len(t) < 4:
        return 0.0

    # 同じ並びが丸ごと繰り返されていないか(周期の検出)
    for period in range(1, len(t) // 2 + 1):
        if len(t) % period == 0 and t == t[:period] * (len(t) // period):
            return 1.0

    # 同じ文字の最長連続が全体に占める割合
    longest_run = 1
    run = 1
    for i in range(1, len(t)):
        run = run + 1 if t[i] == t[i - 1] else 1
        longest_run = max(longest_run, run)
    run_ratio = longest_run / len(t)

    # 2-gram の重複率(異なり数が少ないほど繰り返している)
    grams = [t[i:i + 2] for i in range(len(t) - 1)]
    gram_ratio = 1.0 - (len(set(grams)) / len(grams)) if grams else 0.0

    return round(max(run_ratio, gram_ratio), 3)


def judge(seg: AudioSegment, tr: Transcript, normalized: str) -> Judgement:
    """採用可否を決める。呼び出し側は accepted と code を見て画面を切り替える。"""
    q = settings.get("quality") or {}
    min_chars = int(q.get("min_chars", 1))
    max_cps = float(q.get("max_chars_per_sec", 12.0))
    min_speech_ratio = float(q.get("min_speech_ratio", 0.2))
    prob_min = float(q.get("avg_token_prob_min", 0.45))
    no_speech_max = float(q.get("no_speech_max", 0.6))
    repeat_max = float(q.get("repeat_ratio_max", 0.55))
    warn_prob = float(q.get("warn_token_prob", 0.65))
    min_speech_ms = float(settings.get("vad.min_speech_sec")) * 1000.0

    speech_sec = seg.speech_ms / 1000.0
    chars = len(normalized)
    cps = (chars / speech_sec) if speech_sec > 0 else 0.0
    rep = repeat_ratio(normalized)

    signals: dict[str, float | int | bool | None] = {
        "audio_ms": seg.total_ms,
        "speech_ms": seg.speech_ms,
        "speech_ratio": round(seg.speech_ratio, 3),
        "chars": chars,
        "chars_per_sec": round(cps, 2),
        "repeat_ratio": rep,
        "avg_token_prob": (round(tr.avg_token_prob, 3) if tr.avg_token_prob is not None else None),
        "no_speech_prob": (round(tr.no_speech_prob, 3) if tr.no_speech_prob is not None else None),
        "peak_db": seg.peak_db,
        "noise_floor_db": seg.noise_floor_db,
        "stop_reason": None,        # 呼び出し側が入れる(型を揃えるための場所取り)
    }

    def no(code: str) -> Judgement:
        return Judgement(accepted=False, code=code, tone="weak", signals=signals)

    # ── 音が無い / 短すぎる ───────────────────────────────────────────────
    if seg.stop_reason == "no_speech" or seg.speech_ms <= 0:
        return no("no_speech")
    if seg.speech_ms < min_speech_ms:
        return no("too_short")

    # ── 認識結果が空 ─────────────────────────────────────────────────────
    if chars < min_chars:
        return no("empty_result")

    # ── 壊れ方の判定 ─────────────────────────────────────────────────────
    if rep > repeat_max:
        return no("repetition")
    # 発話時間に対して文字数が多すぎる = 幻聴の疑い
    if speech_sec > 0 and cps > max_cps:
        return no("low_confidence")

    # ── 確信度(取れたときだけ見る) ───────────────────────────────────────
    if tr.avg_token_prob is not None and tr.avg_token_prob < prob_min:
        return no("low_confidence")
    if tr.no_speech_prob is not None and tr.no_speech_prob > no_speech_max:
        return no("low_confidence")

    # ── 無音率が高い録音は、確信度が取れないときだけ弾く ─────────────────
    # (確信度が十分に高ければ、間の空いた喋り方というだけなので通す)
    if seg.speech_ratio < min_speech_ratio and tr.avg_token_prob is None:
        return no("low_confidence")

    tone = "ok"
    if tr.avg_token_prob is not None and tr.avg_token_prob < warn_prob:
        tone = "warn"
    elif seg.speech_ratio < min_speech_ratio:
        tone = "warn"
    return Judgement(accepted=True, code=None, tone=tone, signals=signals)
