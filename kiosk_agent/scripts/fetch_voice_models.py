"""音声認識モデルの検証と、必要なら取得(導入時のみ・以後はオフライン)。

    python3 scripts/fetch_voice_models.py            # 確認して、足りなければ取得
    python3 scripts/fetch_voice_models.py --check    # 確認だけ(取得しない)
    python3 scripts/fetch_voice_models.py --extract  # Vosk の zip を展開する
    python3 scripts/fetch_voice_models.py --check --only vosk-model-small-ja-0.22.zip

**通常はダウンロードは走らない。** モデルの実体はリポジトリに Git LFS で入っている
ので、`git clone` の時点で揃っているのが正しい状態。このスクリプトの主な仕事は

  1. ファイルが揃っているか
  2. SHA-256 が一致するか(壊れていないか)
  3. LFS のポインタのまま実体が落ちてきていないか(`git lfs pull` 忘れ)

を確かめること。壊れている・ポインタのままのときだけ、取得元から落とし直す。

このスクリプトだけがネットワークを使う。音声認識の本体は一切通信しない。
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = AGENT_DIR / "voice_models"
VENDOR_DIR = AGENT_DIR / "vendor"

HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
VOSK = "https://alphacephei.com/vosk/models"
WHISPER_SRC = "https://github.com/ggml-org/whisper.cpp/archive/refs/tags"

# Git LFS のポインタファイルはこの行で始まる(実体なら絶対に一致しない)。
_LFS_MAGIC = b"version https://git-lfs.github.com/spec/v1"


@dataclass(frozen=True)
class Asset:
    path: Path
    url: str
    sha256: str
    size: int
    required: bool
    note: str


ASSETS: tuple[Asset, ...] = (
    Asset(
        path=MODEL_DIR / "ggml-base-q5_1.bin",
        url=f"{HF}/ggml-base-q5_1.bin",
        sha256="422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898",
        size=59_707_625,
        required=True,
        note="whisper.cpp base 量子化。実証実験の既定モデル",
    ),
    Asset(
        path=MODEL_DIR / "ggml-small-q5_1.bin",
        url=f"{HF}/ggml-small-q5_1.bin",
        sha256="ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
        size=190_085_487,
        required=False,
        note="whisper.cpp small 量子化。比較用(Pi では遅すぎて実用にならない)",
    ),
    Asset(
        path=MODEL_DIR / "vosk-model-small-ja-0.22.zip",
        url=f"{VOSK}/vosk-model-small-ja-0.22.zip",
        sha256="efa092d280153a77615e9e0c7d7283e93e600de3d19d3bec686c57ef19d52eac",
        size=49_704_573,
        required=True,
        note="Vosk 日本語軽量。一文の名乗り(受付の既定の入口)で使う",
    ),
    Asset(
        path=VENDOR_DIR / "whisper.cpp-1.9.3.tar.gz",
        url=f"{WHISPER_SRC}/v1.9.3.tar.gz",
        sha256="1650f884effba487025143bd8facd2f9fb40a83b3737a732803c67a8d659d9c0",
        size=9_132_196,
        required=True,
        note="whisper.cpp v1.9.3 ソース。Pi 上でビルドする",
    ),
)

VOSK_DIR = MODEL_DIR / "vosk-model-small-ja-0.22"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def has_git_lfs() -> bool:
    """git-lfs が入っているか。

    **git 本体とは別のプログラム**で、入っていないと `git lfs pull` は
    「'lfs' is not a git command」と言われる。Raspberry Pi OS には既定で入っていない。
    """
    try:
        r = subprocess.run(["git", "lfs", "version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def lfs_advice() -> list[str]:
    """ポインタのままだったときの案内。環境に合わせて出し分ける。

    **git-lfs が無くても解決できる**(このスクリプトが取得元から直接落とせる)ことを
    伝える。ここを知らないと「git lfs が無いから進めない」で止まってしまう。
    """
    if has_git_lfs():
        return ["  リポジトリから取り出す: git lfs install && git lfs pull"]
    return [
        "  git-lfs が入っていません(git 本体とは別のプログラムです)。",
        "  どちらでも解決できます:",
        "    A) git-lfs を入れて取り出す",
        "         sudo apt install git-lfs        # Raspberry Pi OS / Debian",
        "         git lfs install && git lfs pull",
        "    B) git-lfs を使わず取得元から直接落とす(SHA-256 で検証します)",
        "         python3 scripts/fetch_voice_models.py",
    ]


def is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(_LFS_MAGIC)) == _LFS_MAGIC
    except OSError:
        return False


def state_of(asset: Asset) -> tuple[str, str]:
    """(状態, 説明)。状態は ok / missing / pointer / corrupt。"""
    if not asset.path.exists():
        return "missing", "ファイルがありません"
    if is_lfs_pointer(asset.path):
        return "pointer", "Git LFS のポインタのままで、実体が入っていません"
    actual = sha256_of(asset.path)
    if actual != asset.sha256:
        return "corrupt", f"SHA-256 が一致しません ({actual[:16]}…)"
    return "ok", f"{asset.path.stat().st_size / 1e6:.0f}MB"


def download(asset: Asset) -> bool:
    asset.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = asset.path.with_suffix(asset.path.suffix + ".part")
    print(f"  取得中: {asset.path.name} ({asset.size / 1e6:.0f}MB)")
    try:
        with urllib.request.urlopen(asset.url, timeout=120) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f, length=1 << 20)
    except (urllib.error.URLError, OSError) as e:
        print(f"  → 失敗: {e}")
        tmp.unlink(missing_ok=True)
        return False
    actual = sha256_of(tmp)
    if actual != asset.sha256:
        print(f"  → SHA-256 が一致しません。壊れたファイルは残しません ({actual[:16]}…)")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(asset.path)
    print("  → OK")
    return True


def extract_vosk() -> bool:
    """Vosk のモデルを zip から展開する(第3・4段階で使う)。"""
    zip_path = MODEL_DIR / "vosk-model-small-ja-0.22.zip"
    if not zip_path.exists() or is_lfs_pointer(zip_path):
        print("Vosk の zip がありません(先に取得してください)")
        return False
    if VOSK_DIR.exists():
        print(f"展開済み: {VOSK_DIR.name}")
        return True
    print(f"展開中: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as z:
        # zip の中身は vosk-model-small-ja-0.22/ で始まる。そのまま展開する。
        for name in z.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                print(f"  → 危険なパスを含む zip です: {name}")
                return False
        z.extractall(MODEL_DIR)
    print("  → OK")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="確認だけ(取得しない)")
    ap.add_argument("--extract", action="store_true", help="Vosk の zip を展開する")
    ap.add_argument("--all", action="store_true", help="任意のモデルも対象にする")
    ap.add_argument("--only", nargs="*", default=None, metavar="ファイル名",
                    help="このファイルだけを対象にする(例: --only vosk-model-small-ja-0.22.zip)")
    args = ap.parse_args()

    assets = ASSETS
    if args.only:
        want = set(args.only)
        assets = tuple(a for a in ASSETS if a.path.name in want)
        missing = want - {a.path.name for a in assets}
        if missing:
            print(f"知らないファイル: {', '.join(sorted(missing))}")
            print(f"  指定できるのは: {', '.join(a.path.name for a in ASSETS)}")
            return 2

    print(f"音声モデル: {MODEL_DIR}")
    bad: list[Asset] = []
    for asset in assets:
        state, detail = state_of(asset)
        mark = "OK  " if state == "ok" else "NG  "
        need = "必須" if asset.required else "任意"
        print(f"  {mark}[{need}] {asset.path.name:<32} {detail}")
        print(f"          {asset.note}")
        if state != "ok" and (asset.required or args.all):
            bad.append(asset)

    if args.check:
        # --only で絞ったときは、指定したものが揃っていなければ失敗とする
        # (「任意」の印が付いていても、名指しで要ると言われているため)。
        stop = bad if args.only else [a for a in bad if a.required]
        # ポインタのままなら、取り出し方を出さないと利用者がここで詰まる。
        if any(state_of(a)[0] == "pointer" for a in stop):
            print("")
            for line in lfs_advice():
                print(line)
        return 1 if stop else 0

    failed = False
    for asset in bad:
        if not download(asset):
            failed = failed or asset.required

    if args.extract:
        extract_vosk()

    if failed:
        print("\n必須のモデルが揃いませんでした。音声入力は無効のまま起動します。")
        for line in lfs_advice():
            print(line)
        return 1
    print("\nモデルは揃っています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
