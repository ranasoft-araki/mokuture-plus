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


def _quad_candidates(cnt, base_eps: float):
    """1 つの輪郭から四角形の候補を返す。素の輪郭と凸包の両方を試す。

    実機では名刺の輪郭がそのまま閉じることはまずない:
      - 縁を指で持つと、そこがへこんで四角形でなくなる
      - 手のひらや白い壁が背景だと、その辺だけコントラストが出ずに途切れる
    凸包を取ると、指のへこみは埋まり、途切れた断片も名刺の外形に復元される。
    実測（実機の録画）では、名刺の輪郭は面積比 0.026 の断片にしかならないのに、
    その凸包は面積比 0.240・縦横比 1.84 と名刺そのものの形になっていた。

    素の輪郭が四角形になるならそれを優先する（凸包では台形＝遠近が潰れるため）。
    """
    out = []
    q = _approx_quad(cnt, base_eps)
    if q is not None:
        out.append(q)

    hull = cv2.convexHull(cnt)
    if len(hull) < 4:
        return out

    qh = _approx_quad(hull, base_eps)
    if qh is not None and (q is None or quad_area(qh) > quad_area(q) * 1.05):
        out.append(qh)

    # 角を指で隠されると、その角だけ凸包が斜めに切り落とされて多角形近似が崩れる。
    # 残り 3 辺は正しいので、凸包の最小外接矩形を採るとほぼ名刺の形になる。
    # 遠近（台形）は表現できないので最後の候補にとどめる。
    rect = cv2.minAreaRect(hull)
    if min(rect[1]) > 1.0:
        qr = order_quad(cv2.boxPoints(rect))
        if all(quad_area(qr) > quad_area(e) * 1.05 for e in out):
            out.append(qr)
    return out


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


def _skin_bool(bgr, luma_max: int):
    """肌の色をしている画素の真偽配列。明るさの上限だけ用途ごとに変える。

    色域（YCrCb）は暖色の紙とかなり重なる。生成り・クラフト紙の名刺は
    Cr-Cb が 24-33 で、肌の 30-40 と見分けがつかない。実際に分けられるのは
    明るさで、紙は肌より明るい。その上限を用途ごとに変えるのがこの引数。
    """
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    y = ycrcb[:, :, 0].astype(np.int16)
    cr = ycrcb[:, :, 1].astype(np.int16)
    cb = ycrcb[:, :, 2].astype(np.int16)
    d = settings.get("detection")
    return ((cr >= int(d["skin_cr_min"])) & (cr <= int(d["skin_cr_max"]))
            & (cb >= int(d["skin_cb_min"])) & (cb <= int(d["skin_cb_max"]))
            & ((cr - cb) >= int(d["skin_cr_cb_min"]))
            & (y < int(luma_max)))


def skin_mask(bgr):
    """肌の色をしている画素のマスク。エッジを足す用（取りこぼしを減らす側）。

    ここで紙を肌と取り違えても、エッジが 1 本増えるだけで害は小さい。だから
    明るさの上限は skin_luma_max（緩い側）を使う。候補を落とす skin_ratio とは
    別のしきい値なので注意（あちらは skin_reject_luma_max・厳しい側）。
    """
    return (_skin_bool(bgr, settings.get("detection")["skin_luma_max"])
            .astype(np.uint8) * 255)


def has_skin(bgr, min_ratio: float = 0.005) -> bool:
    """肌らしい画素がまとまって写っているか。重い処理へ進む前の足切り。"""
    m = _skin_bool(bgr, settings.get("detection")["skin_luma_max"])
    return float(np.count_nonzero(m)) / float(m.size) >= min_ratio


def skin_boundary_edges(bgr):
    """肌と肌でないものの境目をエッジとして返す。

    キオスクでは名刺を手に持って差し出す。名刺の縁が手のひらや指に重なると、
    その辺は明暗の差がほとんど無く、輝度ベースのエッジ抽出では出てこない。
    一方その境目は「肌か否か」の境目でもあるので、色で切れば確実に線になる。
    実機の録画では、名刺の左辺と下辺が手に重なって輪郭が閉じないのが
    検出できない主因だった。
    """
    mask = skin_mask(bgr)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return cv2.morphologyEx(mask, cv2.MORPH_GRADIENT,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))


