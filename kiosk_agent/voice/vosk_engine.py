"""Vosk での文字起こし。一文の名乗りはこちらを使う。

**whisper.cpp との使い分け**

一文受付で当てたいのは固有名詞の**読み**で、漢字は当てにいかない(同じ読みでも字が
違うことがあるため)。その前提で肉声10発話を測ると、こちらの方が良かった。

                 読みCER   固有名詞が残った   1発話(Windows)
  whisper base    0.217      14/21            1.8秒
  whisper small   0.179      15/21           10.1秒
  Vosk small-ja   0.118      16/21            4.3秒

差は仕組みから来ている。Vosk は**辞書にある語しか出せない**ので「磯野」「荒木」
「服部」という実在の語を選ぶ。whisper は文字を自由に生成するので「伊藻」「新き」
「張っとり」のような存在しない綴りを作る。読みで照合する方針ではこれが効く。

**弱点も仕組みから来る。** 辞書に無い語は別の実在語に化ける(「服部様」→「酉様」、
「磯野」→「五所川原」)。whisper なら仮名で残るところが、Vosk では読みごと失われる。
初めて来る会社名では whisper の方が拾えることがある。

モデルは 48MB と小さく、Vosk はもともと Raspberry Pi のような機械を想定している。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from voice import settings
from voice.types import AudioSegment, Transcript

log = logging.getLogger(__name__)

ENGINE_NAME = "vosk"


class EngineUnavailable(RuntimeError):
    """モデルか vosk パッケージが無い。"""


class EngineFailed(RuntimeError):
    """認識そのものに失敗した。"""


# モデルの読み込みは数秒かかるうえメモリを持つので、一度だけ読んで使い回す。
_model = None
_model_lock = threading.Lock()

# 認識器も使い回す。**毎回作り直すと 3 倍以上遅くなる**(実測: 中央値 4.45秒 → 1.28秒)。
# デコード用のグラフを組み直すのがそれだけ重い。Kaldi の認識器はスレッド安全では
# ないので、ここで直列化する(認識自体も session 側で 1 件ずつに絞っている)。
_rec = None
_rec_rate = 0
_rec_lock = threading.Lock()

# 語彙を絞った 2 パス目の認識器。フリー認識とは別に持つ(片方ずつ暖まっていてほしい)。
_gram_rec = None
_gram_key: tuple[int, str] | None = None
_gram_warned: tuple[str, ...] = ()      # 語彙に入れられなかった名前(同じ顔ぶれでは黙る)


def model_path() -> Path:
    return settings.resolve_path(str(settings.get("vosk.model_path")))


def model_name() -> str:
    return str(settings.get("vosk.model_name"))


def _probe_package() -> tuple[bool, str]:
    try:
        import vosk  # noqa: F401
    except Exception:
        return False, "vosk が入っていません (uv pip install vosk)"
    return True, ""


def available() -> tuple[bool, str]:
    ok, detail = _probe_package()
    if not ok:
        return False, detail
    path = model_path()
    if not path.is_dir():
        return False, (f"Vosk のモデルがありません: {path}"
                       " (python3 scripts/fetch_voice_models.py --extract)")
    return True, f"{model_name()} ({path.name})"


def describe() -> dict:
    ok, detail = available()
    return {
        "engine": ENGINE_NAME,
        "available": ok,
        "detail": detail,
        "model": model_name(),
        "model_file": model_path().name,
        "loaded": _model is not None,
        "timeout_sec": float(settings.get("vosk.timeout_sec")),
    }


def load(force: bool = False) -> object:
    """モデルを読む。**読み込みは数秒かかる**ので、起動時に済ませておくとよい。"""
    global _model
    with _model_lock:
        if _model is not None and not force:
            return _model
        ok, detail = available()
        if not ok:
            raise EngineUnavailable(detail)
        import vosk
        vosk.SetLogLevel(-1)          # Kaldi の大量のログを止める
        started = time.monotonic()
        _model = vosk.Model(str(model_path()))
        log.info("[voice] vosk loaded in %dms (model=%s)",
                 int((time.monotonic() - started) * 1000), model_name())
        return _model


def unload() -> None:
    """モデルと認識器を手放す。設定を変えて読み直すときだけ使う。"""
    global _model, _rec, _rec_rate, _gram_rec, _gram_key
    with _rec_lock:
        _rec, _rec_rate = None, 0
        _gram_rec, _gram_key = None, None
    with _model_lock:
        _model = None


def _recognizer(rate: int):
    """使い回す認識器を返す。呼ぶ側は _rec_lock を持っていること。"""
    global _rec, _rec_rate
    import vosk

    if _rec is None or _rec_rate != rate:
        _rec = vosk.KaldiRecognizer(load(), float(rate))
        _rec.SetWords(True)          # 語ごとの信頼度(品質判定に使う)。速度への影響は無い
        _rec_rate = rate
    else:
        # 前の発話の状態を持ち越さない。§11 の「認識結果を残さない」も兼ねる。
        _rec.Reset()
    return _rec


# ── 語彙を絞った 2 パス目 ─────────────────────────────────────────────────────
# 一般語の言語モデルは固有名詞に弱い。実測(クリーン音源10本)では「服部」が
# 「酉」「都立」「服部祖」に化けた。**辞書に無いのではなく**、文脈で別語に負けて
# いる(辞書 206,715 語に「服部」「磯野」「荒木」はある)。
#
# 担当者は「誰がいるか」が分かっているので、その語彙だけに絞って decode し直すと
# 当たる。実測: 担当者の特定が 8/10 → 10/10、誤爆 0。
#
# **絞った側の結果は候補にしか使わない。** 呼ばれた担当者が名簿に無いとき、別人の
# 名前を埋めることがある(実測 10件中 2件: 「服部様」→「林様」「山本」)。ただし誤って
# 埋めた語は信頼度が落ちる(実測 0.657〜0.871 / 正解は 6/6 すべて 1.000)ので、
# grammar_min_conf で捨てられる。捨てた場合は候補なし = 画面で選ぶ従来の動きに戻る。

# 姓は 2〜4 文字で見る。1 文字の姓を入れないのは、短い語ほどどこにでも当たるうえ、
# 照合側(extract.scan_staff)が 2 文字以上でしか名簿と突き合わせないため。
_NAME_PREFIX_MAX = 4


def lexicon_words(candidates: set[str]) -> set[str]:
    """モデルの発音辞書にある語だけを返す。

    **読み仮名を staff_readings.yaml に登録しても Vosk の発音辞書には入らない。**
    辞書に無い表記をグラマーに渡すと Vosk が失敗するので、ここで落とす。
    辞書は 20 万語あるので、常駐させずに必要な語だけ拾って捨てる。
    """
    path = model_path() / "graph" / "words.txt"
    if not candidates or not path.is_file():
        return set()
    found: set[str] = set()
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            word = line.split(" ", 1)[0]
            if word in candidates:
                found.add(word)
    return found


def grammar_tokens(names: list[str]) -> tuple[list[str], list[str]]:
    """(グラマーに入れる語, 入れられなかった名前)。

    姓だけ言われるのが普通なので、名前の先頭から辞書にある一番長い並びを採る。
    入れられなかった名前は、音声では指名できない(従来どおりフリー認識の読み照合
    だけが頼りになる)ので、呼ぶ側が気づけるように返す。
    """
    compact = [str(n or "").replace(" ", "").replace("　", "").strip() for n in names]
    sizes = range(2, _NAME_PREFIX_MAX + 1)
    known = lexicon_words({n[:i] for n in compact for i in sizes if len(n) >= i})
    tokens: list[str] = []
    missing: list[str] = []
    for name in compact:
        best = max((name[:i] for i in sizes if len(name) >= i and name[:i] in known),
                   key=len, default="")
        if best:
            tokens.append(best)
        elif name:
            missing.append(name)
    return sorted(set(tokens)), missing


def _grammar_json(tokens: list[str]) -> str:
    """Vosk に渡すグラマー。定型句を混ぜないと、周りが全部 [unk] に寄る。"""
    phrases = [str(p) for p in (settings.get("vosk.grammar_phrases") or [])]
    usable = lexicon_words({w for p in phrases for w in p.split(" ")})
    keep = [p for p in phrases if all(w in usable for w in p.split(" "))]
    # [unk] は語彙外の音の逃げ場。無いと未知の会社名が候補の名前に化ける。
    return json.dumps(tokens + keep + ["[unk]"], ensure_ascii=False)


def _grammar_recognizer(rate: int, grammar: str):
    """語彙を絞った認識器。呼ぶ側は _rec_lock を持っていること。

    作り直しは重い(フリー側の実測で 1.28秒 → 4.45秒)ので、語彙が変わったときだけ
    作り直す。担当者一覧が変わるのは一日に数回で、発話ごとではない。
    """
    global _gram_rec, _gram_key
    import vosk

    key = (rate, grammar)
    if _gram_rec is None or _gram_key != key:
        _gram_rec = vosk.KaldiRecognizer(load(), float(rate), grammar)
        _gram_rec.SetWords(True)
        _gram_key = key
    else:
        _gram_rec.Reset()
    return _gram_rec


def transcribe_vocabulary(seg: AudioSegment, names: list[str]) -> tuple[str, list[str]]:
    """担当者の語彙だけで decode し直す。(文字起こし, 信頼できた語) を返す。

    2 パス目なので、失敗しても 1 パス目の結果は使える。呼ぶ側で握りつぶしてよい。
    """
    global _gram_warned
    tokens, missing = grammar_tokens(names)
    if tuple(missing) != _gram_warned:
        _gram_warned = tuple(missing)
        if missing:
            # 読み仮名の登録とは別の話なので、運用者が気づけるようにしておく。
            log.warning("[voice] 発音辞書に無いため音声で指名できない担当者: %s",
                        "、".join(missing))
    if not tokens:
        return "", []
    grammar = _grammar_json(tokens)
    floor = float(settings.get("vosk.grammar_min_conf"))
    with _rec_lock:
        try:
            rec = _grammar_recognizer(seg.sample_rate, grammar)
            rec.AcceptWaveform(seg.pcm)
            payload = json.loads(rec.FinalResult() or "{}")
        except Exception as e:
            globals()["_gram_rec"], globals()["_gram_key"] = None, None
            raise EngineFailed(f"{type(e).__name__}") from e
        finally:
            try:
                if _gram_rec is not None:
                    _gram_rec.Reset()
            except Exception:
                pass

    text = str(payload.get("text") or "").replace(" ", "").strip()
    sure = [str(w.get("word", "")) for w in payload.get("result") or []
            if str(w.get("word", "")) in tokens and float(w.get("conf", 0.0)) >= floor]
    return text, sure


def transcribe(seg: AudioSegment) -> Transcript:
    """1 発話ぶんを文字起こしする。

    whisper と違って外部プロセスを起こさないので、一時ファイルを作らない
    (=音声がディスクに残らない)。渡された PCM はそのまま渡して捨てる。
    """
    load()
    started = time.monotonic()
    with _rec_lock:
        try:
            rec = _recognizer(seg.sample_rate)
            rec.AcceptWaveform(seg.pcm)
            payload = json.loads(rec.FinalResult() or "{}")
        except Exception as e:
            # 壊れた認識器を使い回さない。次回は作り直す。
            globals()["_rec"], globals()["_rec_rate"] = None, 0
            raise EngineFailed(f"{type(e).__name__}") from e
        finally:
            # 認識結果を認識器の中に残さない(§11)。
            try:
                if _rec is not None:
                    _rec.Reset()
            except Exception:
                pass

    # 日本語は語の間に空白が入って返るので詰める。
    text = str(payload.get("text") or "").replace(" ", "").strip()
    words = [(str(w.get("word", "")), float(w.get("conf", 0.0)))
             for w in payload.get("result") or [] if w.get("word")]
    avg = sum(c for _, c in words) / len(words) if words else None

    return Transcript(
        text=text,
        engine=ENGINE_NAME,
        model_name=model_name(),
        recognition_ms=int((time.monotonic() - started) * 1000),
        avg_token_prob=avg,
        words=words,
    )


def warmup() -> None:
    """起動時にモデルと認識器を作っておく。

    **最初の1件だけ大きく遅い。** Windows の実測で 1 回目 4.7秒 → 2 回目以降 0.7秒。
    モデルの読み込みでも認識器の生成でもなく、Kaldi が**最初に実際のデコードを
    行うとき**に払う費用で、モデルファイルを先読みしても消えなかった。
    雑音を流しておくと 4.7秒 → 3.3秒 程度までは減る(語の候補を辿らないので
    全部は肩代わりできない)。

    運用上は、サービスが起動してから最初の来訪者 1 人だけが余分に待つ。
    OTA でサービスが再起動するたびに 1 回起きる。
    """
    import random

    try:
        load()
        rate = int(settings.get("audio.sample_rate") or 16000)
        random.seed(0)
        noise = b"".join(
            int(max(-32000, min(32000, random.gauss(0, 900)))).to_bytes(2, "little", signed=True)
            for _ in range(rate * 2))
        with _rec_lock:
            rec = _recognizer(rate)
            rec.AcceptWaveform(noise)
            rec.FinalResult()
            rec.Reset()
    except EngineUnavailable as e:
        log.info("[voice] vosk: %s", e)
    except Exception as e:                              # 起動は止めない
        log.warning("[voice] vosk のウォームアップに失敗: %s", type(e).__name__)
