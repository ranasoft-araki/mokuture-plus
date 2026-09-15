"""whisper.cpp 連携。

バイナリは Pi 上でビルドするので開発機では動かせない。代わりに
  - 実際に whisper-cli が吐く JSON（`-ojf`）の形をそのまま食わせて解釈を確かめる
  - 組み立てたコマンドラインに必要な引数が入っているか確かめる
  - 異常終了・出力なしのときの振る舞いを確かめる
の 3 点を押さえる。ここがズレると実機で初めて気付くことになる。

JSON の形は vendor/whisper.cpp-1.9.3.tar.gz の examples/cli/cli.cpp（出力を書いている
関数）に合わせてある。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from voice import settings, whisper_cpp
from voice.types import AudioSegment
from voice_audio import parse_wav


def seg(ms: int = 1000) -> AudioSegment:
    return AudioSegment(pcm=b"\x00\x00" * (16 * ms), sample_rate=16000, total_ms=ms,
                        speech_ms=ms, stop_reason="silence", peak_db=-20.0, noise_floor_db=-55.0)


# whisper-cli --output-json-full が実際に吐く形（抜粋だが構造は同じ）
FULL_JSON = {
    "systeminfo": "AVX = 0 | NEON = 1 | ...",
    "model": {"type": "base", "multilingual": True, "vocab": 51865},
    "params": {"model": "ggml-base-q5_1.bin", "language": "ja", "translate": False},
    "result": {"language": "ja"},
    "transcription": [
        {
            "timestamps": {"from": "00:00:00,000", "to": "00:00:02,400"},
            "offsets": {"from": 0, "to": 2400},
            "text": " 株式会社ラナソフト",
            "tokens": [
                {"text": "[_BEG_]", "timestamps": {}, "offsets": {}, "id": 50364, "p": 0.98},
                {"text": "株式", "timestamps": {}, "offsets": {}, "id": 1234, "p": 0.91},
                {"text": "会社", "timestamps": {}, "offsets": {}, "id": 2345, "p": 0.88},
                {"text": "ラナ", "timestamps": {}, "offsets": {}, "id": 3456, "p": 0.72},
                {"text": "ソフト", "timestamps": {}, "offsets": {}, "id": 4567, "p": 0.81},
            ],
        }
    ],
}


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    """whisper-cli の代わり。書き出す JSON と終了コードを差し替えられる。"""
    state = {"payload": FULL_JSON, "returncode": 0, "stderr": b"", "write_json": True,
             "cmd": None, "wav": None}

    cfg = settings.cfg()
    cfg["whisper"]["tmp_dir"] = str(tmp_path)
    monkeypatch.setattr(whisper_cpp, "available", lambda: (True, "test"))
    monkeypatch.setattr(whisper_cpp, "binary_path", lambda: tmp_path / "whisper-cli")
    monkeypatch.setattr(whisper_cpp, "model_path", lambda: tmp_path / "ggml-base-q5_1.bin")

    def fake_run(cmd, **kw):
        state["cmd"] = list(cmd)
        wav = cmd[cmd.index("-f") + 1]
        state["wav"] = open(wav, "rb").read()
        if state["write_json"]:
            base = cmd[cmd.index("-of") + 1]
            with open(base + ".json", "w", encoding="utf-8") as f:
                json.dump(state["payload"], f, ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, state["returncode"], b"", state["stderr"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    return state


# ── JSON の解釈 ───────────────────────────────────────────────────────────────

def test_text_and_confidence_are_parsed(fake_cli):
    tr = whisper_cpp.transcribe(seg())
    assert tr.text == "株式会社ラナソフト"
    # [_BEG_] のような特別トークンは平均から除く（除かないと確率が甘くなる）
    expected = (0.91 + 0.88 + 0.72 + 0.81) / 4
    assert tr.avg_token_prob == pytest.approx(expected, abs=0.001)
    # whisper.cpp の JSON は no-speech 確率を返さない。無理に数値化しない（§7）
    assert tr.no_speech_prob is None
    assert tr.engine == "whisper"
    assert tr.recognition_ms >= 0


def test_multiple_segments_are_joined(fake_cli):
    fake_cli["payload"] = {
        "transcription": [
            {"text": " 株式会社", "tokens": [{"text": "株式会社", "p": 0.9}]},
            {"text": "ラナソフト", "tokens": [{"text": "ラナソフト", "p": 0.8}]},
        ]
    }
    assert whisper_cpp.transcribe(seg()).text == "株式会社ラナソフト"


def test_empty_transcription_gives_empty_text(fake_cli):
    """無音を渡したときに whisper が何も返さない場合。"""
    fake_cli["payload"] = {"transcription": []}
    tr = whisper_cpp.transcribe(seg())
    assert tr.text == ""
    assert tr.avg_token_prob is None


def test_tokens_without_probability_are_ignored(fake_cli):
    fake_cli["payload"] = {
        "transcription": [{"text": "田中", "tokens": [{"text": "田中"}]}]
    }
    tr = whisper_cpp.transcribe(seg())
    assert tr.text == "田中"
    assert tr.avg_token_prob is None


# ── コマンドライン ────────────────────────────────────────────────────────────

def test_command_has_the_flags_we_depend_on(fake_cli):
    whisper_cpp.transcribe(seg())
    cmd = fake_cli["cmd"]
    for flag in ("-m", "-f", "-l", "-t", "-ojf", "-of", "-np", "-nt"):
        assert flag in cmd, f"{flag} が抜けている"
    assert cmd[cmd.index("-l") + 1] == "ja"
    # トークン確率を取るには -ojf（--output-json-full）が要る。-oj だけでは足りない。
    assert "-ojf" in cmd


def test_suppress_non_speech_flag_follows_settings(fake_cli):
    settings.cfg()["whisper"]["suppress_non_speech"] = False
    whisper_cpp.transcribe(seg())
    assert "-sns" not in fake_cli["cmd"]
    settings.cfg()["whisper"]["suppress_non_speech"] = True
    whisper_cpp.transcribe(seg())
    assert "-sns" in fake_cli["cmd"]


def test_extra_args_are_appended(fake_cli):
    settings.cfg()["whisper"]["extra_args"] = ["--best-of", "2"]
    whisper_cpp.transcribe(seg())
    assert fake_cli["cmd"][-2:] == ["--best-of", "2"]


def test_wav_handed_over_is_16k_mono(fake_cli):
    """whisper.cpp は 16kHz モノラルしか受け付けない。"""
    whisper_cpp.transcribe(seg(1500))
    rate, pcm = parse_wav(fake_cli["wav"])
    assert rate == 16000
    assert len(pcm) == 2 * 16 * 1500


# ── 異常系 ────────────────────────────────────────────────────────────────────

def test_non_zero_exit_raises(fake_cli):
    fake_cli["returncode"] = 1
    fake_cli["stderr"] = "error: failed to initialize whisper context\n".encode()
    with pytest.raises(whisper_cpp.EngineFailed):
        whisper_cpp.transcribe(seg())


def test_missing_json_raises(fake_cli):
    fake_cli["write_json"] = False
    with pytest.raises(whisper_cpp.EngineFailed):
        whisper_cpp.transcribe(seg())


def test_timeout_raises(fake_cli, monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(whisper_cpp.EngineTimeout):
        whisper_cpp.transcribe(seg())


def test_unavailable_when_binary_is_missing(tmp_path):
    cfg = settings.cfg()
    cfg["whisper"]["binary"] = str(tmp_path / "nope")
    ok, detail = whisper_cpp.available()
    assert not ok and "whisper-cli" in detail


def test_unavailable_when_model_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(whisper_cpp, "binary_path", lambda: Path(__file__))  # 実在する何か
    cfg = settings.cfg()
    cfg["whisper"]["model_path"] = str(tmp_path / "missing.bin")
    ok, detail = whisper_cpp.available()
    assert not ok and "モデル" in detail


def test_transcribe_refuses_when_unavailable(tmp_path):
    settings.cfg()["whisper"]["binary"] = str(tmp_path / "nope")
    with pytest.raises(whisper_cpp.EngineUnavailable):
        whisper_cpp.transcribe(seg())


# ── 設定の反映 ────────────────────────────────────────────────────────────────

def test_model_can_be_switched_by_settings(fake_cli):
    """モデルの差し替えは設定だけでできる（§3-1）。"""
    cfg = settings.cfg()
    cfg["whisper"]["model_name"] = "whisper-small-q5"
    assert whisper_cpp.transcribe(seg()).model_name == "whisper-small-q5"
