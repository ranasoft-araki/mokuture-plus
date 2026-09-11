"""PaddleOCR の軽量モデルを ONNX Runtime で実行するエンジン（第一候補）。

PaddleOCR 本体（paddlepaddle）は入れない。ONNX へ変換済みの
  - 検出 (DB / PP-OCRv4 mobile det)
  - 認識 (japan PP-OCRv4 mobile rec, 日本語+英数字)
  - 方向分類 (任意, 180 度の上下逆を直す)
を onnxruntime で直接動かす。モデルの取得は scripts/fetch_ocr_models.py（導入時のみ・
以後はオフライン）。

前処理・後処理は PaddleOCR の推論実装に合わせてある。ずらすと精度が落ちるので、
定数を変える場合は必ず tests/test_ocr_paddle.py の実画像テストで確認すること。
DB の unclip は pyclipper を使わず、最小外接矩形を外側へ offset する形で行う
（矩形に対しては pyclipper の結果と一致し、依存を 1 つ減らせる）。
"""
from __future__ import annotations

import logging
import math
import re
import threading

import cv2
import numpy as np

from card import settings
from card.ocr.base import OcrEngine, OcrUnavailable, sort_reading_order
from card.types import OcrLine

log = logging.getLogger(__name__)

# 検出モデルの正規化定数（PaddleOCR の NormalizeImage と同じ。入力は BGR のまま）
_DET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_DET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


# 全角記号・かな・漢字の範囲
_CJK_RANGES = (
    (0x3000, 0x30FF),   # 全角記号・ひらがな・カタカナ
    (0x3400, 0x4DBF),   # CJK 拡張A
    (0x4E00, 0x9FFF),   # CJK 統合漢字
    (0xF900, 0xFAFF),   # CJK 互換漢字
    (0xFF00, 0xFFEF),   # 全角英数・半角カナ
)

# ドメインらしい並び（"example.jp" / "example.com" など）。空白を含まない塊の中に
# ドットがあり、そのあとに 2 文字以上の英字が続くもの。
_DOMAINISH = re.compile(r"\S+\.[A-Za-z]{2,}")


def _has_cjk(text: str) -> bool:
    """漢字・ひらがな・カタカナ・全角記号を含むか。"""
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in _CJK_RANGES)


def _ascii_pass_targets(results: dict, limit: int) -> list[int]:
    """英数字モデルで読み直す行を選ぶ。

    日本語モデルに足りないのは "@" と "_" だけなので、メール・URL になり得る行に
    絞る。ただし日本語モデルがひどく崩して読むと（"...@example.jp" が
    "ft txample. jp" のように空白混じりになる）ドメインの形に見えなくなるため、
    「CJK を含まず、どこかにドットがある」行まで広げたうえで本数を絞る。
    英文の社名や住所まで全部読み直すと認識時間がほぼ倍になる。
    """
    scored: list[tuple[int, int, int]] = []
    for i, (text, _conf) in results.items():
        if not text or _has_cjk(text):
            continue
        if _DOMAINISH.search(text):
            priority = 0                 # ドメインの形をしている＝メール/URL の可能性大
        elif "." in text:
            priority = 1                 # 崩れているがドットはある
        else:
            continue                     # ドットが無い行に "@" は入っていない
        scored.append((priority, -len(text), i))
    scored.sort()
    return [i for _p, _l, i in scored[:max(1, limit)]]


def _import_ort():
    try:
        import onnxruntime  # type: ignore
        return onnxruntime, ""
    except Exception as e:       # pragma: no cover - 環境依存
        return None, f"onnxruntime not importable ({type(e).__name__})"


