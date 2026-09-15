"""マイクからの録音(16kHz / モノラル / 16bit PCM)。

要件 §10 により、マイクを握るのはブラウザではなくこのサービス。Raspberry Pi OS に
最初から入っている `arecord`(alsa-utils)をサブプロセスで回して生 PCM を読む。

バックエンドは 3 つ:
  arecord      …… 既定。Pi 実機。追加の Python 依存が要らない
  sounddevice  …… 任意。入っていれば使える(PortAudio)
  none         …… どちらも無い環境(Windows 開発機など)。available() が False を返し、
                   画面には「音声で入力」ボタンが出ない = 受付は従来どおり動く

読み出しは背景スレッド + キュー。arecord が無言でハングしてもタイムアウトで
抜けられるようにするため(ブロッキング read だと録音が終わらなくなる)。

録音した PCM はメモリ上にだけ置く。ファイルには書かない(§11)。
"""
from __future__ import annotations

import logging
import queue
import shutil
import struct
import subprocess
import threading
from array import array
from typing import Callable, Protocol

from voice import settings

log = logging.getLogger(__name__)

# 16bit PCM の 1 サンプルあたりバイト数
SAMPLE_WIDTH = 2


class CaptureUnavailable(RuntimeError):
    """マイクの入口そのものが無い(コマンド未導入・デバイス未接続)。"""


class CaptureFailed(RuntimeError):
    """録音中に落ちた(デバイスが抜かれた・他プロセスが専有した等)。"""


class Stream(Protocol):
    def read(self, nbytes: int, timeout: float) -> bytes: ...
    def close(self) -> None: ...


# ── arecord ───────────────────────────────────────────────────────────────────

class ArecordStream:
    """arecord -t raw の標準出力を読み続ける。"""

    def __init__(self, device: str, rate: int, channels: int) -> None:
        cmd = [
            "arecord",
            "-q",                      # 進捗表示を出さない
            "-D", device,
            "-f", "S16_LE",
            "-r", str(rate),
            "-c", str(channels),
            "-t", "raw",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            )
        except FileNotFoundError as e:
            raise CaptureUnavailable("arecord が見つかりません") from e
        except OSError as e:
            raise CaptureFailed(f"arecord を起動できません: {type(e).__name__}") from e

        self._buf = bytearray()
        self._q: queue.Queue = queue.Queue(maxsize=256)
        self._closed = False
        self._err_tail: list[bytes] = []
        self._reader = threading.Thread(target=self._pump, name="voice-arecord", daemon=True)
        self._reader.start()
        self._errr = threading.Thread(target=self._pump_err, name="voice-arecord-err", daemon=True)
        self._errr.start()

    def _pump(self) -> None:
        out = self._proc.stdout
        if out is None:
            return
        try:
            while not self._closed:
                chunk = out.read(2048)
                if not chunk:
                    break
                try:
                    self._q.put(chunk, timeout=1.0)
                except queue.Full:
                    # 読み手が居ない(＝録音を終えた)。捨てて構わない。
                    pass
        except Exception:
            pass
        finally:
            try:
                self._q.put_nowait(None)      # EOF 印
            except queue.Full:
                pass

    def _pump_err(self) -> None:
        """arecord の stderr を少しだけ溜める(デバイス名の誤りを status に出すため)。

        中身は ALSA のメッセージだけで、音声も個人情報も含まない。
        """
        err = self._proc.stderr
        if err is None:
            return
        try:
            for line in err:
                self._err_tail.append(line.strip())
                del self._err_tail[:-4]
        except Exception:
            pass

    def read(self, nbytes: int, timeout: float) -> bytes:
        """ちょうど nbytes 返す。timeout 内に集まらなければ短いまま返す。"""
        remaining = timeout
        step = 0.05
        while len(self._buf) < nbytes and remaining > 0:
            try:
                chunk = self._q.get(timeout=min(step, remaining))
            except queue.Empty:
                remaining -= step
                continue
            if chunk is None:                 # arecord が終了した
                if not self._buf:
                    detail = b" / ".join(self._err_tail).decode("utf-8", "replace")
                    raise CaptureFailed(("録音が止まりました " + detail).strip())
                break
            self._buf.extend(chunk)
        out = bytes(self._buf[:nbytes])
        del self._buf[:nbytes]
        return out

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass
        for pipe in (self._proc.stdout, self._proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass
        self._buf.clear()


# ── sounddevice(任意) ────────────────────────────────────────────────────────

class SoundDeviceStream:
    """PortAudio 経由。arecord が使えない環境の予備。"""

    def __init__(self, device: str, rate: int, channels: int) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as e:
            raise CaptureUnavailable("sounddevice が入っていません") from e
        try:
            self._stream = sd.RawInputStream(
                samplerate=rate, channels=channels, dtype="int16",
                device=(None if device in ("", "default") else device),
                blocksize=0,
            )
            self._stream.start()
        except Exception as e:
            raise CaptureFailed(f"マイクを開けません: {type(e).__name__}") from e

    def read(self, nbytes: int, timeout: float) -> bytes:
        frames = nbytes // SAMPLE_WIDTH
        try:
            data, overflowed = self._stream.read(frames)
        except Exception as e:
            raise CaptureFailed(f"録音が止まりました: {type(e).__name__}") from e
        if overflowed:
            log.debug("[voice] input overflow")
        return bytes(data)

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


# ── テスト用 ──────────────────────────────────────────────────────────────────

class BufferStream:
    """あらかじめ用意した PCM を流す。単体テスト用。

    実機のマイクが無い環境でも VAD・整形・判定・API の流れを検証できるようにする。
    尽きたあとは無音を返し続けるので、VAD の「無音で終了」経路もそのまま通せる。

    `realtime=True` にすると、本物のマイクと同じように音の長さぶんだけ待って返す。
    録音ループには実時間で効く判定(開始音ガード・発話開始待ち)があるので、
    それらを通すテストではこちらを使う。VAD 単体のテストは時計を差し替えるので
    待つ必要がなく、既定は待たない。
    """

    def __init__(self, pcm: bytes, *, loop_silence: bool = True,
                 realtime: bool = False, sample_rate: int = 16000) -> None:
        self._pcm = pcm
        self._pos = 0
        self._loop_silence = loop_silence
        self._realtime = realtime
        self._rate = sample_rate
        self._t0: float | None = None
        self._delivered = 0
        self.closed = False

    def _pace(self, nbytes: int, timeout: float) -> None:
        import time
        if self._t0 is None:
            self._t0 = time.monotonic()
        due = self._t0 + (self._delivered + nbytes) / (self._rate * SAMPLE_WIDTH)
        wait = due - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, max(timeout, 0.0)))

    def read(self, nbytes: int, timeout: float) -> bytes:
        if self._realtime:
            self._pace(nbytes, timeout)
        self._delivered += nbytes
        if self._pos >= len(self._pcm):
            return b"\x00" * nbytes if self._loop_silence else b""
        out = self._pcm[self._pos:self._pos + nbytes]
        self._pos += len(out)
        if len(out) < nbytes and self._loop_silence:
            out = out + b"\x00" * (nbytes - len(out))
        return out

    def close(self) -> None:
        self.closed = True


