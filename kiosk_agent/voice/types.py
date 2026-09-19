"""音声入力で受け渡す型と、画面に出すエラーコードの定義。

エラーコードは「利用者に何をしてもらうか」で分けてある。メトリクスにもこの値を
そのまま書く(個人情報を含まない固定語彙なので安全に集計できる)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# 入力項目。第1段階で使うのは company / person_name の 2 つ。
FieldName = Literal["company", "person_name", "staff", "command"]
FIELDS: tuple[str, ...] = ("reception", "company", "person_name", "staff", "command")

# セッションの進行状態。画面はこれを見て文言を切り替える。
#   idle        …… 何もしていない
#   arming      …… 端末の音声案内・開始音の再生待ち(§9)。まだマイクは開けない
#   listening   …… マイクは開いたが、まだ発話が始まっていない(「お話しください」)
#   speaking    …… 発話を検出して録音中(「聞き取り中」)
#   recognizing …… 録音を終えて認識処理中(「認識しています」)
#   done        …… 結果がある(採用可否は result.accepted を見る)
#   error       …… 失敗。error_code に理由が入る
#   cancelled   …… 利用者がやめた
Phase = Literal["idle", "arming", "listening", "speaking", "recognizing", "done", "error", "cancelled"]

# 録音を終えた理由。
StopReason = Literal["silence", "max_duration", "manual", "no_speech", "cancelled"]

# 自動確定せず再入力・候補選択を求める理由(§7)。画面の文言もここで決まる。
ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "mic_unavailable":  ("マイクを使えませんでした", "Microphone unavailable"),
    "mic_error":        ("マイクの調子が悪いようです", "Microphone error"),
    "no_speech":        ("お声を聞き取れませんでした", "No speech detected"),
    "too_short":        ("お声が短すぎました", "Speech too short"),
    "empty_result":     ("聞き取れませんでした", "Nothing recognised"),
    "low_confidence":   ("うまく聞き取れませんでした", "Not confident enough"),
    "repetition":       ("うまく聞き取れませんでした", "Unstable result"),
    "timeout":          ("時間がかかりすぎました", "Recognition timed out"),
    "engine_unavailable": ("音声認識を使えませんでした", "Engine unavailable"),
    "no_match":         ("該当する担当者が見つかりませんでした", "No matching host"),
    "ambiguous":        ("候補が複数あります", "Multiple candidates"),
    "internal":         ("音声入力でエラーが起きました", "Internal error"),
}

# 画面側が「もう一度話す / キーボードで入力」のどちらを勧めるかの指針。
# 再試行しても直らない種類のものは、素直にキーボードへ誘導する。
RETRYABLE: frozenset[str] = frozenset({
    "no_speech", "too_short", "empty_result", "low_confidence", "repetition", "ambiguous", "no_match",
})


def message(code: str) -> tuple[str, str]:
    """エラーコード → (日本語, 英語)。未知のコードでも画面を壊さない。"""
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES["internal"])


@dataclass
class AudioSegment:
    """VAD が切り出した発話区間。PCM はメモリ上にだけ存在する。

    `pcm` は 16bit little-endian モノラル。認識が終わるか、セッションが破棄される
    タイミングで参照を捨てる(§11)。
    """
    pcm: bytes
    sample_rate: int
    total_ms: int           # ボタンを押してから録音を終えるまで
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
class Transcript:
    """認識エンジンの生の出力。ここから先は textnorm / quality が判断する。

    whisper.cpp は必ずしも確信度を返さない(ビルドや出力形式による)。取れなかった
    値は None のままにして、無理に数値をでっち上げない(§7)。
    """
    text: str
    engine: str                       # "whisper" | "vosk"
    model_name: str
    recognition_ms: int
    avg_token_prob: float | None = None
    no_speech_prob: float | None = None
    # 語ごとの確信度(Vosk は word 単位で返す)。担当者照合のヒントに使う。
    words: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Judgement:
    """認識結果を自動で入力欄に入れてよいかの判定(§7)。

    `accepted=False` でも text は画面に出す。「こう聞こえました。違っていたら
    直してください」と見せたほうが、黙って捨てるより利用者は次の行動を選べる。
    """
    accepted: bool
    code: str | None                  # accepted=False のときの理由
    # 画面の色分け用。"ok" | "warn" | "weak"
    tone: str
    signals: dict[str, float | int | bool | None]


@dataclass
class Recognition:
    """1 回の音声入力の結果。画面へ返す形そのもの。"""
    field: str
    text: str                         # 整形後(定型表現を除いたもの)
    raw_text: str                     # 整形前。画面の「そのまま使う」用
    accepted: bool
    tone: str
    error_code: str | None
    engine: str
    model_name: str
    audio_ms: int
    recognition_ms: int
    total_ms: int                     # 発話終了 → 結果表示までの実測(§3-1)
    stop_reason: StopReason | None
    signals: dict
    # 担当者照合(第3段階)。候補が無いときは空。
    candidates: list[dict] = field(default_factory=list)
    # field="reception" のときだけ入る。一文から取り出した受付項目(下書き)。
    extracted: dict | None = None
