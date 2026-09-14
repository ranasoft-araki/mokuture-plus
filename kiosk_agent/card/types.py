"""名刺認識パイプラインで受け渡すデータ型。

numpy / cv2 に依存しない（型だけを読む側が重い依存を引かずに済むように）。
座標系はすべて「入力画像のピクセル」。四隅は常に左上→右上→右下→左下の順。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]   # TL, TR, BR, BL

# 自動撮影の状態。キオスク画面の案内文言と 1:1 で対応する（quality.GUIDANCE）。
CaptureState = Literal[
    "no_card",      # 名刺が見つからない
    "too_small",    # 小さすぎる（近づけてほしい）
    "too_large",    # 大きすぎる／見切れている
    "out_of_frame", # 画面外にはみ出している
    "blurry",       # ピンぼけ
    "glare",        # 反射・白飛び
    "dark",         # 暗すぎる
    "moving",       # 動いている（静止待ち）
    "steady",       # 条件成立・連続フレーム数を稼いでいる
    "capturing",    # 撮影確定
]


@dataclass(frozen=True)
class FrameMetrics:
    """1 フレームの品質指標。しきい値判定は quality.py が行う。"""
    focus: float = 0.0          # Laplacian 分散（大きいほどピントが合っている）
    brightness: float = 0.0     # 名刺領域の輝度 上位5%点 0-255
    glare_ratio: float = 0.0    # 白飛び画素の割合 0-1
    area_ratio: float = 0.0     # 画面に占める名刺の面積比 0-1
    fill_ratio: float = 0.0     # その向きで写せる最大に対する大きさ 0-1（向きに依存しない）
    aspect: float = 0.0         # 名刺の縦横比（長辺/短辺）
    text_regions: int = 0       # 内部で見つかった文字らしい領域の数
    motion: float = 0.0         # 直前フレームからの四隅移動量（画面短辺に対する比）
    text_height: float = 0.0    # 字の高さの中央値(px)。文字ベースの検出でだけ入る


@dataclass(frozen=True)
class Detection:
    """名刺候補 1 件。"""
    quad: Quad
    metrics: FrameMetrics
    score: float = 0.0          # 候補の確からしさ 0-1（複数候補の順位付け用）
    # 四隅をどう決めたか。"edge"=紙の縁 / "text"=文字のかたまり。
    # text のときは四隅が名刺の縁とは一致しないので、撮影可否の条件が変わる。
    source: str = "edge"


@dataclass(frozen=True)
class OcrLine:
    """OCR が返す 1 行。

    box は行を囲む四隅（回転を含む）。conf は認識器が返す平均確信度 0-1。
    order は読み取り順（上から下、同じ高さなら左から右）の連番。
    """
    text: str
    box: Quad
    conf: float
    order: int

    @property
    def height(self) -> float:
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = self.box
        left = ((x3 - x0) ** 2 + (y3 - y0) ** 2) ** 0.5
        right = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        return (left + right) / 2.0

    @property
    def width(self) -> float:
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = self.box
        top = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        bottom = ((x2 - x3) ** 2 + (y2 - y3) ** 2) ** 0.5
        return (top + bottom) / 2.0

    @property
    def center(self) -> Point:
        xs = [p[0] for p in self.box]
        ys = [p[1] for p in self.box]
        return (sum(xs) / 4.0, sum(ys) / 4.0)


@dataclass(frozen=True)
class OcrResult:
    """1 つの前処理バリアントに対する OCR 結果。"""
    lines: list[OcrLine]
    variant: str                 # "color" / "gray" / "binary" / "sharp" / "raw"
    engine: str                  # "paddle_onnx" / "tesseract"
    elapsed_ms: float = 0.0

    @property
    def mean_conf(self) -> float:
        if not self.lines:
            return 0.0
        total_chars = sum(len(l.text) for l in self.lines)
        if total_chars == 0:
            return 0.0
        # 文字数で重み付け（1 文字のゴミ行に平均を引っ張られないように）
        return sum(l.conf * len(l.text) for l in self.lines) / total_chars

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


@dataclass
class Field:
    """抽出した 1 項目。value が None なら「読み取れなかった」。

    candidates は確定できなかったときに画面へ出す候補（氏名など）。
    source_line は根拠にした OCR 行の order（デバッグ用。値そのものは持たない）。
    """
    value: str | None = None
    confidence: float = 0.0
    candidates: list[str] = field(default_factory=list)
    source_line: int | None = None

    def as_dict(self) -> dict:
        d: dict = {"value": self.value or "", "confidence": round(self.confidence, 3)}
        if self.candidates:
            d["candidates"] = self.candidates
        return d


# 抽出対象の項目名。順序は確認画面の表示順。
FIELD_NAMES: tuple[str, ...] = (
    "company_name",
    "person_name",
    "person_name_kana",
    "department",
    "title",
    "postal_code",
    "address",
    "phone",
    "mobile",
    "fax",
    "email",
    "website",
)


@dataclass
class CardFields:
    """抽出結果一式。"""
    company_name: Field = field(default_factory=Field)
    person_name: Field = field(default_factory=Field)
    person_name_kana: Field = field(default_factory=Field)
    department: Field = field(default_factory=Field)
    title: Field = field(default_factory=Field)
    postal_code: Field = field(default_factory=Field)
    address: Field = field(default_factory=Field)
    phone: Field = field(default_factory=Field)
    mobile: Field = field(default_factory=Field)
    fax: Field = field(default_factory=Field)
    email: Field = field(default_factory=Field)
    website: Field = field(default_factory=Field)

    def get(self, name: str) -> Field:
        return getattr(self, name)

    def as_dict(self) -> dict:
        return {name: self.get(name).as_dict() for name in FIELD_NAMES}

    def filled_count(self) -> int:
        return sum(1 for name in FIELD_NAMES if self.get(name).value)
