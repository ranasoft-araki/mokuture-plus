"""キオスク側ロガー（JS）とバックエンド（Python）の語彙・項目が一致していることを固定する。

片方にだけ値を足すと **イベントが1件単位で reject される**（受付は止まらないが、その
ログだけ静かに落ちる）。気付きにくい壊れ方なので、テストで揃っていることを担保する。

`kiosk_agent/` が同じチェックアウトに無い場合（backend だけを取り出した環境）は skip する。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from app.schemas.analytics import ReceptionEventIn
from app.services import analytics_vocab as V

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ANALYTICS_JS = REPO_ROOT / "kiosk_agent" / "static" / "analytics.js"

pytestmark = pytest.mark.skipif(
    not ANALYTICS_JS.exists(), reason="kiosk_agent が同じチェックアウトに無い"
)


def _js() -> str:
    return ANALYTICS_JS.read_text(encoding="utf-8")


def _js_string_array(source: str, name: str) -> set[str]:
    """`name: [ "a", "b", ... ]` から文字列だけを取り出す。"""
    match = re.search(rf"{name}:\s*\[(.*?)\]", source, re.S)
    assert match, f"analytics.js に {name} が見つからない"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_event_payload_keys_match_the_schema():
    """ロガーが作るイベントのキー = 受信スキーマの項目（過不足なし）。"""
    body = re.search(r"var ev = \{(.*?)\n      \};", _js(), re.S)
    assert body, "analytics.js の push() のイベント定義が見つからない"
    js_keys = set(re.findall(r"^\s{8}([a-z_]+):", body.group(1), re.M))
    schema_keys = set(ReceptionEventIn.model_fields)
    assert js_keys == schema_keys, (
        "キオスク側と受信スキーマの項目がズレている。"
        f"\n  JS のみ: {sorted(js_keys - schema_keys)}"
        f"\n  スキーマのみ: {sorted(schema_keys - js_keys)}"
    )


def test_screen_vocabulary_matches():
    js_screens = _js_string_array(_js(), "screens")
    assert js_screens == V.SCREEN_IDS, (
        f"画面IDがズレている。JSのみ: {sorted(js_screens - V.SCREEN_IDS)} / "
        f"Pythonのみ: {sorted(V.SCREEN_IDS - js_screens)}"
    )
    assert "kiosk_settings" not in js_screens, "スタッフ専用の設定画面は記録対象に入れない"


def test_field_vocabulary_matches():
    js_fields = _js_string_array(_js(), "fields")
    assert js_fields == V.FIELD_IDS


def test_error_code_vocabulary_matches():
    js_errors = _js_string_array(_js(), "errors")
    assert js_errors == V.ERROR_CODES


def test_input_and_result_vocabulary_matches():
    source = _js()
    assert _js_string_array(source, "inputMethods") == V.INPUT_METHODS
    assert _js_string_array(source, "entryMethods") == V.ENTRY_METHODS
    assert _js_string_array(source, "results") == V.RESULTS
    assert _js_string_array(source, "notifyChannels") == V.NOTIFY_CHANNELS


def test_survey_questions_and_answers_match():
    source = _js()
    block = re.search(r"survey:\s*\{(.*?)\n    \},", source, re.S)
    assert block, "analytics.js に survey が見つからない"
    js_survey = {
        qid: set(re.findall(r'"([^"]+)"', answers))
        for qid, answers in re.findall(r"(\w+):\s*\[(.*?)\]", block.group(1), re.S)
    }
    assert js_survey == V.SURVEY_ANSWERS, json.dumps(
        {k: sorted(v) for k, v in js_survey.items()}, ensure_ascii=False
    )


def test_kiosk_html_loads_the_logger():
    """kiosk.html がロガーを読み込んでいること（OTA で配る前提）。"""
    html = (REPO_ROOT / "kiosk_agent" / "static" / "kiosk.html").read_text(encoding="utf-8")
    assert 'src="/analytics.js"' in html
