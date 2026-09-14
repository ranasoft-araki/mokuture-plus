"""文字の並びから名刺の位置を求める（輪郭が取れないときの本命）。

なぜこれが要るか。実機のキオスクでは名刺を手に持って差し出すので、名刺の縁は

  * 指に隠れる
  * 逆光の窓や白いシャツと同系色になって明暗差が消える
  * 画面の外へ少しはみ出す

のいずれかになりやすい。実際の失敗画面 3 枚を調べたところ、輪郭ベースの検出は
4 つのエッジ抽出すべてで候補が 1 つも面積の条件を通らず、名刺の輪郭が一度も
組み上がっていなかった。つまり「四角形を見つける」こと自体が成立していない。

一方で名刺には必ず**文字が密に並んでいる**。文字は紙との明暗差が大きいので、
縁が消える条件でも確実に出る。そこで

  1. 文字らしい連結成分を画面全体から拾う
  2. 近いものをつないで、いちばん数の多いかたまりを取る
  3. そのかたまりを字の高さぶん外側へ広げた矩形を名刺の領域とする

という順で位置を決める。紙の縁は使わない。3 枚の失敗画面で試すと、いずれも
氏名または社名を含む 5〜8 項目が取れるようになった（従来は 0）。

切り出す矩形は名刺の縁とぴったりではない。だが OCR は渡された画像の中から
自分で行を探すので、文字が全部入っていて余白が多少あっても読める。確認画面へ
出す画像も「読み取った範囲」として正しい。逆に、縁に合わせようとして
検出できないより、多少ずれても読めるほうが利用者の役に立つ。
"""
from __future__ import annotations

import cv2
import numpy as np

from card import settings
from card.types import Detection, FrameMetrics, Quad

Box = tuple[int, int, int, int]

# 文字から決めた候補の点数。縁から決めた候補と比べるためのものではない
# （縁で見つかったときはそもそもここへ来ない）ので、固定値でよい。
_TEXT_SCORE = 0.5


def text_boxes(gray) -> list[Box]:
    """文字らしい連結成分の矩形 (x, y, w, h) を返す。

    大きさと縦横比、それに「塗りつぶし率」で絞る。塗りつぶし率を見るのは、
    名刺の飾り罫や窓枠のような中空の細長い図形を文字と取り違えないため。
    """
    d = settings.get("detection")
    block = max(3, int(d["text_block_size"]) | 1)
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, block, int(d["text_c"]))
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(th, 8)
    height, width = gray.shape[:2]
    h_max = height * float(d["text_max_height_ratio"])
    w_max = width * float(d["text_max_width_ratio"])
    h_min = float(d["text_min_height_px"])
    ar_max = float(d["text_max_aspect"])
    fill_min = float(d["text_min_fill"])

    out: list[Box] = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if h < h_min or h > h_max:
            continue
        if w < float(d["text_min_width_px"]) or w > w_max:
            continue
        ratio = w / float(h)
        if ratio > ar_max or ratio < 1.0 / ar_max:
            continue
        if area < fill_min * w * h:
            continue
        out.append((x, y, w, h))
    return out


