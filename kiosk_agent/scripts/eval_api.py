"""起動中のエージェントに対して、名刺 API を実際に叩いて一連の流れを確認する。

    .venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8099
    .venv/Scripts/python.exe scripts/eval_api.py --port 8099
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "tests"))

import make_fixtures as mf  # noqa: E402


def call(url: str, data: bytes | None = None, method: str = "GET",
         content_type: str | None = None) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=data, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def jpeg_of(pattern: str, width: int) -> bytes:
    img, _quad, _spec = mf.build(pattern)
    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    if bgr.shape[1] != width:
        scale = width / bgr.shape[1]
        bgr = cv2.resize(bgr, (width, int(bgr.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    assert ok
    return buf.tobytes()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--pattern", default="landscape_ja")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    code, status = call(f"{base}/card/status")
    print(f"GET  /card/status            -> {code}")
    if code != 200:
        print(status)
        return 1
    print(f"     available={status['available']} engine={status['engine']} ({status['detail']})")
    print(f"     dictionaries={status['dictionaries']}")

    code, started = call(f"{base}/card/session", data=b"", method="POST")
    print(f"POST /card/session           -> {code} {started}")
    sid = started["session_id"]

    # 検出ループ: 同じ静止フレームを繰り返し送り、自動撮影が立つまでを見る
    frame = jpeg_of(args.pattern, started["detect_frame_max_width"])
    fired = False
    for i in range(12):
        t = time.perf_counter()
        code, payload = call(f"{base}/card/frame?session_id={sid}", data=frame,
                             method="POST", content_type="image/jpeg")
        ms = (time.perf_counter() - t) * 1000
        if code != 200:
            print(f"  frame {i}: {code} {payload}")
            return 1
        print(f"  frame {i:2d}: {payload['state']:11} steady={payload['steady']}/{payload['steady_needed']} "
              f"capture={payload['should_capture']!s:5} {ms:5.0f}ms  {payload['message']}")
        if payload["should_capture"]:
            fired = True
            break
    if not fired:
        print("  自動撮影が立たなかった")
        return 1

    shot = jpeg_of(args.pattern, started["capture_max_width"])
    t = time.perf_counter()
    code, result = call(f"{base}/card/capture?session_id={sid}", data=shot,
                        method="POST", content_type="image/jpeg")
    ms = (time.perf_counter() - t) * 1000
    print(f"POST /card/capture           -> {code}  {ms:.0f}ms")
    if code != 200:
        print(result)
        return 1
    print(f"     variant={result['variant']} tried={result['variants_tried']} "
          f"conf={result['ocr_confidence']} timings={result['timings_ms']}")
    print(f"     card_image={len(result['card_image'] or '')} bytes(base64) lines={len(result['lines'])}")
    for key, f in result["fields"].items():
        if f["value"] or f.get("candidates"):
            print(f"     {key:18} {f['confidence']:.2f}  {f['value'] or '(空)'}"
                  f"{'  候補=' + str(f['candidates']) if f.get('candidates') else ''}")

    body = json.dumps({"values": {"person_name": "山田 太郎", "company_name": result["fields"]["company_name"]["value"]}}).encode()
    code, confirmed = call(f"{base}/card/session/{sid}/confirm", data=body,
                           method="POST", content_type="application/json")
    print(f"POST /card/session/{{id}}/confirm -> {code}")
    print("     " + json.dumps(confirmed, ensure_ascii=False))

    code, after = call(f"{base}/card/session/{sid}/result")
    print(f"GET  /card/session/{{id}}/result  -> {code} (確定後はセッションが消えている)")

    code, bad = call(f"{base}/card/frame?session_id=notavalidsession", data=frame,
                     method="POST", content_type="image/jpeg")
    print(f"POST /card/frame (不正な session) -> {code} {bad}")

    code, big = call(f"{base}/card/frame?session_id={sid}", data=b"x" * 20,
                     method="POST", content_type="text/plain")
    print(f"POST /card/frame (不正な形式)     -> {code} {big}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
