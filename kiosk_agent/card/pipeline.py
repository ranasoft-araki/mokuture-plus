"""撮影された 1 枚から項目抽出までを通す（§6 の「最良結果を選ぶ」部分）。

同じ名刺を複数の前処理バリアントで読み、いちばん良かった結果を採る。
「良さ」は OCR の信頼度だけで決めない。メールアドレスや電話番号が正しい形で
取れているか、会社名・氏名が埋まっているか（＝受付で実際に使う項目）も見る。
文字の信頼度が高くても項目が取れていない結果は採用しない。

処理時間を抑えるため、先頭のバリアントで十分なスコアが出たら残りは省略する
（preprocess.early_accept_score）。バリアントの順番と本数は設定で変えられる。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from card import settings
from card.extract import extract, overall_confidence
from card.ocr import get_engine
from card.ocr.base import OcrUnavailable
from card.preprocess import make_variant, rectify, to_jpeg
from card.types import CardFields, OcrLine, Quad


@dataclass
class VariantResult:
    variant: str
    lines: list[OcrLine]
    fields: CardFields
    score: float
    mean_conf: float
    ocr_ms: float


@dataclass
class ReadResult:
    """1 回の撮影に対する最終結果。画像はここにしか存在せず、保存はしない。"""
    fields: CardFields
    lines: list[OcrLine]
    variant: str
    card_jpeg: bytes
    card_size: tuple[int, int]
    rotation: int
    upscale: float
    overall: float
    timings_ms: dict[str, float] = field(default_factory=dict)
    tried: list[str] = field(default_factory=list)
    engine: str = ""


def _mean_conf(lines: list[OcrLine]) -> float:
    total = sum(len(l.text) for l in lines)
    if total == 0:
        return 0.0
    return sum(l.conf * len(l.text) for l in lines) / total


def score_result(lines: list[OcrLine], fields: CardFields) -> float:
    """このバリアントの結果の良さ 0-1。

    文字の確からしさ(45%) と、受付で使う項目が取れているか(55%) の合成。
    """
    conf = _mean_conf(lines)
    # 受付フォームに入る 2 項目を重く、連絡先を軽く見る
    weights = {
        "company_name": 0.30,
        "person_name": 0.30,
        "email": 0.16,
        "phone": 0.10,
        "department": 0.07,
        "title": 0.07,
    }
    filled = 0.0
    for name, w in weights.items():
        f = fields.get(name)
        if f.value:
            filled += w * min(1.0, f.confidence + 0.15)
    return round(0.45 * conf + 0.55 * filled, 4)


def read_card(bgr, quad: Quad | None) -> ReadResult | None:
    """撮影画像から名刺を切り出し、最良の前処理で読み取って項目を返す。

    quad が None なら画像全体を名刺として扱う（手動撮影で検出に失敗した場合）。
    戻り値の card_jpeg は確認画面に出すための補正後画像。ディスクには書かない。
    """
    p = settings.get("preprocess")
    engine = get_engine()

    t0 = time.perf_counter()
    card, rotation, upscale = rectify(bgr, quad)
    if card is None:
        return None
    pre_ms = (time.perf_counter() - t0) * 1000.0

    names = list(p["variants"]) or ["color"]
    early = float(p["early_accept_score"])
    best: VariantResult | None = None
    tried: list[str] = []
    ocr_total = 0.0
    ext_total = 0.0

    for name in names:
        try:
            image = make_variant(card, name)
        except ValueError:
            continue
        tried.append(name)

        t0 = time.perf_counter()
        try:
            lines = engine.run(image)
        except OcrUnavailable:
            raise
        ocr_ms = (time.perf_counter() - t0) * 1000.0
        ocr_total += ocr_ms

        t0 = time.perf_counter()
        fields = extract(lines, (card.shape[1], card.shape[0]))
        ext_total += (time.perf_counter() - t0) * 1000.0

        result = VariantResult(
            variant=name, lines=lines, fields=fields,
            score=score_result(lines, fields), mean_conf=_mean_conf(lines), ocr_ms=ocr_ms,
        )
        if best is None or result.score > best.score:
            best = result
        if best.score >= early:
            break

    if best is None:
        return None

    t0 = time.perf_counter()
    jpeg = to_jpeg(card)
    encode_ms = (time.perf_counter() - t0) * 1000.0

    return ReadResult(
        fields=best.fields,
        lines=best.lines,
        variant=best.variant,
        card_jpeg=jpeg,
        card_size=(card.shape[1], card.shape[0]),
        rotation=rotation,
        upscale=upscale,
        overall=overall_confidence(best.fields),
        timings_ms={
            "preprocess": round(pre_ms, 1),
            "ocr": round(ocr_total, 1),
            "extract": round(ext_total, 1),
            "encode": round(encode_ms, 1),
        },
        tried=tried,
        engine=engine.name,
    )


def lines_payload(lines: list[OcrLine]) -> list[dict]:
    """OCR 行を API で返せる形にする（§7 の保持項目）。

    値そのものを持つのでログには出さない。画面のデバッグ表示と、
    どの行から項目を取ったかの確認に使う。
    """
    return [
        {
            "order": l.order,
            "text": l.text,
            "confidence": round(l.conf, 3),
            "box": [[round(x, 1), round(y, 1)] for x, y in l.box],
            "height": round(l.height, 1),
            "width": round(l.width, 1),
        }
        for l in lines
    ]
