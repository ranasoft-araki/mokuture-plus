"""モニター設定(受付完了後のアンケートを出すテナント)。

- 既定はオフ(モニター以外のテナントにはアンケートを出さない)
- 切り替えられるのは運営だけ(店舗の管理者・スタッフは不可)
- キオスクは公開設定(`GET /settings/public/{slug}`)の `is_monitor` を見て出し分ける
"""
from __future__ import annotations

from app.services.auth import create_access_token

from conftest import add_user


async def test_既定ではモニターではない(client, tenant):
    r = await client.get(f"/api/settings/public/{tenant.slug}")
    assert r.status_code == 200
    assert r.json()["is_monitor"] is False


async def test_運営がモニターにするとキオスクの公開設定に出る(client, tenant, operator_headers):
    r = await client.patch(f"/api/operator/tenants/{tenant.id}/monitor", json={"monitor": True}, headers=operator_headers)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "tenant_id": tenant.id, "is_monitor": True}

    pub = (await client.get(f"/api/settings/public/{tenant.slug}")).json()
    assert pub["is_monitor"] is True

    listed = (await client.get("/api/operator/tenants", headers=operator_headers)).json()["items"]
    assert [t["is_monitor"] for t in listed if t["id"] == tenant.id] == [True]


async def test_運営はモニターを解除できる(client, tenant, operator_headers):
    await client.patch(f"/api/operator/tenants/{tenant.id}/monitor", json={"monitor": True}, headers=operator_headers)
    r = await client.patch(f"/api/operator/tenants/{tenant.id}/monitor", json={"monitor": False}, headers=operator_headers)
    assert r.status_code == 200 and r.json()["is_monitor"] is False
    assert (await client.get(f"/api/settings/public/{tenant.slug}")).json()["is_monitor"] is False


async def test_店舗の管理者はモニターを切り替えられない(client, tenant):
    admin = await add_user(tenant.id, "店舗 管理者", role="admin")
    headers = {"Authorization": f"Bearer {create_access_token(tenant_id=tenant.id, user_id=admin.id, role='admin')}"}
    r = await client.patch(f"/api/operator/tenants/{tenant.id}/monitor", json={"monitor": True}, headers=headers)
    assert r.status_code in (401, 403)
    assert (await client.get(f"/api/settings/public/{tenant.slug}")).json()["is_monitor"] is False


async def test_存在しないテナントは404(client, operator_headers):
    r = await client.patch("/api/operator/tenants/no-such-tenant/monitor", json={"monitor": True}, headers=operator_headers)
    assert r.status_code == 404


async def test_店舗の基本設定の保存ではモニターは変わらない(client, tenant):
    # 店舗側の設定保存(PATCH /settings)に is_monitor を混ぜても無視される＝切り替えは運営だけ
    admin = await add_user(tenant.id, "店舗 管理者", role="admin")
    headers = {"Authorization": f"Bearer {create_access_token(tenant_id=tenant.id, user_id=admin.id, role='admin')}"}
    r = await client.patch("/api/settings", json={"is_monitor": True, "kiosk_welcome_message": "ようこそ"}, headers=headers)
    assert r.status_code == 200
    assert (await client.get(f"/api/settings/public/{tenant.slug}")).json()["is_monitor"] is False


async def test_スタッフやトークン無しではモニターを切り替えられない(client, tenant):
    staff = await add_user(tenant.id, "店舗 スタッフ", role="staff")
    staff_headers = {"Authorization": f"Bearer {create_access_token(tenant_id=tenant.id, user_id=staff.id, role='staff')}"}
    for headers in (staff_headers, {}):
        r = await client.patch(f"/api/operator/tenants/{tenant.id}/monitor", json={"monitor": True}, headers=headers)
        assert r.status_code in (401, 403)
    assert (await client.get(f"/api/settings/public/{tenant.slug}")).json()["is_monitor"] is False
