"""実機調整用のフレーム保存。**既定では何もしない。**

名刺読み取りは「画像を端末にもサーバにも保存しない」のが前提（CARD_READER.md §12）。
それでも実機で読み取れない原因を追うには、**端末が実際に OCR へ渡している画像**が要る。
画面録画は縮小プレビューの再エンコードなので、検出範囲の善し悪しは分かっても
OCR の精度は測れない（それで一度、誤った結論に進みかけた）。

そのための逃げ道をここに 1 つだけ用意する。性質上、**書き出すのは個人情報そのもの**
なので、次の条件を守る:

  - 既定は無効（`debug.dump_dir` が空）。設定を書かない限り 1 バイトも書かない
  - 有効な間は保存のたびに警告ログを出す。黙って溜まることがない
  - 件数に上限を置き、古いものから消す（SD カードを埋めない）
  - 調整が終わったらフォルダごと削除する。`purge()` でも消せる
  - ここでの失敗は読み取りを止めない（調整の道具が本番を壊さない）

書き出すもの（1 回の撮影につき 4 ファイル）:

  NNN_capture.jpg  ブラウザから届いた撮影画像そのもの（検出はこれに対して行う）
  NNN_region.jpg   その画像に検出した四隅を描いたもの（範囲の当たり外れが一目で分かる）
  NNN_card.jpg     台形補正後＝ OCR が実際に読んだ画像
  NNN.json         検出の指標・抽出した項目と確からしさ・所要時間
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from card import settings

log = logging.getLogger(__name__)

_lock = threading.Lock()
_warned = False
_seq = 0
_NAME_RE = re.compile(r"^(\d{4})_capture\.jpg$")


def target_dir() -> Path | None:
    """保存先。設定が空なら None（＝無効）。"""
    raw = str(settings.get("debug.dump_dir") or "").strip()
    if not raw:
        return None
    return settings.resolve_path(raw)


def enabled() -> bool:
    return target_dir() is not None


def _next_seq(d: Path) -> int:
    """既存のファイルの続きから番号を振る（再起動しても上書きしない）。"""
    global _seq
    if _seq == 0:
        used = [int(m.group(1)) for f in d.glob("*_capture.jpg")
                if (m := _NAME_RE.match(f.name))]
        _seq = max(used, default=0)
    _seq += 1
    return _seq


def _rotate(d: Path, keep: int) -> None:
    """古い撮影から順に消す。1 回の撮影に付随する 4 ファイルをまとめて消す。"""
    stems = sorted(m.group(1) for f in d.glob("*_capture.jpg")
                   if (m := _NAME_RE.match(f.name)))
    for stem in stems[:max(0, len(stems) - keep)]:
        for f in d.glob(stem + "*"):
            try:
                f.unlink()
            except OSError:
                pass


def _draw_region(image, quad) -> Any:
    vis = image.copy()
    if quad:
        pts = np.array([[int(x), int(y)] for x, y in quad], np.int32)
        cv2.polylines(vis, [pts], True, (0, 255, 0), 3)
        for x, y in quad:
            cv2.circle(vis, (int(x), int(y)), 7, (0, 0, 255), -1)
    return vis


def save_capture(image, detection, result, extra: dict | None = None) -> None:
    """撮影 1 回ぶんを書き出す。無効なら即座に戻る。**例外は外に出さない。**"""
    global _warned
    try:
        d = target_dir()
        if d is None:
            return
        with _lock:
            d.mkdir(parents=True, exist_ok=True)
            if not _warned:
                _warned = True
                log.warning(
                    "[card] フレーム保存が有効です（個人情報を書き出します）: %s "
                    "— 調整が終わったらフォルダごと削除してください", d,
                )
            n = _next_seq(d)
            stem = f"{n:04d}"
            q = int(settings.get("debug.dump_jpeg_quality") or 92)
            enc = [cv2.IMWRITE_JPEG_QUALITY, q]

            # **cv2.imwrite は使わない。** Windows では非 ASCII を含むパスに対して
            # 例外を投げずに False を返すだけで、ファイルが黙って作られない
            # （保存先フォルダ名に日本語が入ると起きる）。encode してから書く。
            _write(d / f"{stem}_capture.jpg", image, enc)
            quad = detection.quad if detection is not None else None
            _write(d / f"{stem}_region.jpg", _draw_region(image, quad), enc)
            if result is not None and result.card_jpeg:
                (d / f"{stem}_card.jpg").write_bytes(result.card_jpeg)

            h, w = image.shape[:2]
            meta: dict[str, Any] = {
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "capture_size": {"width": w, "height": h},
                "detection": None,
                "result": None,
            }
            if detection is not None:
                m = detection.metrics
                meta["detection"] = {
                    "source": detection.source,
                    "quad": [[round(float(x), 1), round(float(y), 1)] for x, y in detection.quad],
                    # 外接矩形が画面に占める割合。背景まで掴んでいると 1 に近づく
                    "cover_ratio": round(_cover(detection.quad, w, h), 3),
                    "area_ratio": round(float(m.area_ratio), 4),
                    "fill_ratio": round(float(m.fill_ratio), 4),
                    "aspect": round(float(m.aspect), 3),
                    "text_regions": m.text_regions,
                    "text_height_px": round(float(m.text_height), 1),
                    "text_clipped": m.text_clipped,
                }
            if result is not None:
                meta["result"] = {
                    "engine": result.engine,
                    "variant": result.variant,
                    "variants_tried": result.tried,
                    "rotation": result.rotation,
                    "overall": round(float(result.overall), 3),
                    "line_count": len(result.lines),
                    "card_size": {"width": result.card_size[0], "height": result.card_size[1]},
                    "timings_ms": result.timings_ms,
                    # as_dict() は {項目名: {value, confidence, candidates?}} を返す
                    "fields": result.fields.as_dict(),
                    "lines": [l.text for l in result.lines],
                }
            if extra:
                meta.update(extra)
            (d / f"{stem}.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            _rotate(d, max(1, int(settings.get("debug.dump_max_captures") or 40)))
            log.warning("[card] フレームを保存しました: %s (%s)", d / f"{stem}_capture.jpg", stem)
    except Exception as e:  # 調整の道具が読み取りを止めないこと
        log.warning("[card] フレーム保存に失敗（読み取りは続行）: %s", e)


def _write(path: Path, image, enc) -> None:
    ok, buf = cv2.imencode(".jpg", image, enc)
    if not ok:
        raise RuntimeError(f"JPEG に変換できませんでした: {path.name}")
    path.write_bytes(buf.tobytes())


def _cover(quad, w: int, h: int) -> float:
    if not quad or w <= 0 or h <= 0:
        return 0.0
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return ((max(xs) - min(xs)) * (max(ys) - min(ys))) / float(w * h)


def purge() -> int:
    """保存済みのファイルを消す。消した件数を返す。"""
    d = target_dir()
    if d is None or not d.exists():
        return 0
    n = 0
    for f in list(d.iterdir()):
        if f.is_file():
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    global _seq
    _seq = 0
    return n
