"""遠隔ログイン用の常駐(mokuture-tunnel.service)。

運営が運営パネルで「遠隔ログインを開く」を押した端末だけが、踏み台サーバーへ外向きに
SSH をつなぎ、逆向きの転送口を開く。運営はその転送口から、この端末の中だけで待っている
受け口(127.0.0.1:2222 の sshd。鍵は署名つきのシステム更新で配った運営の公開鍵だけ)へ入る。

決まり:
  - 普段はどこにもつながない。1 分ごとにサーバーへ「開けと言われているか」を聞くだけ。
  - 開いたら、サーバーが返した残り時間で自分から閉じる(サーバーや回線が落ちて「終了」が
    届かなくても開きっぱなしにならない)。時刻ではなく経過時間で数える(時計を持たない端末がある)。
  - 再起動したら必ず閉じた状態から始まる。
  - キオスク本体(mokuture-kiosk)とは別の常駐で、仮想環境も使わない(標準ライブラリだけ)。
    本体が起動しなくなった端末にこそ入りたいので、本体の不具合に巻き込まれないようにする。
  - サーバーが返す値(つなぎ先など)は、ssh に渡す前に形を確かめる。

状態は `systemctl status mokuture-tunnel` / `journalctl -u mokuture-tunnel` で見る。
"""
from __future__ import annotations

import getpass
import hashlib
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
KEY_DIR = Path(os.environ.get("MOKUTURE_TUNNEL_DIR") or (Path.home() / ".mokuture-tunnel"))
KEY = KEY_DIR / "id_ed25519"
KNOWN_HOSTS = KEY_DIR / "known_hosts"
SSH_LOG = KEY_DIR / "ssh.log"
# この端末の受け口(system/apply.sh が置く。127.0.0.1 だけで待つ)
LOCAL_SSH_PORT = 2222
LOCAL_HOST_KEY_PUB = Path("/etc/mokuture/tunnel_sshd/ssh_host_ed25519_key.pub")

DEFAULT_API = "https://mokuture-plus-api.onrender.com/api"
IDLE_POLL_SEC = 60          # サーバーが間隔を返さなかったとき
MIN_POLL_SEC, MAX_POLL_SEC = 3, 900
# 「つながった」と報告するのは、ssh が「転送口を開けた」と記録してから(OPEN_MARKER)。
# 動き続けているだけでは決めない: 設置先が 443 番を黙って捨てると、つながらないまま
# 15 秒(ConnectTimeout)動き続け、運営の画面に「接続中」と通らないコマンドが出てしまう。
OPEN_MARKER = b"remote forward success"
# 記録の文言が変わった ssh でも「接続待ち」のまま止まらないように、これだけ動き続けたらつながったとみなす
# (つなぐ 15 秒 + 踏み台が鍵を確かめる時間より長く)
OPEN_AFTER_SEC = 45
RETRY_AFTER_SEC = 10        # つなげなかったあと、やり直すまで
PROBE_EVERY_SEC = 6 * 3600  # 踏み台へ届くかを確かめ直す間隔
MAX_TTL_SEC = 24 * 3600

_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_ED25519 = re.compile(r"^ssh-ed25519 AAAAC3NzaC1lZDI1NTE5[A-Za-z0-9+/]{48}$")


def log(message: str) -> None:
    print(f"[tunnel] {message}", flush=True)


# ── 設定と鍵 ──────────────────────────────────────────────────────────────────

def read_env_file(path: Path) -> dict[str, str]:
    """`.env` の KEY=VALUE を読む(キオスク本体と同じファイル)。読めなければ空。"""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def api_base() -> str:
    value = os.environ.get("REMOTE_API_URL") or read_env_file(AGENT_DIR / ".env").get("REMOTE_API_URL") or DEFAULT_API
    return value.rstrip("/")


def device_token() -> str:
    """キオスク本体が登録のときに保存したトークン。未登録・壊れているときは空。"""
    try:
        data = json.loads((AGENT_DIR / "device_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("device_token") or "") if isinstance(data, dict) else ""


def clean_key(value: str | None) -> str:
    """「ssh-ed25519 AAAA... コメント」から種類と本体だけ。形が違えば空。"""
    parts = (value or "").split()
    key = " ".join(parts[:2])
    return key if _ED25519.match(key) else ""


def ensure_key() -> str:
    """踏み台へつなぐときの、この端末の鍵。無ければ作る。公開鍵を返す(作れなければ空)。"""
    pub = KEY.with_name(KEY.name + ".pub")
    try:
        KEY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not (KEY.exists() and pub.exists()):
            for p in (KEY, pub):
                p.unlink(missing_ok=True)
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "mokuture-kiosk", "-f", str(KEY)],
                check=True, timeout=30, stdin=subprocess.DEVNULL)
            log("踏み台へつなぐ鍵を作った")
        return clean_key(pub.read_text(encoding="utf-8", errors="replace"))
    except (OSError, subprocess.SubprocessError) as e:
        log(f"鍵を用意できない: {e}")
        return ""


