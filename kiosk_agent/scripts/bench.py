"""実機（Raspberry Pi）での処理時間としきい値を測る。

    # 架空名刺で一連の処理時間を測る
    python3 scripts/bench.py

    # 実際に撮った写真で測る（推奨。実機のカメラ・照明の条件が入る）
    python3 scripts/bench.py --image /path/to/photo.jpg --runs 10

    # しきい値の調整用。ピント・明るさ・反射の実測値を出す
    python3 scripts/bench.py --image /path/to/photo.jpg --metrics

    # OCR エンジンの比較（paddle_onnx と tesseract）
    python3 scripts/bench.py --compare-engines

写真は個人情報なのでリポジトリに置かないこと。--image は端末上のファイルを
その場で読むだけで、どこにも保存しない。
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import cv2

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "tests"))

from card import settings                                   # noqa: E402
from card.detect import detect_card                          # noqa: E402
from card.extract import extract, overall_confidence         # noqa: E402
from card.ocr import ENGINE_NAMES, get_engine, reset         # noqa: E402
from card.preprocess import make_variant, rectify            # noqa: E402
from card.quality import evaluate                            # noqa: E402


def machine_info() -> str:
    model = ""
    try:
        model = Path("/proc/device-tree/model").read_text(errors="ignore").strip("\x00").strip()
    except OSError:
        pass
    cores = os.cpu_count() or 0
    mem = ""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                mem = f"{int(line.split()[1]) / 1024 / 1024:.1f}GB"
                break
    except OSError:
        pass
    parts = [p for p in (model, platform.machine(), f"{cores}コア", mem,
                         f"Python {platform.python_version()}") if p]
    return " / ".join(parts)


def rss_mb() -> float:
    """このプロセスの常駐メモリ(MB)。取れなければ 0。"""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def load_image(path: str | None):
    if path:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"画像を読めない: {path}")
        return img, Path(path).name
    import make_fixtures as mf
    import numpy as np
    pil, _quad, _spec = mf.build("landscape_ja")
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR), "landscape_ja(架空名刺)"


def stat_line(label: str, values: list[float]) -> str:
    if not values:
        return f"  {label:12} —"
    med = statistics.median(values)
    p95 = sorted(values)[min(len(values) - 1, int(len(values) * 0.95))]
    return (f"  {label:12} 中央値 {med:7.1f}ms  最小 {min(values):7.1f}  "
            f"最大 {max(values):7.1f}  95% {p95:7.1f}")


def bench_frames(bgr, runs: int) -> None:
    """検出ループ（カメラ映像 1 フレームあたり）の処理時間。"""
    width = int(settings.get("camera.detect_frame_max_width"))
    scale = width / bgr.shape[1]
    frame = cv2.resize(bgr, (width, int(bgr.shape[0] * scale))) if scale < 1 else bgr

    detect_ms, quality_ms = [], []
    prev = None
    for _ in range(runs):
        t = time.perf_counter()
        det = detect_card(frame, prev)
        detect_ms.append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()
        evaluate(frame, det, prev)
        quality_ms.append((time.perf_counter() - t) * 1000)
        prev = det.quad if det else None

    print(f"\n■ 検出ループ（{width}px のフレーム 1 枚あたり・{runs} 回）")
    print(stat_line("検出", detect_ms))
    print(stat_line("品質判定", quality_ms))
    total = statistics.median([a + b for a, b in zip(detect_ms, quality_ms)])
    interval = int(settings.get("camera.detect_interval_ms"))
    print(f"  合計の中央値 {total:.1f}ms / 送信間隔 {interval}ms "
          f"→ {'間に合っている' if total < interval else '間に合っていない（間隔を広げるか work_width を下げる）'}")


def bench_capture(bgr, runs: int, variant: str | None) -> None:
    """撮影後（台形補正 → OCR → 項目抽出）の処理時間。"""
    engine = get_engine()
    ok, reason = engine.available()
    if not ok:
        print(f"\n■ 撮影後: OCR が使えないため測れない（{reason}）")
        return
    engine.warmup()

    names = [variant] if variant else list(settings.get("preprocess.variants"))
    det = detect_card(bgr)
    pre_ms, ocr_ms, ext_ms, totals = [], [], [], []
    lines = []
    fields = None

    for _ in range(runs):
        t0 = time.perf_counter()
        card, _angle, _factor = rectify(bgr, det.quad if det else None)
        image = make_variant(card, names[0])
        t1 = time.perf_counter()
        lines = engine.run(image)
        t2 = time.perf_counter()
        fields = extract(lines, (card.shape[1], card.shape[0]))
        t3 = time.perf_counter()
        pre_ms.append((t1 - t0) * 1000)
        ocr_ms.append((t2 - t1) * 1000)
        ext_ms.append((t3 - t2) * 1000)
        totals.append((t3 - t0) * 1000)

    print(f"\n■ 撮影後（バリアント={names[0]} / {runs} 回）")
    print(stat_line("画像補正", pre_ms))
    print(stat_line("OCR", ocr_ms))
    print(stat_line("項目抽出", ext_ms))
    print(stat_line("合計", totals))
    med = statistics.median(totals)
    print(f"  目標 5000ms に対して {'達成' if med <= 5000 else '未達（README のボトルネック対処を参照）'}")
    print(f"  読めた行数 {len(lines)} / 埋まった項目 {fields.filled_count() if fields else 0} / "
          f"全体の信頼度 {overall_confidence(fields) if fields else 0}")
    if rss_mb():
        print(f"  常駐メモリ {rss_mb():.0f}MB")


def show_metrics(bgr) -> None:
    """しきい値調整用。実機の写真でピント・明るさ・反射がいくつになるかを出す。"""
    width = int(settings.get("camera.detect_frame_max_width"))
    scale = width / bgr.shape[1]
    frame = cv2.resize(bgr, (width, int(bgr.shape[0] * scale))) if scale < 1 else bgr
    det = detect_card(frame)
    state, m = evaluate(frame, det, det.quad if det else None)

    print("\n■ この写真の実測値（card_reader.yaml のしきい値と見比べる）")
    print(f"  判定           {state}")
    print(f"  ピント         {m.focus:8.1f}   （quality.focus_min = {settings.get('quality.focus_min')}）")
    print(f"  明るさ(上位5%) {m.brightness:8.1f}   （quality.brightness_min = {settings.get('quality.brightness_min')}）")
    print(f"  白飛び率       {m.glare_ratio:8.3f}   （quality.glare_max = {settings.get('quality.glare_max')}）")
    print(f"  占有率         {m.fill_ratio:8.3f}   （quality.capture_fill_min = {settings.get('quality.capture_fill_min')}）")
    print(f"  面積比         {m.area_ratio:8.3f}   （参考。向きで変わるので判定には使わない）")
    print(f"  縦横比         {m.aspect:8.3f}   （detection.aspect_min/max = "
          f"{settings.get('detection.aspect_min')}/{settings.get('detection.aspect_max')}）")
    print(f"  文字領域数     {m.text_regions:8d}   （detection.min_text_regions = {settings.get('detection.min_text_regions')}）")
    print("\n  ピントの値はカメラと照明で大きく変わる。ぼけた写真と合焦した写真の両方で")
    print("  測り、その間に quality.focus_min を置くこと。")


def compare_engines(bgr, runs: int) -> None:
    """OCR エンジンの比較（§16 の「OCR エンジンの比較結果」用）。"""
    det = detect_card(bgr)
    card, _a, _f = rectify(bgr, det.quad if det else None)
    image = make_variant(card, "color")

    print(f"\n■ OCR エンジンの比較（同じ画像・{runs} 回）")
    print(f"  {'エンジン':14} {'状態':10} {'中央値':>10} {'行数':>6} {'平均信頼度':>10} {'項目数':>7}")
    for name in ENGINE_NAMES:
        reset()
        engine = get_engine(name)
        ok, reason = engine.available()
        if not ok:
            print(f"  {name:14} {'使えない':10} {'—':>10} {'—':>6} {'—':>10} {'—':>7}   {reason}")
            continue
        engine.warmup()
        times, lines = [], []
        for _ in range(runs):
            t = time.perf_counter()
            lines = engine.run(image)
            times.append((time.perf_counter() - t) * 1000)
        fields = extract(lines, (card.shape[1], card.shape[0]))
        chars = sum(len(l.text) for l in lines) or 1
        conf = sum(l.conf * len(l.text) for l in lines) / chars
        print(f"  {name:14} {'利用可能':10} {statistics.median(times):9.0f}ms "
              f"{len(lines):6d} {conf:10.3f} {fields.filled_count():7d}")
    reset()


def main() -> int:
    ap = argparse.ArgumentParser(description="名刺読み取りの処理時間としきい値を測る")
    ap.add_argument("--image", help="実機で撮った写真のパス（保存はしない）")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--variant", help="撮影後の計測に使う前処理（既定は設定の先頭）")
    ap.add_argument("--metrics", action="store_true", help="しきい値調整用の実測値だけ出す")
    ap.add_argument("--compare-engines", action="store_true", help="OCR エンジンを比較する")
    ap.add_argument("--frames-only", action="store_true", help="検出ループだけ測る")
    args = ap.parse_args()

    bgr, label = load_image(args.image)
    print("=" * 78)
    print(f"対象   : {label}  ({bgr.shape[1]}x{bgr.shape[0]})")
    print(f"実行環境: {machine_info()}")
    print(f"設定   : engine={settings.get('ocr.engine')} threads={settings.get('ocr.threads')} "
          f"variants={settings.get('preprocess.variants')} work_width={settings.get('detection.work_width')}")
    print("=" * 78)

    if args.metrics:
        show_metrics(bgr)
        return 0
    if args.compare_engines:
        compare_engines(bgr, args.runs)
        return 0

    bench_frames(bgr, max(args.runs, 5))
    if not args.frames_only:
        bench_capture(bgr, args.runs, args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