def _edge_strategies(gray, d, skin_edges=None):
    """エッジ画像を「効きやすい順」に遅延生成する。

    固定しきい値の Canny だけでは、白い名刺を明るい机に置いた場合（境界の輝度差が
    10 程度）や暗所でほとんど輪郭が出ない。そこで
      (1) 設定値の Canny            … 通常のコントラスト。最も速い
      (2) 正規化＋モルフォロジー勾配 … 低コントラスト・暗所・部分的な白飛びに強い
      (3) 中央値ベースの自動 Canny  … 上記で取れないときの保険
      (4) (1)(2) に肌との境目を足したもの … 手に重なった辺が輝度では出ないとき
    の順に試し、名刺候補が採れた時点で打ち切る（毎フレーム全部走らせると Pi では
    検出間隔に間に合わない）。

    肌の境目を最後に回すのが重要。全部の戦略に足すと、手が紙より明らかに暗くて
    輝度だけで縁が出ているとき（＝本来うまくいく場合）にまで余計な線が入り、
    輪郭が分かれて検出率が落ちる。横型の名刺を手に持った合成画像 180 通り
    （回転・傾き・大きさ・肌の明るさ・背景を振ったもの）で実測すると:

        手の明るさ    全戦略に足す   予備に回す(現在)   足さない
        紙と同程度        42/60          43/60           22/60
        中間              38/60          48/60           47/60
        紙より暗い        34/60          58/60           58/60

    つまり「輝度で取れるならそのまま、取れないときだけ色に頼る」のが正しい。
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
    # 肌の境目を足した版は最後の 1 本だけ。実機の録画では予備が 2 本あると
    # 検出は 27.2%→31.3% と少し上がるが、1 フレームの処理が 50ms→128ms になり
    # 送信間隔 120ms に間に合わなくなる（自動撮影の回数は 15→16 でほぼ変わらない）。
    if skin_edges is not None:
        strategies.append(("canny_skin", lambda: cv2.bitwise_or(fixed(), skin_edges)))
    return tuple(strategies)


# ── 文字らしさ ────────────────────────────────────────────────────────────────

def edge_support(gray, quad: Quad, thresh: float, window: int | None = None) -> float:
    """四隅を結ぶ辺のうち、実際に輝度の段差がある割合 0-1。

    本物の名刺の縁は明暗の境目になっている。背景の雑多なエッジを凸包でつないだ
    だけの四角形は、辺の大部分に段差が無い。この違いで誤検出を落とす。

    指で隠れている部分や、背景と同系色で段差が出ない辺もあるので「全部」ではなく
    「何割あるか」で見る。実機では名刺の 1〜2 辺が白いシャツや手のひらに重なる。

    段差は「その点のちょうど上」ではなく window ピクセルの範囲で探す。エッジの
    途切れを埋めるクロージングで輪郭が数 px 外へ膨らむため、当てはめた辺は真の縁から
    少しずれる。厳密に同じ画素を見ると、正しい四角形でも段差なしと判定してしまう。
    """
    if window is None:
        window = int(settings.get("detection.edge_support_window"))
    h, w = gray.shape[:2]
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    total = 0
    supported = 0
    for i in range(4):
        ax, ay = quad[i]
        bx, by = quad[(i + 1) % 4]
        length = math.hypot(bx - ax, by - ay)
        n = max(4, min(60, int(length / 4)))
        for k in range(n):
            t = (k + 0.5) / n
            x = int(round(ax + (bx - ax) * t))
            y = int(round(ay + (by - ay) * t))
            if not (0 <= x < w and 0 <= y < h):
                continue
            total += 1
            y0, y1 = max(0, y - window), min(h, y + window + 1)
            x0, x1 = max(0, x - window), min(w, x + window + 1)
            if grad[y0:y1, x0:x1].max() >= thresh:
                supported += 1
    if total == 0:
        return 0.0
    return supported / total


def skin_ratio(bgr, quad: Quad) -> float:
    """四角形の内側のうち、肌の色をしている画素の割合 0-1。

    キオスクでは利用者が名刺を顔の前に持つので、顔・首・手のひらが候補として
    出てくる。顔の輪郭には本物の段差があり、肌にも文字らしい細かい模様が出るため、
    辺の裏付けや文字領域の条件だけでは落ちない。名刺の内側が肌色で埋まることは
    ないので、これで人物を落とす。

    取り違えたときの損得は大きく非対称になる。顔を名刺と誤検出しても、撮影後の
    受理判定で弾かれて撮り直すだけで済む。一方、本物の名刺を肌と誤判定すると
    その名刺は永久に読み取れない。だから候補を落とすこちら側は
    skin_reject_luma_max（厳しい側）を使い、「明らかに肌」だけに絞る。

    しきい値の根拠。暖色の紙は色域では肌と分けられない（生成り・クラフト紙で
    Cr-Cb=24-33 に対し肌は 30-40）。分かれるのは明るさで、紙は肌より明るい:

      生成り・クラフト紙の名刺   Y=170-225
      実機の録画での肌           Y 中央値 53 / 95 パーセンタイル 110

    既定の 165 はこの間に置いてある。上げると生成りの名刺が読み取れなくなるので、
    顔の誤検出が気になっても下げる方向で調整すること。
    """
    warped = warp_card(bgr, quad, width=160)
    if warped is None or warped.size == 0:
        return 0.0
    skin = _skin_bool(warped, settings.get("detection")["skin_reject_luma_max"])
    return float(np.count_nonzero(skin)) / float(skin.size)


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
        return Detection(quad=quad, metrics=det.metrics, score=det.score,
                         source=det.source)  # type: ignore[arg-type]
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

    close_k = max(3, int(d["close_kernel"]) | 1)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_k, close_k))
    best_overall: Detection | None = None
    # 「名刺ではない別の物体がはっきり写っている」ことの記録（文字ベース検出の抑止）
    veto: list = []
    stop_area = float(d["strategy_stop_area"])
    # 肌の境目は予備の戦略でしか使わないので、肌がほとんど写っていないフレーム
    # （＝検出ループの大半）ではモルフォロジーまで進まずに切り上げる。
    skin_edges = None
    if bool(d["use_skin_boundary"]) and has_skin(bgr):
        skin_edges = skin_boundary_edges(bgr)
    for _name, make_edges in _edge_strategies(gray, d, skin_edges):
        edges = make_edges()
        # 途切れた輪郭をつなぐ。実機では名刺の 1 辺が背景（手のひら・白い壁）と
        # 同系色になって数 px〜十数 px 途切れる。膨張だけでは埋まらないので
        # クロージング（膨張→収縮）で穴を閉じてから輪郭を拾う。
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, close_kernel)
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
        found = _best_quad(bgr, gray, edges, frame_area, d, prev_quad, veto)
        if found is not None and (best_overall is None or found.score > best_overall.score):
            best_overall = found
        # 名刺らしい大きさで見つかったらそこで打ち切る。小さな四角形（名刺の中の
        # 枠線や背景の一部）で止めてしまうと、本体を見つける機会を失う。
        if best_overall is not None and best_overall.metrics.area_ratio >= stop_area:
            break
    if best_overall is not None:
        return best_overall
    if veto:
        # A4 の書類やスマートフォンの画面のように、外形がはっきり測れていて
        # かつ名刺の形ではないものが写っている。その上の文字を名刺と見ない。
        return None
    # 紙の縁では四角形が組めなかった。名刺を手に持つと縁が指・逆光・同系色の
    # 背景で消えるので、実機ではここに落ちてくるほうが多い。文字の並びから
    # 位置を決め直す（card/text_detect.py）。
    from card.text_detect import detect_by_text
    return detect_by_text(bgr)


def _best_quad(bgr, gray, edges, frame_area: float, d: dict,
               prev_quad: Quad | None, veto: list | None = None) -> Detection | None:
    """1 つのエッジ画像から最良の名刺候補を選ぶ。条件を満たすものが無ければ None。

    veto を渡すと「はっきりした外形を持つのに名刺の形ではないもの」（A4 の書類、
    スマートフォンの画面など）をそこへ記録する。文字ベースの検出は紙の縁を見ない
    ので、こうした物体の上の文字を名刺と取り違えうる。外形が測れている以上は
    「名刺ではない」と判定できるので、その根拠として使う。
    """
    h, w = bgr.shape[:2]
    # 辺の裏付けを測るしきい値も、画像ごとのノイズ床に合わせる（固定値では
    # コントラストの低い名刺と、ノイズの多い映像を同時に扱えない）。
    # 段差を測る画像は、輪郭を拾ったのと同じ「正規化後」のものを使う。生の輝度で
    # 測ると、暗所の名刺（縁の差が 5 程度しかない）で段差なしと判定してしまう。
    support_gray = _stretch(gray, float(d["normalize_lo_pct"]), float(d["normalize_hi_pct"]))
    base = cv2.morphologyEx(support_gray, cv2.MORPH_GRADIENT,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    edge_thresh = max(float(d["gradient_thresh"]),
                      float(np.percentile(base, 85)) * float(d["edge_support_mult"]))
    contours = _find_contours(edges)
    if contours is None or len(contours) == 0:
        return None
    # 並べ替えは輪郭そのものの面積ではなく凸包の面積で行う。名刺の輪郭は断片に
    # なりがちで、面積で並べると候補から漏れる（実測: 断片の面積比 0.026 に対し
    # 凸包は 0.240）。凸包の面積なら、途切れていても名刺が上位に来る。
    contours = sorted(contours, key=lambda c: cv2.contourArea(cv2.convexHull(c)),
                      reverse=True)[: int(d["max_candidates"])]

    margin = float(d["margin_px"])
    best: Detection | None = None

    for cnt in contours:
        for quad in _quad_candidates(cnt, float(d["approx_epsilon"])):
            if bool(d["refine_corners"]):
                quad = refine_quad(cnt, quad)

            area_ratio = quad_area(quad) / frame_area
            if not (float(d["min_area_ratio"]) <= area_ratio <= float(d["max_area_ratio"])):
                continue

            aspect = quad_aspect(quad)
            angles = quad_angles(quad)
            if not (float(d["aspect_min"]) <= aspect <= float(d["aspect_max"])):
                # 名刺の形ではない。ただし大きくて四隅が直角に近く、辺に本当の
                # 段差があるなら「別の物体がはっきり写っている」ことの証拠になる。
                if (veto is not None and not veto
                        and area_ratio >= float(d["text_veto_min_area"])
                        and all(60.0 <= a <= 120.0 for a in angles)):
                    sup = edge_support(support_gray, quad, edge_thresh,
                                       window=int(d["edge_support_window"]))
                    if sup >= float(d["text_veto_support"]):
                        veto.append((area_ratio, aspect, sup))
                continue

            lo, hi = float(d["min_corner_angle_deg"]), float(d["max_corner_angle_deg"])
            if any(a < lo or a > hi for a in angles):
                continue

            # 画面の縁に達している候補は捨てる。背景の雑多なエッジを凸包でつなぐと
            # 画面いっぱいの四角形ができやすく、これを残すと誤検出になる。
            # 本当に名刺が見切れている場合は「枠内に入れてください」で足りる。
            if not all(margin <= x <= (w - margin) and margin <= y <= (h - margin)
                       for x, y in quad):
                continue

            # 直前のフレームと同じ位置にあるなら、辺の裏付けの条件を緩める。
            # 手に持った名刺は 1 辺が手のひらや服に重なって段差が消えることがあり、
            # 毎フレーム同じ厳しさを求めると検出が点滅して静止判定が積み上がらない。
            # 一度きちんと見つけた場所の近くだけを緩めるので、誤検出は増えにくい。
            required = float(d["min_edge_support"])
            if prev_quad is not None:
                moved = quad_motion(prev_quad, quad, float(min(h, w)))
                if moved < float(d["track_motion_max"]):
                    required *= float(d["track_support_relax"])

            support = edge_support(support_gray, quad, edge_thresh,
                                   window=int(d["edge_support_window"]))
            if support < required:
                continue

            if skin_ratio(bgr, quad) > float(d["max_skin_ratio"]):
                continue          # 顔や手のひらを名刺と取り違えない

            regions, rows = count_text_regions(bgr, quad)
            if regions < int(d["min_text_regions"]) or rows < 2:
                continue

            # スコア: 大きさ・長方形らしさ・辺の裏付け・文字量・前フレームとの近さ。
            # 大きさを重く見るのは、画面の片隅の小さな四角形（名刺の中の枠線など）が
            # 名刺本体に勝ってしまわないようにするため。名刺は普通いちばん大きい。
            rect_score = 1.0 - min(1.0, sum(abs(a - 90.0) for a in angles) / 120.0)
            size_score = min(1.0, area_ratio / 0.35)
            text_score = min(1.0, regions / 24.0)
            stick = 0.0
            if prev_quad is not None:
                short = float(min(h, w))
                stick = max(0.0, 1.0 - quad_motion(prev_quad, quad, short) * 12.0) * 0.15
            score = (0.25 * rect_score + 0.30 * size_score + 0.20 * text_score
                     + 0.25 * support + stick)

            metrics = FrameMetrics(
                area_ratio=area_ratio,
                aspect=aspect,
                text_regions=regions,
            )
            cand = Detection(quad=quad, metrics=metrics, score=round(score, 4))
            if best is None or cand.score > best.score:
                best = cand
            # 十分に確からしい候補が出たら残りは見ない。候補は凸包の面積の降順に
            # 並んでいるので、名刺は普通ここで見つかる。実機の雑然とした背景では
            # 候補が 10 本以上出ることがあり、全部に文字領域や肌色の判定をかけると
            # 1 フレームの処理が検出間隔に間に合わなくなる。
            if best.score >= float(d["candidate_stop_score"]):
                return best

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
