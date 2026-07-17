"""ローカル kana→漢字 変換 (実験: experiment/kanji-ime)

キオスク受付フォームの五十音キーボードで入力した「読み(ひらがな)」を
漢字候補に変換する。**オフライン・外部依存なし・クラウド往復なし**。

方式:
  1. 同梱辞書 kana_dict.tsv (読み<TAB>候補,候補,…) をロード。
  2. 任意で SKK-JISYO 形式の辞書(環境変数 KANA_DICT_EXTRA / 同ディレクトリの
     SKK-JISYO.L)があればマージして語彙を全面拡張する。
  3. convert(読み):
       - 読み全体の完全一致候補(最優先)
       - 辞書での貪欲(最長一致)分割による連結候補 例: やまだ+たろう→山田太郎
       - 常にひらがな・カタカナのフォールバック候補
     を重複除去して返す。

mozc のような文節解析ほどの精度は無いが、受付で必要な「姓名・会社名・
用件語彙」を辞書で確実に拾えれば実用になる。将来 mozc 連携に差し替える
場合もこの convert() のI/Fを保てばフロントは無改修で済む。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

_DICT_PATH = Path(__file__).parent / "kana_dict.tsv"
_SKK_LOCAL = Path(__file__).parent / "SKK-JISYO.L"
_SKK_URL = "https://skk-dev.github.io/dict/SKK-JISYO.L.gz"
# SKK-JISYO を置く既定パス(存在すれば自動マージ)。環境変数でも指定可。
_SKK_CANDIDATES = [
    os.environ.get("KANA_DICT_EXTRA", ""),
    str(_SKK_LOCAL),
    str(Path(__file__).parent / "SKK-JISYO"),
]

_CACHE: Optional[Dict[str, List[str]]] = None

# ひらがな⇔カタカナ (U+3041-U+3096 ⇔ U+30A1-U+30F6, +0x60)
_HIRA_MIN, _HIRA_MAX = 0x3041, 0x3096
_KATA_MIN, _KATA_MAX = 0x30A1, 0x30F6


def _to_hira(s: str) -> str:
    return "".join(
        chr(ord(c) - 0x60) if _KATA_MIN <= ord(c) <= _KATA_MAX else c for c in s
    )


def _to_kata(s: str) -> str:
    return "".join(
        chr(ord(c) + 0x60) if _HIRA_MIN <= ord(c) <= _HIRA_MAX else c for c in s
    )


def _add(dic: Dict[str, List[str]], reading: str, cands: List[str]) -> None:
    if not reading:
        return
    bucket = dic.setdefault(reading, [])
    for c in cands:
        c = c.strip()
        if c and c not in bucket:
            bucket.append(c)


def _load_bundled(dic: Dict[str, List[str]]) -> None:
    try:
        text = _DICT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        reading = _to_hira(parts[0].strip())
        cands = [c for c in parts[1].replace("/", ",").split(",") if c.strip()]
        _add(dic, reading, cands)


def _load_skk(dic: Dict[str, List[str]], path: str) -> int:
    """SKK-JISYO 形式(読み /候補;注釈/候補/)をマージ。EUC-JP/UTF-8 両対応。
    送り仮名あり(読みに英字が混じる)エントリはスキップ(名詞系のみ採用)。"""
    p = Path(path)
    if not path or not p.is_file():
        return 0
    raw: Optional[str] = None
    for enc in ("utf-8", "euc-jp", "cp932"):
        try:
            raw = p.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if raw is None:
        return 0
    count = 0
    for line in raw.splitlines():
        if not line or line.startswith(";"):
            continue
        sp = line.find(" ")
        if sp <= 0:
            continue
        reading = line[:sp]
        # 送り仮名あり/英字混じりの読みは除外(受付用途では不要)
        if any("a" <= ch.lower() <= "z" for ch in reading):
            continue
        body = line[sp + 1 :].strip()
        cands: List[str] = []
        for chunk in body.split("/"):
            chunk = chunk.strip()
            if not chunk:
                continue
            # "候補;注釈" の注釈を落とす
            cand = chunk.split(";", 1)[0].strip()
            if cand:
                cands.append(cand)
        if cands:
            _add(dic, _to_hira(reading), cands)
            count += 1
    return count


def _load() -> Dict[str, List[str]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    dic: Dict[str, List[str]] = {}
    _load_bundled(dic)
    seen_paths = set()
    for path in _SKK_CANDIDATES:
        if path and path not in seen_paths:
            seen_paths.add(path)
            _load_skk(dic, path)
    _CACHE = dic
    return dic


def reload() -> int:
    """辞書を再読込(テスト・辞書差し替え用)。エントリ数を返す。"""
    global _CACHE
    _CACHE = None
    return len(_load())


def warmup() -> int:
    """辞書を事前ロードしてキャッシュを温める。SKK-JISYO.L は数万〜十数万語で
    初回ロードに時間がかかるため、起動時に別スレッドで呼んで最初の来訪者を待たせない。"""
    return len(_load())


def ensure_dict(timeout: float = 30.0) -> bool:
    """全面辞書 SKK-JISYO.L が無ければ取得する(best-effort)。既存 or 取得成功で True。
    通常は SKK-JISYO.L をリポジトリに同梱(資産として commit 済み)しているので即 True。
    これは万一ファイルが欠けている環境向けの自己修復フォールバック。取得失敗(オフライン)
    時は False で同梱 kana_dict.tsv(約160語)にフォールバックする。"""
    if _SKK_LOCAL.exists():
        return True
    try:
        import gzip
        import httpx
        resp = httpx.get(_SKK_URL, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        _SKK_LOCAL.write_bytes(gzip.decompress(resp.content))
        return True
    except Exception:
        return False


def _segment(reading: str, dic: Dict[str, List[str]]) -> Optional[List[List[str]]]:
    """読みを辞書で最長一致・貪欲に分割。全区間が辞書にあれば各区間の候補列を返す。
    分割できない箇所があれば None。"""
    segs: List[List[str]] = []
    i, n = 0, len(reading)
    while i < n:
        best_end = -1
        for j in range(n, i, -1):
            if reading[i:j] in dic:
                best_end = j
                break
        if best_end < 0:
            return None
        segs.append(dic[reading[i:best_end]])
        i = best_end
    return segs


def convert(raw: str, limit: int = 60) -> List[str]:
    """読み(ひらがな/カタカナ)→ 漢字候補リスト。オフライン。"""
    if not raw:
        return []
    # 全角/半角スペースは除去(長音符ーは読みの一部なので残す)
    reading = _to_hira(raw).strip().replace("　", "").replace(" ", "")
    if not reading:
        return []

    dic = _load()
    out: List[str] = []

    # 1. 読み全体の完全一致
    out.extend(dic.get(reading, []))

    # 2. 貪欲分割の連結候補(例: やまだ+たろう→山田太郎)
    segs = _segment(reading, dic)
    if segs and len(segs) >= 2:
        out.append("".join(s[0] for s in segs))
        # 先頭区間の別候補も1つだけ提示(姓の異体字など)
        if len(segs[0]) >= 2:
            out.append(segs[0][1] + "".join(s[0] for s in segs[1:]))

    # 3. 常にひらがな・カタカナのフォールバック
    out.append(reading)
    out.append(_to_kata(reading))

    # 重複除去(順序維持) + 上限
    seen = set()
    res: List[str] = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            res.append(c)
        if len(res) >= limit:
            break
    return res
