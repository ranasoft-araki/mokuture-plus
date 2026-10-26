"""OTA bundle updater for mokuture+ kiosk agent.

Flow:
  1. On startup (after 15 s) and every NORMAL_INTERVAL seconds, fetch bundle manifest
     (also on demand: POST /update-check from the device-check screen).
  2. Hash the files on disk against the manifest; download the ones that differ to
     STAGING_DIR. (Compared by content, not by the recorded version, so a device whose
     files were reverted behind OTA's back is detected and repaired.)
  3. Set self.pending so /update-status reports ready=True.
  4. kiosk.html polls /update-status; when screen is idle (or force=True), calls
     POST /apply-update which triggers this module's apply().
  5. If any Python source files changed, apply() schedules a service restart via
     os._exit(0) so systemd (Restart=always) brings the agent back up cleanly.

The installed version is recorded in .bundle_version (content hash, also reported to
the backend) and .bundle_info.json (the commit it came from and when it was applied,
shown on the device-check screen). Both are per-device and gitignored.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx

from config import settings
from state import get_device_token

log = logging.getLogger(__name__)

_APP_DIR    = Path(__file__).parent
STAGING_DIR = Path("/tmp/mokuture-staging")
_VERSION_FILE = _APP_DIR / ".bundle_version"
_INFO_FILE    = _APP_DIR / ".bundle_info.json"

# Files managed by OTA (relative to kiosk_agent root).
MANAGED_FILES = [
    "static/kiosk.html",
    "static/analytics.js",   # 行動ログ(匿名)のロガー。kiosk.html が <script> で読む(再起動不要)
    "static/tap.mp3",   # タップ操作音の音源(バイナリ)。再起動不要でコピーのみ
    "main.py",
    "updater.py",
    "gpio.py",
    "sync.py",
    "state.py",
    "config.py",
    "locker_store.py",  # ロッカーのローカル状態・ミラーペイロード生成。実機へ確実に届ける
    # 端末稼働ログ(ANALYTICS.md §9)。main.py がこれらを import するので**必ず一緒に配る**
    # （main.py だけ新しくなると import 失敗でエージェントが起動しなくなる）。
    "analytics.py",
    "sysinfo.py",
    "watchdog.py",
    # 名刺読み取り(QR無し来訪者の受付フォーム自動入力)。Python の変更は再起動が要る。
    # 依存パッケージ(opencv/onnxruntime)と OCR モデルは OTA では配れない(サイズと
    # ビルドの都合)。それらは install.sh / scripts/fetch_ocr_models.py の担当で、
    # ここで配るのはコードと辞書だけ。未導入の端末に届いても import に失敗して
    # 名刺機能が無効になるだけで、キオスク本体は動き続ける。
    "card/__init__.py",
    "card/api.py",
    "card/defaults.py",
    "card/detect.py",
    "card/text_detect.py",
    "card/dicts.py",
    # 辞書そのものも配信対象にする。**コードだけ配っても中身が古いままになる。**
    # 姓辞書を 113 件から約 2 万件へ増やしたとき、ここに無いと既設の端末には
    # 届かず、読めた氏名が確信度不足で空欄になる挙動が残ったままになる。
    # 現場で足した語は `*.local.*` に書く（そちらは配信しないので消えない）。
    "card/dictionaries/surnames.tsv",
    "card/dictionaries/company_suffixes.txt",
    "card/dictionaries/company_suffixes_en.txt",
    "card/dictionaries/departments.txt",
    "card/dictionaries/department_suffixes.txt",
    "card/dictionaries/titles.txt",
    "card/dictionaries/prefectures.txt",
    "card/dictionaries/address_keywords.txt",
    "card/dictionaries/phone_labels.txt",
    "card/dump.py",
    "card/extract.py",
    "card/pipeline.py",
    "card/preprocess.py",
    "card/quality.py",
    "card/session.py",
    "card/settings.py",
    "card/textnorm.py",
    "card/types.py",
    "card/ocr/__init__.py",
    "card/ocr/base.py",
    "card/ocr/paddle_onnx.py",
    "card/ocr/tesseract.py",
    # 辞書は運用中に現場で追記されうる。OTA で上書きされると消えてしまうため
    # 配信対象に入れない(初期セットは install / git pull で入る)。
    #
    # 声で操作する(実験導入)。**別プロセス**(mokuture-voice.service / 127.0.0.1:8181)で
    # 動くが、コードはここに置いてあるので OTA で配れる。エージェント本体の再起動では
    # 音声サービスは新しいコードにならないため、音声サービス側が自分のソースの
    # ハッシュ変化を検知して自ら終了し、systemd に起こし直してもらう
    # (voice/server.py の _watch_sources)。
    "voice/__init__.py",
    "voice/api.py",
    "voice/capture.py",
    "voice/defaults.py",
    "voice/metrics.py",
    "voice/server.py",
    "voice/session.py",
    "voice/settings.py",
    "voice/types.py",
    "voice/vad.py",
    "voice/vosk_engine.py",
    # 英語の Vosk モデル(130MB・声で操作するの英語対応)。**唯一 OTA で配るモデルファイル**
    # (日本語モデル(50MB)は従来どおり install_voice.sh の担当=サイズと、現場で既に
    # 入っている版を無言で上書きしたくないため)。英語は新規機能で未導入の端末が大半な
    # ので、OTA で自動的に届けて手作業のインストールを不要にする。Git LFS 管理
    # (.gitattributes の voice_models/*.zip)。backend 側は zip のまま配り、展開は
    # 端末の voice/server.py 起動時(fetch_voice_models.extract_vosk)に任せる。
    "voice_models/vosk-model-en-us-0.22-lgraph.zip",
    # 端末ごとに現場で調整する設定(voice_input.yaml / staff_readings.yaml)は
    # 上書きしたくないので配信対象に入れない。
]

# Changing these files requires a service restart to take effect.
RESTART_FILES = {"main.py", "updater.py", "gpio.py", "sync.py", "state.py", "config.py", "locker_store.py",
                 "analytics.py", "sysinfo.py", "watchdog.py"}
# card/ 配下はすべて Python なので、変更があれば再起動する（下の apply() が判定）。
# voice/ は別プロセスなので**ここには入れない**。エージェントを再起動しても音声
# サービスは入れ替わらず、音声サービス側が自分で気づいて再起動する。
_RESTART_DIRS = ("card",)

NORMAL_INTERVAL = 1800   # 30 min between normal checks
FORCE_INTERVAL  = 60     # 1 min when a force-flagged update is pending




def _local_hash(rel: str) -> str:
    p = _APP_DIR / rel
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def read_version() -> str:
    return _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else ""


def _save_version(v: str) -> None:
    _VERSION_FILE.write_text(v)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime_iso(p: Path) -> str | None:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def _read_info() -> dict:
    try:
        info = json.loads(_INFO_FILE.read_text(encoding="utf-8"))
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def _note_installed(version: str, source: dict | None, *, just_applied: bool) -> None:
    """いま手元にある版を記録する。版の記録(.bundle_version)と、画面に出す名前・日時。

    source はサーバーが付けた版の名前(コミット)。付いていなくても、同じ版について前に
    記録した名前があればそれを残す(中身が同じなら名前も同じ)。"""
    prev = _read_info()
    same = prev.get("version") == version
    if just_applied or read_version() != version:
        applied_at = _now_iso()
    elif same and prev.get("applied_at"):
        applied_at = prev["applied_at"]
    else:
        # この記録を始める前に入った版。版の記録を書いた時刻を「この版になった時刻」とみなす
        applied_at = _mtime_iso(_VERSION_FILE)
    if read_version() != version:
        _save_version(version)
    info = {
        "version": version,
        "source": source or (prev.get("source") if same else None),
        "applied_at": applied_at,
    }
    if info != prev:
        _INFO_FILE.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")


def _diff(files: list[dict]) -> list[str]:
    """サーバーの一覧と中身が違う(または無い)ファイル。"""
    return [f["path"] for f in files if _local_hash(f["path"]) != f["hash"]]


def ota_enabled() -> bool:
    # 端末は Raspberry Pi(Linux)だけ。Windows などの開発機で本体を起動すると、master の版と
    # 違う手元のファイル(未コミットの kiosk.html や voice/*.py)を取り寄せ、待機画面へ戻った
    # ときに上書きしてしまう。開発機では自動更新しない(試す必要があるときは Pi で)。
    return os.name == "posix" and os.environ.get("KIOSK_OTA_DISABLE") != "1"


class BundleUpdater:
    def __init__(self) -> None:
        self._pending: dict | None = None
        self._lock = asyncio.Lock()
        self.enabled = ota_enabled()
        # 確認の結果(デバイスチェック画面の「ソフトウェア更新」に出す)。
        self._check_lock = asyncio.Lock()      # 定期確認と「今すぐ確認」を同時に走らせない
        self._checking = False
        self._checked_at: str | None = None    # 最後に確認した時刻(UTC)
        self._error: str | None = None         # 最後の確認が失敗した理由(画面にそのまま出す)
        self._remote: dict | None = None       # 最後に見たサーバーの版 {version, source, files}
        self._mismatch: list[str] | None = None  # サーバーと中身が違うファイル。None=未確認

    # ── Public state ──────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._pending is not None

    def is_force(self) -> bool:
        return self._pending is not None and bool(self._pending.get("force"))

    def status(self) -> dict:
        """デバイスチェック画面向けの更新状況。"""
        local_ver = read_version()
        info = _read_info()
        known = bool(local_ver) and info.get("version") == local_ver
        pending = None
        if self._pending is not None:
            pending = {
                "version": self._pending.get("version"),
                "source": self._pending.get("source"),
                "files": len(self._pending.get("_changed", [])),
                "force": bool(self._pending.get("force")),
            }
        return {
            "enabled": self.enabled,
            "checking": self._checking,
            "checked_at": self._checked_at,
            "error": self._error,
            "local": {
                "version": local_ver or None,
                "source": info.get("source") if known else None,
                "applied_at": info.get("applied_at") if known else _mtime_iso(_VERSION_FILE),
            },
            "remote": self._remote,
            "mismatch": self._mismatch,
            "pending": pending,
        }

    # ── Background loop ───────────────────────────────────────────────────────

    async def run(self) -> None:
        if not self.enabled:
            log.info("[updater] 開発機(非Linux)または KIOSK_OTA_DISABLE=1 のため自動更新しません")
            return
        await asyncio.sleep(15)  # let the server fully start first
        while True:
            await self.check()
            wait = FORCE_INTERVAL if (self._pending and self._pending.get("force")) else NORMAL_INTERVAL
            await asyncio.sleep(wait)

    async def check(self) -> None:
        """配信サーバーと突き合わせ、自動更新が有効なら違うファイルを取り寄せて適用待ちにする。
        定期確認と、デバイスチェック画面の「今すぐ確認」の両方から呼ばれる。
        自動更新が無効(開発機)なら突き合わせるだけで、何も書き換えない。"""
        if self._check_lock.locked():
            async with self._check_lock:  # 確認中なら、それが終わるのを待って同じ結果を使う
                return
        async with self._check_lock:
            self._checking = True
            try:
                await self._check_and_stage()
            except Exception:
                log.exception("[updater] check failed")
                self._error = "確認中にエラーが起きました"
            finally:
                self._checking = False
                self._checked_at = _now_iso()

    # ── Core logic ────────────────────────────────────────────────────────────

    async def _check_and_stage(self) -> None:
        token = get_device_token()
        if not token:
            self._error = "端末が未登録です"
            return

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{settings.remote_api_url}/kiosk/bundle/manifest",
                    headers={"X-Kiosk-Token": token},
                    timeout=15,
                )
                resp.raise_for_status()
            except Exception as e:
                log.warning(f"[updater] manifest fetch failed: {e}")
                self._error = "配信サーバーに接続できません"
                return

        manifest = resp.json()
        remote_ver = manifest["version"]
        force = manifest.get("force", False)
        files = manifest.get("files") or []
        self._remote = {"version": remote_ver, "source": manifest.get("source"), "files": len(files)}
        if not files:
            # 配信元が空。実際に起きた(Render のイメージに kiosk_agent が無く、全端末が長期間
            # 更新されていなかった)。何も配られていないのに「最新」と見せないよう異常として出す。
            self._error = "配信元にファイルがありません"
            self._mismatch = None
            return

        # 記録した版ではなく、ディスク上の中身で比べる。git で巻き戻された等で記録と中身が
        # 食い違っていても、届いていないものは届いていないと分かり、取り寄せ直せる。
        mismatch = await asyncio.to_thread(_diff, files)
        self._mismatch = mismatch
        self._error = None

        if not mismatch:
            # 中身はもうサーバーと同じ(適用済み・同じ中身の別の版)。版の記録だけ揃える。
            _note_installed(remote_ver, manifest.get("source"), just_applied=False)
            async with self._lock:
                if self._pending is not None:
                    self._pending = None
                    shutil.rmtree(STAGING_DIR, ignore_errors=True)
            return

        async with self._lock:
            if self._pending is not None and self._pending.get("version") == remote_ver:
                # 取り寄せ済みで適用待ち。force の切り替わりだけ反映する。
                self._pending = {**self._pending, "force": force}
                return

        if not self.enabled:
            return

        log.info(f"[updater] new version {remote_ver} (current: {read_version()}, {len(mismatch)} file(s) differ)")
        await self._download(manifest, token, mismatch)

    async def _download(self, manifest: dict, token: str, rels: list[str]) -> None:
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        changed: list[str] = []
        # ファイルごとの既定 60 秒は声の英語モデル(130MB)には短すぎる(弱い回線だと
        # 間に合わない)。manifest の size からおおよその下限を見積もる(1Mbps 想定=
        # 1秒あたり約125KB。実際の回線はもっと速いことが多いので、これは余裕を持った下限)。
        sizes = {f["path"]: f.get("size", 0) for f in (manifest.get("files") or [])}

        async with httpx.AsyncClient() as client:
            for rel in rels:
                log.info(f"[updater] downloading {rel}")
                timeout = max(60, int(sizes.get(rel, 0) / 125_000) + 30)
                try:
                    r = await client.get(
                        f"{settings.remote_api_url}/kiosk/bundle/file/{rel}",
                        headers={"X-Kiosk-Token": token},
                        timeout=timeout,
                    )
                    r.raise_for_status()
                except Exception as e:
                    log.error(f"[updater] download failed {rel}: {e}")
                    shutil.rmtree(STAGING_DIR, ignore_errors=True)
                    self._error = f"取り寄せに失敗しました（{rel}）"
                    return  # abort staging; retry next cycle

                dest = STAGING_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                changed.append(rel)

        log.info(f"[updater] staged {len(changed)} file(s): {changed}")
        async with self._lock:
            self._pending = {**manifest, "_changed": changed}

    # ── Apply ─────────────────────────────────────────────────────────────────

    async def apply(self) -> bool:
        """Copy staged files to app dir.  Returns True if a service restart is needed."""
        async with self._lock:
            if self._pending is None:
                return False

            changed      = self._pending.get("_changed", [])
            version      = self._pending["version"]
            files        = self._pending.get("files", [])
            needs_restart = False

            for rel in changed:
                src = STAGING_DIR / rel
                dst = _APP_DIR / rel
                if not src.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                # 一時ファイル経由 + os.replace (同じディレクトリ内なら atomic)。
                # 直接 copy2 で上書きしていると、適用中に電源が落ちる・プロセスが
                # 落ちると壊れた(不完全な)ファイルが残る。英語の声モデル(130MB)は
                # コピーにかかる時間がそれだけ長く、途中で切れる確率も上がる。
                tmp = dst.with_name(dst.name + ".part")
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                log.info(f"[updater] applied {rel}")
                if Path(rel).name in RESTART_FILES or Path(rel).parts[0] in _RESTART_DIRS:
                    needs_restart = True

            _note_installed(version, self._pending.get("source"), just_applied=True)
            self._pending = None
            shutil.rmtree(STAGING_DIR, ignore_errors=True)

        # 書き込めたかを中身で確かめ直す(画面の「最新です」を記録ではなく実物で出すため)。
        self._mismatch = await asyncio.to_thread(_diff, files)
        return needs_restart


updater = BundleUpdater()
