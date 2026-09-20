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
    global _model, _rec, _rec_rate
    with _rec_lock:
        _rec, _rec_rate = None, 0
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