def local_host_key() -> str:
    try:
        return clean_key(LOCAL_HOST_KEY_PUB.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


# ── サーバーの返事を確かめる ─────────────────────────────────────────────────

def parse_target(resp: dict) -> dict | None:
    """サーバーが返したつなぎ先。形がおかしければ None(ssh に渡さない)。"""
    host = str(resp.get("host") or "")
    user = str(resp.get("user") or "")
    host_key = clean_key(str(resp.get("host_key") or ""))
    try:
        port = int(resp.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if not (_HOST.match(host) and _USER.match(user) and host_key and 1 <= port <= 65535):
        return None
    return {"host": host, "port": port, "user": user, "host_key": host_key}


def parse_want(resp: dict) -> dict | None:
    """「開け」と言われているときの、つなぎ先・転送口・残り時間。そうでなければ None。"""
    if resp.get("want") is not True:
        return None
    target = parse_target(resp)
    if target is None:
        return None
    try:
        remote_port = int(resp.get("remote_port") or 0)
        ttl = int(resp.get("ttl_sec") or 0)
    except (TypeError, ValueError):
        return None
    if not (1024 <= remote_port <= 65535) or ttl <= 0:
        return None
    return {**target, "remote_port": remote_port, "ttl_sec": min(ttl, MAX_TTL_SEC)}


def poll_interval(resp: dict | None) -> int:
    try:
        value = int((resp or {}).get("poll_sec") or IDLE_POLL_SEC)
    except (TypeError, ValueError):
        value = IDLE_POLL_SEC
    return max(MIN_POLL_SEC, min(MAX_POLL_SEC, value))


def known_hosts_line(target: dict) -> str:
    host = target["host"] if target["port"] == 22 else f"[{target['host']}]:{target['port']}"
    return f"{host} {target['host_key']}\n"


def ssh_command(want: dict) -> list[str]:
    """踏み台へつなぎ、逆向きの転送口を 1 つ開くだけの ssh。端末側の設定ファイルは読まない。"""
    return [
        "ssh", "-F", "/dev/null", "-N", "-T", "-v",   # -v: 転送口を開けたことを記録から読むため
        "-p", str(want["port"]),
        "-i", str(KEY),
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=20",
        "-o", "ServerAliveCountMax=3",
        "-o", "ForwardAgent=no",
        "-o", "ForwardX11=no",
        "-R", f"127.0.0.1:{want['remote_port']}:127.0.0.1:{LOCAL_SSH_PORT}",
        f"{want['user']}@{want['host']}",
    ]


def probe(host: str, port: int, timeout: float = 8.0) -> str:
    """踏み台へ届くか。SSH の挨拶が返れば ok。届かない・別のもの(検査する中継)が答えたら blocked。"""
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            return "ok" if s.recv(64).startswith(b"SSH-") else "blocked"
    except OSError:
        return "blocked"


def post_json(url: str, token: str, body: dict, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-Kiosk-Token": token,
                 "User-Agent": "mokuture-tunnel-agent"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read(65536).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected response")
    return data


# ── つなぐ・閉じる ────────────────────────────────────────────────────────────

class Tunnel:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.params: tuple | None = None
        self.started = 0.0
        self.deadline = 0.0
        self.error = ""
        self.retry_at = 0.0
        self.opened = False

    @staticmethod
    def _key(want: dict) -> tuple:
        return (want["host"], want["port"], want["user"], want["host_key"], want["remote_port"])

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _forwarded(self) -> bool:
        """ssh が「転送口を開けた」と記録したか(一度見たら覚える)。"""
        if not self.opened:
            try:
                with open(SSH_LOG, "rb") as f:
                    self.opened = OPEN_MARKER in f.read(262144)
            except OSError:
                pass
        return self.opened

    def state(self, wanted: bool) -> str:
        if self.running():
            if self._forwarded() or time.monotonic() - self.started >= OPEN_AFTER_SEC:
                return "open"
            return "connecting"
        return "connecting" if wanted else "idle"

    def _reap(self) -> None:
        """ssh が自分で終わっていたら、理由を控えて片づける。"""
        if self.proc is None or self.proc.poll() is None:
            return
        code = self.proc.returncode
        self.proc = None
        self.retry_at = time.monotonic() + RETRY_AFTER_SEC
        tail = ""
        try:
            # -v の記録(debug1: ...)は飛ばし、ssh が言った最後の理由を拾う
            lines = [ln for ln in SSH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                     if ln.strip() and not ln.startswith("debug")]
            tail = lines[-1].strip()
        except (OSError, IndexError):
            pass
        tail = "".join(ch for ch in tail if 32 <= ord(ch) < 127)[:160]
        self.error = f"ssh exit {code}: {tail}" if tail else f"ssh exit {code}"
        log(f"切れた({self.error})")

    def ensure(self, want: dict) -> None:
        """開けと言われている。つながっていなければつなぎ、残り時間を数え直す。"""
        self._reap()
        self.deadline = time.monotonic() + want["ttl_sec"]
        if self.running():
            if self.params == self._key(want):
                return
            self.stop("つなぎ先が変わった")
        if time.monotonic() < self.retry_at:
            return
        try:
            KNOWN_HOSTS.write_text(known_hosts_line(want), encoding="utf-8")
            with open(SSH_LOG, "wb") as err:
                self.proc = subprocess.Popen(
                    ssh_command(want), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                    start_new_session=True)
        except OSError as e:
            self.proc = None
            self.error = f"ssh を起動できない: {e}"[:160]
            self.retry_at = time.monotonic() + RETRY_AFTER_SEC
            log(self.error)
            return
        self.params = self._key(want)
        self.started = time.monotonic()
        self.opened = False
        self.error = ""
        log(f"踏み台へつなぐ({want['host']}:{want['port']} 転送口 {want['remote_port']} 残り {want['ttl_sec']} 秒)")

    def stop(self, why: str) -> None:
        self._reap()
        if self.proc is None:
            return
        log(f"閉じる({why})")
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.proc = None
        self.params = None

    def tick(self) -> None:
        """毎秒の見回り。残り時間が尽きていたら、サーバーの指示を待たずに閉じる。"""
        self._reap()
        if self.running() and time.monotonic() >= self.deadline:
            self.stop("時間切れ")


def _source_hash() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return ""


def main() -> int:
    if not sys.platform.startswith("linux"):
        log("端末(Linux)でだけ動かす")
        return 0
    tunnel = Tunnel()

    def _quit(*_):
        tunnel.stop("常駐の停止")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _quit)
    signal.signal(signal.SIGINT, _quit)

    started_hash = _source_hash()
    pubkey = ensure_key()
    reach: str | None = None
    probe_at = 0.0
    wanted = False
    log(f"始めた({api_base()})")

    while True:
        token = device_token()
        resp: dict | None = None
        if not pubkey:
            pubkey = ensure_key()
        if token:
            body = {"state": tunnel.state(wanted), "pubkey": pubkey, "host_key": local_host_key(),
                    "login_user": getpass.getuser()}
            if reach:
                body["reach"] = reach
            if tunnel.error and not tunnel.running():
                body["error"] = tunnel.error
            try:
                resp = post_json(f"{api_base()}/kiosk/tunnel/poll", token, body)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404):
                    # サーバーがこの端末を知らないと答えた(端末を消された・登録し直しになった)。
                    # 「聞けない」とは違う。残り時間を待たずに閉じる
                    wanted = False
                    tunnel.stop(f"サーバーがこの端末を受け付けない({e.code})")
                log(f"サーバーに断られた: {e.code}")
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
                # サーバーに聞けない。開いているものは残り時間まで保ち、tick() が閉じる
                log(f"サーバーに聞けない: {str(e)[:120]}")
        if resp is not None:
            want = parse_want(resp) if pubkey else None
            wanted = want is not None
            if want is not None:
                tunnel.ensure(want)
            else:
                tunnel.stop("サーバーの指示")
                tunnel.error = ""
            target = parse_target(resp)
            if target and time.monotonic() >= probe_at and not tunnel.running():
                reach = probe(target["host"], target["port"])
                probe_at = time.monotonic() + PROBE_EVERY_SEC
                log(f"踏み台へ届くか: {reach}")
            if tunnel.error and not tunnel.running():
                # つなげなかった。届くかを確かめ直す(ただし 5 分に 1 回まで。失敗が続くあいだ
                # 毎回確かめに行かない)
                probe_at = min(probe_at, time.monotonic() + 300)

        # 配信でこのファイルが新しくなったら、開いていないときに終了して起こし直してもらう
        if not tunnel.running() and not wanted and started_hash and _source_hash() != started_hash:
            log("新しい版が届いたので起動し直す")
            return 0

        wait_until = time.monotonic() + poll_interval(resp)
        while time.monotonic() < wait_until:
            time.sleep(1)
            was_running = tunnel.running()
            tunnel.tick()
            if was_running and not tunnel.running():
                break   # 切れた・時間切れ。すぐ報告する


if __name__ == "__main__":
    sys.exit(main())
