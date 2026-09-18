"""whisper.cpp 連携(会社名・訪問者名の認識)。

事前登録されていない社名・氏名を拾う必要があるため、語彙を限定しない whisper.cpp を
使う(§3-1)。バイナリ(`whisper-cli`)をサブプロセスで呼び、JSON を読んで捨てる。

モデルは設定で差し替えられる(§3-1):
    voice_input.yaml の whisper.model_path / whisper.model_name
    環境変数 VOICE_WHISPER__MODEL_PATH / VOICE_WHISPER__MODEL_NAME

一時ファイルの扱い(§11):
  - whisper-cli は WAV ファイルのパスを受け取る API なので、音声を一度ディスクに
    置く必要がある。置き先は既定で tmpfs の `/dev/shm`(RAM 上)にして、認識・
    キャンセル・タイムアウトのいずれでも finally で必ず消す。永続化はしない。
  - 認識結果の JSON も同じ場所に出て、読んだ直後に消す。

確信度について(§7):
  whisper.cpp の JSON(`-ojf`)が返すのはトークンごとの確率 `p` だけで、no-speech 確率は
  含まれない。ここでは取れたものだけを Transcript に入れ、取れないものは None のまま
  返す。無理に数値化せず、判断は `quality.py` が複数の手がかりを合わせて行う。
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from voice import capture, settings
from voice.types import AudioSegment, Transcript

log = logging.getLogger(__name__)

ENGINE_NAME = "whisper"

# JSON に混ざる特別トークン([_BEG_] など)。確信度の平均から除く。
_SPECIAL_TOKEN = re.compile(r"^\s*\[[^\]]*\]\s*$")


class EngineUnavailable(RuntimeError):
    """バイナリかモデルが無い。機能を出さないだけで、受付は続けられる。"""


class EngineTimeout(RuntimeError):
    """認識が制限時間内に終わらなかった(§7 のタイムアウト)。"""


class EngineFailed(RuntimeError):
    """whisper-cli が異常終了した。"""


def binary_path() -> Path:
    """使う whisper-cli の場所。OS で持ち替える。

    本番(Pi)は install_voice.sh がソースからビルドしたもの、Windows は上流の配布
    バイナリ(同じ版)。同じ設定ファイルを両方で使えるよう、キーを分けてある。
    """
    if platform.system() == "Windows":
        win = str(settings.get("whisper.binary_windows") or "").strip()
        if win:
            return settings.resolve_path(win)
    return settings.resolve_path(str(settings.get("whisper.binary")))


def model_path() -> Path:
    return settings.resolve_path(str(settings.get("whisper.model_path")))


def model_name() -> str:
    return str(settings.get("whisper.model_name"))


def available() -> tuple[bool, str]:
    """(使えるか, 理由)。理由に個人情報は含まない。"""
    b = binary_path()
    if not b.exists():
        how = ("scripts/install_voice_windows.ps1 を実行"
               if platform.system() == "Windows" else "scripts/install_voice.sh を実行")
        return False, f"whisper-cli がありません ({b.name}: {how})"
    if not os.access(b, os.X_OK):
        return False, "whisper-cli に実行権限がありません"
    m = model_path()
    if not m.exists():
        return False, f"モデルがありません ({m.name})"
    return True, f"{model_name()} ({m.name})"


def describe() -> dict:
    ok, detail = available()
    return {
        "engine": ENGINE_NAME,
        "available": ok,
        "detail": detail,
        "model": model_name(),
        "model_file": model_path().name,
        "threads": int(settings.get("whisper.threads")),
        "timeout_sec": float(settings.get("whisper.timeout_sec")),
    }


def _tmp_dir() -> Path:
    """音声と JSON の置き場。既定は tmpfs(RAM)。無ければ OS の一時領域。"""
    want = Path(str(settings.get("whisper.tmp_dir")))
    if want.is_dir() and os.access(want, os.W_OK):
        return want
    return Path(tempfile.gettempdir())


def _build_cmd(wav: Path, out_base: Path) -> list[str]:
    cmd = [
        str(binary_path()),
        "-m", str(model_path()),
        "-f", str(wav),
        "-l", str(settings.get("whisper.language")),
        "-t", str(int(settings.get("whisper.threads"))),
        "-bs", str(int(settings.get("whisper.beam_size"))),
        "-et", str(float(settings.get("whisper.entropy_thold"))),
        "-nth", str(float(settings.get("whisper.no_speech_thold"))),
        "-np",          # 進捗・システム情報を出さない
        "-nt",          # タイムスタンプ無しのテキスト
        "-ojf",         # トークン確率つき JSON
        "-of", str(out_base),
    ]
    if bool(settings.get("whisper.suppress_non_speech")):
        cmd.append("-sns")
    extra = settings.get("whisper.extra_args") or []
    cmd.extend(str(a) for a in extra)
    return cmd


def _parse(payload: dict) -> tuple[str, float | None]:
    """JSON からテキストと平均トークン確率を取り出す。"""
    segments = payload.get("transcription") or []
    texts: list[str] = []
    probs: list[float] = []
    for seg in segments:
        t = seg.get("text")
        if isinstance(t, str):
            texts.append(t)
        for tok in seg.get("tokens") or []:
            text = tok.get("text")
            p = tok.get("p")
            if not isinstance(p, (int, float)):
                continue
            if isinstance(text, str) and _SPECIAL_TOKEN.match(text):
                continue
            probs.append(float(p))
    avg = (sum(probs) / len(probs)) if probs else None
    return "".join(texts).strip(), avg


def transcribe(seg: AudioSegment) -> Transcript:
    """発話区間を認識する。呼び出し側は必ず seg.clear() で PCM を捨てること。"""
    ok, detail = available()
    if not ok:
        raise EngineUnavailable(detail)

    tmp = _tmp_dir()
    stem = f"mokuture-voice-{uuid.uuid4().hex}"
    wav = tmp / f"{stem}.wav"
    out_base = tmp / stem
    out_json = tmp / f"{stem}.json"
    timeout = float(settings.get("whisper.timeout_sec"))

    started = time.monotonic()
    try:
        wav.write_bytes(capture.to_wav(seg.pcm, seg.sample_rate))
        try:
            proc = subprocess.run(
                _build_cmd(wav, out_base),
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise EngineTimeout(f"{timeout:.0f} 秒で終わりませんでした") from e

        if proc.returncode != 0:
            # stderr は whisper.cpp のメッセージのみ。音声も認識結果も含まない。
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
            raise EngineFailed(" ".join(tail) or f"exit={proc.returncode}")

        if not out_json.exists():
            raise EngineFailed("認識結果の JSON が出力されませんでした")
        payload = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
        text, avg_prob = _parse(payload)
    finally:
        # 成功・失敗・タイムアウトのどれでも必ず消す(§11)
        for p in (wav, out_json):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                log.warning("[voice] 一時ファイルを消せませんでした (%s)", p.name)

    return Transcript(
        text=text,
        engine=ENGINE_NAME,
        model_name=model_name(),
        recognition_ms=int((time.monotonic() - started) * 1000),
        avg_token_prob=avg_prob,
        # whisper.cpp の JSON は no-speech 確率を返さない。取れないものは None のまま。
        no_speech_prob=None,
    )


def warmup() -> None:
    """モデルをページキャッシュに載せる。初回の待ち時間を減らすため。

    失敗しても無視する(使えないなら status が available=false を返す)。
    """
    ok, _ = available()
    if not ok:
        return
    rate = int(settings.get("audio.sample_rate"))
    silence = AudioSegment(
        pcm=b"\x00\x00" * rate,      # 1 秒の無音
        sample_rate=rate,
        total_ms=1000,
        speech_ms=0,
        stop_reason="silence",
        peak_db=-100.0,
        noise_floor_db=-100.0,
    )
    started = time.monotonic()
    try:
        transcribe(silence)
    except Exception as e:
        log.info("[voice] warmup skipped: %s", type(e).__name__)
        return
    finally:
        silence.clear()
    log.info("[voice] whisper warmed up in %.0fms (model=%s)",
             (time.monotonic() - started) * 1000, model_name())
