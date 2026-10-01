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
import threading
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
    しきい値が持ち上がって語尾が切れてしまう。話し始める前の見積もりは _FloorTracker。
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


class _NoiseHistory:
    """話し始める前に聞いた音(dBFS)の履歴。画面が選択を待つ間は数秒おきに窓を開け直すので、
    窓ごとに測り直さず持ち回る。窓の頭だけで測ると、開けた瞬間にもう話している人の声を
    暗騒音と取り違える。

    セッションは最大 4 つあり、それぞれのワーカーが録音ループを回しうるので、鍵を掛けて
    読み書きする(確かめてから読むまでの間に別の窓が消すと、空の履歴を読んで落ちる)。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dbs: deque[float] = deque()
        self._updated_at = 0.0

    def begin(self, frames: int, memory_sec: float) -> None:
        """窓を開けた。長さが変わったか、しばらく聞いていなければ測り直す。"""
        with self._lock:
            if self._dbs.maxlen != frames or time.monotonic() - self._updated_at > memory_sec:
                self._dbs = deque(maxlen=frames)

    def add(self, db: float) -> None:
        with self._lock:
            self._dbs.append(db)
            self._updated_at = time.monotonic()

    def median(self, minimum: int = 3) -> float | None:
        with self._lock:
            values = sorted(self._dbs)
        if len(values) < minimum:
            return None
        return values[len(values) // 2]

    def clear(self) -> None:
        with self._lock:
            self._dbs.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._dbs)


_bg_history = _NoiseHistory()
# 暗騒音をまだ測れていない(履歴が無い)ときは、この長さの音を測るまで判定しない。
# 測る前に判定すると、うるさい場所では最初のコマで話し始めになる。**経過時間ではなく、
# 受け取った本物の音(0 埋めでないコマ)の長さで数える**。録音の立ち上がりが遅れて最初の音が
# ガードの後に届いたり、マイクが開いた直後に 0 を返したりすると、経過時間やコマ数では
# 1 コマも測らずに判定を始めてしまう。
_MIN_MEASURE_MS = 100.0
# ノイズゲート付きのマイク(無音を 0 で返す)の見分け。**音が鳴ったあとに 0 がこれだけ続いた**
# のを一度でも見たら覚えておき(_zero_gate_seen)、以後は 0 がこれだけ続いた窓を「静かな部屋」と
# みなして、測らずに固定の初期値(noise_floor_init_db)以下で判定する。0 を数えないだけだと、
# 話す前がずっと 0 のマイクでは履歴が育たず、毎回声の頭を暗騒音として測って声を拾えない
# (合成音声で 176/180 → 15/180)。
# **窓の頭の 0 だけでは決めない。** マイクが開いた直後だけ 0 を返す機材だと、うるさい部屋でも
# 「静かな部屋」になって元の打ち切りに戻り、窓ごとに繰り返す。ゲートのマイクでも、起動後に
# 一度ゲートが閉じるのを見るまで(たいていは最初の発話の後)は測ってから判定する。
_ZERO_ROOM_MS = 300.0
_zero_gate_seen = False


def forget_noise_floor() -> None:
    """持ち回っている暗騒音の履歴と、マイクの見分けを捨てる(試験用・マイクを替えたとき)。"""
    global _zero_gate_seen
    _bg_history.clear()
    _zero_gate_seen = False


class _FloorTracker:
    """話し始める前の音から暗騒音を見積もる。

    **固定の初期値(-55 dBFS)から判定を始めてはいけない。** それより 9dB 以上うるさい場所
    (空調・人の多いロビー)では、窓を開けた最初の 1 コマが「話し始め」になり、
    話していると判定している間は暗騒音を学ばないので、そのまま 3 秒の上限で切れる。
    来訪者がいつ話しても、録音は窓を開けた時刻から 3 秒で切れていた(実機で
    「話している最中に認識が始まる」)。

    見積もりは直近の音(開始音ガードの間も含む)の**中央値**。下のほうの値だと、近くの
    雑談の息継ぎの静けさを拾って低く出る。**話し始めになったコマは入れない**(入れると
    話し始めた途端に見積もりが声へ寄り、話し始めにならない)ので、onset の判定が済むまで
    手前に置いてから足す(pending)。
    """

    def __init__(self, frames: int, hold: int) -> None:
        _bg_history.begin(max(3, frames), float(settings.get("vad.noise_floor_memory_sec")))
        self._hold = hold
        self._pending: deque[float] = deque()

    def add(self, db: float, *, hold: bool = True) -> None:
        """聞いた音を足す。hold=True のコマは話し始めの判定が済むまで見積もりに入れない。"""
        if db <= -95.0:                     # マイク断・取りこぼしの 0 埋めは数えない
            return
        if not hold:
            _bg_history.add(db)
        else:
            self._pending.append(db)
            while len(self._pending) > self._hold:
                _bg_history.add(self._pending.popleft())

    def discard_pending(self) -> None:
        """話し始めになった。手前に置いていたコマは声なので捨てる。"""
        self._pending.clear()

    def estimate(self) -> float | None:
        return _bg_history.median()

    def forget(self) -> None:
        """上限まで声が続いた = 暗騒音を低く見積もっていたかもしれない。次の窓は測り直す。"""
        _bg_history.clear()
        self._pending.clear()


def record_utterance(
    stream: capture.Stream,
    *,
    max_record_sec: float | None = None,
    silence_sec: float | None = None,
    start_timeout_sec: float | None = None,
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
    global _zero_gate_seen
    rate = int(settings.get("audio.sample_rate"))
    frame_ms = int(settings.get("vad.frame_ms"))
    frame_bytes = int(rate * frame_ms / 1000) * capture.SAMPLE_WIDTH
    # 画面操作のキーワードは「画面が選択を待っている間」ずっと聞くので、項目入力より長く待つ。
    start_timeout = float(start_timeout_sec if start_timeout_sec is not None
                          else settings.get("vad.start_timeout_sec"))
    # 一文をまとめて話すときは文の途中で間が空くので、項目ごとに長さを変えられる。
    silence_sec = float(silence_sec if silence_sec is not None else settings.get("vad.silence_sec"))
    max_sec = float(max_record_sec if max_record_sec is not None else settings.get("vad.max_record_sec"))
    pre_roll_frames = max(0, int(float(settings.get("vad.pre_roll_ms")) / frame_ms))
    post_roll_frames = max(0, int(float(settings.get("vad.post_roll_ms")) / frame_ms))
    guard_ms = float(settings.get("audio.start_guard_ms"))
    gain = float(settings.get("audio.input_gain"))

    init_floor = float(settings.get("vad.noise_floor_init_db"))
    judge_energy = _EnergyJudge(
        init_floor,
        float(settings.get("vad.noise_floor_adapt")),
        float(settings.get("vad.speech_margin_db")),
        float(settings.get("vad.silence_margin_db")),
    )
    # 話し始めは「直近 onset_window コマのうち onset_frames コマ以上が声らしい大きさ(暗騒音
    # ＋silence_margin_db)で、そのどこかで声の大きさ(＋speech_margin_db)を越えた」で決める。
    # 1 コマ(20ms)で決めると、ドア・足音・咳・机を叩く音で録音が始まる。かといって
    # 「声の大きさが 0.1 秒」を求めると、少し離れて話した声(判定ラインすれすれ)で始まらず、
    # 実機で「かなりマイクに近づかないと認識しない」になった(合成音声で、空調音の中の
    # 小さめの声が 12/12 → 6/12。この形で 12/12 に戻る)。
    onset_frames = max(1, int(round(float(settings.get("vad.onset_ms")) / frame_ms)))
    onset_window = onset_frames * 2
    onset_repeat = max(0, int(settings.get("vad.onset_repeat_frames")))
    floor_track = _FloorTracker(int(float(settings.get("vad.noise_floor_window_ms")) / frame_ms), onset_window)
    judge = judge_energy
    engine = str(settings.get("vad.engine") or "auto").lower()
    if engine in ("webrtc", "auto"):
        try:
            judge = _WebrtcJudge(rate, frame_ms, int(settings.get("vad.webrtc_aggressiveness")))
        except Exception:
            if engine == "webrtc":
                log.info("[voice] webrtcvad を使えないのでエネルギーVADにする")
            judge = judge_energy

    # 話し始めと判定するまでに溜めたコマも残す(判定を待つぶん語頭が欠けないように)。
    pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames + onset_window)
    recent: deque[bool] = deque(maxlen=onset_window)     # 声らしい大きさ(＋silence_margin_db)
    peaks: deque[bool] = deque(maxlen=onset_window)      # 声の大きさ(＋speech_margin_db)
    soft_margin = float(settings.get("vad.silence_margin_db"))
    voiced: list[bytes] = []
    # 話し終わりかもしれない無音を溜めておく。話し終わりの判定(silence_sec)ぶんは全部持つ。
    # 以前は post_roll ぶんしか持たず、話し終わりに足す「声の直後の 0.25 秒」が実際には
    # 「無音の最後の 0.25 秒」になって、語尾の直後(0.46 秒ほど)が録音から抜けていた。
    tail: deque[bytes] = deque(maxlen=max(post_roll_frames, int(silence_sec * 1000 / frame_ms) + 1, 1))

    started = now()
    speech_started_at: float | None = None
    silence_run = 0.0
    speech_ms = 0
    peak_db = -100.0
    stop_reason: StopReason = "no_speech"
    guard_until = started + guard_ms / 1000.0
    # 履歴が無ければ、本物の音をこのコマ数だけ測ってから判定する(_MIN_MEASURE_MS)。
    min_measure_frames = max(1, int(round(_MIN_MEASURE_MS / frame_ms)))
    measure_left = min_measure_frames if floor_track.estimate() is None else 0
    zero_room_frames = max(1, int(round(_ZERO_ROOM_MS / frame_ms)))
    zero_run = 0
    heard_sound = False      # この窓で 0 でない音を受け取ったか
    gated = False            # 無音を 0 で返すマイクの静かな部屋(_ZERO_ROOM_MS)。この窓では測らない

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
        if db > -95.0:
            zero_run = 0
            heard_sound = True
        else:
            zero_run += 1
            if zero_run >= zero_room_frames:
                if heard_sound:
                    _zero_gate_seen = True       # 音のあとに 0 へ戻った = ノイズゲートのマイク
                if _zero_gate_seen:
                    gated = True

        # 受付開始音の回り込み対策(§9)。頭の数百 ms は発話の判定に使わない。
        # その間の音も暗騒音の見積もりには入れる(_FloorTracker)。
        if t < guard_until:
            floor_track.add(db, hold=False)
            if db > -95.0:
                measure_left -= 1
            if on_level is not None:
                on_level(0.0, db)
            continue

        if on_level is not None:
            on_level(meter_level(db), db)

        if speech_started_at is None:
            est = floor_track.estimate()
            if est is None and measure_left <= 0 and not gated:
                measure_left = min_measure_frames      # 別の窓が履歴を消した。測り直す
            if measure_left > 0 and not gated:
                # まだ暗騒音を測っている(_MIN_MEASURE_MS)。判定には使わない。
                if should_stop is not None and should_stop():
                    stop_reason = "no_speech"
                    break
                floor_track.add(db, hold=False)
                if db > -95.0:
                    measure_left -= 1
                # 測ったコマも語頭の手前として残す(音源がすぐ話し始めると、ここに語頭が入る)。
                pre_roll.append(frame)
                recent.append(False)
                peaks.append(False)
                if t - started >= start_timeout + guard_ms / 1000.0:
                    stop_reason = "no_speech"
                    break
                continue
            if gated:
                # 無音が 0 の部屋。履歴に声の頭を覚えていても、初期値より高くは見積もらない。
                judge_energy.floor = init_floor if est is None else min(est, init_floor)
            elif est is not None:
                judge_energy.floor = est
        speaking = judge.is_speech(frame, db, judge_energy.floor)

        if speech_started_at is None:
            # ── まだ話し始めていない ──
            # ここでも「入力を終了」を見る。話す前に押されたときに、発話開始待ちの
            # 5 秒を待たせてしまうと、画面のボタンが効かないように見える。
            if should_stop is not None and should_stop():
                stop_reason = "no_speech"
                break
            pre_roll.append(frame)
            soft = speaking or (judge is judge_energy and db > judge_energy.floor + soft_margin)
            recent.append(soft)
            peaks.append(speaking)
            # 声らしいコマは暗騒音に入れない。入れると、話し始めにならなかった小さめの声で
            # 見積もりが上がり、言い直すほど大きな声が要るようになる。
            if not soft:
                floor_track.add(db)
            if sum(recent) >= onset_frames and any(peaks):
                floor_track.discard_pending()
                speech_started_at = t
                # 頭に残すのは「最初に声と判定したコマ」の pre_roll 前から。判定を待ったぶん
                # まで残すと頭の無音が長くなり、短い数字(「にばん」の「に」)が頭の雑音に
                # 吸われて信頼度が落ちる(頭 0.25 秒で 0.81 → 0.45 秒で 0.53)。
                held = list(pre_roll)
                first = len(held) - len(recent) + list(recent).index(True)
                voiced.extend(held[max(0, first - pre_roll_frames):first + 1])
                # 最初に声と判定したコマを重ねて、語頭を少し引き延ばす(onset_repeat_frames)。
                # 1 拍の数字は頭の子音が短く、頭の雑音に吸われる。直す前の録音ループは
                # 書き間違いでこのコマを 2 回入れていて、それで数字が当たっていた(外すと
                # 「五」0.79 → 0.65)。雑音を重ねたロッカー番号 672 本で 468 → 473・にばん 37 → 44/96。
                voiced.extend([held[first]] * onset_repeat)
                voiced.extend(held[first + 1:])
                pre_roll.clear()
                speech_ms += sum(recent) * frame_ms
                silence_run = 0.0
                if on_speech_start is not None:
                    on_speech_start()
            elif t - started >= start_timeout + guard_ms / 1000.0:
                stop_reason = "no_speech"
                break
            continue

        # ── 発話中 ──
        if should_stop is not None and should_stop():
            voiced.extend(tail)
            stop_reason = "manual"
            break

        # 話し終わりは低いほうの線(＋silence_margin_db)で見る。始まりは高い線、終わりは低い線
        # (ヒステリシス)。高い線(＋speech_margin_db)のままだと、小さめの声が続く間を無音と数えて
        # 途中で「話し終わり」になり、溜めきれない声(tail を越えたぶん)も録音から落ちる。
        still_voice = speaking or (judge is judge_energy and not judge_energy.is_silence(db))
        if still_voice:
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
            # 話している最中は、本当に静かなコマ(＋silence_margin_db 未満)だけで暗騒音を追う。
            # 小さめの声まで入れると、話している間に判定ラインが上がっていく。
            if judge_energy.is_silence(db):
                judge_energy.observe_silence(db)
            if silence_run >= silence_sec:
                voiced.extend(list(tail)[:post_roll_frames])
                stop_reason = "silence"
                break

        if t - speech_started_at >= max_sec:
            voiced.extend(tail)
            stop_reason = "max_duration"
            break

    if stop_reason == "max_duration":
        floor_track.forget()
        if gated:
            # 0 の部屋とみなした窓が上限まで鳴り続けた = ゲートの見分けが外れていた(ミュートや
            # USB の瞬断で一度だけ 0 が出た等)。覚えたままだと、開いた直後に 0 を返す機材で
            # うるさい部屋のとき元の打ち切りに戻るので、見分け直す。
            _zero_gate_seen = False

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
