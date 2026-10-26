"""検出→補正→OCR→抽出を全フィクスチャで通し、抽出結果と所要時間を一覧する。

    .venv/Scripts/python.exe scripts/eval_pipeline.py             # 全部
    .venv/Scripts/python.exe scripts/eval_pipeline.py landscape_ja mixed_ja_en
    .venv/Scripts/python.exe scripts/eval_pipeline.py --variant gray
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "tests"))

from card.detect import detect_card          # noqa: E402
from card.extract import extract, overall_confidence  # noqa: E402
from card.ocr import get_engine              # noqa: E402
from card.preprocess import make_variant, rectify     # noqa: E402
from card.types import FIELD_NAMES           # noqa: E402
import make_fixtures as mf                   # noqa: E402

# 各フィクスチャで「これは取れていてほしい」項目（架空の値）。
EXPECT = {
    "landscape_ja":  {"company_name": "株式会社サンプル商会", "person_name": "山田太郎",
                      "department": "営業部", "title": "部長", "email": "taro.yamada@example.jp"},
    "portrait_ja":   {"company_name": "有限会社きらめき工房", "person_name": "鈴木花子",
                      "department": "制作課", "title": "主任"},
    "mixed_ja_en":   {"person_name": "佐藤健一", "department": "開発本部", "title": "マネージャー"},
    "english_only":  {"person_name": "Alex Morgan", "title": "Director"},
    "white_card":    {"company_name": "株式会社サンプル商会", "person_name": "山田太郎"},
    "colored_card":  {"company_name": "株式会社あおば技研", "person_name": "高橋美咲"},
    "wood_background": {"company_name": "株式会社サンプル商会", "person_name": "山田太郎"},
    "skewed":        {"company_name": "株式会社サンプル商会", "person_name": "山田太郎"},
    "glare":         {"company_name": "株式会社サンプル商会"},
    "multi_phone":   {"phone": "03-1234-5678", "mobile": "080-9876-5432", "fax": "03-1234-5679"},
    "no_corporate_suffix": {"company_name": "あおぞらクリエイティブ", "person_name": "伊藤直樹"},
    "small_name":    {"person_name": "渡辺三郎"},
    "with_kana":     {"person_name": "中村優子", "person_name_kana": "なかむらゆうこ"},
    # 縦書きの名刺。連絡先の縦列は取りこぼすが、受付フォームに入る 2 項目は取れる。
    "vertical_writing": {"company_name": "株式会社松風堂", "person_name": "小林誠"},
    # 手に持って差し出した状態。指が下辺を隠すので、下側に組まれた連絡先までは
    # 求めず、受付フォームへ渡す会社名・氏名が取れることを見る。
    "held_in_hand":  {"company_name": "株式会社サンプル商会", "person_name": "山田太郎"},
    # 縦型を手に持った状態。親指が上辺をまたぐと上辺の輪郭が切れ、検出が社名の下の
    # 罫線を上辺と取り違えて名刺の上端 9% を落とす（この名刺は罫線が高さの 9.9% に
    # ある）。結果として社名は読めない。受理判定は require_any で氏名が取れていれば
    # 通るので確認画面へは進み、社名は利用者が手入力する。
    "held_in_hand_portrait": {"person_name": "鈴木花子"},
}

# 撮影ゲート（quality）で止まるため OCR まで進まないもの。抽出の期待値は置かない。
SKIP = {"not_a_card_paper", "not_a_card_phone", "blank_card", "empty_desk", "dark", "too_small"}


def run_one(name: str, variant: str, engine):
    img, _quad, _spec = mf.build(name)
    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

    t0 = time.perf_counter()
    det = detect_card(bgr)
    t_det = time.perf_counter() - t0

    t0 = time.perf_counter()
    card, _angle, _factor = rectify(bgr, det.quad if det else None)
    v = make_variant(card, variant)
    t_pre = time.perf_counter() - t0

    t0 = time.perf_counter()
    lines = engine.run(v)
    t_ocr = time.perf_counter() - t0

    t0 = time.perf_counter()
    fields = extract(lines, (card.shape[1], card.shape[0]))
    t_ext = time.perf_counter() - t0

    return fields, lines, (t_det, t_pre, t_ocr, t_ext)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="*", default=None)
    ap.add_argument("--variant", default="color")
    ap.add_argument("--show-lines", action="store_true")
    args = ap.parse_args()

    engine = get_engine()
    ok, reason = engine.available()
    print(f"engine={engine.name} available={ok} ({reason})\n")
    if not ok:
        return 1
    engine.warmup()

    names = args.patterns or [p for p in mf.PATTERNS if p not in SKIP]
    misses = 0
    checks = 0
    for name in names:
        fields, lines, timings = run_one(name, args.variant, engine)
        t_det, t_pre, t_ocr, t_ext = timings
        total = sum(timings) * 1000
        print(f"── {name}   total={total:6.0f}ms "
              f"(det {t_det*1000:4.0f} / pre {t_pre*1000:4.0f} / ocr {t_ocr*1000:5.0f} / ext {t_ext*1000:4.0f}) "
              f"overall_conf={overall_confidence(fields):.2f}")
        if args.show_lines:
            for l in lines:
                print(f"      | {l.conf:.3f} {l.text}")
        for key in FIELD_NAMES:
            f = fields.get(key)
            if not f.value and not f.candidates:
                continue
            mark = ""
            want = EXPECT.get(name, {}).get(key)
            if want is not None:
                checks += 1
                got = (f.value or "").replace(" ", "").replace("　", "")
                if got != want.replace(" ", ""):
                    mark = f"   <-- 期待: {want}"
                    misses += 1
            cand = f"  候補={f.candidates}" if f.candidates else ""
            print(f"    {key:18} {f.confidence:.2f}  {f.value or '(空)'}{cand}{mark}")
        # 期待した項目がまったく出なかった場合も取りこぼしとして数える
        for key, want in EXPECT.get(name, {}).items():
            f = fields.get(key)
            if not f.value and not f.candidates:
                checks += 1
                misses += 1
                print(f"    {key:18} ----  (空)   <-- 期待: {want}")
        print()

    print(f"期待どおりでない項目: {misses}/{checks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
