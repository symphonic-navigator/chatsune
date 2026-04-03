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


_VALID_PERSONA = {
    "name": "Aria",
    "tagline": "Your helpful companion",
    "model_unique_id": "ollama_cloud:llama3.2",
    "system_prompt": "You are a helpful assistant.",
    "temperature": 0.8,
    "reasoning_enabled": False,
    "colour_scheme": "#7c3aed",
    "display_order": 0,
}


async def test_list_personas_empty(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/personas", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Aria"
    assert data["model_unique_id"] == "ollama_cloud:llama3.2"
    assert "id" in data
    assert "created_at" in data


async def test_create_persona_invalid_model_id_format(client: AsyncClient):
    token = await _setup_and_login(client)
    invalid = {**_VALID_PERSONA, "model_unique_id": "no-colon-here"}
    resp = await client.post("/api/personas", json=invalid, headers=_auth(token))
    assert resp.status_code == 400


async def test_create_persona_unknown_provider(client: AsyncClient):
    token = await _setup_and_login(client)
    invalid = {**_VALID_PERSONA, "model_unique_id": "nonexistent_provider:model"}
    resp = await client.post("/api/personas", json=invalid, headers=_auth(token))
    assert resp.status_code == 400


async def test_get_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.get(f"/api/personas/{persona_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == persona_id


async def test_get_persona_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/personas/nonexistent-id", headers=_auth(token))
    assert resp.status_code == 404


async def test_list_personas_after_create(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    second = {**_VALID_PERSONA, "name": "Zara", "display_order": 1}
    await client.post("/api/personas", json=second, headers=_auth(token))

    resp = await client.get("/api/personas", headers=_auth(token))
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert names == ["Aria", "Zara"]  # ordered by display_order


async def test_put_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    updated = {**_VALID_PERSONA, "name": "Aria v2", "temperature": 1.2}
    resp = await client.put(f"/api/personas/{persona_id}", json=updated, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Aria v2"
    assert resp.json()["temperature"] == 1.2


async def test_patch_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/personas/{persona_id}",
        json={"name": "Aria Patched"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Aria Patched"
    assert resp.json()["tagline"] == "Your helpful companion"  # unchanged


async def test_patch_persona_empty_body(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/personas/{persona_id}", json={}, headers=_auth(token)
    )
    assert resp.status_code == 400


async def test_delete_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/personas/{persona_id}", headers=_auth(token))
    assert resp.status_code == 200

    get_resp = await client.get(f"/api/personas/{persona_id}", headers=_auth(token))
    assert get_resp.status_code == 404


async def test_delete_persona_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete("/api/personas/nonexistent-id", headers=_auth(token))
    assert resp.status_code == 404


async def test_unauthenticated_access_rejected(client: AsyncClient):
    resp = await client.get("/api/personas")
    assert resp.status_code == 401
