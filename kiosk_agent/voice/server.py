"""音声入力サービスの起動口(別プロセス・127.0.0.1 限定)。

    .venv/bin/python -m voice.server
    .venv/bin/uvicorn voice.server:app --host 127.0.0.1 --port 8181

キオスク本体(main.py / port 8080 / 0.0.0.0)とは別プロセスで動かす。理由は
`voice/__init__.py` の冒頭に書いたとおりで、要点は 3 つ:

  1. 音声 API を LAN から見えなくする(bind を 127.0.0.1 にする)
  2. 実験機能が落ちても受付本体(GPIO・ロッカー・扉)を巻き込まない
  3. whisper.cpp が CPU を占有する影響を切り分けやすくする

systemd(`mokuture-voice.service`, Restart=always)が起動と再起動を受け持つ。
OTA で `voice/` のソースが差し替わったら、このプロセスが自分で気づいて終了し、
systemd に起こし直してもらう(OTA は kiosk 本体の updater が配るが、本体の
再起動では別プロセスのこちらは新しいコードにならないため)。
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from voice import session as session_mod, settings, whisper_cpp
from voice.api import router as voice_router

log = logging.getLogger(__name__)

_VOICE_DIR = Path(__file__).resolve().parent


def _sources_digest() -> str:
    """voice/ 配下の .py の内容をまとめた指紋。OTA 差し替えの検知に使う。"""
    h = hashlib.sha256()
    for p in sorted(_VOICE_DIR.glob("*.py")):
        try:
            h.update(p.name.encode("utf-8"))
            h.update(p.read_bytes())
        except OSError:
            continue
    return h.hexdigest()[:16]


async def _purge_loop() -> None:
    """放置されたセッション(= メモリ上の音声と結果)を定期的に捨てる(§11)。"""
    while True:
        try:
            await asyncio.sleep(30)
            removed = session_mod.store.purge()
            if removed:
                log.info("[voice] purged %d expired session(s)", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[voice] purge failed")


async def _watch_sources() -> None:
    """OTA でソースが変わったら自分で終了する(systemd が起こし直す)。"""
    interval = int(settings.get("server.watch_sources_sec"))
    if interval <= 0:
        return
    baseline = _sources_digest()
    while True:
        try:
            await asyncio.sleep(interval)
            if _sources_digest() != baseline:
                log.info("[voice] ソースが更新されたので再起動します")
                # セッションを畳んでから落ちる(録音中でも音声は残さない)。
                session_mod.store.clear()
                os._exit(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[voice] source watch failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ok, detail = whisper_cpp.available()
    log.info("[voice] whisper: %s (%s)", "ready" if ok else "unavailable", detail)
    mic_ok, mic_detail = _mic_status()
    log.info("[voice] microphone: %s (%s)", "ready" if mic_ok else "unavailable", mic_detail)

    tasks = [
        asyncio.create_task(_purge_loop()),
        asyncio.create_task(_watch_sources()),
        # モデルをページキャッシュに載せる。初回の待ち時間を削る。
        asyncio.create_task(asyncio.to_thread(whisper_cpp.warmup)),
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        session_mod.store.clear()


def _mic_status() -> tuple[bool, str]:
    from voice import capture
    try:
        return capture.available()
    except Exception as e:
        return False, type(e).__name__


app = FastAPI(title="mokuture+ Voice Input (experimental)", lifespan=lifespan)

# CORS はキオスク画面のオリジン(ループバックの 8080)だけ。ワイルドカードにはしない。
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.get("server.allowed_origins") or []),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(voice_router)


@app.get("/health")
async def health():
    ok, detail = whisper_cpp.available()
    return {"ok": True, "engine_ready": ok, "detail": detail, "sources": _sources_digest()}


def main() -> None:
    import uvicorn

    host = str(settings.get("server.bind_host"))
    port = int(settings.get("server.port"))
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        # §13「localhost の音声認識 API を外部公開しない」に反する設定。
        # 黙って従わず、はっきり警告を出す(止めはしない。閉じた検証環境もあるため)。
        log.warning("[voice] bind_host=%s はループバックではありません。"
                    "音声 API が端末の外から見える状態です", host)
    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
