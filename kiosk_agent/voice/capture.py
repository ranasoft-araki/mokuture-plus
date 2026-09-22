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
import re
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
        _mark_recording(+1)

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
                    # 挿し替え・抜き差しでデバイスが変わったのかもしれない。
                    # 次の録音で選び直す。
                    forget_device()
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
        _mark_recording(-1)
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


# ── 録音デバイスの解決 ────────────────────────────────────────────────────────
# USB マイクのカード番号は固定できない。挿す位置・挿す順・起動時の認識順で変わるし、
# USB カメラのマイクのような別の録音デバイスが増えることもある。設定に番号を焼き
# 込むと、挿し直しただけで受付から音声入力が消える。
#
# そこで毎回「設定の指定 → 実際に短く録ってみる → 駄目なら見つかったデバイスを
# 順に試す」で決める。一覧に出るかどうかは当てにならない: この現場の `default` は
# asym プラグインで再生側しか定義されておらず(capture slave is not defined)、
# `arecord -l` には出るのに開くと EINVAL で落ちた。**開けるかは開いてみないと
# 分からない。**
#
# 決まった結果は覚えておき(テスト録音を毎回はやらない)、録音が止まったら忘れて
# 決め直す = 挿し替えに次の録音から追従する。
_DEVICE_TEST_SEC = 1
_FAIL_RETRY_SEC = 30.0                     # 開けなかったときに覚えておく時間
_resolved: tuple[str, str | None] | None = None   # (設定値, 実際に使うデバイス)
_resolved_at = 0.0
_resolve_lock = threading.RLock()
_recording = 0                             # 録音中はテスト録音をしない(奪い合う)


def _mark_recording(delta: int) -> None:
    global _recording
    with _resolve_lock:
        _recording = max(0, _recording + delta)


def forget_device() -> None:
    """次の録音でデバイスを決め直す(挿し替え・抜き差しへの追従)。"""
    global _resolved
    with _resolve_lock:
        _resolved = None


def _is_usb_card(card: int) -> bool:
    """USB の音声デバイスか。USB マイクを先に試すための優先度にだけ使う。"""
    return Path(f"/proc/asound/card{card}/usbid").exists()


def capture_devices() -> list[str]:
    """`arecord -l` に見えている録音デバイス。USB を先に返す。

    内蔵(HDMI 等)は録音できないか、録れても使い物にならないので後ろに回す。
    """
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True,
                           timeout=5, env=_LOCALE_C_ENV)
    except Exception:
        return []
    found: list[tuple[int, str]] = []
    for line in r.stdout.splitlines():
        m = re.match(r"card (\d+):.*?device (\d+):", line)
        if not m:
            continue
        card, dev = int(m.group(1)), int(m.group(2))
        # hw: ではなく plughw: を使う。USB マイクは 48kHz ステレオ固定のものが
        # 多く、16kHz モノラルへの変換を plug 層にやらせないと開けない。
        found.append((0 if _is_usb_card(card) else 1, f"plughw:{card},{dev}"))
    found.sort(key=lambda x: x[0])            # 安定ソート: 同じ優先度なら一覧の順
    return [d for _, d in found]


def _can_open(device: str, rate: int, channels: int) -> bool:
    """本当に録れるか、短く録って確かめる。"""
    cmd = ["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", str(rate),
           "-c", str(channels), "-t", "raw", "-d", str(_DEVICE_TEST_SEC)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=_DEVICE_TEST_SEC + 3,
                           env=_LOCALE_C_ENV)
    except Exception:
        return False
    return r.returncode == 0 and bool(r.stdout)


def resolve_device(*, probe: bool = True) -> str | None:
    """`arecord -D` に渡すデバイス。開けるものが無ければ None。

    設定(audio.device)の指定は必ず最初に試す。開ければそれを使う = 現場で名指し
    した設定は尊重される。開けないときだけ、見つかったデバイスへ自動で移る。
    """
    global _resolved, _resolved_at
    want = str(settings.get("audio.device") or "default").strip() or "default"
    with _resolve_lock:
        if _resolved is not None and _resolved[0] == want:
            # 開けなかったという結果も少しの間は覚えておく。画面は status を
            # 繰り返し引くので、毎回テスト録音を走らせるわけにいかない。
            if _resolved[1] is not None or time.monotonic() - _resolved_at < _FAIL_RETRY_SEC:
                return _resolved[1]
        if not probe or _recording:
            # 録音中は奪い合うので試さない。まだ決まっていなければ設定のまま。
            return want
        rate = int(settings.get("audio.sample_rate"))
        channels = int(settings.get("audio.channels"))
        order = [want] + [d for d in capture_devices() if d != want]
        for device in order:
            if not _can_open(device, rate, channels):
                continue
            if device != want:
                log.warning("[voice] 録音デバイスを %s にしました (設定: %s は開けません)",
                            device, want)
            _resolved, _resolved_at = (want, device), time.monotonic()
            return device
        _resolved, _resolved_at = (want, None), time.monotonic()
        return None


def _probe_arecord() -> tuple[bool, str]:
    """設定されたデバイスを実際に開けるかまで見る。

    一覧に出るかどうかだけを見ていると、画面には「使える」と出るのに「話す」を
    押した瞬間に落ちる、という一番たちの悪い形になる。
    """
    devices = capture_devices()
    if not devices:
        return False, "録音デバイスが見つかりません (USB マイクの接続を確認)"
    device = resolve_device()
    if device is None:
        return False, "録音デバイスを開けませんでした (" + ", ".join(devices[:3]) + ")"
    return True, f"arecord (device={device})"


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
    if backend == "arecord":
        # 設定の指定が開けるならそのまま、駄目なら挿さっているマイクへ移る。
        device = resolve_device() or device
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
