"""テスト用の合成音声。

実マイクを使わずに録音ループを回すため、決まった音量・長さの PCM を作る。
乱数は使わない(同じテストが毎回同じ結果になるように)。

conftest.py ではなくここに置いているのは、conftest を fixture 専用にして
`from voice_audio import tone` のようにはっきり取り込めるようにするため。
"""
from __future__ import annotations

import math
import struct
from array import array

RATE = 16000


def tone(ms: int, *, rate: int = RATE, dbfs: float = -20.0, freq: float = 220.0) -> bytes:
    """指定した音量の正弦波。発話の代わりに使う。"""
    amp = int(32767 * (10 ** (dbfs / 20.0)) * math.sqrt(2))
    amp = max(1, min(32767, amp))
    n = int(rate * ms / 1000)
    samples = array("h", (int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))
    return samples.tobytes()


def silence(ms: int, *, rate: int = RATE) -> bytes:
    return b"\x00\x00" * int(rate * ms / 1000)


def noise(ms: int, *, rate: int = RATE, dbfs: float = -60.0) -> bytes:
    """暗騒音。ノイズフロア追従の確認に使う。"""
    amp = max(1, int(32767 * (10 ** (dbfs / 20.0)) * math.sqrt(2)))
    n = int(rate * ms / 1000)
    samples = array("h", (int(amp * math.sin(i * 0.7)) for i in range(n)))
    return samples.tobytes()


def parse_wav(data: bytes) -> tuple[int, bytes]:
    """(サンプリングレート, PCM) を返す。whisper へ渡した WAV の検証用。"""
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    rate = struct.unpack("<I", data[24:28])[0]
    idx = data.find(b"data")
    size = struct.unpack("<I", data[idx + 4:idx + 8])[0]
    return rate, data[idx + 8: idx + 8 + size]


def ms_of(pcm: bytes, rate: int = RATE) -> int:
    return int(len(pcm) / 2 / rate * 1000)
