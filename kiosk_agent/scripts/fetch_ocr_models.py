"""OCR モデルを取得して kiosk_agent/models/ に置く（導入時のみ・以後はオフライン）。

    python3 scripts/fetch_ocr_models.py              # 必須＋任意すべて
    python3 scripts/fetch_ocr_models.py --required   # 必須のみ（約 14MB）
    python3 scripts/fetch_ocr_models.py --check      # 取得済みの確認だけ
    python3 scripts/fetch_ocr_models.py --mirror URL # 別の配布元から取る

取得するのは PaddleOCR の推論モデルを ONNX へ変換したもの。ダウンロード後に
SHA-256 を照合し、一致しないファイルは残さない（途中で切れた/差し替えられた
ファイルで OCR が静かに壊れるのを防ぐ）。

このスクリプトだけがネットワークを使う。名刺の読み取り本体は一切通信しない。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = AGENT_DIR / "models"

HF = "https://huggingface.co"


@dataclass(frozen=True)
class Model:
    filename: str
    url: str
    sha256: str
    size: int
    required: bool
    note: str


MODELS: tuple[Model, ...] = (
    Model(
        filename="det.onnx",
        url=f"{HF}/cycloneboy/ch_PP-OCRv4_det_infer/resolve/main/model.onnx",
        sha256="69ce850fec741a2a4568c7c924bb025c9d4f1129e5f96ab428c799ccc5ef2275",
        size=4_729_474,
        required=True,
        note="文字領域の検出 (PP-OCRv4 mobile det / DB)。言語に依存しない",
    ),
    Model(
        filename="rec_japan.onnx",
        url=f"{HF}/cycloneboy/japan_PP-OCRv4_rec_infer/resolve/main/model.onnx",
        sha256="bb0f23444c059d27a615c1a426414240bbd02d3658900d0455e007dc47d3e4a4",
        size=9_735_983,
        required=True,
        note="日本語の認識 (japan PP-OCRv4 mobile rec)。漢字・かな・英数字",
    ),
    Model(
        filename="japan_dict.txt",
        url=f"{HF}/cycloneboy/japan_PP-OCRv4_rec_infer/resolve/main/japan_dict.txt",
        sha256="2a0842e81ef31d6a99d811a36fc12c33e37aa9406667ef1bd9b468f9108a66bf",
        size=21_731,
        required=True,
        note="日本語モデルの文字セット (4399 字)。モデルと対で使う",
    ),
    Model(
        filename="rec_en.onnx",
        url=f"{HF}/cycloneboy/en_PP-OCRv4_rec_infer/resolve/main/model.onnx",
        sha256="02672d591fee561a95a2491bd5504d66c812b145d1043026c5658ecc165c7e85",
        size=7_652_836,
        required=False,
        note="英数字の認識。日本語モデルの文字セットには '@' が無くメールアドレスを"
             " 出力できないため、英数字だけの行はこちらで読み直す",
    ),
    Model(
        filename="en_dict.txt",
        url=f"{HF}/cycloneboy/en_PP-OCRv4_rec_infer/resolve/main/en_dict.txt",
        sha256="f27a6aa993c9cb67a588e7ea9aea90bb96b8e51dec6ce98bd7e76c104c1829fe",
        size=285,
        required=False,
        note="英数字モデルの文字セット (95 字)",
    ),
    Model(
        filename="cls.onnx",
        url=f"{HF}/SWHL/RapidOCR/resolve/main/PP-OCRv1/ch_ppocr_mobile_v2.0_cls_infer.onnx",
        sha256="e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
        size=585_532,
        required=False,
        note="行の向き（180 度の上下逆）の判定。逆さに置かれた名刺を直す",
    ),
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_ready(model: Model) -> bool:
    path = MODEL_DIR / model.filename
    return path.exists() and sha256_of(path) == model.sha256


def download(model: Model, url: str) -> bool:
    dest = MODEL_DIR / model.filename
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  取得中 {model.filename} ({model.size / 1_000_000:.1f}MB) …", end="", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mokuture-kiosk/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f" 失敗 ({e})")
        tmp.unlink(missing_ok=True)
        return False

    got = sha256_of(tmp)
    if got != model.sha256:
        print(f" ハッシュ不一致\n    期待 {model.sha256}\n    実際 {got}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    print(" 完了")
    return True


def report() -> int:
    missing_required = 0
    print(f"モデルの場所: {MODEL_DIR}")
    for m in MODELS:
        path = MODEL_DIR / m.filename
        if not path.exists():
            state = "未取得"
        elif sha256_of(path) != m.sha256:
            state = "壊れている（再取得が必要）"
        else:
            state = "OK"
        kind = "必須" if m.required else "任意"
        print(f"  [{kind}] {m.filename:16} {state:22} {m.note}")
        if m.required and state != "OK":
            missing_required += 1
    if missing_required:
        print(f"\n必須モデルが {missing_required} 件足りない。"
              " `python3 scripts/fetch_ocr_models.py` を実行すること。")
        return 1
    print("\n必須モデルは揃っている。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="名刺 OCR のモデルを取得する")
    ap.add_argument("--required", action="store_true", help="必須モデルだけ取得する")
    ap.add_argument("--check", action="store_true", help="取得状況を表示して終了する")
    ap.add_argument("--force", action="store_true", help="取得済みでも取り直す")
    ap.add_argument("--mirror", default="", help="配布元を差し替える（末尾スラッシュ無し）")
    args = ap.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if args.check:
        return report()

    targets = [m for m in MODELS if m.required or not args.required]
    failed: list[Model] = []
    for m in targets:
        if not args.force and is_ready(m):
            print(f"  済み  {m.filename}")
            continue
        url = m.url.replace(HF, args.mirror) if args.mirror else m.url
        if not download(m, url):
            failed.append(m)

    print()
    hard = [m for m in failed if m.required]
    if hard:
        print("必須モデルを取得できなかった:")
        for m in hard:
            print(f"  - {m.filename}  {m.url}")
        print("\nネットワークを確認して再実行するか、別の端末で取得したファイルを")
        print(f"{MODEL_DIR} へ置くこと。")
        print("どうしても取得できない場合は Tesseract へ切り替えられる:")
        print("  sudo apt install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-eng")
        print("  card_reader.yaml で ocr.engine: tesseract")
        return 1

    soft = [m for m in failed if not m.required]
    if soft:
        print("任意モデルを取得できなかった（動作はする。精度が少し落ちる）:")
        for m in soft:
            print(f"  - {m.filename}: {m.note}")
    return report()


if __name__ == "__main__":
    sys.exit(main())
