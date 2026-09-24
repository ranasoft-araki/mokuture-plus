"""辞書ファイルの読み込み。

`card/dictionaries/*.txt` は 1 行 1 語、`#` で始まる行と空行は無視する。読み込みは
プロセス内でキャッシュし、ファイルの更新時刻が変わっていれば読み直す（端末に
入ったまま辞書を足しても再起動が要らない）。

**現場で足した語は `*.local.*` に書く。** 本体の辞書（surnames.tsv など）は OTA で
配信するので、端末上で直接書き足すと次の配信で消える。同じ名前に `.local` を挟んだ
ファイル（`surnames.local.tsv` / `titles.local.txt`）があれば、本体の後ろに足して
読む。こちらは配信対象ではないので上書きされない。
"""
from __future__ import annotations

import logging
from pathlib import Path

from card import settings

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, list[str]]] = {}


def _dict_dir() -> Path:
    return settings.resolve_path(str(settings.get("extraction.dictionaries_dir")))


def load(name: str) -> list[str]:
    """辞書を読む。存在しなければ空リスト（機能は落ちるが落ちない）。

    name に拡張子が含まれていればそれを使い、無ければ .txt を補う
    （「値<TAB>表記」形式のものは .tsv にしてある）。
    現場で足した `*.local.*` があれば後ろに足して返す。
    """
    words = _load_one(name)
    extra = _load_one(_local_name(name))
    return words + extra if extra else words


def _local_name(name: str) -> str:
    """surnames.tsv → surnames.local.tsv / titles → titles.local"""
    stem, dot, ext = name.partition(".")
    return f"{stem}.local{dot}{ext}" if dot else f"{stem}.local"


def _load_one(name: str) -> list[str]:
    filename = name if "." in name else f"{name}.txt"
    path = _dict_dir() / filename
    try:
        mtime = path.stat().st_mtime
    except OSError:
        if name not in _cache:
            # 現場の追記ファイルは無いのが普通なので騒がない
            if ".local" not in name:
                log.warning("[card] dictionary not found: %s", filename)
            _cache[name] = (0.0, [])
        return _cache[name][1]

    cached = _cache.get(name)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    words: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            words.append(line)
    except Exception as e:
        log.warning("[card] dictionary %s.txt unreadable (%s)", name, type(e).__name__)
        words = []

    _cache[name] = (mtime, words)
    return words


def load_pairs(name: str) -> list[tuple[str, str]]:
    """「値<TAB>表記」形式の辞書を読む（phone_labels など）。"""
    out: list[tuple[str, str]] = []
    for line in load(name):
        if "\t" not in line:
            continue
        key, _, value = line.partition("\t")
        key, value = key.strip(), value.strip()
        if key and value:
            out.append((key, value))
    return out


def longest_first(words: list[str]) -> list[str]:
    """長い語から照合するための並べ替え（「部長」より「代表取締役」を先に見る）。"""
    return sorted(words, key=len, reverse=True)


def company_suffixes() -> list[str]:
    return longest_first(load("company_suffixes"))


def company_suffixes_en() -> list[str]:
    return longest_first(load("company_suffixes_en"))


def titles() -> list[str]:
    return longest_first(load("titles"))


def departments() -> list[str]:
    return longest_first(load("departments"))


def department_suffixes() -> list[str]:
    return longest_first(load("department_suffixes"))


def prefectures() -> list[str]:
    return load("prefectures")


def surnames() -> dict[str, str]:
    """{姓(漢字): よみ(ひらがな)} を返す。surnames.tsv が無ければ空。"""
    return {k: v for k, v in load_pairs("surnames.tsv")}


def address_keywords() -> list[str]:
    return load("address_keywords")


def phone_labels() -> list[tuple[str, str]]:
    """[(種別, 表記), ...] を表記の長い順に返す。"""
    pairs = load_pairs("phone_labels")
    return sorted(pairs, key=lambda p: len(p[1]), reverse=True)


def reset() -> None:
    """キャッシュを捨てる（テスト用）。"""
    _cache.clear()


def summary() -> dict[str, int]:
    """status API 用。語数だけを返す（中身は出さない）。"""
    names = (
        "company_suffixes", "company_suffixes_en", "titles", "departments",
        "department_suffixes", "prefectures", "surnames.tsv", "address_keywords",
        "phone_labels",
    )
    return {n: len(load(n)) for n in names}
