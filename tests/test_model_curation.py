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


async def _setup_regular_user(client: AsyncClient, admin_token: str) -> str:
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201, f"User creation failed: {create_resp.text}"
    generated_pw = create_resp.json()["generated_password"]
    resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_set_curation_requires_admin(client: AsyncClient):
    admin_token = await _setup_admin(client)
    user_token = await _setup_regular_user(client, admin_token)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "recommended", "hidden": False},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


async def test_set_curation_success(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={
            "overall_rating": "recommended",
            "hidden": False,
            "admin_description": "Great general-purpose model",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_rating"] == "recommended"
    assert data["hidden"] is False
    assert data["admin_description"] == "Great general-purpose model"
    assert data["last_curated_by"] is not None


async def test_set_curation_unknown_provider(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/nonexistent/models/llama3/curation",
        json={"overall_rating": "available"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_update_curation_overwrites(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "recommended"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "not_recommended", "hidden": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_rating"] == "not_recommended"
    assert data["hidden"] is True


async def test_delete_curation(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "recommended"},
        headers=_auth(token),
    )
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        headers=_auth(token),
    )
    assert resp.status_code == 200


async def test_delete_curation_when_none_exists(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        headers=_auth(token),
    )
    assert resp.status_code == 404
