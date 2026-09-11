"""名刺候補の検出（OpenCV の長方形検出）。

AI 物体検出は使わない。グレースケール化 → ノイズ除去 → Canny → 輪郭 → 多角形近似
→ 四角形判定 → 縦横比/面積/角度 → 内部の文字領域、の順に絞り込む。

「四角形である」だけでは名刺としない。机の木目・書類・タブレットの縁などを落とす
ために、内部に文字らしい領域が複数あり、かつそれが複数の行に分かれていることを
要求する（cfg detection.min_text_regions）。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from card import settings
from card.types import Detection, FrameMetrics, Quad


# ── 幾何ユーティリティ ────────────────────────────────────────────────────────

def order_quad(pts) -> Quad:
    """4 点を 左上→右上→右下→左下 に並べ替える。

    x+y が最小/最大で TL/BR、y-x が最小/最大で TR/BL を決める（回転に強い）。
    """
    p = np.asarray(pts, dtype=np.float64).reshape(4, 2)
    s = p.sum(axis=1)
    d = (p[:, 1] - p[:, 0])
    tl = p[int(np.argmin(s))]
    br = p[int(np.argmax(s))]
    tr = p[int(np.argmin(d))]
    bl = p[int(np.argmax(d))]
    return (
        (float(tl[0]), float(tl[1])),
        (float(tr[0]), float(tr[1])),
        (float(br[0]), float(br[1])),
        (float(bl[0]), float(bl[1])),
    )


def quad_area(quad: Quad) -> float:
    """多角形の面積（靴紐公式）。"""
    a = 0.0
    for i in range(4):
        x1, y1 = quad[i]
        x2, y2 = quad[(i + 1) % 4]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def quad_sides(quad: Quad) -> tuple[float, float, float, float]:
    """上・右・下・左の辺長。"""
    out = []
    for i in range(4):
        x1, y1 = quad[i]
        x2, y2 = quad[(i + 1) % 4]
        out.append(math.hypot(x2 - x1, y2 - y1))
    return (out[0], out[1], out[2], out[3])


def quad_aspect(quad: Quad) -> float:
    """長辺/短辺。縦型名刺でも横型でも 1 以上の同じ値になる。"""
    top, right, bottom, left = quad_sides(quad)
    w = (top + bottom) / 2.0
    h = (left + right) / 2.0
    if min(w, h) <= 1e-6:
        return 0.0
    return max(w, h) / min(w, h)


def quad_angles(quad: Quad) -> list[float]:
    """各頂点の内角（度）。"""
    angles = []
    for i in range(4):
        prev = np.array(quad[(i - 1) % 4])
        cur = np.array(quad[i])
        nxt = np.array(quad[(i + 1) % 4])
        v1, v2 = prev - cur, nxt - cur
        n1, n2 = float(np.linalg.norm(v1)), float(np.linalg.norm(v2))
        if n1 < 1e-6 or n2 < 1e-6:
            angles.append(0.0)
            continue
        cosv = float(np.clip(float(np.dot(v1, v2)) / (n1 * n2), -1.0, 1.0))
        angles.append(math.degrees(math.acos(cosv)))
    return angles


def quad_motion(a: Quad | None, b: Quad | None, short_side: float) -> float:
    """2 つの四隅の平均移動量を画面短辺との比で返す。どちらか欠けていれば 1.0。"""
    if a is None or b is None or short_side <= 0:
        return 1.0
    total = sum(math.hypot(b[i][0] - a[i][0], b[i][1] - a[i][1]) for i in range(4))
    return (total / 4.0) / short_side


def _find_contours(edges):
    """OpenCV 3 系(3 返り値) と 4/5 系(2 返り値) の差を吸収する。"""
    res = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    return res[0] if len(res) == 2 else res[1]


def _point_segment_distance(p, a, b) -> float:
    ab = b - a
    denom = float(ab[0] * ab[0] + ab[1] * ab[1])
    if denom < 1e-9:
        return float(np.hypot(*(p - a)))
    t = float(np.clip(np.dot(p - a, ab) / denom, 0.0, 1.0))
    return float(np.hypot(*(p - (a + t * ab))))


def _line_intersection(l1, l2):
    """(vx, vy, x0, y0) 形式の 2 直線の交点。ほぼ平行なら None。"""
    (vx1, vy1, x1, y1), (vx2, vy2, x2, y2) = l1, l2
    det = vx1 * (-vy2) - vy1 * (-vx2)
    if abs(det) < 1e-6:
        return None
    dx, dy = x2 - x1, y2 - y1
    t = (dx * (-vy2) - dy * (-vx2)) / det
    return (x1 + vx1 * t, y1 + vy1 * t)


def refine_quad(cnt, quad: Quad) -> Quad:
    """輪郭の点を 4 辺に振り分けて直線を当てはめ、その交点を四隅にする。

    approxPolyDP は輪郭のギザつきに引きずられる。名刺が画面内で小さいとき
    （縦型の名刺を横長のカメラで写した場合など）は特に顕著で、4 頂点に落とすために
    許容誤差を大きくせざるを得ず、四隅が数十 px ずれる。辺は本来まっすぐなので、
    辺ごとに直線を当てはめて交点を取り直したほうがずっと正確になる。

    当てはめに失敗したら元の四隅をそのまま返す（悪化させない）。
    """
    pts = np.asarray(cnt, dtype=np.float64).reshape(-1, 2)
    if len(pts) < 12:
        return quad

    corners = np.asarray(quad, dtype=np.float64)
    side_len = [float(np.hypot(*(corners[(i + 1) % 4] - corners[i]))) for i in range(4)]
    if min(side_len) < 8.0:
        return quad

    # 各点を最も近い辺へ割り当てる。角の近くの点はどちらの辺にも属しうるので捨てる。
    # 検出ループで毎フレーム走るので、点ごとの Python ループにはしない
    # （輪郭は数百点あり、素直に書くと 1 フレームで数十 ms 食う）。
    a = corners                                   # (4, 2) 各辺の始点
    b = np.roll(corners, -1, axis=0)              # (4, 2) 各辺の終点
    ab = b - a                                    # (4, 2)
    denom = np.einsum("ij,ij->i", ab, ab)         # (4,)
    denom[denom < 1e-9] = 1e-9
    rel = pts[:, None, :] - a[None, :, :]         # (N, 4, 2)
    t = np.einsum("nij,ij->ni", rel, ab) / denom  # (N, 4) 辺上の位置 0-1
    t_clamped = np.clip(t, 0.0, 1.0)
    foot = a[None, :, :] + t_clamped[:, :, None] * ab[None, :, :]
    dist = np.linalg.norm(pts[:, None, :] - foot, axis=2)   # (N, 4)
    nearest = np.argmin(dist, axis=1)                        # (N,)
    t_near = t[np.arange(len(pts)), nearest]
    keep = (t_near >= 0.12) & (t_near <= 0.88)               # 角から離れた点だけ

    lines = []
    for i in range(4):
        sel = pts[keep & (nearest == i)]
        if len(sel) < 5:
            return quad
        vx, vy, x0, y0 = cv2.fitLine(
            sel.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        lines.append((float(vx), float(vy), float(x0), float(y0)))

    refined = []
    for i in range(4):
        p = _line_intersection(lines[(i - 1) % 4], lines[i])
        if p is None:
            return quad
        refined.append(p)

    # 大きく動いたら当てはめが失敗している。元のほうを信じる。
    limit = max(side_len) * 0.25
    for i in range(4):
        if float(np.hypot(refined[i][0] - corners[i][0], refined[i][1] - corners[i][1])) > limit:
            return quad
    return order_quad(np.array(refined))


def _approx_quad(cnt, base_eps: float) -> Quad | None:
    """輪郭を四角形に落とす。落とせなければ None。

    approxPolyDP の許容誤差は 1 つに決め打ちできない。ノイズで輪郭が波打つと同じ
    名刺でも 4 頂点にならず 6-8 頂点になるため、設定値を中心に何段階か試す。
    それでも駄目で、かつ輪郭が最小外接矩形をほぼ埋めているなら（＝実質長方形）、
    最小外接矩形の 4 隅を使う。ただしこの経路では台形（遠近）は表現できないので、
    あくまで最後の手段。
    """
    peri = cv2.arcLength(cnt, True)
    if peri <= 0:
        return None
    for factor in (1.0, 0.5, 1.5, 2.5, 4.0):
        approx = cv2.approxPolyDP(cnt, base_eps * factor * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return order_quad(approx.reshape(4, 2))

    rect = cv2.minAreaRect(cnt)
    rect_area = rect[1][0] * rect[1][1]
    if rect_area <= 0:
        return None
    if cv2.contourArea(cnt) / rect_area < 0.88:
        return None
    return order_quad(cv2.boxPoints(rect))


def _stretch(gray, lo_pct: float, hi_pct: float):
    """輝度を百分位で 0-255 に引き伸ばす。

    暗所（全体が 40-50 付近に潰れている）や、白い名刺を明るい机に置いた場合
    （差が 10 程度しかない）でも、この後の勾配しきい値を同じ値で扱えるようにする。
    """
    lo, hi = np.percentile(gray, [lo_pct, hi_pct])
    if hi - lo < 1.0:
        return gray
    out = (gray.astype(np.float32) - float(lo)) * (255.0 / float(hi - lo))
    return np.clip(out, 0, 255).astype(np.uint8)


def _edge_strategies(gray, d):
    """エッジ画像を「効きやすい順」に遅延生成する。

    固定しきい値の Canny だけでは、白い名刺を明るい机に置いた場合（境界の輝度差が
    10 程度）や暗所でほとんど輪郭が出ない。そこで
      (1) 設定値の Canny            … 通常のコントラスト。最も速い
      (2) 正規化＋モルフォロジー勾配 … 低コントラスト・暗所・部分的な白飛びに強い
      (3) 中央値ベースの自動 Canny  … 上記で取れないときの保険
    の順に試し、名刺候補が採れた時点で打ち切る（毎フレーム全部走らせると Pi では
    検出間隔に間に合わない）。
    """
    k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    def fixed():
        return cv2.Canny(gray, int(d["canny_low"]), int(d["canny_high"]))

    cache: dict[str, object] = {}

    def _gradient():
        """正規化してからモルフォロジー勾配。2 つの戦略で共有するので 1 度だけ計算する。"""
        if "grad" not in cache:
            n = _stretch(gray, float(d["normalize_lo_pct"]), float(d["normalize_hi_pct"]))
            cache["grad"] = cv2.morphologyEx(n, cv2.MORPH_GRADIENT, k3)
        return cache["grad"]

    def _has_glare():
        """強い反射が写っているか。固定しきい値の戦略を出すかどうかの判断に使う。"""
        if "glare" not in cache:
            cache["glare"] = float(np.count_nonzero(gray >= 250)) / float(gray.size)
        return cache["glare"] > float(d["glare_fallback_ratio"])

    def grad_norm():
        """ノイズ床に追従するしきい値。通常はこれで取れる。

        固定値では成立しない: 実測で名刺の境界の勾配は 16(白い名刺×明るい机) から
        130(木目の机) まで開き、背景のノイズ床も 0(きれいな面) から 15(暗所) まで
        動く。画面の大半は平坦なので、高めの百分位がノイズ床のよい推定になる。
        """
        grad = _gradient()
        floor = float(np.percentile(grad, float(d["gradient_noise_pct"])))
        thr = max(float(d["gradient_thresh"]), floor * float(d["gradient_noise_mult"]))
        return (grad >= thr).astype(np.uint8) * 255

    def grad_fixed():
        """ノイズ床を見ない固定しきい値。

        強い反射があると画面全体の勾配分布が持ち上がり、適応しきい値が名刺の境界
        （反射で弱くなっている）まで切り落としてしまう。そのときの取りこぼし対策。
        ノイズを拾いやすいので、適応版で取れなかったときだけ使う。
        """
        return (_gradient() >= int(d["gradient_thresh"])).astype(np.uint8) * 255

    def auto_canny():
        med = float(np.median(gray))
        lo = int(max(0.0, 0.66 * med))
        hi = int(min(255.0, 1.33 * med))
        if hi - lo < 20:                      # 平坦な画像では開きを確保する
            lo, hi = max(0, lo - 10), min(255, hi + 20)
        return cv2.Canny(gray, lo, hi)

    strategies = [("canny", fixed), ("grad_norm", grad_norm)]
    # 固定しきい値は反射があるときだけ。ノイズを拾いやすいうえ、名刺が写っていない
    # フレーム（＝検出ループの大半）で毎回走らせると 1 フレームの処理時間が伸びる。
    if _has_glare():
        strategies.append(("grad_fixed", grad_fixed))
    strategies.append(("auto_canny", auto_canny))
    return tuple(strategies)


# ── 文字らしさ ────────────────────────────────────────────────────────────────

def count_text_regions(bgr, quad: Quad) -> tuple[int, int]:
    """名刺候補の内部にある「文字らしい領域」の数と、それが何行に分かれるかを返す。

    木目や布地は細長い縞になるため縦横比で落ち、無地の紙や画面の反射は領域自体が
    出ない。日本語は正方形に近い字形なので、極端な縦横比だけを除外する。
    """
    warped = warp_card(bgr, quad, width=400)
    if warped is None or warped.size == 0:
        return 0, 0
    h, w = warped.shape[:2]
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    # 局所コントラストで文字を拾う（照明ムラに強い）
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 9
    )
    # 隣接する字を 1 つの塊にまとめすぎない程度に横へつなぐ
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    n, _, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
    card_area = float(h * w)
    rows: list[float] = []
    count = 0
    for i in range(1, n):
        _x, _y, cw, ch, area = stats[i]
        if ch < h * 0.02 or ch > h * 0.30:      # 小さすぎるノイズ / 大きすぎる図形
            continue
        if cw < 1 or ch < 1:
            continue
        ratio = cw / float(ch)
        if ratio < 0.12 or ratio > 12.0:        # 木目のような極端な細長さを除外
            continue
        if area < card_area * 0.00004 or area > card_area * 0.04:
            continue
        count += 1
        rows.append(float(centroids[i][1]))

    # 中心 y をまとめて「行」の数を数える（同じ行＝高さの 4% 以内）
    rows.sort()
    row_count = 0
    last = -1e9
    tol = max(4.0, h * 0.04)
    for y in rows:
        if y - last > tol:
            row_count += 1
        last = y
    return count, row_count


def warp_card(bgr, quad: Quad, width: int | None = None):
    """四隅から台形補正して切り抜く。width 指定時はその幅にそろえる。

    縦型（高さ>幅）の場合も比率を保ったまま返す。向きの正規化は preprocess 側。
    """
    top, right, bottom, left = quad_sides(quad)
    w = max(top, bottom)
    h = max(left, right)
    if w < 2 or h < 2:
        return None
    if width is not None:
        scale = width / w
        w, h = float(width), max(2.0, h * scale)
    dst_w, dst_h = int(round(w)), int(round(h))
    src = np.array(quad, dtype=np.float32)
    dst = np.array(
        [[0, 0], [dst_w - 1, 0], [dst_w - 1, dst_h - 1], [0, dst_h - 1]], dtype=np.float32
    )
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(bgr, m, (dst_w, dst_h), flags=cv2.INTER_LINEAR)


# ── 検出本体 ──────────────────────────────────────────────────────────────────

def detect_card(bgr, prev_quad: Quad | None = None) -> Detection | None:
    """名刺候補を 1 件返す。見つからなければ None。四隅は入力画像の座標で返す。

    検出は必ず detection.work_width の幅に縮小してから行う。エッジのしきい値や
    連結成分の大きさは画素単位で効くため、入力解像度（検出ループの 640px と撮影時の
    1920px）で挙動が変わってしまうのを防ぐ。処理時間も入力サイズに依存しなくなる。

    prev_quad があれば、そこに近い候補を僅かに優遇する（フレーム間のちらつき抑制）。
    """
    d = settings.get("detection")
    work_w = int(d["work_width"])
    if bgr.shape[1] > work_w:
        ratio = work_w / float(bgr.shape[1])
        work = cv2.resize(bgr, (work_w, max(2, int(bgr.shape[0] * ratio))),
                          interpolation=cv2.INTER_AREA)
        prev_small = tuple((x * ratio, y * ratio) for x, y in prev_quad) if prev_quad else None
        det = _detect_at_scale(work, prev_small)  # type: ignore[arg-type]
        if det is None:
            return None
        inv = 1.0 / ratio
        quad = tuple((x * inv, y * inv) for x, y in det.quad)
        return Detection(quad=quad, metrics=det.metrics, score=det.score)  # type: ignore[arg-type]
    return _detect_at_scale(bgr, prev_quad)


def _detect_at_scale(bgr, prev_quad: Quad | None) -> Detection | None:
    d = settings.get("detection")
    h, w = bgr.shape[:2]
    frame_area = float(h * w)
    if frame_area <= 0:
        return None

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = int(d["blur_kernel"]) | 1
    gray = cv2.GaussianBlur(gray, (k, k), 0)

    for _name, make_edges in _edge_strategies(gray, d):
        edges = make_edges()
        # 途切れた輪郭をつなぐ（名刺の白い縁が背景と近いときに効く）
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
        best = _best_quad(bgr, edges, frame_area, d, prev_quad)
        if best is not None:
            return best
    return None


def _best_quad(bgr, edges, frame_area: float, d: dict, prev_quad: Quad | None) -> Detection | None:
    """1 つのエッジ画像から最良の名刺候補を選ぶ。条件を満たすものが無ければ None。"""
    h, w = bgr.shape[:2]
    contours = _find_contours(edges)
    if contours is None or len(contours) == 0:
        return None
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[: int(d["max_candidates"])]

    margin = float(d["margin_px"])
    best: Detection | None = None

    for cnt in contours:
        quad = _approx_quad(cnt, float(d["approx_epsilon"]))
        if quad is None:
            continue
        if bool(d["refine_corners"]):
            quad = refine_quad(cnt, quad)

        area_ratio = quad_area(quad) / frame_area
        if not (float(d["min_area_ratio"]) <= area_ratio <= float(d["max_area_ratio"])):
            continue

        aspect = quad_aspect(quad)
        if not (float(d["aspect_min"]) <= aspect <= float(d["aspect_max"])):
            continue

        angles = quad_angles(quad)
        lo, hi = float(d["min_corner_angle_deg"]), float(d["max_corner_angle_deg"])
        if any(a < lo or a > hi for a in angles):
            continue

        inside = all(
            margin <= x <= (w - margin) and margin <= y <= (h - margin) for x, y in quad
        )

        regions, rows = count_text_regions(bgr, quad)
        if regions < int(d["min_text_regions"]) or rows < 2:
            continue

        # スコア: 長方形らしさ・面積・文字量・前フレームとの近さ
        rect_score = 1.0 - min(1.0, sum(abs(a - 90.0) for a in angles) / 120.0)
        size_score = min(1.0, area_ratio / 0.5)
        text_score = min(1.0, regions / 24.0)
        stick = 0.0
        if prev_quad is not None:
            short = float(min(h, w))
            stick = max(0.0, 1.0 - quad_motion(prev_quad, quad, short) * 12.0) * 0.15
        score = 0.40 * rect_score + 0.20 * size_score + 0.30 * text_score + stick
        if not inside:
            score *= 0.5

        metrics = FrameMetrics(
            area_ratio=area_ratio,
            aspect=aspect,
            text_regions=regions,
        )
        cand = Detection(quad=quad, metrics=metrics, score=round(score, 4))
        if best is None or cand.score > best.score:
            best = cand

    return best


def fill_ratio(quad: Quad, width: int, height: int) -> float:
    """名刺が「その向きで写せる最大の大きさ」の何割を占めているか 0-1。

    面積比をそのまま使うと向きで不公平になる。16:9 の横長カメラでは、横型の名刺は
    画面の 93% まで占められるのに対し、縦型は最大でも 34% にしかならない（長辺を
    画面の高さに合わせても横に余白が残るため）。同じしきい値を当てると、縦型だけ
    「もう少し近づけてください」が出続ける。

    そこで名刺の長辺が「その向きで取り得る最大の長さ」の何割かで測る。この値なら
    向きに関係なく「画面いっぱいに写せていれば 1.0」になる。
    """
    top, right, bottom, left = quad_sides(quad)
    horiz = (top + bottom) / 2.0
    vert = (left + right) / 2.0
    long_px = max(horiz, vert)
    if long_px <= 0 or width <= 0 or height <= 0:
        return 0.0
    aspect = max(1.0, quad_aspect(quad))
    if horiz >= vert:                      # 長辺が横向き
        limit = min(float(width), aspect * float(height))
    else:                                  # 長辺が縦向き（縦型の名刺）
        limit = min(float(height), aspect * float(width))
    if limit <= 0:
        return 0.0
    return float(min(1.0, long_px / limit))


def is_inside_frame(quad: Quad, width: int, height: int, margin: float | None = None) -> bool:
    """四隅がすべて画面内（マージン込み）にあるか。"""
    m = float(settings.get("detection.margin_px")) if margin is None else margin
    return all(m <= x <= (width - m) and m <= y <= (height - m) for x, y in quad)