# 差し替え口。テストはここに関数を入れて実マイクを迂回する。
_override: Callable[[], Stream] | None = None


def set_override(factory: Callable[[], Stream] | None) -> None:
    """録音ストリームの生成を差し替える(テスト専用)。None で元に戻す。"""
    global _override
    _override = factory


# ── 選択と可否 ────────────────────────────────────────────────────────────────

def _backend() -> str:
    want = str(settings.get("audio.backend") or "auto").lower()
    if want != "auto":
        return want
    if shutil.which("arecord"):
        return "arecord"
    try:
        import sounddevice  # type: ignore  # noqa: F401
        return "sounddevice"
    except ImportError:
        return "none"


def available() -> tuple[bool, str]:
    """(使えるか, 理由や状態の説明)。説明に個人情報は含まない。"""
    if _override is not None:
        return True, "test override"
    backend = _backend()
    if backend == "arecord":
        if not shutil.which("arecord"):
            return False, "arecord が見つかりません (sudo apt install alsa-utils)"
        return _probe_arecord()
    if backend == "sounddevice":
        try:
            import sounddevice  # type: ignore  # noqa: F401
        except ImportError:
            return False, "sounddevice が入っていません"
        return True, "sounddevice"
    return False, "録音手段がありません (arecord も sounddevice も無い)"


def _probe_arecord() -> tuple[bool, str]:
    """入力デバイスが 1 つでも見えるか確認する。"""
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
    except Exception as e:
        return False, f"arecord を実行できません: {type(e).__name__}"
    if r.returncode != 0 or "card" not in r.stdout:
        return False, "録音デバイスが見つかりません (USB マイクの接続を確認)"
    return True, "arecord (device=" + str(settings.get("audio.device")) + ")"


def list_devices() -> list[str]:
    """arecord -L の一覧。マイク選択手順(成果物 10)で使う。"""
    try:
        r = subprocess.run(["arecord", "-L"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    names: list[str] = []
    for line in r.stdout.splitlines():
        if line and not line.startswith(" "):
            names.append(line.strip())
    return names[:40]


def open_stream() -> Stream:
    """設定にしたがって録音ストリームを開く。"""
    if _override is not None:
        return _override()
    device = str(settings.get("audio.device") or "default")
    rate = int(settings.get("audio.sample_rate"))
    channels = int(settings.get("audio.channels"))
    backend = _backend()
    retries = max(0, int(settings.get("audio.open_retries")))

    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            if backend == "arecord":
                return ArecordStream(device, rate, channels)
            if backend == "sounddevice":
                return SoundDeviceStream(device, rate, channels)
            raise CaptureUnavailable("録音手段がありません")
        except CaptureFailed as e:
            last = e
            continue
    raise last if last is not None else CaptureUnavailable("録音手段がありません")


# ── PCM のユーティリティ ──────────────────────────────────────────────────────

def apply_gain(pcm: bytes, gain: float) -> bytes:
    """利得を掛ける。1.0 ならそのまま返す(コピーもしない)。"""
    if gain == 1.0 or not pcm:
        return pcm
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % SAMPLE_WIDTH)])
    for i, s in enumerate(samples):
        v = int(s * gain)
        samples[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
    return samples.tobytes()


def to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """16bit PCM を WAV(RIFF)にする。whisper.cpp へ渡すため。"""
    data_len = len(pcm)
    byte_rate = sample_rate * channels * SAMPLE_WIDTH
    block_align = channels * SAMPLE_WIDTH
    header = b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16)
    header += b"data" + struct.pack("<I", data_len)
    return header + pcm
