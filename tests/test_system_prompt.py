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


async def test_get_system_prompt_default_empty(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get("/api/settings/system-prompt", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == ""


async def test_set_and_get_system_prompt(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/settings/system-prompt",
        json={"content": "Be helpful and harmless."},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Be helpful and harmless."
    assert data["updated_by"] is not None

    resp = await client.get("/api/settings/system-prompt", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["content"] == "Be helpful and harmless."


async def test_update_system_prompt_overwrites(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/system-prompt",
        json={"content": "Version 1"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/settings/system-prompt",
        json={"content": "Version 2"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Version 2"


async def test_system_prompt_requires_admin(client: AsyncClient):
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

    resp = await client.get("/api/settings/system-prompt", headers=_auth(user_token))
    assert resp.status_code == 403

    resp = await client.put(
        "/api/settings/system-prompt",
        json={"content": "nope"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403
