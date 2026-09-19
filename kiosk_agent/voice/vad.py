"""VAD(発話区間の検出)と録音ループ。

やること(§8):
  - ボタンが押されたらマイクを開き、話し始めるのを待つ(既定 5 秒)
  - 話し始めたら録音し、無音が一定時間続いたら自動で終える(既定 0.7 秒)
  - 「入力を終了」ボタン・最大録音時間でも終える
  - 前後の不要な無音は認識処理へ渡さない(pre/post roll の分だけ残す)

既定のエンジンは追加依存の要らない**エネルギーベース**。暗騒音(空調・人通り)の
レベルを走りながら推定し、そこから一定 dB 上を発話とみなす。ロビーの騒がしさが
端末ごとに違っても、しきい値を手で調整しないで済むようにするため。

`webrtcvad` が入っていれば `vad.engine: webrtc` でそちらも使える。判定だけ差し替わり、
録音ループ・pre/post roll・終了条件は共通。

音声はメモリ上にだけ置く(§11)。この関数を抜けた後に残るのは戻り値の AudioSegment
だけで、呼び出し側が認識を終えたら clear() で捨てる。
"""
from __future__ import annotations

import logging
import math
import time
from array import array
from collections import deque
from typing import Callable

from voice import capture, settings
from voice.types import AudioSegment, StopReason

log = logging.getLogger(__name__)

# 画面のレベルメーターを 0〜1 に正規化するときの下限・上限(dBFS)
METER_MIN_DB = -60.0
METER_MAX_DB = -12.0


def dbfs(pcm: bytes) -> float:
    """フレームの RMS を dBFS で返す。無音は -100 を返す。"""
    if not pcm:
        return -100.0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return -100.0
    total = 0
    for s in samples:
        total += s * s
    rms = math.sqrt(total / len(samples))
    if rms <= 0:
        return -100.0
    return 20.0 * math.log10(rms / 32768.0)


def meter_level(db: float) -> float:
    """dBFS → 0.0〜1.0。画面の音量バー用。"""
    if db <= METER_MIN_DB:
        return 0.0
    if db >= METER_MAX_DB:
        return 1.0
    return (db - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB)


class _WebrtcJudge:
    """webrtcvad による発話判定。入っていなければ生成に失敗する。"""

    def __init__(self, rate: int, frame_ms: int, aggressiveness: int) -> None:
        import webrtcvad  # type: ignore
        if frame_ms not in (10, 20, 30):
            raise ValueError("webrtcvad は 10/20/30ms フレームのみ")
        if rate not in (8000, 16000, 32000, 48000):
            raise ValueError("webrtcvad が扱えないサンプリングレート")
        self._vad = webrtcvad.Vad(aggressiveness)
        self._rate = rate

    def is_speech(self, frame: bytes, db: float, floor: float) -> bool:
        try:
            return bool(self._vad.is_speech(frame, self._rate))
        except Exception:
            return db > floor + 9.0


class _EnergyJudge:
    """暗騒音に追従するエネルギー判定。追加依存なしの既定エンジン。

    無音が続く間だけノイズフロアを更新する。発話中に更新すると、長く話すほど
    しきい値が持ち上がって語尾が切れてしまう。
    """

    def __init__(self, floor_db: float, adapt: float, speech_margin: float, silence_margin: float) -> None:
        self.floor = floor_db
        self._adapt = adapt
        self._speech_margin = speech_margin
        self._silence_margin = silence_margin

    def is_speech(self, frame: bytes, db: float, floor: float) -> bool:
        return db > self.floor + self._speech_margin

    def is_silence(self, db: float) -> bool:
        return db < self.floor + self._silence_margin

    def observe_silence(self, db: float) -> None:
        # 極端に小さい値(マイク断)には引っ張られないようにする
        if db > -95.0:
            self.floor = self.floor * (1.0 - self._adapt) + db * self._adapt


