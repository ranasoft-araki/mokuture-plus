"""キオスク画面(ブラウザ)が叩く URL に、広告ブロッカーが止める語を入れていないことを見張る。

Raspberry Pi OS の Chromium には uBlock Origin Lite が最初から入っている。行動ログの送信先が
/device/analytics/events だった頃、EasyPrivacy の `/analytics/event` に当たって送信が
ブラウザ内で止められ（Failed to fetch）、Pi からは行動ログが 1 件も届いていなかった。
受付は普通に動くので誰も気づけない。同じ名前に戻さないためのテスト。

照合は語で見るだけ（実際の規則は数万件あり、ここでは持たない）。
"""
from __future__ import annotations

import re
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
KIOSK_HTML = AGENT / "static" / "kiosk.html"
LOGGER_JS = AGENT / "static" / "analytics.js"
MAIN_PY = AGENT / "main.py"

# 追跡ブロッカーの汎用規則によく出る語。ブラウザから叩く URL に入れない。
BLOCKED_WORDS = ("analytics", "track", "telemetry", "beacon", "collect", "pixel")

# 引用符で始まる "/英字…" をすべて URL とみなす（先頭を決め打ちすると新しい URL を見落とす）
_PATH_RE = re.compile(r"""["'`](/[A-Za-z][^"'`\s?]*)""")


def _logger_endpoint() -> str:
    m = re.search(r'endpoint:\s*"([^"]+)"', LOGGER_JS.read_text(encoding="utf-8"))
    assert m, "analytics.js に endpoint が見つからない"
    return m.group(1)


def _logger_script_src() -> str:
    html = KIOSK_HTML.read_text(encoding="utf-8")
    m = re.search(r'<script src="([^"]+)"></script>\s*</head>', html)
    assert m, "kiosk.html の </head> 直前にロガーの script タグが無い"
    return m.group(1)


def test_logger_urls_avoid_blocker_words():
    for url in (_logger_endpoint(), _logger_script_src()):
        hit = [w for w in BLOCKED_WORDS if w in url.lower()]
        assert not hit, f"{url} に {hit} が入っている（Pi の Chromium の広告ブロッカーに止められる）"


def test_every_browser_path_avoids_blocker_words():
    src = KIOSK_HTML.read_text(encoding="utf-8") + LOGGER_JS.read_text(encoding="utf-8")
    paths = sorted(set(_PATH_RE.findall(src)))
    assert "/device/oplog" in paths and "/proxy/reception" in paths, "URL を拾えていない（正規表現が古い）"
    bad = {p: [w for w in BLOCKED_WORDS if w in p.lower()] for p in paths}
    bad = {p: w for p, w in bad.items() if w}
    assert not bad, f"広告ブロッカーに止められうる URL: {bad}"


def test_agent_serves_the_logger_urls():
    """画面が叩く名前をエージェントが本当に持っていること（名前だけ変えて 404 にしない）。"""
    src = MAIN_PY.read_text(encoding="utf-8")
    assert f'@app.post("{_logger_endpoint()}")' in src
    assert f'@app.get("{_logger_script_src()}"' in src
