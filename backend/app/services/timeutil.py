"""日時のシリアライズ補助。

DB 日時列は naive(UTC 壁時計)を建前とするが、本番 Neon の一部の列は実質
timestamptz として作られており、asyncpg が **aware(tz付き)** な datetime を読み戻す。
その場合 `dt.isoformat()` は既に `+00:00` を含むため、素朴に `+ "Z"` を足すと
`...+00:00Z` という不正な ISO 文字列になり、ブラウザの `new Date()` が Invalid Date を返す
(管理画面の「最終同期: NaN日前」「発行日: Invalid Date」の原因)。

`iso_z` は aware / naive のどちらでも、単一の `Z` を持つ正しい UTC ISO 文字列にそろえる。
"""
from datetime import datetime, timezone


def iso_z(dt: datetime | None) -> str | None:
    """datetime をフロントがパースできる単一 `Z` の UTC ISO 文字列にする。

    - aware: UTC へ変換してから naive 化し `Z` を付ける(`+00:00Z` の二重付与を防ぐ)。
    - naive: UTC 壁時計とみなしてそのまま `Z` を付ける。
    - None: None を返す。
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"