def record_utterance(
    stream: capture.Stream,
    *,
    max_record_sec: float | None = None,
    silence_sec: float | None = None,
    on_level: Callable[[float, float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_speech_start: Callable[[], None] | None = None,
    now: Callable[[], float] = time.monotonic,
) -> AudioSegment:
    """1 項目ぶんの発話を録る。

    on_level(level 0..1, db) は 1 フレームごとに呼ばれる。画面の音量バー用。
    should_cancel() が真になったら即座に打ち切る(「キャンセル」ボタン)。
    should_stop() が真になったらそこまでを発話として確定する(「入力を終了」ボタン)。
    """
    rate = int(settings.get("audio.sample_rate"))
    frame_ms = int(settings.get("vad.frame_ms"))
    frame_bytes = int(rate * frame_ms / 1000) * capture.SAMPLE_WIDTH
    start_timeout = float(settings.get("vad.start_timeout_sec"))
    # 一文をまとめて話すときは文の途中で間が空くので、項目ごとに長さを変えられる。
    silence_sec = float(silence_sec if silence_sec is not None else settings.get("vad.silence_sec"))
    max_sec = float(max_record_sec if max_record_sec is not None else settings.get("vad.max_record_sec"))
    pre_roll_frames = max(0, int(float(settings.get("vad.pre_roll_ms")) / frame_ms))
    post_roll_frames = max(0, int(float(settings.get("vad.post_roll_ms")) / frame_ms))
    guard_ms = float(settings.get("audio.start_guard_ms"))
    gain = float(settings.get("audio.input_gain"))

    judge_energy = _EnergyJudge(
        float(settings.get("vad.noise_floor_init_db")),
        float(settings.get("vad.noise_floor_adapt")),
        float(settings.get("vad.speech_margin_db")),
        float(settings.get("vad.silence_margin_db")),
    )
    judge = judge_energy
    engine = str(settings.get("vad.engine") or "auto").lower()
    if engine in ("webrtc", "auto"):
        try:
            judge = _WebrtcJudge(rate, frame_ms, int(settings.get("vad.webrtc_aggressiveness")))
        except Exception:
            if engine == "webrtc":
                log.info("[voice] webrtcvad を使えないのでエネルギーVADにする")
            judge = judge_energy

    pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames or 1)
    voiced: list[bytes] = []
    tail: deque[bytes] = deque(maxlen=post_roll_frames or 1)

    started = now()
    speech_started_at: float | None = None
    silence_run = 0.0
    speech_ms = 0
    peak_db = -100.0
    stop_reason: StopReason = "no_speech"
    guard_until = started + guard_ms / 1000.0

    # フレームが届かない事態(マイクが刺さっているのに無音のまま)でも、
    # 全体の待ち時間で必ず抜ける。
    hard_deadline = started + start_timeout + max_sec + 2.0

    while True:
        if should_cancel is not None and should_cancel():
            stop_reason = "cancelled"
            break

        frame = stream.read(frame_bytes, timeout=max(0.2, frame_ms / 1000.0 * 4))
        t = now()
        if t > hard_deadline:
            stop_reason = "max_duration" if speech_started_at is not None else "no_speech"
            break
        if len(frame) < frame_bytes:
            # 取りこぼし。無音として扱い、次のフレームを待つ。
            if not frame:
                continue
            frame = frame + b"\x00" * (frame_bytes - len(frame))

        if gain != 1.0:
            frame = capture.apply_gain(frame, gain)

        db = dbfs(frame)
        if db > peak_db:
            peak_db = db

        # 受付開始音の回り込み対策(§9)。頭の数百 ms は捨てて判定にも使わない。
        if t < guard_until:
            if on_level is not None:
                on_level(0.0, db)
            continue

        if on_level is not None:
            on_level(meter_level(db), db)

        speaking = judge.is_speech(frame, db, judge_energy.floor)

        if speech_started_at is None:
            # ── まだ話し始めていない ──
            # ここでも「入力を終了」を見る。話す前に押されたときに、発話開始待ちの
            # 5 秒を待たせてしまうと、画面のボタンが効かないように見える。
            if should_stop is not None and should_stop():
                stop_reason = "no_speech"
                break
            pre_roll.append(frame)
            if speaking:
                speech_started_at = t
                voiced.extend(pre_roll)
                pre_roll.clear()
                voiced.append(frame)
                speech_ms += frame_ms
                silence_run = 0.0
                if on_speech_start is not None:
                    on_speech_start()
            else:
                judge_energy.observe_silence(db)
                if t - started >= start_timeout + guard_ms / 1000.0:
                    stop_reason = "no_speech"
                    break
            continue

        # ── 発話中 ──
        if should_stop is not None and should_stop():
            voiced.extend(tail)
            stop_reason = "manual"
            break

        if speaking:
            if tail:
                voiced.extend(tail)
                tail.clear()
            voiced.append(frame)
            speech_ms += frame_ms
            silence_run = 0.0
        else:
            # 語間の短い無音は捨てずに後ろへ溜める(「た・なか」で切らないため)
            tail.append(frame)
            silence_run += frame_ms / 1000.0
            judge_energy.observe_silence(db)
            if silence_run >= silence_sec:
                voiced.extend(list(tail)[:post_roll_frames])
                stop_reason = "silence"
                break

        if t - speech_started_at >= max_sec:
            voiced.extend(tail)
            stop_reason = "max_duration"
            break

    pcm = b"".join(voiced)
    total_ms = int((now() - started) * 1000)
    return AudioSegment(
        pcm=pcm,
        sample_rate=rate,
        total_ms=total_ms,
        speech_ms=speech_ms,
        stop_reason=stop_reason,
        peak_db=round(peak_db, 1),
        noise_floor_db=round(judge_energy.floor, 1),
    )
