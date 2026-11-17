"""CSV 出力のセルを表計算ソフトで開いても安全にする。

受付ログの氏名・会社名などは来訪者がキオスクで入力した文字列。`=` などで始まる
セルは Excel 等で開いたときに数式として扱われるので、先頭に `'` を付けて
ただの文字列として表示させる(表示上は元の値のまま見える)。
"""
from __future__ import annotations

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_row(values) -> list:
    return [safe_cell(v) for v in values]
