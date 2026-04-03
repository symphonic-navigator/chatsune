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


async def test_credential_status_empty(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get("/api/llm/admin/credential-status", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_credential_status_after_setting_key(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-key-123"},
        headers=_auth(token),
    )
    resp = await client.get("/api/llm/admin/credential-status", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["providers"][0]["provider_id"] == "ollama_cloud"
    assert data[0]["providers"][0]["is_configured"] is True


async def test_credential_status_requires_admin(client: AsyncClient):
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

    resp = await client.get("/api/llm/admin/credential-status", headers=_auth(user_token))
    assert resp.status_code == 403