def _ring_level(gray, box: Box) -> float:
    """文字のすぐ外側（＝その文字が乗っている紙）の明るさ。"""
    x, y, w, h = box
    pad = max(2, h // 2)
    hh, ww = gray.shape[:2]
    y0, y1 = max(0, y - pad), min(hh, y + h + pad)
    x0, x1 = max(0, x - pad), min(ww, x + w + pad)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    # 文字そのものは暗いので、上側の分位を取れば紙の明るさになる
    return float(np.percentile(patch, 75))


def dominant_cluster(boxes: list[Box], shape, gray=None) -> tuple[list[Box], list[Box]]:
    """近い文字どうしをつなぎ、いちばん数の多いかたまりを返す。

    戻り値は (密なかたまり, そのまわりの文字を取り込んだもの)。前者は名刺の
    本文が固まっている場所で、背景のノイズが混じりにくい。見切れの判定には
    こちらを使う。

    つなぐ距離は「その画像の字の高さ」を単位にする。画素で決め打ちにすると、
    名刺が画面に大きく写っているときと小さいときで挙動が変わってしまう。
    行方向（横）より行間（縦）を広くつなぐのは、名刺は行間が広く空くため。
    """
    d = settings.get("detection")
    if len(boxes) < int(d["text_min_boxes"]):
        return [], []
    mh = float(np.median([b[3] for b in boxes]))
    mask = np.zeros(shape[:2], np.uint8)
    for x, y, w, h in boxes:
        cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
    kx = max(3, int(mh * float(d["text_link_x"]))) | 1
    ky = max(3, int(mh * float(d["text_link_y"]))) | 1
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky)))
    n, lab, _stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return [], []
    height, width = shape[:2]
    groups: dict[int, list[Box]] = {}
    for b in boxes:
        x, y, w, h = b
        i = int(lab[min(height - 1, y + h // 2), min(width - 1, x + w // 2)])
        if i:
            groups.setdefault(i, []).append(b)
    if not groups:
        return [], []
    core = max(groups.values(), key=len)
    return core, _absorb(core, boxes, mh, gray)


def _absorb(group: list[Box], boxes: list[Box], mh: float, gray=None) -> list[Box]:
    """かたまりの近くにある文字を取り込む。

    名刺は「社名・氏名」と「連絡先」の間が大きく空く組み方が多い。最初につなぐ
    距離をその空きに合わせて広げると、こんどは背景の文字まで拾ってしまう。そこで
    いったん密なかたまりを作ってから、そのすぐ外にある文字だけを取り込む。

    距離は**かたまりの外接矩形からではなく、すでに入っている文字のうち
    いちばん近いものから**測る。外接矩形から測ると、端の 1 文字を取り込むたびに
    矩形が広がり、次のまわりがまた広がる…と連鎖して画面全体に届いてしまう
    （実機の映像で実際にそうなり、領域が画面いっぱいになって撮影できなくなった）。

    横は狭く、縦は広く取る。名刺で大きく空くのは行間（縦）であって、横に離れた
    文字は別の物体であることが多い。
    """
    d = settings.get("detection")
    reach_x = mh * float(d["text_absorb_ratio_x"])
    reach_y = mh * float(d["text_absorb_ratio_y"])
    chosen = list(group)
    rest = [b for b in boxes if b not in chosen]
    # 「同じ紙の上にあるか」で絞る。距離だけで取り込むと、実機の映像では
    # ブラインドの桟やシャツの襟を文字として拾って、領域が画面いっぱいになった。
    if gray is not None and rest:
        tol = float(d["text_absorb_level_tol"])
        level = float(np.median([_ring_level(gray, b) for b in chosen]))
        rest = [b for b in rest if abs(_ring_level(gray, b) - level) <= tol]
    for _ in range(int(d["text_absorb_passes"])):
        if not rest:
            break
        cur = np.asarray(chosen, dtype=np.float64)
        cand = np.asarray(rest, dtype=np.float64)
        # 矩形どうしの隙間（重なっていれば 0）を全組み合わせで出す
        gap_x = np.abs((cand[:, None, 0] + cand[:, None, 2] / 2)
                       - (cur[None, :, 0] + cur[None, :, 2] / 2))             - (cand[:, None, 2] + cur[None, :, 2]) / 2
        gap_y = np.abs((cand[:, None, 1] + cand[:, None, 3] / 2)
                       - (cur[None, :, 1] + cur[None, :, 3] / 2))             - (cand[:, None, 3] + cur[None, :, 3]) / 2
        near = ((gap_x <= reach_x) & (gap_y <= reach_y)).any(axis=1)
        if not near.any():
            break
        chosen += [b for b, ok in zip(rest, near) if ok]
        rest = [b for b, ok in zip(rest, near) if not ok]
    return chosen


def row_count(boxes: list[Box]) -> int:
    """かたまりが何行に分かれているか。1 行しかないものは名刺ではない。"""
    if not boxes:
        return 0
    gap = float(settings.get("detection.text_row_gap"))
    mh = float(np.median([b[3] for b in boxes]))
    centers = sorted(b[1] + b[3] / 2.0 for b in boxes)
    rows = 1
    last = centers[0]
    for c in centers[1:]:
        if c - last > mh * gap:
            rows += 1
            last = c
    return rows


def _clamp(quad, width: int, height: int) -> Quad:
    return tuple((float(min(max(x, 0.0), width - 1.0)),
                  float(min(max(y, 0.0), height - 1.0))) for x, y in quad)


def detect_by_text(bgr) -> Detection | None:
    """文字のかたまりから名刺の四隅を決める。見つからなければ None。

    四隅は名刺の縁ではなく「文字が全部入る範囲」なので、返す Detection の
    aspect や area_ratio は縁ベースのものと意味が違う。撮影可否の判定は
    quality 側が source を見て切り替える。
    """
    d = settings.get("detection")
    if not bool(d["text_fallback"]):
        return None
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    boxes = text_boxes(gray)
    core, group = dominant_cluster(boxes, gray.shape, gray)
    if len(group) < int(d["text_min_boxes"]):
        return None
    rows = row_count(group)
    if rows < int(d["text_min_rows"]):
        return None

    mh = float(np.median([b[3] for b in group]))
    pts = []
    for x, y, w, h in group:
        pts += [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    # 見切れているか。判定には取り込み後ではなく**密なかたまり**を使う。
    # 取り込み後は背景のノイズ（ブラインドの桟・襟）まで入ることがあり、実機の
    # 映像ではそれが画面の端に届いて、まともに写っている名刺まで
    # 「全体が入るように」で止まってしまった。密なかたまりは名刺の本文が
    # 固まっている場所なので、ここが端に達していれば本当に見切れている。
    margin = float(d["margin_px"])
    cxs = [b[0] for b in core] + [b[0] + b[2] for b in core]
    cys = [b[1] for b in core] + [b[1] + b[3] for b in core]
    clipped = (min(cxs) <= margin or max(cxs) >= width - margin
               or min(cys) <= margin or max(cys) >= height - margin)
    (cx, cy), (rw, rh), angle = cv2.minAreaRect(np.array(pts, np.float32))
    pad = mh * float(d["text_pad_ratio"])
    rect = ((cx, cy), (rw + 2 * pad, rh + 2 * pad), angle)
    quad = _clamp(_order(cv2.boxPoints(rect)), width, height)

    area_ratio = _area(quad) / float(width * height)
    if not (float(d["min_area_ratio"]) <= area_ratio <= float(d["max_area_ratio"])):
        return None

    from card.detect import quad_aspect, skin_ratio        # 循環 import を避ける
    aspect = quad_aspect(quad)
    # 名刺の「文字が入る範囲」は正方形に近いことも横長なこともあるが、細長い帯に
    # はならない。レシートのような細長い印刷物を落とすための上限。
    if aspect > float(d["text_max_region_aspect"]):
        return None
    if skin_ratio(bgr, quad) > float(d["max_skin_ratio"]):
        return None                    # 顔や手のひらの上の模様を文字と見ない

    metrics = FrameMetrics(
        area_ratio=area_ratio,
        aspect=aspect,
        text_regions=len(group),
        text_height=mh,
        text_clipped=clipped,
    )
    return Detection(quad=quad, metrics=metrics, score=_TEXT_SCORE, source="text")


def _order(box) -> Quad:
    from card.detect import order_quad
    return order_quad(box)


def _area(quad: Quad) -> float:
    from card.detect import quad_area
    return quad_area(quad)
