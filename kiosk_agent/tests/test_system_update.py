"""システム更新(管理者権限で動く側)の決まり。

OTA で届いたものを管理者権限で動かすので、次を崩さない:
1. 端末が実行するのは署名を確かめられた版だけ。署名は開発機の鍵でしか作れない。
2. 署名した一覧(SYSTEM_MANIFEST)は、リポジトリのいまの中身と合っている
   (apply.sh を書き換えて署名し直し忘れると、端末は「ハッシュが合わない」で実行しない)。
3. 確かめに失敗したら何も実行しない。古い署名済みの版(連番が戻る版)も実行しない。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import sysupdate
import updater

AGENT_DIR = Path(__file__).resolve().parent.parent
SYSTEM = AGENT_DIR / "system"
ROOT_SCRIPT = SYSTEM / "sysupdate-root.sh"
IDENTITY = NAMESPACE = "mokuture-sysupdate"


def _manifest_lines(path: Path) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        out.append((digest, rel))
    return out


def _lf(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")   # 端末へは LF で届く


# ── リポジトリの中身 ─────────────────────────────────────────────────────────

def test_署名した一覧がいまの中身と合っている():
    for digest, rel in _manifest_lines(SYSTEM / "SYSTEM_MANIFEST"):
        actual = hashlib.sha256(_lf(AGENT_DIR / rel)).hexdigest()
        assert actual == digest, f"{rel} を書き換えたあと署名し直していない: bash kiosk_agent/scripts/sign_system.sh"


def test_一覧の署名を公開鍵で確かめられる(tmp_path):
    if not shutil.which("ssh-keygen"):
        pytest.skip("ssh-keygen が無い")
    manifest = tmp_path / "SYSTEM_MANIFEST"
    manifest.write_bytes(_lf(SYSTEM / "SYSTEM_MANIFEST"))
    sig = tmp_path / "SYSTEM_MANIFEST.sig"
    sig.write_bytes(_lf(SYSTEM / "SYSTEM_MANIFEST.sig"))
    signers = tmp_path / "allowed_signers"
    signers.write_bytes(_lf(SYSTEM / "allowed_signers"))
    r = subprocess.run(
        ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", IDENTITY, "-n", NAMESPACE, "-s", str(sig)],
        input=manifest.read_bytes(), capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr.decode(errors="replace")


def test_署名の対象と一覧と署名が配信される():
    managed = set(updater.MANAGED_FILES)
    for _, rel in _manifest_lines(SYSTEM / "SYSTEM_MANIFEST"):
        assert rel in managed, f"署名したのに配信されない: {rel}"
    for rel in ("system/SYSTEM_MANIFEST", "system/SYSTEM_MANIFEST.sig", "sysupdate.py", "pyproject.toml"):
        assert rel in managed, rel
    listed = {rel for _, rel in _manifest_lines(SYSTEM / "SYSTEM_MANIFEST")}
    assert {"system/apply.sh", "system/sysupdate-root.sh", "system/SERIAL", "system/PYPROJECT_SHA"} <= listed


def test_ライブラリの一覧を変えたら版が変わる():
    """pyproject.toml は署名しない(管理者権限では読ませない)が、変えたら端末で pip を
    やり直す必要がある。ハッシュを署名の対象に入れてあるので、署名し直せば版が変わる。"""
    want = hashlib.sha256(_lf(AGENT_DIR / "pyproject.toml")).hexdigest()
    have = (SYSTEM / "PYPROJECT_SHA").read_text().strip()
    assert have == want, "pyproject.toml を変えたあと署名し直していない: bash kiosk_agent/scripts/sign_system.sh"


def test_秘密鍵と公開鍵の置き場所():
    """秘密鍵をリポジトリに入れない。公開鍵と install.sh は配信しない(どちらも人が管理者として
    使うもので署名が無い。配信で差し替えられたら署名で守る意味が無い)。"""
    assert "system/allowed_signers" not in updater.MANAGED_FILES
    assert "install.sh" not in updater.MANAGED_FILES
    for p in SYSTEM.iterdir():
        assert b"PRIVATE KEY" not in p.read_bytes(), f"秘密鍵が入っている: {p.name}"


# ── エージェントが読む状態 ───────────────────────────────────────────────────

@pytest.fixture
def state(tmp_path, monkeypatch):
    helper = tmp_path / "helper.sh"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    manifest = tmp_path / "SYSTEM_MANIFEST"
    manifest.write_bytes(b"abc  system/apply.sh\n")
    monkeypatch.setattr(sysupdate, "_IS_DEVICE", True)
    monkeypatch.setattr(sysupdate, "HELPER", helper)
    monkeypatch.setattr(sysupdate, "STATE_DIR", state_dir)
    monkeypatch.setattr(sysupdate, "MANIFEST", manifest)
    return helper, state_dir, hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]


def _write_status(state_dir: Path, **kw):
    (state_dir / "sysupdate.status").write_text(json.dumps(kw), encoding="utf-8")


def test_仕組みが入っていない端末は未導入と出す(state):
    assert sysupdate.status()["state"] == "not_installed"


def test_開発機では出さない(state, monkeypatch):
    monkeypatch.setattr(sysupdate, "_IS_DEVICE", False)
    assert sysupdate.status() == {"state": "unsupported"}


def test_届いた版と適用した版を比べる(state):
    helper, state_dir, wanted = state
    helper.write_text("#!/bin/bash\n")
    assert sysupdate.status()["state"] == "pending", "まだ一度も適用していない"
    _write_status(state_dir, state="ok", version="0000000000000000", serial=1, at="x", message="")
    assert sysupdate.status()["state"] == "pending", "前の版を適用済みでも、新しい版はまだ"
    _write_status(state_dir, state="ok", version=wanted, serial=2, at="x", message="")
    assert sysupdate.status()["state"] == "ok"
    _write_status(state_dir, state="failed", version=wanted, serial=2, at="x", message="i2c, packages")
    s = sysupdate.status()
    assert s["state"] == "failed" and s["message"] == "i2c, packages"
    _write_status(state_dir, state="rejected", version=wanted, serial=0, at="x", message="signature")
    assert sysupdate.status()["state"] == "rejected"


def test_壊れた状態ファイルで落ちない(state):
    helper, state_dir, _ = state
    helper.write_text("#!/bin/bash\n")
    (state_dir / "sysupdate.status").write_text("{こわれている", encoding="utf-8")
    assert sysupdate.status()["state"] == "pending"


def test_まだ配信されていなければ適用待ちと出さない(state):
    helper, _, _ = state
    helper.write_text("#!/bin/bash\n")
    sysupdate.MANIFEST.unlink()
    assert sysupdate.status()["state"] == "not_delivered"


def test_再起動の頼みは起動より後のものだけ(state, monkeypatch):
    """印の中身で比べる(時刻では比べない。時計を持たない Pi は起動直後の時刻が戻る)。"""
    _, state_dir, _ = state
    monkeypatch.setattr(sysupdate, "_TOKEN_AT_START", "")
    assert sysupdate.restart_requested() is False, "印が無い"
    flag = state_dir / "restart-requested"
    flag.write_text("1700000000-12-345\n")
    assert sysupdate.restart_requested() is True
    # 再起動したあと(起動時に同じ印を覚えている)は、同じ頼みで何度も再起動しない。
    # ファイルの時刻が未来でも関係ない。
    monkeypatch.setattr(sysupdate, "_TOKEN_AT_START", sysupdate._restart_token())
    os.utime(flag, (4102444800, 4102444800))
    assert sysupdate.restart_requested() is False
    flag.write_text("1700000999-13-999\n")
    assert sysupdate.restart_requested() is True, "新しい頼み"


def test_待機画面は再起動の頼みにも応じる(monkeypatch):
    import asyncio

    import main

    monkeypatch.setattr(main, "_sys_restart_requested", lambda: True)
    data = asyncio.run(main.update_status())
    assert data["ready"] is True and "system" in data


# ── 確かめる手順そのもの(管理者でない利用者として、別の場所を根にして動かす) ───

BASH = shutil.which("bash")
NEEDED = all(shutil.which(t) for t in ("bash", "ssh-keygen", "sha256sum"))


def _posix(p: Path) -> str:
    """bash へ渡すパス。Windows(Git Bash)では C:\\x を /c/x にする。"""
    s = str(p)
    if os.name == "nt" and len(s) > 1 and s[1] == ":":
        return "/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


class Device:
    """試験用の端末ひとつぶん(/ の代わりのディレクトリと、エージェントの置き場所)。"""

    def __init__(self, tmp: Path):
        self.root = tmp / "root"
        self.agent = tmp / "agent"
        self.key = tmp / "key"
        self.state = self.root / "var/lib/mokuture"
        (self.root / "etc/mokuture").mkdir(parents=True)
        self.state.mkdir(parents=True)
        (self.agent / "system").mkdir(parents=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "t", "-f", str(self.key)],
                       check=True, timeout=30)
        pub = " ".join(Path(str(self.key) + ".pub").read_text().split()[:2])
        self._w(self.root / "etc/mokuture/allowed_signers", f'{IDENTITY} namespaces="{NAMESPACE}" {pub}\n')
        self._w(self.root / "etc/mokuture/sysupdate.conf",
                f"AGENT_DIR='{_posix(self.agent)}'\nAGENT_USER=nobody\nVENV='{_posix(self.agent)}/.venv'\n")

    @staticmethod
    def _w(path: Path, text: str) -> None:
        path.write_bytes(text.encode("utf-8"))   # 改行を LF のまま書く

    def publish(self, serial: int, script: str = 'echo ran > "$STATE_DIR/ran"\n', key: Path | None = None):
        """配信された体で、apply.sh と連番を置いて署名する。"""
        self._w(self.agent / "system/apply.sh", "#!/bin/bash\n" + script)
        self._w(self.agent / "system/SERIAL", f"{serial}\n")
        lines = "".join(
            f"{hashlib.sha256((self.agent / rel).read_bytes()).hexdigest()}  {rel}\n"
            for rel in ("system/apply.sh", "system/SERIAL"))
        manifest = self.agent / "system/SYSTEM_MANIFEST"
        self._w(manifest, lines)
        sig = Path(str(manifest) + ".sig")
        sig.unlink(missing_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(key or self.key), "-n", NAMESPACE, str(manifest)],
                       check=True, timeout=30, capture_output=True)

    def run(self) -> subprocess.CompletedProcess:
        env = {**os.environ, "SYSUPDATE_TEST_ROOT": _posix(self.root)}
        return subprocess.run([BASH, _posix(ROOT_SCRIPT)], env=env, capture_output=True, timeout=120)

    def status(self) -> dict:
        try:
            return json.loads((self.state / "sysupdate.status").read_text(encoding="utf-8"))
        except OSError:
            return {}

    @property
    def ran(self) -> bool:
        return (self.state / "ran").exists()


@pytest.fixture
def device(tmp_path):
    if not NEEDED:
        pytest.skip("bash / ssh-keygen / sha256sum が無い")
    return Device(tmp_path)


def test_署名が正しければ実行して記録する(device):
    device.publish(1)
    r = device.run()
    assert r.returncode == 0, r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")
    assert device.ran
    assert device.status()["state"] == "ok" and device.status()["serial"] == 1
    # 同じ版は二度実行しない
    (device.state / "ran").unlink()
    assert device.run().returncode == 0 and not device.ran


def test_署名が無ければ実行しない(device):
    device.publish(1)
    (device.agent / "system/SYSTEM_MANIFEST.sig").write_bytes(b"")
    assert device.run().returncode != 0
    assert not device.ran and device.status()["message"] == "signature"


def test_別の鍵の署名では実行しない(device, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)], check=True, timeout=30)
    device.publish(1, key=other)
    assert device.run().returncode != 0
    assert not device.ran and device.status()["state"] == "rejected"


def test_署名のあとで中身を差し替えたら実行しない(device):
    device.publish(1)
    Device._w(device.agent / "system/apply.sh", '#!/bin/bash\necho evil > "$STATE_DIR/ran"\n')
    assert device.run().returncode != 0
    assert not device.ran and device.status()["message"] == "hash_mismatch"


def test_一覧を書き換えたら実行しない(device):
    """一覧のほうを中身に合わせて書き換えても、署名が合わなくなる。"""
    device.publish(1)
    evil = '#!/bin/bash\necho evil > "$STATE_DIR/ran"\n'
    Device._w(device.agent / "system/apply.sh", evil)
    manifest = device.agent / "system/SYSTEM_MANIFEST"
    lines = manifest.read_text().splitlines()
    lines[0] = f"{hashlib.sha256(evil.encode()).hexdigest()}  system/apply.sh"
    Device._w(manifest, "\n".join(lines) + "\n")
    assert device.run().returncode != 0
    assert not device.ran and device.status()["message"] == "signature"


def test_連番が戻る版は実行しない(device):
    device.publish(5)
    assert device.run().returncode == 0 and device.ran
    (device.state / "ran").unlink()
    device.publish(4, script='echo old > "$STATE_DIR/ran"\n')   # 正しく署名された、古い版
    assert device.run().returncode != 0
    assert not device.ran and device.status()["message"] == "rollback"


def test_失敗させ続けても古い版は流し直せない(device):
    """連番の下限は実行の前に進める。成功したときだけ進めると、わざと失敗させて止め、
    署名済みの古い版を何度でも管理者権限で動かせてしまう。"""
    fail = 'echo x >> "$STATE_DIR/count"\nexit 1\n'
    device.publish(5)
    assert device.run().returncode == 0
    device.publish(6, script=fail + "# six\n")
    six = {n: (device.agent / "system" / n).read_bytes() for n in ("apply.sh", "SERIAL", "SYSTEM_MANIFEST", "SYSTEM_MANIFEST.sig")}
    assert device.run().returncode != 0
    device.publish(7, script=fail + "# seven\n")
    assert device.run().returncode != 0
    runs = (device.state / "count").read_text().count("x")
    for name, data in six.items():            # 正しく署名された 6 を置き直す
        (device.agent / "system" / name).write_bytes(data)
    assert device.run().returncode != 0
    assert device.status()["message"] == "rollback"
    assert (device.state / "count").read_text().count("x") == runs, "古い版を実行した"


def test_同じ連番の別の版は実行しない(device):
    device.publish(3)
    assert device.run().returncode == 0
    (device.state / "ran").unlink()
    device.publish(3, script='echo other > "$STATE_DIR/ran"\n')
    assert device.run().returncode != 0
    assert not device.ran and device.status()["message"] == "rollback"


def test_連番の無い一覧は実行しない(device):
    device.publish(1)
    manifest = device.agent / "system/SYSTEM_MANIFEST"
    Device._w(manifest, manifest.read_text().splitlines()[0] + "\n")   # apply.sh の行だけ
    sig = Path(str(manifest) + ".sig")
    sig.unlink()
    subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(device.key), "-n", NAMESPACE, str(manifest)],
                   check=True, timeout=30, capture_output=True)
    assert device.run().returncode != 0
    assert not device.ran and device.status()["message"] == "no_serial"


def test_大きすぎるファイルは取り込まない(device):
    device.publish(1)
    (device.agent / "system/SYSTEM_MANIFEST").write_bytes(b"0" * (1024 * 1024 + 10))
    device.run()
    assert not device.ran
    assert not any(p.name.startswith("stage.") for p in device.state.iterdir()), "一時置き場が残っている"


def test_失敗した版はすぐにはやり直さない(device):
    device.publish(1, script='echo i2c > "$STATE_DIR/apply.failed"\necho x >> "$STATE_DIR/count"\nexit 1\n')
    assert device.run().returncode != 0
    s = device.status()
    assert s["state"] == "failed" and s["message"] == "i2c"
    device.run()
    assert (device.state / "count").read_text().count("x") == 1, "1 時間たつ前にやり直した"
    # 直した版(中身が変わる)が届けば、待たずに適用する
    device.publish(2)
    assert device.run().returncode == 0 and device.ran and device.status()["state"] == "ok"


def test_管理者でも試験用でもなければ動かない():
    if not NEEDED:
        pytest.skip("bash が無い")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("管理者として動かしている")
    env = {k: v for k, v in os.environ.items() if k != "SYSUPDATE_TEST_ROOT"}
    r = subprocess.run([BASH, _posix(ROOT_SCRIPT)], env=env, capture_output=True, timeout=30)
    assert r.returncode != 0
