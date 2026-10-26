"""OCR にかける前の画像補正。

    四隅で台形補正 → 向きの正規化（90度単位） → 文字が小さければ拡大
      → バリアント生成（カラー補正 / グレースケール / 二値化 / シャープ）

バリアントを複数返すのは、どれが最も読めるかが名刺の作りによって変わるため。
どれを採用するかは ocr 側（pipeline）が信頼度と抽出結果の妥当性で決める。

180 度の上下逆は射影だけでは判別できない。ここでは 90 度単位の向きだけを直し、
上下逆の検出は OCR 側（方向分類モデル、または 180 度回転して読み直したときの
信頼度比較）に任せる。
"""
from __future__ import annotations

import cv2
import numpy as np

from card import settings
from card.detect import warp_card
from card.types import Quad

# バリアント名 → 説明（README / API ドキュメント用）
VARIANT_LABELS = {
    "raw": "台形補正のみ",
    "color": "カラー + コントラスト補正(CLAHE)",
    "gray": "グレースケール + コントラスト補正",
    "binary": "適応的二値化",
    "sharp": "グレースケール + アンシャープマスク",
}


# ── 向きの判定 ────────────────────────────────────────────────────────────────

def _row_profile_score(gray) -> float:
    """横書きテキストらしさ。

    二値化した画像の行ごとの黒画素数を並べると、横書きなら「文字行」と「行間」で
    大きく上下する。その分散（平均で正規化）を返す。90 度回した画像と比べて
    大きいほうが、文字が横に並んでいる向き。
    """
    if gray.size == 0:
        return 0.0
    small = cv2.resize(gray, (240, max(8, int(240 * gray.shape[0] / max(1, gray.shape[1])))))
    binary = cv2.adaptiveThreshold(
        small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 9
    )
    profile = binary.sum(axis=1).astype(np.float64) / 255.0
    mean = float(profile.mean())
    if mean <= 1e-6:
        return 0.0
    return float(profile.var()) / (mean * mean)


def normalize_orientation(bgr) -> tuple[np.ndarray, int]:
    """文字が横に並ぶ向きへ 90 度単位で回す。(画像, 回した角度) を返す。

    **縦型（縦長）の名刺は回さない。** 射影だけでは「縦書きの名刺」と「横書きの
    名刺が横倒しになっている」を区別できず、縦書きを回すと全部の文字が横倒しに
    なって 読めなくなる（実測で 8 行中 3 行しか読めなくなった）。

    縦長のまま OCR に渡せば、縦長の枠は行ごとに「縦書き」と「倒れた横書き」の
    両方で読まれ、確からしいほうが採られる（card/ocr/paddle_onnx.py）。つまり
    どちらの名刺でも取りこぼさない。ここで無理に判断しない。

    横長に写っている場合だけ、射影が明確に「行が縦に並んでいる」と言うときに回す。
    """
    if bgr.shape[0] > bgr.shape[1]:
        return bgr, 0

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    rotated = cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    gray_r = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)

    s0 = _row_profile_score(gray)
    s90 = _row_profile_score(gray_r)
    if s90 > s0 * 1.15:
        return rotated, 90
    return bgr, 0


def rotate_180(bgr):
    return cv2.rotate(bgr, cv2.ROTATE_180)


# ── 文字サイズ ────────────────────────────────────────────────────────────────

def median_text_height(gray) -> float:
    """文字らしい連結成分の高さの中央値(px)。見つからなければ 0。"""
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 9
    )
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    h = gray.shape[0]
    heights = []
    for i in range(1, n):
        _x, _y, cw, ch, _area = stats[i]
        if ch < h * 0.015 or ch > h * 0.30:
            continue
        if cw < 1 or ch < 1:
            continue
        ratio = cw / float(ch)
        if ratio < 0.12 or ratio > 12.0:
            continue
        heights.append(float(ch))
    if not heights:
        return 0.0
    return float(np.median(heights))


