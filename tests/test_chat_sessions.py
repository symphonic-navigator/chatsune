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
    "name": "Test Persona",
    "tagline": "A test persona",
    "model_unique_id": "ollama_cloud:qwen3:32b",
    "system_prompt": "You are helpful.",
    "temperature": 0.7,
    "reasoning_enabled": False,
    "colour_scheme": "#7c3aed",
    "display_order": 0,
}


async def test_create_session(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    assert create_resp.status_code == 201
    persona_id = create_resp.json()["id"]

    resp = await client.post("/api/chat/sessions", json={"persona_id": persona_id}, headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()
    assert data["persona_id"] == persona_id
    assert data["state"] == "idle"
    assert data["model_unique_id"] == "ollama_cloud:qwen3:32b"
    assert "id" in data
    assert "created_at" in data


async def test_create_session_invalid_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post("/api/chat/sessions", json={"persona_id": "nonexistent"}, headers=_auth(token))
    assert resp.status_code == 404


async def test_list_sessions(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    await client.post("/api/chat/sessions", json={"persona_id": persona_id}, headers=_auth(token))
    await client.post("/api/chat/sessions", json={"persona_id": persona_id}, headers=_auth(token))

    resp = await client.get("/api/chat/sessions", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_session(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    session_resp = await client.post("/api/chat/sessions", json={"persona_id": persona_id}, headers=_auth(token))
    session_id = session_resp.json()["id"]

    resp = await client.get(f"/api/chat/sessions/{session_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == session_id


async def test_get_session_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/chat/sessions/nonexistent", headers=_auth(token))
    assert resp.status_code == 404


async def test_get_session_messages(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    session_resp = await client.post("/api/chat/sessions", json={"persona_id": persona_id}, headers=_auth(token))
    session_id = session_resp.json()["id"]

    resp = await client.get(f"/api/chat/sessions/{session_id}/messages", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_session_messages_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/chat/sessions/nonexistent/messages", headers=_auth(token))
    assert resp.status_code == 404


async def test_delete_session(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    session_resp = await client.post("/api/chat/sessions", json={"persona_id": persona_id}, headers=_auth(token))
    session_id = session_resp.json()["id"]

    resp = await client.delete(f"/api/chat/sessions/{session_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    get_resp = await client.get(f"/api/chat/sessions/{session_id}", headers=_auth(token))
    assert get_resp.status_code == 404


async def test_delete_session_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete("/api/chat/sessions/nonexistent", headers=_auth(token))
    assert resp.status_code == 404


async def test_unauthenticated_access_rejected(client: AsyncClient):
    resp = await client.get("/api/chat/sessions")
    assert resp.status_code == 401
