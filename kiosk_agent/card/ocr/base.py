"""OCR エンジンの共通インターフェース。

PaddleOCR(ONNX Runtime) と Tesseract を、設定 `ocr.engine` の一語だけで差し替え
られるようにするための境界。呼び出し側（pipeline）はこの型しか知らない。

エンジンは「使えない」状態を例外ではなく available() で表明する。依存パッケージ
やモデルが無い端末でもキオスク本体は起動し続け、名刺導線だけを隠したいため。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from card.types import OcrLine


class OcrUnavailable(RuntimeError):
    """エンジンが利用できない状態で run() が呼ばれた。"""


class OcrEngine(ABC):
    """1 枚の画像から行単位の認識結果を返すもの。"""

    #: 設定 `ocr.engine` に書く識別子
    name: str = "base"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(使えるか, 理由) を返す。理由は英数字のみ（画面・ログにそのまま出す）。"""

    @abstractmethod
    def run(self, bgr) -> list[OcrLine]:
        """BGR 画像を認識して行のリストを返す。読み取り順に並べて返すこと。"""

    def warmup(self) -> None:
        """初回推論の遅さを起動時に吸収する（任意実装）。"""
        return None

    def describe(self) -> dict:
        """status API が返すエンジン情報。個人情報は含めない。"""
        ok, reason = self.available()
        return {"engine": self.name, "available": ok, "detail": reason}


def sort_reading_order(lines: list[OcrLine], line_tol_ratio: float = 0.6) -> list[OcrLine]:
    """上から下、同じ高さなら左から右に並べ替え、order を振り直す。

    「同じ行」の判定は行の高さに対する中心 y のズレで行う（傾いた名刺でも崩れない）。
    """
    if not lines:
        return []
    remaining = sorted(lines, key=lambda l: (l.center[1], l.center[0]))
    out: list[OcrLine] = []
    used = [False] * len(remaining)

    for i, line in enumerate(remaining):
        if used[i]:
            continue
        tol = max(4.0, line.height * line_tol_ratio)
        row = [(i, line)]
        used[i] = True
        for j in range(i + 1, len(remaining)):
            if used[j]:
                continue
            other = remaining[j]
            if abs(other.center[1] - line.center[1]) <= tol:
                row.append((j, other))
                used[j] = True
        row.sort(key=lambda pair: pair[1].center[0])
        out.extend(item for _idx, item in row)

    return [
        OcrLine(text=l.text, box=l.box, conf=l.conf, order=n)
        for n, l in enumerate(out)
    ]