def upscale_if_small(bgr):
    """文字が小さすぎるときだけ拡大する。(画像, 倍率) を返す。"""
    p = settings.get("preprocess")
    target = float(p["min_text_height_px"])
    limit = float(p["upscale_max"])
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h = median_text_height(gray)
    if h <= 0 or h >= target:
        return bgr, 1.0
    factor = min(limit, target / h)
    if factor <= 1.01:
        return bgr, 1.0
    out = cv2.resize(bgr, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    return out, float(factor)


# ── 台形補正 ──────────────────────────────────────────────────────────────────

def rectify(bgr, quad: Quad | None):
    """四隅から名刺を切り出して向きをそろえる。

    quad が None のときは画像全体をそのまま使う（自動検出に失敗した手動撮影など）。
    戻り値は (補正後画像, 回転角, 拡大倍率)。
    """
    p = settings.get("preprocess")
    width = int(p["output_width"])

    if quad is None:
        card = bgr
        if card.shape[1] != width:
            scale = width / float(card.shape[1])
            card = cv2.resize(card, (width, max(2, int(card.shape[0] * scale))),
                              interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    else:
        card = warp_card(bgr, quad, width=width)
        if card is None:
            return None, 0, 1.0

    card, angle = normalize_orientation(card)
    # 回転で縦横が入れ替わったら、幅を基準にそろえ直す
    if card.shape[1] != width:
        scale = width / float(card.shape[1])
        card = cv2.resize(card, (width, max(2, int(card.shape[0] * scale))),
                          interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)

    card, factor = upscale_if_small(card)
    return card, angle, factor


# ── バリアント生成 ────────────────────────────────────────────────────────────

def _to_bgr(img):
    return img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def make_variant(card, name: str):
    """補正済みの名刺画像から 1 つのバリアントを作る。返すのは常に 3ch BGR。

    OCR エンジンは 3ch を前提にするものが多いので、グレースケール系も 3ch に戻す。
    """
    p = settings.get("preprocess")

    if name == "raw":
        return _to_bgr(card)

    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY) if card.ndim == 3 else card

    if name == "color":
        lab = cv2.cvtColor(_to_bgr(card), cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=float(p["clahe_clip"]),
            tileGridSize=(int(p["clahe_grid"]), int(p["clahe_grid"])),
        )
        l = clahe.apply(l)
        out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        if p["denoise"]:
            # bilateralFilter / fastNlMeansDenoising は品質は良いが 1024px の名刺で
            # 100-300ms かかり、Pi ではこれだけで撮影後 5 秒の目標を食い潰す。
            # 3x3 メディアンはごま塩ノイズにはほぼ同等に効いて 1ms 未満。
            out = cv2.medianBlur(out, 3)
        return out

    if name == "gray":
        clahe = cv2.createCLAHE(
            clipLimit=float(p["clahe_clip"]),
            tileGridSize=(int(p["clahe_grid"]), int(p["clahe_grid"])),
        )
        g = clahe.apply(gray)
        if p["denoise"]:
            g = cv2.medianBlur(g, 3)
        return _to_bgr(g)

    if name == "binary":
        g = cv2.GaussianBlur(gray, (3, 3), 0)
        block = int(p["binary_block"]) | 1
        th = cv2.adaptiveThreshold(
            g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
            block, int(p["binary_c"]),
        )
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
        return _to_bgr(th)

    if name == "sharp":
        blurred = cv2.GaussianBlur(gray, (0, 0), 2.0)
        sharpened = cv2.addWeighted(gray, 1.7, blurred, -0.7, 0)
        return _to_bgr(sharpened)

    raise ValueError(f"unknown variant: {name}")


def variants(card, names: list[str] | None = None):
    """設定で指定されたバリアントを順に生成する（遅延評価）。

    早期採用で打ち切れるように generator で返す。
    """
    names = names or list(settings.get("preprocess.variants"))
    for name in names:
        try:
            yield name, make_variant(card, name)
        except ValueError:
            continue


def to_jpeg(bgr, quality: int = 88) -> bytes:
    """確認画面に出すための JPEG バイト列。ファイルには書かない。"""
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return b""
    return buf.tobytes()


def decode_image(data: bytes):
    """受信したバイト列を BGR 画像にする。読めなければ None。"""
    arr = np.frombuffer(data, dtype=np.uint8)
    if arr.size == 0:
        return None
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def limit_width(bgr, max_width: int):
    """幅の上限に収める（縮小のみ。拡大はしない）。"""
    if bgr is None or bgr.shape[1] <= max_width:
        return bgr, 1.0
    scale = max_width / float(bgr.shape[1])
    out = cv2.resize(bgr, (max_width, max(2, int(bgr.shape[0] * scale))),
                     interpolation=cv2.INTER_AREA)
    return out, scale
