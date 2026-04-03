from httpx import AsyncClient


async def _setup_and_login(client: AsyncClient) -> str:
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


async def test_list_providers_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/llm/providers")
    assert resp.status_code == 401


async def test_list_providers_returns_all_registered(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/llm/providers", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    provider_ids = [p["provider_id"] for p in data]
    assert "ollama_cloud" in provider_ids


async def test_list_providers_not_configured_by_default(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/llm/providers", headers=_auth(token))
    assert resp.status_code == 200
    ollama = next(p for p in resp.json() if p["provider_id"] == "ollama_cloud")
    assert ollama["is_configured"] is False
    assert ollama["created_at"] is None


async def test_set_provider_key(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-api-key-12345"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_id"] == "ollama_cloud"
    assert data["is_configured"] is True
    assert "api_key" not in data  # key must never be returned


async def test_set_provider_key_shows_in_list(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-api-key-12345"},
        headers=_auth(token),
    )
    resp = await client.get("/api/llm/providers", headers=_auth(token))
    ollama = next(p for p in resp.json() if p["provider_id"] == "ollama_cloud")
    assert ollama["is_configured"] is True
    assert ollama["created_at"] is not None


async def test_set_provider_key_unknown_provider(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.put(
        "/api/llm/providers/nonexistent/key",
        json={"api_key": "key"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_remove_provider_key(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-api-key-12345"},
        headers=_auth(token),
    )
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/key",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    # Verify it's gone
    list_resp = await client.get("/api/llm/providers", headers=_auth(token))
    ollama = next(p for p in list_resp.json() if p["provider_id"] == "ollama_cloud")
    assert ollama["is_configured"] is False


async def test_remove_provider_key_when_none_set(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/key",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_test_provider_key_unknown_provider(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/llm/providers/nonexistent/test",
        json={"api_key": "test-api-key"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_list_models_unknown_provider(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get(
        "/api/llm/providers/nonexistent/models",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_key_update_overwrites_existing(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "first-key"},
        headers=_auth(token),
    )
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "second-key"},
        headers=_auth(token),
    )
    # Verify only one entry exists (upsert, not duplicate)
    list_resp = await client.get("/api/llm/providers", headers=_auth(token))
    ollama_entries = [p for p in list_resp.json() if p["provider_id"] == "ollama_cloud"]
    assert len(ollama_entries) == 1
    assert ollama_entries[0]["is_configured"] is True
