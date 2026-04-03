import pytest
from httpx import AsyncClient


async def _setup_admin(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_list_settings_empty(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get("/api/settings", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_set_and_get_setting(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/settings/global_system_prompt",
        json={"value": "Be helpful and harmless."},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "global_system_prompt"
    assert data["value"] == "Be helpful and harmless."
    assert data["updated_by"] is not None

    resp = await client.get(
        "/api/settings/global_system_prompt",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "Be helpful and harmless."


async def test_update_setting_overwrites(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/global_system_prompt",
        json={"value": "Version 1"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/settings/global_system_prompt",
        json={"value": "Version 2"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "Version 2"


async def test_get_nonexistent_setting(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get(
        "/api/settings/nonexistent",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_delete_setting(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/test_key",
        json={"value": "some value"},
        headers=_auth(token),
    )
    resp = await client.delete("/api/settings/test_key", headers=_auth(token))
    assert resp.status_code == 200

    resp = await client.get("/api/settings/test_key", headers=_auth(token))
    assert resp.status_code == 404


async def test_delete_nonexistent_setting(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.delete("/api/settings/nonexistent", headers=_auth(token))
    assert resp.status_code == 404


async def test_settings_require_admin(client: AsyncClient):
    admin_token = await _setup_admin(client)
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers=_auth(admin_token),
    )
    generated_pw = create_resp.json()["generated_password"]
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    user_token = login_resp.json()["access_token"]

    resp = await client.get("/api/settings", headers=_auth(user_token))
    assert resp.status_code == 403

    resp = await client.put(
        "/api/settings/test",
        json={"value": "nope"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


async def test_list_settings_returns_all(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/key_a",
        json={"value": "value a"},
        headers=_auth(token),
    )
    await client.put(
        "/api/settings/key_b",
        json={"value": "value b"},
        headers=_auth(token),
    )
    resp = await client.get("/api/settings", headers=_auth(token))
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()]
    assert "key_a" in keys
    assert "key_b" in keys
