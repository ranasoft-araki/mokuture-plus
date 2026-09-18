"""音声入力の動作試験（Windows 開発機でも Raspberry Pi でも動く）。

録音 → VAD → whisper.cpp → 整形 → 採否判定 まで、**本番と同じ経路**を 1 往復させて
結果を表示する。サービスを起動しなくても、ここだけで中身を確かめられる。

    # まず状態だけ見る（マイク・バイナリ・モデルが揃っているか）
    .venv/Scripts/python scripts/voice_selftest.py --status

    # 合成音声で 1 往復（マイク不要。Windows の読み上げ機能で音源を作る）
    .venv/Scripts/python scripts/voice_selftest.py --say "株式会社ラナソフトです"

    # 手元の WAV で 1 往復（16bit なら何 Hz でも可。読み込み時に 16kHz へ直す）
    .venv/Scripts/python scripts/voice_selftest.py --wav sample.wav

    # 実際にマイクへ話しかけて 1 往復
    .venv/Scripts/python scripts/voice_selftest.py --mic

    # 画面から試す（サービスを起動して、キオスク画面の「音声で入力」を押す）
    .venv/Scripts/python -m voice.server

`--say` は Windows の音声合成(SAPI)で読み上げた音を使う。**合成音声は人の声より
認識しにくい**ので、ここで多少崩れても実際の精度とは別物と考えること。経路が通って
いるか・整形と判定が意図どおりかを見るためのもの。

認識したテキストは画面に出るだけで、どこにも保存しない。
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from voice import capture, quality, settings, textnorm, vad, whisper_cpp  # noqa: E402
from voice.types import message  # noqa: E402


def show_status() -> bool:
    """揃っているものと足りないものを並べる。全部そろっていれば True。"""
    print("== 音声入力の状態 ==")
    print(f"  OS            : {platform.system()} {platform.machine()}")

    mic_ok, mic_detail = capture.available()
    print(f"  マイク        : {'OK  ' if mic_ok else 'NG  '}{mic_detail}")
    if mic_ok:
        devices = capture.list_devices()
        if devices:
            print(f"                  入力デバイス {len(devices)} 件（--devices で一覧）")

    engine_ok, engine_detail = whisper_cpp.available()
    print(f"  whisper.cpp   : {'OK  ' if engine_ok else 'NG  '}{engine_detail}")
    print(f"                  {whisper_cpp.binary_path()}")
    print(f"  モデル        : {whisper_cpp.model_path()}")

    notes = settings.notes()
    if notes:
        print(f"  設定          : {' / '.join(notes)}")

    if not engine_ok and platform.system() == "Windows":
        print("\n  → whisper-cli が無い場合は次で用意できます:")
        print("     powershell -ExecutionPolicy Bypass -File scripts\\install_voice_windows.ps1")
    if not mic_ok and platform.system() == "Windows":
        print("\n  → マイクを使うには sounddevice が要ります:")
        print("     uv pip install --python .venv\\Scripts\\python.exe sounddevice")
        print("     マイクが無くても --say / --wav なら試せます。")
    return mic_ok and engine_ok


def synth_wav(text: str, out: Path) -> Path:
    """Windows の音声合成で 16kHz モノラルの WAV を作る（動作試験用）。"""
    if platform.system() != "Windows":
        print("--say は Windows 専用です（--wav で音源を渡してください）")
        sys.exit(2)
    script = f'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$jp = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq 'ja-JP' }} | Select-Object -First 1
if ($jp) {{ $s.SelectVoice($jp.VoiceInfo.Name) }}
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("{out}", $fmt)
$s.Speak(@'
{text}
'@)
$s.Dispose()
'''
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0 or not out.exists():
        print("音声合成に失敗しました:", (r.stderr or "").strip()[:200])
        sys.exit(1)
    return out


def run_once(field: str, source: str, wav: Path | None, show_text: bool) -> int:
    """1 往復させて結果を出す。戻り値はプロセスの終了コード。"""
    cfg = settings.cfg()
    if source == "file":
        cfg["audio"]["backend"] = "file"
        cfg["audio"]["file_path"] = str(wav)
        # 音源の頭から使うので、開始音のガードは要らない
        cfg["audio"]["start_guard_ms"] = 0

    ok, detail = capture.available()
    if not ok:
        print(f"マイク/音源を使えません: {detail}")
        return 1
    ok, detail = whisper_cpp.available()
    if not ok:
        print(f"whisper.cpp を使えません: {detail}")
        return 1

    fcfg = settings.field_cfg(field)
    print(f"\n== {fcfg.get('prompt_ja', field)} ==")
    if source == "mic":
        print("  3 秒後に録音を始めます。話し終えたら黙ってください。")
        for i in (3, 2, 1):
            print(f"  {i}...", flush=True)
            time.sleep(1)
        print("  どうぞ", flush=True)

    stream = capture.open_stream()
    try:
        seg = vad.record_utterance(
            stream,
            max_record_sec=float(fcfg.get("max_record_sec") or settings.get("vad.max_record_sec")),
            on_speech_start=lambda: print("  （発話を検出）", flush=True),
        )
    finally:
        stream.close()
    speech_end = time.monotonic()

    print(f"  音声 {seg.total_ms}ms / うち発話 {seg.speech_ms}ms / 終了理由 {seg.stop_reason}")
    if seg.speech_ms <= 0:
        ja, _ = message("no_speech")
        print(f"  → {ja}（画面では再入力を促します）")
        seg.clear()
        return 1

    try:
        tr = whisper_cpp.transcribe(seg)
    except whisper_cpp.EngineTimeout:
        print("  → 認識がタイムアウトしました")
        seg.clear()
        return 1
    except Exception as e:
        print(f"  → 認識に失敗しました: {type(e).__name__}: {e}")
        seg.clear()
        return 1

    normalized = textnorm.normalize(field, tr.text)
    verdict = quality.judge(seg, tr, normalized)
    total_ms = int((time.monotonic() - speech_end) * 1000)
    seg.clear()

    print(f"  認識 {tr.recognition_ms}ms / 発話終了から表示まで {total_ms}ms / モデル {tr.model_name}")
    if show_text:
        print(f"  生の認識  : {textnorm.normalize_common(tr.text)}")
        print(f"  入力欄の値: {normalized}")
    else:
        print(f"  文字数    : {len(normalized)}（中身を見るには --show-text）")

    if verdict.accepted:
        print(f"  判定      : 採用（色={verdict.tone}）")
    else:
        ja, _ = message(verdict.code or "internal")
        print(f"  判定      : 再入力を促す（{verdict.code}: {ja}）")
    prob = verdict.signals.get("avg_token_prob")
    print(f"  手がかり  : 平均トークン確率={prob} / 無音率={1 - float(verdict.signals['speech_ratio']):.2f}"
          f" / 1秒あたり文字数={verdict.signals['chars_per_sec']}"
          f" / 繰り返し={verdict.signals['repeat_ratio']}")
    return 0 if verdict.accepted else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="状態だけ表示して終わる")
    ap.add_argument("--devices", action="store_true", help="入力デバイスの一覧を出す")
    ap.add_argument("--mic", action="store_true", help="実際のマイクから録る")
    ap.add_argument("--wav", type=Path, help="この WAV をマイクの代わりに流す")
    ap.add_argument("--say", help="この文を読み上げた音で試す（Windows のみ）")
    ap.add_argument("--field", default="company", choices=("company", "person_name", "staff"),
                    help="どの項目として整形・判定するか")
    ap.add_argument("--show-text", action="store_true",
                    help="認識結果を画面に出す（保存はしない）")
    args = ap.parse_args()

    if args.devices:
        devices = capture.list_devices()
        print("入力デバイス（voice_input.yaml の audio.device に書く値）:")
        for d in devices or ["（見つかりません）"]:
            print("  ", d)
        return 0

    ready = show_status()
    if args.status:
        return 0 if ready else 1

    if args.mic:
        return run_once(args.field, "mic", None, args.show_text)

    wav = args.wav
    tmp: Path | None = None
    if args.say:
        tmp = Path(tempfile.gettempdir()) / "mokuture-voice-selftest.wav"
        wav = synth_wav(args.say, tmp)
        print(f"\n（読み上げ音を作りました: {wav.name}）")
    if wav is None:
        # 既定は合成音声。マイクが無い環境でも「とりあえず動くか」を見られる。
        tmp = Path(tempfile.gettempdir()) / "mokuture-voice-selftest.wav"
        wav = synth_wav("株式会社ラナソフトです", tmp)
        print(f"\n（音源の指定が無いので読み上げ音で試します: 株式会社ラナソフトです）")
    if not wav.exists():
        print(f"音源が見つかりません: {wav}")
        return 1

    try:
        return run_once(args.field, "file", wav, args.show_text)
    finally:
        # 合成した音源は残さない
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
