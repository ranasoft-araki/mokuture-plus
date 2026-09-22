"""マイクからの録音(16kHz / モノラル / 16bit PCM)。

要件 §10 により、マイクを握るのはブラウザではなくこのサービス。Raspberry Pi OS に
最初から入っている `arecord`(alsa-utils)をサブプロセスで回して生 PCM を読む。

バックエンドは 4 つ:
  arecord      …… 既定。Pi 実機。追加の Python 依存が要らない
  sounddevice  …… Windows 開発機での動作試験。PortAudio 経由でマイクを開く
  file         …… WAV を「マイクから入ってきた音」として流す。マイクが無くても
                   録音ループから認識までを本番と同じ経路で通せる(何度でも同じ結果)
  none         …… どれも使えない環境。available() が False を返し、画面には
                   「音声で入力」ボタンが出ない = 受付は従来どおり動く

`auto` は arecord → sounddevice の順に探す。Windows には arecord が無いので、
`pip install sounddevice` さえ入っていれば自動で sounddevice を選ぶ。

読み出しは背景スレッド + キュー。arecord が無言でハングしてもタイムアウトで
抜けられるようにするため(ブロッキング read だと録音が終わらなくなる)。

録音した PCM はメモリ上にだけ置く。ファイルには書かない(§11)。
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import struct
import subprocess
import threading
import time
import wave
from array import array
from pathlib import Path
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
    """PortAudio 経由。arecord が無い環境（Windows 開発機）で使う。

    デバイス指定は sounddevice の流儀に合わせる。数字なら装置番号、文字列なら名前の
    部分一致。`default` / 空 なら OS の既定入力。
    """

    def __init__(self, device: str, rate: int, channels: int) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as e:
            raise CaptureUnavailable("sounddevice が入っていません (pip install sounddevice)") from e
        try:
            self._stream = sd.RawInputStream(
                samplerate=rate, channels=channels, dtype="int16",
                device=parse_device(device),
                blocksize=0,
            )
            self._stream.start()
        except Exception as e:
            raise CaptureFailed(f"マイクを開けません: {type(e).__name__}: {e}") from e

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


def parse_device(device: str):
    """設定の device 文字列を sounddevice へ渡せる形にする。

    数字だけなら装置番号として整数で渡す（名前が日本語で環境によって化けるため、
    番号指定が確実）。"default" と空文字は OS の既定入力（None）。
    """
    name = (device or "").strip()
    if not name or name.lower() == "default":
        return None
    if name.isdigit():
        return int(name)
    return name


# ── WAV をマイクの代わりに流す ────────────────────────────────────────────────

class FileStream:
    """WAV ファイルを「マイクから入ってきた音」として流す。

    マイクが無い環境でも、録音ループ(VAD)から認識・整形・判定までを**本番と同じ経路**で
    通せる。同じ音源なら毎回同じ結果になるので、しきい値を触ったときの比較にも使える。

    実時間で刻む（本物のマイクと同じ速さで届く）。VAD には実時間で効く判定（開始音の
    ガード・発話開始待ち）があるので、一気に流し込むとそれらを通過できない。
    音が尽きたあとは無音を流し続け、通常どおり「無音で終了」に入る。
    """

    def __init__(self, path: Path, rate: int) -> None:
        self._pcm = read_wav_as_pcm(path, rate)
        self._pos = 0
        self._rate = rate
        self._t0: float | None = None
        self._delivered = 0
        self.closed = False

    def read(self, nbytes: int, timeout: float) -> bytes:
        if self._t0 is None:
            self._t0 = time.monotonic()
        due = self._t0 + (self._delivered + nbytes) / (self._rate * SAMPLE_WIDTH)
        wait = due - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, max(timeout, 0.0)))
        self._delivered += nbytes

        if self._pos >= len(self._pcm):
            return b"\x00" * nbytes
        out = self._pcm[self._pos:self._pos + nbytes]
        self._pos += len(out)
        if len(out) < nbytes:
            out = out + b"\x00" * (nbytes - len(out))
        return out

    def close(self) -> None:
        self.closed = True
        self._pcm = b""


def read_wav_as_pcm(path: Path, rate: int) -> bytes:
    """WAV を 16bit・モノラル・指定サンプリングレートの PCM にして返す。

    録音した音源をそのまま使えるよう、多チャンネルは平均してモノラル化し、
    レートが違えば線形補間で合わせる（外部ライブラリを増やさないための簡易版。
    動作試験には十分で、本番の経路では使わない）。
    """
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != SAMPLE_WIDTH:
            raise CaptureFailed(
                f"16bit の WAV を指定してください（このファイルは {w.getsampwidth() * 8}bit）"
            )
        channels = w.getnchannels()
        src_rate = w.getframerate()
        raw = w.readframes(w.getnframes())

    samples = array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % SAMPLE_WIDTH)])

    if channels > 1:
        mono = array("h", [0]) * (len(samples) // channels)
        for i in range(len(mono)):
            chunk = samples[i * channels:(i + 1) * channels]
            mono[i] = int(sum(chunk) / channels)
        samples = mono

    if src_rate != rate and samples:
        ratio = src_rate / rate
        out_len = int(len(samples) / ratio)
        resampled = array("h", [0]) * out_len
        for i in range(out_len):
            pos = i * ratio
            left = int(pos)
            frac = pos - left
            right = min(left + 1, len(samples) - 1)
            resampled[i] = int(samples[left] * (1 - frac) + samples[right] * frac)
        samples = resampled

    return samples.tobytes()


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
        return _probe_sounddevice()
    if backend == "file":
        path = _file_path()
        if path is None:
            return False, "audio.file_path が未設定です (動作試験用の WAV を指定してください)"
        if not path.exists():
            return False, f"音源が見つかりません ({path.name})"
        return True, f"file ({path.name}) — 動作試験用。マイクは使いません"
    return False, "録音手段がありません (arecord も sounddevice も無い)"


def _probe_sounddevice() -> tuple[bool, str]:
    """入力デバイスが 1 つでもあるか確かめる。import が通るだけでは足りない。"""
    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        return False, "sounddevice が入っていません (pip install sounddevice)"
    try:
        wanted = parse_device(str(settings.get("audio.device") or ""))
        info = sd.query_devices(wanted, "input")
    except Exception as e:
        return False, f"入力デバイスが見つかりません ({type(e).__name__})"
    name = info.get("name", "?") if isinstance(info, dict) else "?"
    return True, f"sounddevice ({name})"


def _file_path() -> Path | None:
    raw = str(settings.get("audio.file_path") or "").strip()
    if not raw:
        return None
    return settings.resolve_path(raw)


# `arecord` の出力は端末の表示言語に翻訳される。日本語の Pi では見出しが
# 「カード 0: ...」になり、英語の "card" を探す判定が必ず外れる = マイクが
# 挿さっていても「録音デバイスが見つかりません」になる。機械で読む呼び出しは
# ロケールを C に固定し、翻訳されない出力を読む。
# (キオスク本体の /devices は main.py が「card|カード」両方を拾っている。
#  そちらで OK に見えるのにここだけ false、という食い違いはこれが原因だった)
_LOCALE_C_ENV = {**os.environ, "LC_ALL": "C", "LANGUAGE": "C"}


def _probe_arecord() -> tuple[bool, str]:
    """入力デバイスが 1 つでも見えるか確認する。"""
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True,
                           timeout=5, env=_LOCALE_C_ENV)
    except Exception as e:
        return False, f"arecord を実行できません: {type(e).__name__}"
    if r.returncode != 0 or "card" not in r.stdout:
        return False, "録音デバイスが見つかりません (USB マイクの接続を確認)"
    return True, "arecord (device=" + str(settings.get("audio.device")) + ")"


def list_devices() -> list[str]:
    """設定に書ける入力デバイス名の一覧。マイク選択手順で使う。

    arecord なら `arecord -L` の名前、sounddevice なら「番号: 名前」を返す
    （番号で指定するほうが確実。名前は環境によって化ける）。
    """
    backend = _backend()
    if backend == "sounddevice":
        try:
            import sounddevice as sd  # type: ignore

            out: list[str] = []
            for i, d in enumerate(sd.query_devices()):
                if int(d.get("max_input_channels", 0)) > 0:
                    out.append(f"{i}: {d.get('name', '?')}")
            return out[:40]
        except Exception:
            return []
    if backend != "arecord":
        return []
    try:
        r = subprocess.run(["arecord", "-L"], capture_output=True, text=True,
                           timeout=5, env=_LOCALE_C_ENV)
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
            if backend == "file":
                path = _file_path()
                if path is None or not path.exists():
                    raise CaptureUnavailable("動作試験用の音源(audio.file_path)がありません")
                return FileStream(path, rate)
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
