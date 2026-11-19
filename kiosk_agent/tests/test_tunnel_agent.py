"""遠隔ログイン用の常駐(tunnel_agent.py)。

実際の ssh も踏み台も使わない。確かめるのは「サーバーの返事をそのまま信じない」
「開きっぱなしにならない」「キオスク本体に依存しない」の 3 つ。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

import tunnel_agent as ta  # noqa: E402
import updater  # noqa: E402

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5" + "A" * 48


def _resp(**over):
    base = {"enabled": True, "want": True, "poll_sec": 5, "host": "bastion.example.test", "port": 443,
            "user": "mokuture-tunnel", "host_key": KEY, "remote_port": 20001, "ttl_sec": 600}
    base.update(over)
    return base


def test_開けと言われたときのつなぎ方():
    want = ta.parse_want(_resp())
    assert want == {"host": "bastion.example.test", "port": 443, "user": "mokuture-tunnel", "host_key": KEY,
                    "remote_port": 20001, "ttl_sec": 600}
    cmd = ta.ssh_command(want)
    assert cmd[0] == "ssh" and cmd[-1] == "mokuture-tunnel@bastion.example.test"
    # 開くのは、この端末の中の受け口(127.0.0.1:2222)への転送口 1 つだけ。踏み台の外向きには開けない
    assert cmd[cmd.index("-R") + 1] == "127.0.0.1:20001:127.0.0.1:2222"
    assert cmd.count("-R") == 1 and "-L" not in cmd and "-D" not in cmd
    joined = " ".join(cmd)
    for must in ("-F /dev/null", "StrictHostKeyChecking=yes", "ExitOnForwardFailure=yes", "BatchMode=yes",
                 "IdentitiesOnly=yes", "GlobalKnownHostsFile=/dev/null", "ForwardAgent=no"):
        assert must in joined, must
    assert ta.known_hosts_line(want) == f"[bastion.example.test]:443 {KEY}\n"
    assert ta.known_hosts_line({**want, "port": 22}) == f"bastion.example.test {KEY}\n"


@pytest.mark.parametrize("over", [
    {"want": False},
    {"want": "true"},                                   # 真偽値そのものでなければ開かない
    {"host": "-oProxyCommand=sh"},                      # ssh のオプションに化ける
    {"host": "a b"}, {"host": "a;b"}, {"host": ""}, {"host": "x" * 300},
    {"user": "root;id"}, {"user": "-l"}, {"user": ""},
    {"host_key": "ssh-rsa AAAA"}, {"host_key": ""}, {"host_key": KEY[:-1]},
    {"port": 0}, {"port": 70000}, {"port": "x"},
    {"remote_port": 22}, {"remote_port": 70000}, {"remote_port": None},
    {"ttl_sec": 0}, {"ttl_sec": -5}, {"ttl_sec": "soon"},
])
def test_形のおかしい返事では開かない(over):
    assert ta.parse_want(_resp(**over)) is None


def test_残り時間には上限がある():
    assert ta.parse_want(_resp(ttl_sec=10 ** 9))["ttl_sec"] == ta.MAX_TTL_SEC


def test_聞きに行く間隔は範囲に収める():
    assert ta.poll_interval({"poll_sec": 1}) == ta.MIN_POLL_SEC
    assert ta.poll_interval({"poll_sec": 0}) == ta.IDLE_POLL_SEC
    assert ta.poll_interval({"poll_sec": 10 ** 6}) == ta.MAX_POLL_SEC
    assert ta.poll_interval({"poll_sec": "x"}) == ta.IDLE_POLL_SEC
    assert ta.poll_interval(None) == ta.IDLE_POLL_SEC


def test_鍵は種類と本体だけを取り出す():
    assert ta.clean_key(KEY + " kiosk@host\n") == KEY
    assert ta.clean_key('command="x" ' + KEY) == ""
    assert ta.clean_key(None) == ""


def test_envファイルを読む(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nREMOTE_API_URL="https://api.example.test/api/"\nPORT=8080\nBROKEN\n', encoding="utf-8")
    assert ta.read_env_file(env) == {"REMOTE_API_URL": "https://api.example.test/api/", "PORT": "8080"}
    assert ta.read_env_file(tmp_path / "missing") == {}


class _FakeProc:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def fake_ssh(monkeypatch, tmp_path):
    """ssh を起動する代わりに、起動した回数と引数を控える。時計も手で進める。"""
    clock = {"now": 1000.0}
    started: list[_FakeProc] = []

    def popen(cmd, **kwargs):
        proc = _FakeProc()
        proc.cmd = cmd
        started.append(proc)
        return proc

    monkeypatch.setattr(ta.subprocess, "Popen", popen)
    monkeypatch.setattr(ta.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(ta, "KNOWN_HOSTS", tmp_path / "known_hosts")
    monkeypatch.setattr(ta, "SSH_LOG", tmp_path / "ssh.log")
    return clock, started


def test_残り時間が尽きたら指示を待たずに閉じる(fake_ssh):
    clock, started = fake_ssh
    t = ta.Tunnel()
    t.ensure(ta.parse_want(_resp(ttl_sec=600)))
    assert len(started) == 1 and t.state(True) == "connecting"
    # 動き続けているだけでは「つながった」と言わない(443 番を黙って捨てる設置先がある)
    clock["now"] += 10
    assert t.state(True) == "connecting"
    ta.SSH_LOG.write_bytes(b"debug1: Connecting to bastion\n"
                           b"debug1: remote forward success for: listen 127.0.0.1:20001, connect 127.0.0.1:2222\n")
    assert t.state(True) == "open"

    # サーバーに聞けないまま時間が過ぎる(ensure が呼ばれない)
    clock["now"] += 599 - 10
    t.tick()
    assert t.running()
    clock["now"] += 2
    t.tick()
    assert not t.running() and started[0].terminated


def test_聞けているあいだは残り時間を数え直す(fake_ssh):
    clock, started = fake_ssh
    t = ta.Tunnel()
    t.ensure(ta.parse_want(_resp(ttl_sec=60)))
    clock["now"] += 50
    t.ensure(ta.parse_want(_resp(ttl_sec=600)))   # 運営が延長した
    clock["now"] += 100
    t.tick()
    assert t.running() and len(started) == 1      # つなぎ直しはしない


def test_切れたら理由を控えて間を置いてやり直す(fake_ssh):
    clock, started = fake_ssh
    t = ta.Tunnel()
    want = ta.parse_want(_resp())
    t.ensure(want)
    ta.SSH_LOG.write_text("ssh: connect to host bastion.example.test port 443: Connection timed out\n"
                          "debug1: Exit status -1\n\n", encoding="utf-8")
    started[0].returncode = 255
    t.tick()
    assert not t.running() and "Connection timed out" in t.error and t.state(True) == "connecting"
    t.ensure(want)
    assert len(started) == 1                      # すぐにはやり直さない
    clock["now"] += ta.RETRY_AFTER_SEC
    t.ensure(want)
    assert len(started) == 2 and t.error == ""


def test_記録の文言が変わったsshでも接続待ちのまま止まらない(fake_ssh):
    clock, _ = fake_ssh
    t = ta.Tunnel()
    t.ensure(ta.parse_want(_resp()))
    clock["now"] += ta.OPEN_AFTER_SEC
    assert t.state(True) == "open"


def test_つなぎ直したら前の接続の記録を引きずらない(fake_ssh):
    clock, started = fake_ssh
    t = ta.Tunnel()
    want = ta.parse_want(_resp())
    t.ensure(want)
    ta.SSH_LOG.write_bytes(b"debug1: remote forward success for: listen 127.0.0.1:20001\n")
    assert t.state(True) == "open"
    started[0].returncode = 255
    t.tick()
    clock["now"] += ta.RETRY_AFTER_SEC
    t.ensure(want)   # ここで記録は空に戻る(実物は ssh の起動時に上書きする)
    ta.SSH_LOG.write_bytes(b"debug1: Connecting\n")
    assert t.state(True) == "connecting"


def test_つなぎ先が変わったらつなぎ直す(fake_ssh):
    _, started = fake_ssh
    t = ta.Tunnel()
    t.ensure(ta.parse_want(_resp(remote_port=20001)))
    t.ensure(ta.parse_want(_resp(remote_port=20002)))
    assert len(started) == 2 and started[0].terminated
    assert "127.0.0.1:20002:127.0.0.1:2222" in started[1].cmd


def test_キオスク本体にも仮想環境にも頼らない():
    """本体が起動しなくなった端末にこそ入りたい。標準ライブラリだけで動かす
    (本体のモジュールや、pip で入れるライブラリを import しない)。"""
    tree = ast.parse((AGENT_DIR / "tunnel_agent.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    names.discard("__future__")
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)
    unit = (AGENT_DIR / "system" / "mokuture-tunnel.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/python3 @AGENT_DIR@/tunnel_agent.py" in unit and "VENV" not in unit


def test_配信されるが本体の再起動は起こさない():
    assert "tunnel_agent.py" in updater.MANAGED_FILES
    assert "tunnel_agent.py" not in updater.RESTART_FILES


def test_受け口は端末の中だけで鍵でしか入れない():
    socket_unit = (AGENT_DIR / "system" / "mokuture-tunnel-sshd.socket").read_text(encoding="utf-8")
    listen = [line for line in socket_unit.splitlines() if line.startswith("ListenStream=")]
    assert listen == [f"ListenStream=127.0.0.1:{ta.LOCAL_SSH_PORT}"]
    conf = (AGENT_DIR / "system" / "tunnel_sshd_config").read_text(encoding="utf-8")
    settings = dict(line.split(None, 1) for line in conf.splitlines() if line and not line.startswith("#"))
    assert settings["PasswordAuthentication"] == "no"
    assert settings["KbdInteractiveAuthentication"] == "no"
    assert settings["PermitRootLogin"] == "no"
    # 端末の利用者が自分で置ける場所(~/.ssh)の鍵は見ない。署名つきで配った鍵だけ
    assert settings["AuthorizedKeysFile"] == "/etc/mokuture/tunnel_sshd/authorized_keys"
    assert settings["AllowUsers"] == "@AGENT_USER@"


def test_運営の鍵と受け口の設定は署名の対象():
    """ここが署名されていないと、配信元を乗っ取った者が自分の鍵を足して端末に入れる。"""
    listed = {line.split("  ", 1)[1] for line in
              (AGENT_DIR / "system" / "SYSTEM_MANIFEST").read_text(encoding="utf-8").splitlines() if line.strip()}
    for rel in ("system/operator_keys", "system/tunnel_sshd_config", "system/mokuture-tunnel.service",
                "system/mokuture-tunnel-sshd.socket", "system/mokuture-tunnel-sshd-at.service"):
        assert rel in listed, f"署名の対象に入っていない: {rel}"
    keys = (AGENT_DIR / "system" / "operator_keys").read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in keys
