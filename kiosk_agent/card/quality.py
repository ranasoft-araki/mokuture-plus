"""自動撮影の可否判定と、画面へ出す案内文言。

しきい値はすべて設定（card.defaults / card_reader.yaml / 環境変数）から読む。
ここにマジックナンバーを置かない。

「名刺が検出できない」ときも黙って no_card にはしない。全画面の明るさ・白飛びを
見て、暗すぎる / 反射で飛んでいる場合はその案内を出す（暗所や強い反射では輪郭
自体が消えるので、no_card のままだと利用者が何を直せばよいか分からなくなる）。
"""
from __future__ import annotations

import cv2
import numpy as np

from card import settings
from card.detect import fill_ratio, quad_motion
from card.types import CaptureState, Detection, FrameMetrics, Quad

# 画面に出す案内。spec の文言をそのまま使う（en は補助表示用）。
GUIDANCE: dict[str, tuple[str, str]] = {
    "no_card":      ("名刺を枠内に入れてください", "Place your card inside the frame"),
    "out_of_frame": ("名刺全体が入るようにしてください", "Fit the whole card in the frame"),
    "too_small":    ("もう少しカメラに近づけてください", "Move the card closer"),
    "too_large":    ("少しカメラから離してください", "Move the card slightly away"),
    "blurry":       ("ピントを合わせています", "Focusing"),
    "glare":        ("光の反射を避けてください", "Avoid glare on the card"),
    "dark":         ("もう少し明るい場所でお願いします", "Please move to a brighter spot"),
    "moving":       ("名刺を動かさずにお待ちください", "Hold the card still"),
    "steady":       ("名刺を動かさずにお待ちください", "Hold the card still"),
    "capturing":    ("名刺を読み取っています", "Reading the card"),
}


def message(state: CaptureState) -> tuple[str, str]:
    return GUIDANCE.get(state, GUIDANCE["no_card"])


# ── 画像指標 ──────────────────────────────────────────────────────────────────

def focus_score(gray) -> float:
    """Laplacian 分散。大きいほどピントが合っている。"""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def brightness(gray) -> float:
    """明るさ＝上位 5% 点（95 パーセンタイル）。

    平均ではなく上位側を見るのは、濃色の名刺（濃紺・黒地に白文字など）を「暗い場面」
    と取り違えないため。知りたいのは「その場に十分な光があるか」であって、名刺の
    地色の濃さではない。十分な光があれば紙の白や文字のハイライトが上位側に出る。
    """
    if gray.size == 0:
        return 0.0
    return float(np.percentile(gray, 95))


def glare_ratio(gray, sat_level: int = 250) -> float:
    """白飛び（ほぼ 255）画素の割合。"""
    if gray.size == 0:
        return 0.0
    return float(np.count_nonzero(gray >= sat_level)) / float(gray.size)


def _mask_for(quad: Quad, shape) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [np.array(quad, dtype=np.int32)], 255)
    return mask


def region_metrics(bgr, quad: Quad | None) -> tuple[float, float, float]:
    """(ピント, 明るさ, 白飛び率) を返す。quad が None なら画面全体で測る。

    名刺領域だけを見るのは、背景（暗い机・明るい窓）に引きずられないため。
    ピントは名刺部分の切り抜きに対して測る（背景のボケは無関係なので）。
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if quad is None:
        return focus_score(gray), brightness(gray), glare_ratio(gray)

    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    x0, x1 = max(0, int(min(xs))), min(bgr.shape[1], int(max(xs)) + 1)
    y0, y1 = max(0, int(min(ys))), min(bgr.shape[0], int(max(ys)) + 1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return focus_score(gray), brightness(gray), glare_ratio(gray)

    crop = gray[y0:y1, x0:x1]
    mask = _mask_for(quad, bgr.shape)[y0:y1, x0:x1]
    inside = crop[mask > 0]
    if inside.size == 0:
        return focus_score(crop), brightness(crop), glare_ratio(crop)
    return focus_score(crop), brightness(inside), glare_ratio(inside)


# ── 判定 ──────────────────────────────────────────────────────────────────────

def evaluate(
    bgr,
    detection: Detection | None,
    prev_quad: Quad | None = None,
) -> tuple[CaptureState, FrameMetrics]:
    """このフレーム単体の状態を返す。連続フレーム数の管理は session 側。

    優先順位は「直せるものから順に案内する」。位置 → 明るさ/反射 → ピント → 静止。
    """
    q = settings.get("quality")
    d = settings.get("detection")
    h, w = bgr.shape[:2]
    short_side = float(min(h, w))

    if detection is None:
        focus, bright, glare = region_metrics(bgr, None)
        metrics = FrameMetrics(focus=focus, brightness=bright, glare_ratio=glare)
        # 輪郭が出ない原因が明るさ側にあるなら、それを案内する。
        if bright < float(q["brightness_min"]):
            return "dark", metrics
        if glare > float(q["glare_max"]) * 2.0 or bright > float(q["brightness_max"]):
            return "glare", metrics
        return "no_card", metrics

    quad = detection.quad
    focus, bright, glare = region_metrics(bgr, quad)
    motion = quad_motion(prev_quad, quad, short_side) if prev_quad is not None else 1.0
    base = detection.metrics
    fill = fill_ratio(quad, w, h)
    metrics = FrameMetrics(
        focus=focus,
        brightness=bright,
        glare_ratio=glare,
        area_ratio=base.area_ratio,
        fill_ratio=fill,
        aspect=base.aspect,
        text_regions=base.text_regions,
        motion=motion,
        text_height=base.text_height,
        text_clipped=base.text_clipped,
    )

    if detection.source == "text":
        # 文字のかたまりから決めた四隅は名刺の縁ではないので、見切れも占有率も
        # そのままでは測れない。
        #
        # 見切れでは止めない。縁が見えない以上「名刺が切れている」のか「画面の端に
        # たまたま文字（ブラインドの桟・襟など）がある」のかを区別できず、実機の
        # 映像では後者で止まって**まったく読み取れなくなった**。誤って止めると
        # 利用者は何もできないが、誤って撮ってしまっても受理判定（氏名か社名が
        # 取れていること）で弾かれて撮り直しになるだけで、損得が釣り合わない。
        # text_clipped は記録だけ残す。
        # 大きさは「字が読める大きさか」で見る。しきい値は画面幅に対する比で持つ
        # （検出フレームの幅を変えても挙動が変わらないように）。
        if base.text_height < float(q["text_height_min_ratio"]) * float(w):
            return "too_small", metrics
    else:
        margin = float(d["margin_px"])
        if not all(margin <= x <= (w - margin) and margin <= y <= (h - margin)
                   for x, y in quad):
            return "out_of_frame", metrics
        # 大きさは面積比ではなく「その向きで写せる最大に対する割合」で見る。
        # 面積比だと縦型の名刺が原理的に不利になる（detect.fill_ratio の説明を参照）。
        if fill < float(q["capture_fill_min"]):
            return "too_small", metrics
        if fill > float(q["capture_fill_max"]):
            return "too_large", metrics
    if bright < float(q["brightness_min"]):
        return "dark", metrics
    if glare > float(q["glare_max"]) or bright > float(q["brightness_max"]):
        return "glare", metrics
    if focus < float(q["focus_min"]):
        return "blurry", metrics
    if motion > float(q["motion_max"]):
        return "moving", metrics
    return "steady", metrics


def is_capturable(state: CaptureState) -> bool:
    """この状態が「あとは連続回数だけ」の合格状態か。"""
    return state == "steady"
