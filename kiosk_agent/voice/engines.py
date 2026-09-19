"""項目ごとに文字起こしエンジンを選ぶ。

同じ音声でも、当てたいものによって向くエンジンが違う。

  一文の名乗り(reception) … 固有名詞の**読み**が欲しい。Vosk が良い(読みCER 0.118 /
                            whisper base 0.217)。辞書にある語しか出さないので、
                            存在しない綴りを作らない。
  会社名・氏名を単独で言う … 辞書に無い社名が化けると読みごと失われるので、
                            仮名で残る whisper の方が安全なことがある。

設定 `fields.<項目>.engine` で決める。
  "vosk"    … Vosk だけ。使えなければエラー
  "whisper" … whisper.cpp だけ
  "auto"    … Vosk が使えれば Vosk、駄目なら whisper
"""
from __future__ import annotations

from types import ModuleType

from voice import settings, vosk_engine, whisper_cpp

#: 設定に書く名前 → 実体
ENGINES: dict[str, ModuleType] = {
    whisper_cpp.ENGINE_NAME: whisper_cpp,
    vosk_engine.ENGINE_NAME: vosk_engine,
}


class NoEngine(RuntimeError):
    """その項目で使えるエンジンが1つも無い。"""


def wanted(field: str) -> str:
    """その項目で使うことになっている名前。未設定なら whisper。"""
    return str((settings.field_cfg(field) or {}).get("engine") or "whisper").strip().lower()


def pick(field: str) -> ModuleType:
    """実際に使うエンジンを返す。

    "auto" のときだけ実際に使えるかを見て決める。名前で指定されている場合は
    **使えなくてもそれを返す**。黙って別のエンジンに変わると、精度が変わった
    理由が分からなくなるため。呼び出し側が available() を見てエラーにする。
    """
    name = wanted(field)
    if name == "auto":
        ok, _ = vosk_engine.available()
        return vosk_engine if ok else whisper_cpp
    return ENGINES.get(name, whisper_cpp)


def describe_all() -> dict[str, dict]:
    """画面の状態表示用。どのエンジンが使えるかを並べて返す。"""
    return {name: mod.describe() for name, mod in ENGINES.items()}


def any_available() -> bool:
    return any(mod.available()[0] for mod in ENGINES.values())
