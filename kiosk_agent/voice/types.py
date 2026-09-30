"""声で操作する(画面操作のキーワード)で受け渡す型と、エラーコードの定義。

エラーコードは「利用者に何をしてもらうか」で分けてある。メトリクスにもこの値を
そのまま書く(個人情報を含まない固定語彙なので安全に集計できる)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# セッションの進行状態。画面はこれを見て文言を切り替える。
#   idle        …… 何もしていない
#   arming      …… マイクを開ける準備中
#   listening   …… マイクは開いたが、まだ発話が始まっていない(「お話しください」)
#   speaking    …… 発話を検出して録音中(「聞き取り中」)
#   recognizing …… 録音を終えて認識処理中
#   done        …… 判定が出た(どの選択肢かは command.matched を見る)
#   error       …… 失敗。error_code に理由が入る(no_speech = 話しかけられずに窓が閉じた)
#   cancelled   …… 取り消された(画面が変わった等)
Phase = Literal["idle", "arming", "listening", "speaking", "recognizing", "done", "error", "cancelled"]

# 録音を終えた理由。
StopReason = Literal["silence", "max_duration", "manual", "no_speech", "cancelled"]

ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "mic_unavailable":  ("マイクを使えませんでした", "Microphone unavailable"),
    "mic_error":        ("マイクの調子が悪いようです", "Microphone error"),
    "no_speech":        ("お声を聞き取れませんでした", "No speech detected"),
    "engine_unavailable": ("音声認識を使えませんでした", "Engine unavailable"),
    # どれにも当たらなかった / 2 つ同時に当たった。画面は動かさない。
    "unmatched":        ("もう一度お願いします", "Please say it again"),
    "ambiguous":        ("もう一度お願いします", "Please say it again"),
    # キーワードが文の一部として言われた(周りの会話を拾った可能性が高い)。
    "embedded":         ("もう一度お願いします", "Please say it again"),
    "no_vocabulary":    ("この画面は声で操作できません", "No voice commands on this screen"),
    "internal":         ("声の操作でエラーが起きました", "Internal error"),
}


def message(code: str) -> tuple[str, str]:
    """エラーコード → (日本語, 英語)。未知のコードでも画面を壊さない。"""
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES["internal"])


@dataclass
class AudioSegment:
    """VAD が切り出した発話区間。PCM はメモリ上にだけ存在する。

    `pcm` は 16bit little-endian モノラル。認識が終わるか、セッションが破棄される
    タイミングで参照を捨てる。
    """
    pcm: bytes
    sample_rate: int
    total_ms: int           # 聞き取りを始めてから録音を終えるまで
    speech_ms: int          # うち発話と判定した長さ
    stop_reason: StopReason
    peak_db: float
    noise_floor_db: float

    @property
    def speech_ratio(self) -> float:
        return (self.speech_ms / self.total_ms) if self.total_ms > 0 else 0.0

    def clear(self) -> None:
        self.pcm = b""


@dataclass
class CommandMatch:
    """画面操作のキーワード 1 回ぶんの判定。

    `reason` は外れたときだけ入る: unmatched(どれにも当たらない) / ambiguous(2 つ以上に
    当たった) / embedded(文の一部として言われた) / no_vocabulary(辞書の語で書ける言い回しが
    1 つも無い)。
    `words` は (語, 信頼度, 開始秒, 終了秒)。調整用スクリプトのためだけに持つ。
    **画面にもログにも出さない。**
    """
    matched: str | None
    confidence: float | None
    reason: str | None
    recognition_ms: int
    words: list[tuple] = field(default_factory=list)
