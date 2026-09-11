"""Tesseract 5 を使う OCR エンジン（第二候補）。

ARM64 で onnxruntime / PaddleOCR の ONNX が入らない端末向けの代替。
`ocr.engine: tesseract` にすると切り替わる。

pytesseract は使わず `tesseract` コマンドを直接呼ぶ。依存パッケージを増やさないのと、
画像を一時ファイルに書かずに標準入力へ渡せる（名刺の画像をディスクに残さない）ため。
出力は TSV 形式で受け取り、単語を行にまとめ直す。
"""
from __future__ import annotations

import logging
import shutil
import subprocess

import cv2
import numpy as np

from card import settings
from card.ocr.base import OcrEngine, OcrUnavailable, sort_reading_order
from card.types import OcrLine

log = logging.getLogger(__name__)


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def _cfg(self) -> dict:
        return settings.get("ocr.tesseract")

    # ── 準備 ──────────────────────────────────────────────────────────────────

    def _cmd(self) -> str:
        return str(self._cfg()["cmd"])

    def available(self) -> tuple[bool, str]:
        cmd = self._cmd()
        if shutil.which(cmd) is None:
            return False, f"{cmd} not found in PATH"
        try:
            r = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=10)
        except Exception as e:
            return False, f"{cmd} not runnable ({type(e).__name__})"
        installed = {ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()}
        wanted = [x for x in str(self._cfg()["lang"]).split("+") if x]
        missing = [x for x in wanted if x not in installed]
        if missing:
            return False, f"missing language data: {'+'.join(missing)}"
        return True, "ready"

    def warmup(self) -> None:
        try:
            self.run(np.full((64, 320, 3), 240, dtype=np.uint8))
        except Exception as e:
            log.info("[card] tesseract warmup skipped: %s", type(e).__name__)

    # ── 実行 ──────────────────────────────────────────────────────────────────

    def run(self, bgr) -> list[OcrLine]:
        ok, reason = self.available()
        if not ok:
            raise OcrUnavailable(reason)
        if bgr is None or bgr.size == 0:
            return []
        if bgr.ndim == 2:
            bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)

        c = self._cfg()
        encoded, buf = cv2.imencode(".png", bgr)
        if not encoded:
            return []

        args = [
            self._cmd(), "stdin", "stdout", "tsv",
            "-l", str(c["lang"]),
            "--psm", str(int(c["psm"])),
            "--oem", str(int(c["oem"])),
        ]
        try:
            proc = subprocess.run(
                args, input=buf.tobytes(), capture_output=True,
                timeout=float(settings.get("ocr.timeout_sec")),
            )
        except subprocess.TimeoutExpired:
            raise OcrUnavailable("tesseract timed out")
        if proc.returncode != 0:
            raise OcrUnavailable(f"tesseract exited {proc.returncode}")

        return self._parse_tsv(proc.stdout.decode("utf-8", errors="replace"),
                               float(c["drop_score"]))

    @staticmethod
    def _parse_tsv(tsv: str, drop_score: float) -> list[OcrLine]:
        """単語単位の TSV を行単位にまとめ直す。

        列は tesseract の仕様どおり
        level page block par line word left top width height conf text。
        level==5 が単語。(block, par, line) が同じものを 1 行として連結する。
        """
        rows = tsv.splitlines()
        if not rows:
            return []
        header = rows[0].split("\t")
        try:
            idx = {name: header.index(name) for name in
                   ("level", "block_num", "par_num", "line_num",
                    "left", "top", "width", "height", "conf", "text")}
        except ValueError:
            return []

        groups: dict[tuple[int, int, int], list[dict]] = {}
        for row in rows[1:]:
            cols = row.split("\t")
            if len(cols) <= idx["text"]:
                continue
            try:
                if int(cols[idx["level"]]) != 5:
                    continue
                conf = float(cols[idx["conf"]])
                left, top = int(cols[idx["left"]]), int(cols[idx["top"]])
                width, height = int(cols[idx["width"]]), int(cols[idx["height"]])
            except ValueError:
                continue
            text = cols[idx["text"]].strip()
            if not text or conf < 0:
                continue
            key = (int(cols[idx["block_num"]]), int(cols[idx["par_num"]]),
                   int(cols[idx["line_num"]]))
            groups.setdefault(key, []).append({
                "text": text, "conf": conf / 100.0,
                "l": left, "t": top, "r": left + width, "b": top + height,
            })

        lines: list[OcrLine] = []
        for words in groups.values():
            if not words:
                continue
            words.sort(key=lambda w: w["l"])
            # 日本語は単語間に空白を置かないので、全角文字だけの並びは詰めて連結する
            text = _join_words([w["text"] for w in words])
            total = sum(len(w["text"]) for w in words) or 1
            conf = sum(w["conf"] * len(w["text"]) for w in words) / total
            if conf < drop_score or not text:
                continue
            l = min(w["l"] for w in words)
            t = min(w["t"] for w in words)
            r = max(w["r"] for w in words)
            b = max(w["b"] for w in words)
            box = ((float(l), float(t)), (float(r), float(t)),
                   (float(r), float(b)), (float(l), float(b)))
            lines.append(OcrLine(text=text, box=box, conf=conf, order=0))  # type: ignore[arg-type]

        return sort_reading_order(lines)


def _join_words(words: list[str]) -> str:
    """単語列を 1 行にする。日本語同士は空白を入れず、英数字の間だけ空ける。"""
    out = ""
    for w in words:
        if not out:
            out = w
            continue
        if _is_ascii_word(out[-1]) and _is_ascii_word(w[0]):
            out += " " + w
        else:
            out += w
    return out.strip()


def _is_ascii_word(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in "@._-+/:")
