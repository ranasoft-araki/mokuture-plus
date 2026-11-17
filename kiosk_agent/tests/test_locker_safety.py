"""ロッカーの安全側の決まりと、端末エージェントの受け口の決まり。

- 扉センサーが「開」を示す空きの口は、預け入れ・置き配で開けない(409)。読めない(None)ときは従来どおり。
- 受け取りは、錠を動かせたときだけ空きに戻す(動かせなければ 503・利用中のまま)。
- 暗証番号は口ごとに 5 回続けて違えると 5 分受け付けない(429)。
- 全解除は扉の状態にかかわらず錠を動かす。
- 端末の外(ループバック以外)からの要求は断る(KIOSK_ALLOW_REMOTE=1 のときだけ通す)。
- 「通電したまま」の ON は一定時間で自動的に OFF へ戻る。

本物の状態ファイル(locker_state.json / device_state.json)と本番の backend には触らない:
状態ファイルは tmp_path へ差し替え、裏で走る処理(_spawn)は捨てる。lifespan も動かさない。
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import locker_store
import main
import state


class FakeDoor:
    def __init__(self, closed: bool | None):
        self.pin = 99
        self.configured = True
        self.is_closed = closed

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _locker_ctrl(monkeypatch):
    # 開発機の .env は LOCKER_PINS_JSON={} のことがある。3 口の模擬リレーを用意する。
    monkeypatch.setattr(main, "locker_ctrl", main.LockerController({"1": 14, "2": 15, "3": 18}))


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(locker_store, "_STATE_FILE", tmp_path / "locker_state.json")
    # 既定では、どの扉のセンサーも「閉」を読めたことがある(=働いている)扱いにする。
    monkeypatch.setattr(locker_store, "_seen_closed_cache", {1, 2, 3})
    monkeypatch.setattr(state, "_STATE_FILE", tmp_path / "device_state.json")
    monkeypatch.delenv("KIOSK_ALLOW_REMOTE", raising=False)

    def fake_spawn(coro):   # 置き配通知・ミラー・扉の見張りなどは走らせない
        coro.close()
        return None

    monkeypatch.setattr(main, "_spawn", fake_spawn)
    monkeypatch.setattr(main, "_locker_op_lock", asyncio.Lock())
    main._pin_failures.clear()
    # 扉センサーは既定で「閉」。実機の GPIO が読めている扱いにする(開発機の模擬は None になるため)。
    doors = {str(i): FakeDoor(True) for i in range(1, 4)}
    monkeypatch.setattr(main, "doors", doors)
    monkeypatch.setattr(main, "gpio_status", lambda: {"hardware": True, "reason": None})
    monkeypatch.setattr(main, "_MOCK_DEVICE", True)   # 錠は gpio.py の模擬で「動いた」と答える
    locker_store.ensure_local_roster([1, 2, 3])
    client = TestClient(main.app, client=("127.0.0.1", 50000))
    yield client, doors
    main._pin_failures.clear()


def _occupy(client, lid="1", pin="1234"):
    r = client.post(f"/device/locker/{lid}/occupy", json={"pin": pin})
    assert r.status_code == 200, r.text


# ── 扉の状態 ────────────────────────────────────────────────────────────────

def test_一覧に扉の状態が載る(agent):
    client, doors = agent
    doors["2"].is_closed = False
    items = {it["id"]: it for it in client.get("/device/locker-list").json()["lockers"]}
    assert items["1"]["door_closed"] is True
    assert items["2"]["door_closed"] is False


def test_閉を一度も読めていない扉の開は信じない(agent, monkeypatch):
    """センサーをつないでいない入力はずっと「開」と読める。真に受けると全部の口が使えなくなる。"""
    client, doors = agent
    monkeypatch.setattr(locker_store, "_seen_closed_cache", set())
    doors["2"].is_closed = False
    items = {it["id"]: it for it in client.get("/device/locker-list").json()["lockers"]}
    assert items["2"]["door_closed"] is None          # 開だが、働いているか分からない
    assert client.post("/device/locker/2/open").status_code == 200
    assert items["1"]["door_closed"] is True          # 閉を読めた扉は、以後「開」も信じる
    doors["1"].is_closed = False
    items = {it["id"]: it for it in client.get("/device/locker-list").json()["lockers"]}
    assert items["1"]["door_closed"] is False
    assert client.post("/device/locker/1/open").status_code == 409
    assert 1 in locker_store._load()["doors_seen_closed"]   # 再起動しても覚えている


def test_GPIOが実機でなければ扉は分からない扱い(agent, monkeypatch):
    client, doors = agent
    doors["1"].is_closed = False   # 模擬の DoorSensor は常に「開」と答える
    monkeypatch.setattr(main, "gpio_status", lambda: {"hardware": False, "reason": "no_library"})
    items = client.get("/device/locker-list").json()["lockers"]
    assert all(it["door_closed"] is None for it in items)
    # 分からないときは従来どおり開けられる
    assert client.post("/device/locker/1/open").status_code == 200


def test_センサーの無い扉は分からない扱い(agent, monkeypatch):
    client, doors = agent
    monkeypatch.setattr(main, "doors", {"1": doors["1"]})
    items = {it["id"]: it for it in client.get("/device/locker-list").json()["lockers"]}
    assert items["2"]["door_closed"] is None


def test_センサーの無い口はパルスの終わりを待たずに返す(agent, monkeypatch):
    client, _ = agent
    monkeypatch.setattr(main, "doors", {})

    async def must_not_wait(*a, **k):
        raise AssertionError("固定パルスの終わりまで待ってから返している")

    monkeypatch.setattr(main.locker_ctrl, "open", must_not_wait)
    r = client.post("/device/locker/1/open")
    assert r.status_code == 200
    assert r.json()["autolock"] is False
    assert main.locker_ctrl.is_on("1") is True   # 通電した(戻すのは裏の処理)


def test_扉が開いている空きの口は開けない(agent):
    client, doors = agent
    doors["1"].is_closed = False
    r = client.post("/device/locker/1/open")
    assert r.status_code == 409
    assert "扉が開いている" in r.json()["detail"]
    assert client.post("/device/locker/2/open").status_code == 200


def test_利用中の口は扉が開いていても開けられる(agent):
    client, doors = agent
    _occupy(client, "1")
    doors["1"].is_closed = False
    assert client.post("/device/locker/1/open").status_code == 200


# ── 受け取り ────────────────────────────────────────────────────────────────

def test_受け取りは錠を動かしてから空きに戻す(agent):
    client, _ = agent
    _occupy(client, "1", "4321")
    r = client.post("/device/locker/1/release", json={"pin": "4321"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unlocked"] is True and body["door_number"] == 1
    items = {it["id"]: it for it in client.get("/device/locker-list").json()["lockers"]}
    assert items["1"]["occupied"] is False


def test_実機でGPIOが模擬に落ちていたら受け取りは失敗にして利用中のまま(agent, monkeypatch):
    client, _ = agent
    _occupy(client, "1", "4321")
    monkeypatch.setattr(main, "_MOCK_DEVICE", False)
    monkeypatch.setattr(main, "gpio_status", lambda: {"hardware": False, "reason": "no_library"})
    r = client.post("/device/locker/1/release", json={"pin": "4321"})
    assert r.status_code == 503
    items = {it["id"]: it for it in client.get("/device/locker-list").json()["lockers"]}
    assert items["1"]["occupied"] is True and items["1"]["has_pin"] is True
    # 預け入れの解錠も同じく動かせないと答える
    assert client.post("/device/locker/2/open").status_code == 503


def test_リレーが動かなければ受け取りは失敗(agent, monkeypatch):
    client, _ = agent
    _occupy(client, "1", "4321")
    monkeypatch.setattr(main.locker_ctrl, "set_state", lambda lid, on: False)
    assert client.post("/device/locker/1/release", json={"pin": "4321"}).status_code == 503
    assert locker_store.door_occupied(1)


def test_開発機の模擬では受け取りが成功する(agent, monkeypatch):
    client, _ = agent
    monkeypatch.setattr(main, "gpio_status", lambda: {"hardware": False, "reason": "no_library"})
    _occupy(client, "1", "4321")
    assert client.post("/device/locker/1/release", json={"pin": "4321"}).status_code == 200


# ── 暗証番号の試行回数 ────────────────────────────────────────────────────────

def test_5回続けて違うとしばらく受け付けない(agent, monkeypatch):
    client, _ = agent
    _occupy(client, "1", "4321")
    for _ in range(4):
        assert client.post("/device/locker/1/release", json={"pin": "0000"}).status_code == 403
    r = client.post("/device/locker/1/release", json={"pin": "0000"})
    assert r.status_code == 429
    # 正しい番号でも、期限までは受け付けない
    assert client.post("/device/locker/1/release", json={"pin": "4321"}).status_code == 429
    assert locker_store.door_occupied(1)
    # 他の口には影響しない
    _occupy(client, "2", "1111")
    assert client.post("/device/locker/2/release", json={"pin": "1111"}).status_code == 200
    # 期限が過ぎれば受け付ける
    real = main.time.monotonic
    monkeypatch.setattr(main.time, "monotonic", lambda: real() + main._PIN_LOCKOUT_SEC + 1)
    assert client.post("/device/locker/1/release", json={"pin": "4321"}).status_code == 200


def test_正しい番号で数え直す(agent):
    client, _ = agent
    _occupy(client, "1", "4321")
    for _ in range(4):
        assert client.post("/device/locker/1/release", json={"pin": "0000"}).status_code == 403
    assert client.post("/device/locker/1/release", json={"pin": "4321"}).status_code == 200
    _occupy(client, "1", "4321")
    for _ in range(4):
        assert client.post("/device/locker/1/release", json={"pin": "0000"}).status_code == 403


# ── 全解除 ──────────────────────────────────────────────────────────────────

def test_全解除は扉の状態にかかわらず錠を動かす(agent, monkeypatch):
    client, doors = agent
    _occupy(client, "1")
    doors["1"].is_closed = False
    driven = []
    real = main.locker_ctrl.set_state

    def spy(lid, on):
        if on:
            driven.append(lid)
        return real(lid, on)

    monkeypatch.setattr(main.locker_ctrl, "set_state", spy)
    r = client.post("/device/lockers/open-all")
    assert r.status_code == 200
    body = r.json()
    assert body["driven"] is True and body["failed"] == []
    assert sorted(driven) == ["1", "2", "3"]
    assert not locker_store.door_occupied(1)


def test_実機でGPIOが模擬でも全解除は記録を消し動かせなかった扉を返す(agent, monkeypatch):
    """錠は動かせないが、記録まで残すとその端末では利用中の口を空きに戻す手段が無くなる。"""
    client, _ = agent
    _occupy(client, "1")
    monkeypatch.setattr(main, "_MOCK_DEVICE", False)
    monkeypatch.setattr(main, "gpio_status", lambda: {"hardware": False, "reason": "no_library"})
    r = client.post("/device/lockers/open-all")
    assert r.status_code == 200
    assert sorted(r.json()["failed"]) == [1, 2, 3]
    assert not locker_store.door_occupied(1)


# ── 端末の外からは受け付けない ────────────────────────────────────────────────

def test_ループバック以外からは断る(agent):
    remote = TestClient(main.app, client=("192.168.1.50", 50000))
    assert remote.get("/device/locker-list").status_code == 403
    assert remote.post("/device/lockers/open-all").status_code == 403
    assert remote.post("/register").status_code == 403


def test_IPv4射影のループバックは通す(agent):
    mapped = TestClient(main.app, client=("::ffff:127.0.0.1", 50000))
    assert mapped.get("/device/locker-list").status_code == 200
    v6 = TestClient(main.app, client=("::1", 50000))
    assert v6.get("/device/locker-list").status_code == 200


def test_明示的に許可すれば外からも通す(agent, monkeypatch):
    monkeypatch.setenv("KIOSK_ALLOW_REMOTE", "1")
    remote = TestClient(main.app, client=("192.168.1.50", 50000))
    assert remote.get("/device/locker-list").status_code == 200


def test_CORSはこの端末のオリジンだけ(agent):
    client, _ = agent
    ok = client.get("/device/pir", headers={"Origin": "http://localhost:8080"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8080"
    other = client.get("/device/pir", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


# ── 通電したままの自動 OFF ───────────────────────────────────────────────────

def test_通電ONは一定時間で自動的にOFFへ戻る(monkeypatch):
    monkeypatch.setattr(main, "_STATE_ON_MAX_SEC", 0.05)

    async def run():
        main._state_off_tasks.clear()
        r = await main.set_locker_state("1", main.LockerStateBody(on=True))
        assert r["on"] is True and r["auto_off_sec"] == 0.05
        await asyncio.sleep(0.15)
        assert main.locker_ctrl.is_on("1") is False

        # OFF を押せば取り消す(後から勝手に動かない)
        await main.set_locker_state("1", main.LockerStateBody(on=True))
        await main.set_locker_state("1", main.LockerStateBody(on=False))
        assert "1" not in main._state_off_tasks

        # ON を押し直すと数え直す
        await main.set_locker_state("1", main.LockerStateBody(on=True))
        await asyncio.sleep(0.03)
        await main.set_locker_state("1", main.LockerStateBody(on=True))
        await asyncio.sleep(0.03)
        assert main.locker_ctrl.is_on("1") is True   # 最初の ON からは 0.06 秒だが、押し直しから 0.03 秒
        await asyncio.sleep(0.1)
        assert main.locker_ctrl.is_on("1") is False

    asyncio.run(run())


# ── /register の再登録 ─────────────────────────────────────────────────────

def _register_env(monkeypatch, status_code: int):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/kiosk/status"):
            return httpx.Response(status_code, json={"status": "active", "device_name": "受付"})
        return httpx.Response(200, json={"device_token": "new-token", "device_name": "受付", "status": "pending"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(main.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(main.settings, "tenant_slug", "demo")
    return seen


def test_再登録はいまのトークンを添え返ってきたトークンを保存する(agent, monkeypatch):
    client, _ = agent
    state.save_device_state("old-token", "受付")
    seen = _register_env(monkeypatch, 401)   # 保存トークンが無効と言われた
    r = client.post("/register")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    post = [q for q in seen if q.url.path.endswith("/kiosk/register")][0]
    assert post.headers.get("X-Kiosk-Token") == "old-token"
    assert state.get_device_token() == "new-token"


def test_トークンが無ければ添えない(agent, monkeypatch):
    client, _ = agent
    seen = _register_env(monkeypatch, 401)
    assert client.post("/register").status_code == 200
    post = [q for q in seen if q.url.path.endswith("/kiosk/register")][0]
    assert "X-Kiosk-Token" not in post.headers
    assert state.get_device_token() == "new-token"


# ── 電子錠のつなぎ先が登録されていない口 ─────────────────────────────────────

def test_錠のつなぎ先が無い口を設定画面とデバイスチェックへ伝える(agent, monkeypatch):
    """台帳は口数から作るので、LOCKER_PINS_JSON={} でも口は画面に出て、タッチすると開けられない。
    原因を設定画面(/device/locker-config)とデバイスチェック(/device/status)に出せるようにする。"""
    client, _ = agent
    assert client.get("/device/locker-config").json()["locks_missing"] == []
    monkeypatch.setattr(main, "locker_ctrl", main.LockerController({"2": 15}))
    assert client.get("/device/locker-config").json()["locks_missing"] == [1, 3]
    assert client.get("/device/status").json()["locks_missing"] == [1, 3]
    assert client.post("/device/locker/1/open").status_code == 404


def test_口数を選んだかどうかが分かる(agent):
    client, _ = agent
    cfg = client.get("/device/locker-config").json()
    assert cfg["chosen"] is False and cfg["count"] == 3
    cfg = client.post("/device/locker-config", json={"count": 3}).json()
    assert cfg["chosen"] is True
