"""検出だけを全フィクスチャで走らせて結果を一覧する（開発用の目視確認ツール）。

    .venv/Scripts/python.exe scripts/eval_detect.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "tests"))

from card.detect import detect_card, quad_area  # noqa: E402
import make_fixtures as mf  # noqa: E402


def iou_quad(a, b, shape) -> float:
    ma = np.zeros(shape[:2], np.uint8)
    mb = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(ma, [np.array(a, np.int32)], 255)
    cv2.fillPoly(mb, [np.array(b, np.int32)], 255)
    inter = np.count_nonzero(cv2.bitwise_and(ma, mb))
    union = np.count_nonzero(cv2.bitwise_or(ma, mb))
    return inter / union if union else 0.0


# 名刺ではないので検出されてはいけないもの。
# blank_card は「文字が無いだけで形は名刺そのもの」なので四隅は持っているが、
# 検出されてはいけない。四隅の有無から期待値を推測できないため明示する。
NOT_A_CARD = {"not_a_card_paper", "not_a_card_phone", "blank_card", "empty_desk"}
# 検出できなくてよいもの（案内は画面全体の明るさから出る）
MAY_MISS = {"dark"}


def inside_ratio(quad, truth, shape) -> float:
    """quad のうち、名刺(truth)の内側に収まっている割合。

    文字から決めた四隅は名刺より小さいので iou では低く出る。知りたいのは
    「切り出す範囲が名刺からはみ出していないか」なので、こちらで見る。
    """
    ma = np.zeros(shape[:2], np.uint8)
    mb = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(ma, [np.array(quad, np.int32)], 255)
    cv2.fillPoly(mb, [np.array(truth, np.int32)], 255)
    own = int(np.count_nonzero(ma))
    return int(np.count_nonzero(cv2.bitwise_and(ma, mb))) / own if own else 0.0


def main() -> int:
    print(f"{'pattern':22} {'det':>4} {'src':>4} {'iou':>6} {'in':>5} "
          f"{'area':>6} {'asp':>5} {'txt':>4} {'ms':>6}  expect")
    bad = 0
    for name in mf.PATTERNS:
        img_pil, truth, _spec = mf.build(name)
        bgr = cv2.cvtColor(np.asarray(img_pil), cv2.COLOR_RGB2BGR)
        # ブラウザが送る検出用フレームと同じ幅に落としてから測る
        scale = 640 / bgr.shape[1]
        small = cv2.resize(bgr, (640, int(bgr.shape[0] * scale)))
        t = time.perf_counter()
        det = detect_card(small)
        ms = (time.perf_counter() - t) * 1000

        expect = "none" if name in NOT_A_CARD else ("card*" if name in MAY_MISS else "card")
        if det is None:
            got, src, iou, inside, area, asp, txt = "no", "-", 0.0, 0.0, 0.0, 0.0, 0
        else:
            got, src = "yes", det.source
            scaled_truth = [(x * scale, y * scale) for x, y in truth] if truth else None
            iou = iou_quad(det.quad, scaled_truth, small.shape) if scaled_truth else 0.0
            inside = inside_ratio(det.quad, scaled_truth, small.shape) if scaled_truth else 0.0
            area, asp, txt = det.metrics.area_ratio, det.metrics.aspect, det.metrics.text_regions

        if expect == "none":
            ok = got == "no"
        elif name in MAY_MISS:
            ok = True
        elif det is not None and det.source == "text":
            # 文字から決めた四隅は名刺の縁ではなく「文字が入る範囲」なので、
            # 重なり具合(iou)ではなく「名刺の内側に収まっているか」で見る。
            ok = inside > 0.90
        else:
            ok = got == "yes" and iou > 0.75
        if not ok:
            bad += 1
        print(f"{name:22} {got:>4} {src:>4} {iou:6.3f} {inside:5.2f} "
              f"{area:6.3f} {asp:5.2f} {txt:4d} {ms:6.1f}  {expect} {'' if ok else '  <-- NG'}")
    print(f"\nNG: {bad}/{len(mf.PATTERNS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
