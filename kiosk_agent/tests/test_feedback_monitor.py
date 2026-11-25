"""受付完了後のアンケートはモニターのテナントだけに出す（kiosk.html を文字列で確かめる）。

キオスク画面は実ブラウザでしか動かないので、出し分けの条件と、設定を読み直す処理が
消えていないことだけを見張る。
"""
from __future__ import annotations

import pathlib
import re

KIOSK = (pathlib.Path(__file__).resolve().parents[1] / "static" / "kiosk.html").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = KIOSK.index(f"function {name}(")
    return KIOSK[start:KIOSK.index("\n}\n", start)]


def test_アンケートはモニターのテナントだけ():
    body = _body("goAfterResult")
    assert re.search(r'if \(FEEDBACK_ENABLED && ST\.is_monitor && .*go\("feedback"\)', body)


def test_モニターの既定はオフ():
    assert re.search(r"^\s*is_monitor: false,", KIOSK, re.M)


def test_モニター設定は定期的に読み直す():
    # 起動時に1回読むだけだと、運営が切り替えても端末を再起動するまで反映されない
    poll = KIOSK[KIOSK.index("// Poll schedule every 60 s"):]
    poll = poll[:poll.index("}, 60000);")]
    assert 'apiGet("/proxy/settings")' in poll
    assert "ST.is_monitor = st.is_monitor" in poll