class PaddleOnnxEngine(OcrEngine):
    name = "paddle_onnx"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._det = None
        self._rec = None
        self._rec_en = None
        self._cls = None
        self._charset: list[str] = []
        self._charset_en: list[str] = []
        self._loaded = False
        self._reason = "not loaded"

    # ── 準備 ──────────────────────────────────────────────────────────────────

    def _cfg(self) -> dict:
        return settings.get("ocr.paddle_onnx")

    def available(self) -> tuple[bool, str]:
        ort, err = _import_ort()
        if ort is None:
            return False, err
        c = self._cfg()
        for key in ("det_model", "rec_model", "rec_dict"):
            p = settings.resolve_path(str(c[key]))
            if not p.exists():
                return False, f"missing {key}: {p.name} (run scripts/fetch_ocr_models.py)"
        if self._loaded:
            return True, "ready"
        return True, "models present"

    def _session(self, ort, path):
        opts = ort.SessionOptions()
        threads = int(settings.get("ocr.threads"))
        opts.intra_op_num_threads = max(1, threads)
        opts.inter_op_num_threads = 1
        # Pi では並列化しすぎると UI 側のフレーム処理が詰まる。明示的に絞る。
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            ok, reason = self.available()
            if not ok:
                self._reason = reason
                raise OcrUnavailable(reason)
            ort, _ = _import_ort()
            c = self._cfg()
            self._det = self._session(ort, settings.resolve_path(str(c["det_model"])))
            self._rec = self._session(ort, settings.resolve_path(str(c["rec_model"])))
            cls_path = str(c.get("cls_model") or "")
            if cls_path:
                p = settings.resolve_path(cls_path)
                if p.exists():
                    self._cls = self._session(ort, p)

            self._charset = self._load_charset(str(c["rec_dict"]), bool(c.get("use_space_char", True)))
            out_dim = self._rec.get_outputs()[0].shape[-1]
            if isinstance(out_dim, int) and out_dim != len(self._charset):
                self._reason = f"charset size {len(self._charset)} != model classes {out_dim}"
                raise OcrUnavailable(self._reason)

            # 英数字専用モデル（任意）。日本語モデルの文字セットには "@" や "_" が
            # 無く、メールアドレスを原理的に出力できないため、CJK を含まない行だけを
            # こちらで読み直す。無ければその行は補正規則側で処理する。
            en_model = str(c.get("rec_model_en") or "")
            en_dict = str(c.get("rec_dict_en") or "")
            if en_model and en_dict:
                mp, dp = settings.resolve_path(en_model), settings.resolve_path(en_dict)
                if mp.exists() and dp.exists():
                    try:
                        self._rec_en = self._session(ort, mp)
                        self._charset_en = self._load_charset(en_dict, True)
                        en_dim = self._rec_en.get_outputs()[0].shape[-1]
                        if isinstance(en_dim, int) and en_dim != len(self._charset_en):
                            log.warning("[card] en rec charset mismatch; disabled")
                            self._rec_en = None
                    except Exception as e:
                        log.warning("[card] en rec model unusable: %s", type(e).__name__)
                        self._rec_en = None

            self._loaded = True
            self._reason = "ready"

    @staticmethod
    def _load_charset(rel: str, use_space: bool) -> list[str]:
        chars = settings.resolve_path(rel).read_text(encoding="utf-8").split("\n")
        if chars and chars[-1] == "":
            chars = chars[:-1]
        # PaddleOCR の CTCLabelDecode と同じ並び: [blank] + 辞書 + (空白)
        charset = ["blank"] + chars
        if use_space:
            charset.append(" ")
        return charset

    def warmup(self) -> None:
        try:
            self._ensure_loaded()
            self.run(np.full((64, 320, 3), 240, dtype=np.uint8))
        except Exception as e:
            log.info("[card] paddle_onnx warmup skipped: %s", type(e).__name__)

    # ── 検出 (DB) ─────────────────────────────────────────────────────────────

    def _det_preprocess(self, bgr):
        limit = int(self._cfg()["det_limit_side_len"])
        h, w = bgr.shape[:2]
        ratio = min(1.0, limit / float(max(h, w)))
        rh = max(32, int(round(h * ratio / 32) * 32))
        rw = max(32, int(round(w * ratio / 32) * 32))
        resized = cv2.resize(bgr, (rw, rh), interpolation=cv2.INTER_LINEAR)
        x = resized.astype(np.float32) / 255.0
        x = (x - _DET_MEAN) / _DET_STD
        x = x.transpose(2, 0, 1)[None, ...]
        return np.ascontiguousarray(x), (w / float(rw), h / float(rh))

    @staticmethod
    def _box_score(prob_map, box) -> float:
        """PaddleOCR の box_score_fast 相当。枠内の確率平均。"""
        h, w = prob_map.shape
        xs = np.clip(np.floor(box[:, 0]).astype(np.int32), 0, w - 1)
        ys = np.clip(np.floor(box[:, 1]).astype(np.int32), 0, h - 1)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        if x1 < x0 or y1 < y0:
            return 0.0
        mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.uint8)
        shifted = box.copy()
        shifted[:, 0] -= x0
        shifted[:, 1] -= y0
        cv2.fillPoly(mask, [shifted.astype(np.int32)], 1)
        region = prob_map[y0:y1 + 1, x0:x1 + 1]
        if region.size == 0 or mask.sum() == 0:
            return 0.0
        return float(cv2.mean(region, mask)[0])

    @staticmethod
    def _unclip(rect, ratio: float):
        """最小外接矩形を外側へ広げる。

        pyclipper の PyclipperOffset(JT_ROUND, ET_CLOSEDPOLYGON) を矩形に適用したときの
        オフセット量 d = area * ratio / perimeter と同じ式を使い、幅と高さを 2d 増やす。
        """
        (cx, cy), (w, h), angle = rect
        if w <= 0 or h <= 0:
            return None
        area = w * h
        perimeter = 2.0 * (w + h)
        d = area * ratio / perimeter
        return ((cx, cy), (w + 2.0 * d, h + 2.0 * d), angle)

    def _det_postprocess(self, prob_map, scale) -> list[np.ndarray]:
        c = self._cfg()
        thresh = float(c["det_db_thresh"])
        box_thresh = float(c["det_db_box_thresh"])
        unclip_ratio = float(c["det_db_unclip_ratio"])
        min_side = float(c["det_min_box_side"])

        binary = (prob_map > thresh).astype(np.uint8)
        res = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = res[0] if len(res) == 2 else res[1]

        sx, sy = scale
        boxes: list[np.ndarray] = []
        for cnt in contours[:1000]:
            if len(cnt) < 4:
                continue
            rect = cv2.minAreaRect(cnt)
            if min(rect[1]) < min_side:
                continue
            pts = cv2.boxPoints(rect)
            if self._box_score(prob_map, pts) < box_thresh:
                continue
            grown = self._unclip(rect, unclip_ratio)
            if grown is None or min(grown[1]) < min_side + 2:
                continue
            box = cv2.boxPoints(grown)
            box[:, 0] *= sx
            box[:, 1] *= sy
            boxes.append(box.astype(np.float32))
        return boxes

    # ── 認識 (CRNN + CTC) ─────────────────────────────────────────────────────

    @staticmethod
    def _order_box(box: np.ndarray) -> np.ndarray:
        """4 点を 左上→右上→右下→左下 に並べる（PaddleOCR の順に合わせる）。"""
        pts = np.array(box, dtype=np.float32).reshape(4, 2)
        s = pts.sum(axis=1)
        diff = pts[:, 1] - pts[:, 0]
        return np.array([
            pts[int(np.argmin(s))],
            pts[int(np.argmin(diff))],
            pts[int(np.argmax(s))],
            pts[int(np.argmax(diff))],
        ], dtype=np.float32)

    @staticmethod
    def _crop_rotated(bgr, box: np.ndarray):
        """PaddleOCR の get_rotate_crop_image 相当。枠を正対した短冊に起こす。

        縦長のまま返す（ここでは回さない）。縦長の枠は「縦書きの列」かもしれないし
        「倒れた横書きの行」かもしれず、画像だけでは決められない。どちらなのかは
        run() が両方読んでみて確信度の高いほうを採る。
        """
        pts = box.astype(np.float32)
        w = int(max(
            np.linalg.norm(pts[0] - pts[1]),
            np.linalg.norm(pts[2] - pts[3]),
        ))
        h = int(max(
            np.linalg.norm(pts[0] - pts[3]),
            np.linalg.norm(pts[1] - pts[2]),
        ))
        if w < 2 or h < 2:
            return None
        dst = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        m = cv2.getPerspectiveTransform(pts, dst)
        crop = cv2.warpPerspective(
            bgr, m, (w, h), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC
        )
        return np.ascontiguousarray(crop)

    @staticmethod
    def _split_vertical(crop, max_cells: int = 40) -> list:
        """縦書きの列を 1 文字ずつのマスに切る。

        1 文字ずつなら向きを変えずにそのまま認識器へ渡せる。切れ目は字間の空白で
        探す。列の幅で等分する方法は、字間が空いている組み方だと 1 文字ぶんずれて
        以降が全部ずれるので、空白が見つかるならそちらを優先する。
        """
        h, w = crop.shape[:2]
        if w < 4 or h < 4:
            return []

        cuts = PaddleOnnxEngine._vertical_cuts(crop)
        if not cuts:
            # 空白が見つからない（字が詰まっている）。全角の字送りを仮定して等分する。
            n = max(1, min(int(round(h / float(w))), max_cells))
            step = h / float(n)
            cuts = [(int(round(i * step)), int(round((i + 1) * step) if i < n - 1 else h))
                    for i in range(n)]

        pad = max(2, int(w * 0.12))        # 認識器は字の周りに少し余白があるほうが強い
        cells = []
        for y0, y1 in cuts[:max_cells]:
            a, b = max(0, y0 - pad), min(h, y1 + pad)
            if b - a < 4:
                continue
            cell = crop[a:b, :]
            cell = cv2.copyMakeBorder(cell, 0, 0, pad, pad, cv2.BORDER_REPLICATE)
            cells.append(np.ascontiguousarray(cell))
        return cells

    @staticmethod
    def _vertical_cuts(crop) -> list[tuple[int, int]]:
        """縦書きの列を字ごとに区切る位置を、行方向の空白から求める。

        見つからない（字間が無い / 判定できない）場合は空リストを返す。
        """
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        h, w = gray.shape[:2]
        # 文字は背景より暗いとは限らない（濃地に白文字）。振れ幅の大きいほうを字とみなす。
        mid = float(np.median(gray))
        ink = (np.abs(gray.astype(np.float32) - mid) > 28).sum(axis=1)
        if ink.max() <= 0:
            return []
        filled = ink > max(1.0, ink.max() * 0.12)

        runs: list[tuple[int, int]] = []
        start = None
        for y in range(h):
            if filled[y] and start is None:
                start = y
            elif not filled[y] and start is not None:
                runs.append((start, y))
                start = None
        if start is not None:
            runs.append((start, h))

        # 小さすぎる塊（濁点・句読点など）は前の字にくっつける
        merged: list[list[int]] = []
        for a, b in runs:
            if merged and (a - merged[-1][1]) < w * 0.25 and (b - a) < w * 0.45:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        out = [(a, b) for a, b in merged if b - a >= max(3, int(w * 0.25))]
        if len(out) < 2:
            return []
        # 字送りが極端にばらつくなら空白の読み違い。等分割に任せる。
        sizes = [b - a for a, b in out]
        if max(sizes) > min(sizes) * 3.0:
            return []
        return out

    def _rec_resize(self, crop, target_h: int, max_wh_ratio: float):
        h, w = crop.shape[:2]
        ratio = w / float(max(1, h))
        target_w = int(math.ceil(target_h * min(ratio, max_wh_ratio)))
        target_w = max(target_h // 2, target_w)
        resized = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        x = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
        x -= 0.5
        x /= 0.5
        return x

    @staticmethod
    def _ctc_decode(probs, charset: list[str]) -> tuple[str, float]:
        idx = probs.argmax(axis=1)
        conf = probs.max(axis=1)
        chars: list[str] = []
        scores: list[float] = []
        prev = -1
        for t, i in enumerate(idx):
            i = int(i)
            if i == prev:
                continue
            prev = i
            if i == 0:                     # blank
                continue
            if i < len(charset):
                chars.append(charset[i])
                scores.append(float(conf[t]))
        if not chars:
            return "", 0.0
        return "".join(chars), float(np.mean(scores))

    def _recognize(self, session, charset, crops, indices, batch_size: int | None = None) -> dict[int, tuple[str, float]]:
        """指定した crop 群を 1 つのモデルで認識し {index: (text, conf)} を返す。"""
        c = self._cfg()
        target_h = int(c["rec_image_height"])
        batch = max(1, int(batch_size if batch_size else c["rec_batch"]))
        rec_in = session.get_inputs()[0].name
        out: dict[int, tuple[str, float]] = {}

        # 幅の近いものをまとめてバッチにする（パディングの無駄を減らす）
        order = sorted(indices, key=lambda i: crops[i].shape[1] / max(1, crops[i].shape[0]))
        for start in range(0, len(order), batch):
            chunk = order[start:start + batch]
            max_ratio = max(crops[i].shape[1] / max(1.0, crops[i].shape[0]) for i in chunk)
            max_ratio = min(max_ratio, 25.0)
            tensors = [self._rec_resize(crops[i], target_h, max_ratio) for i in chunk]
            width = max(t.shape[2] for t in tensors)
            padded = np.zeros((len(tensors), 3, target_h, width), dtype=np.float32)
            for n, t in enumerate(tensors):
                padded[n, :, :, : t.shape[2]] = t
            preds = session.run(None, {rec_in: padded})[0]
            for n, i in enumerate(chunk):
                out[i] = self._ctc_decode(preds[n], charset)
        return out

    def _recognize_vertical(self, bgr, boxes: list) -> list[tuple[str, float]]:
        """縦書きの列として読む。列を 1 文字ずつに切り、上から順に連結する。

        1 文字ずつなら向きを変えずに認識器へ渡せる（列ごと 90 度回すと、文字が
        横倒しになってほとんど読めない）。
        """
        cells: list = []
        spans: list[tuple[int, int]] = []
        for box in boxes:
            crop = self._crop_rotated(bgr, box)
            start = len(cells)
            if crop is not None:
                cells.extend(self._split_vertical(crop))
            spans.append((start, len(cells)))

        if not cells:
            return [("", 0.0) for _ in boxes]

        # マスはどれも 1 文字ぶんの小さな正方形なので、まとめて流したほうが速い
        # （既定のバッチ 6 のままだと縦書きの名刺で OCR が 3 倍近くかかる）。
        decoded = self._recognize(
            self._rec, self._charset, cells, list(range(len(cells))),
            batch_size=int(self._cfg().get("vertical_batch", 32)),
        )
        out: list[tuple[str, float]] = []
        for start, end in spans:
            chars, confs = [], []
            for i in range(start, end):
                text, conf = decoded.get(i, ("", 0.0))
                text = text.strip()
                if not text:
                    continue
                chars.append(text)
                confs.append(conf)
            out.append(("".join(chars), float(np.mean(confs)) if confs else 0.0))
        return out

    def _classify_direction(self, crops: list) -> tuple[list, int]:
        """任意の方向分類モデルで 180 度の上下逆を直す。(crops, 反転した本数) を返す。"""
        if self._cls is None or not crops:
            return crops, 0
        out = []
        flipped = 0
        name = self._cls.get_inputs()[0].name
        for crop in crops:
            x = cv2.resize(crop, (192, 48), interpolation=cv2.INTER_LINEAR)
            x = x.astype(np.float32).transpose(2, 0, 1) / 255.0
            x -= 0.5
            x /= 0.5
            pred = self._cls.run(None, {name: x[None, ...]})[0][0]
            # 出力は [0度の確率, 180度の確率]
            if len(pred) >= 2 and float(pred[1]) > 0.9:
                crop = cv2.rotate(crop, cv2.ROTATE_180)
                flipped += 1
            out.append(crop)
        return out, flipped

    # ── 実行 ──────────────────────────────────────────────────────────────────

    def run(self, bgr) -> list[OcrLine]:
        self._ensure_loaded()
        c = self._cfg()
        if bgr is None or bgr.size == 0:
            return []
        if bgr.ndim == 2:
            bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)

        x, scale = self._det_preprocess(bgr)
        det_out = self._det.run(None, {self._det.get_inputs()[0].name: x})[0]
        prob_map = det_out[0, 0].astype(np.float32)
        boxes = self._det_postprocess(prob_map, scale)
        if not boxes:
            return []

        ordered = [self._order_box(b) for b in boxes]
        crops = []
        kept_boxes = []
        for box in ordered:
            crop = self._crop_rotated(bgr, box)
            if crop is None:
                continue
            crops.append(crop)
            kept_boxes.append(box)
        if not crops:
            return []

        # 縦長の枠は「縦書きの列」か「倒れた横書きの行」のどちらか。画像だけでは
        # 決められないので、両方読んで確信度の高いほうを採る（行ごとに判断する）。
        ratio = float(c.get("vertical_ratio", 1.5))
        vert_idx = [
            i for i, cr in enumerate(crops)
            if cr.shape[0] / max(1.0, cr.shape[1]) >= ratio
        ]
        # 横書きとして読むぶんは 90 度起こしてから通常経路に乗せる
        for i in vert_idx:
            crops[i] = np.ascontiguousarray(np.rot90(crops[i]))

        crops, flipped = self._classify_direction(crops)
        # 大半の行が上下逆だった＝名刺自体が 180 度回っている。画像を読み直さず、
        # 枠の座標を点対称に写して「正立したときの位置」に直す。これで読み取り順と
        # 項目抽出の位置判定（会社名は上、連絡先は下）が正しく働く。
        upside_down = len(crops) >= 3 and flipped >= len(crops) * 0.6
        if upside_down:
            h, w = bgr.shape[:2]
            kept_boxes = [
                np.array([[w - px, h - py] for px, py in box], dtype=np.float32)
                for box in kept_boxes
            ]

        results = self._recognize(self._rec, self._charset, crops, list(range(len(crops))))

        # 縦書きとしての読み（1 文字ずつのマスに切って上から連結）と比べる。
        # 実測では、縦書きの列を 90 度起こして 1 行として読む従来の経路のほうが
        # たいてい強い（文字が大きい列では 0.98 に達する）。1 文字ずつ読むのは
        # 前後の文脈が無くなるぶん弱い。そこで「起こして読んだ結果が怪しい列」
        # だけを対象にする。全部の列でやると縦書きの名刺で OCR が倍近くかかる。
        if vert_idx and bool(c.get("vertical_text", True)):
            weak = float(c.get("vertical_try_below", 0.75))
            targets = [i for i in vert_idx if results.get(i, ("", 0.0))[1] < weak]
            if targets:
                vertical = self._recognize_vertical(bgr, [kept_boxes[i] for i in targets])
                margin = float(c.get("vertical_margin", 0.05))
                for n, i in enumerate(targets):
                    v_text, v_conf = vertical[n]
                    h_text, h_conf = results[i]
                    # 明確に確からしいときだけ差し替える。同点なら従来の解釈を残す。
                    if v_text and v_conf > h_conf + margin:
                        results[i] = (v_text, v_conf)

        # CJK を含まない行（メール・URL・電話番号など）は英数字モデルで読み直す。
        # 日本語モデルの文字セットには "@" や "_" が無く、これらを含む文字列は
        # 原理的に正しく出力できないため。信頼度が大きく落ちない限り差し替える。
        if self._rec_en is not None:
            ascii_idx = _ascii_pass_targets(results, int(c.get("en_pass_max_lines", 4)))
            if ascii_idx:
                en = self._recognize(self._rec_en, self._charset_en, crops, ascii_idx)
                for i, (en_text, en_conf) in en.items():
                    jp_text, jp_conf = results[i]
                    if not en_text:
                        continue
                    gains_symbol = ("@" in en_text or "_" in en_text) and "@" not in jp_text
                    if gains_symbol or en_conf >= jp_conf * 0.9:
                        results[i] = (en_text, en_conf)

        drop = float(c["drop_score"])
        lines: list[OcrLine] = []
        for i, (text, conf) in results.items():
            text = text.strip()
            if not text or conf < drop:
                continue
            box = kept_boxes[i]
            quad = tuple((float(px), float(py)) for px, py in box)
            lines.append(OcrLine(text=text, box=quad, conf=conf, order=0))  # type: ignore[arg-type]

        return sort_reading_order(lines)
