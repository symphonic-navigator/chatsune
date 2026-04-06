"""Integration tests for memory REST API endpoints."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from backend.database import get_db
from backend.modules.memory._repository import MemoryRepository


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
    "colour_scheme": "solar",
    "display_order": 0,
}


async def _create_persona(client: AsyncClient, token: str) -> str:
    resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    assert resp.status_code == 201
    return resp.json()["id"]


async def _seed_journal_entry(
    user_id: str,
    persona_id: str,
    content: str = "User prefers dark mode",
    category: str | None = "preference",
) -> str:
    """Insert a journal entry directly via the repository and return its ID."""
    repo = MemoryRepository(get_db())
    return await repo.create_journal_entry(
        user_id=user_id,
        persona_id=persona_id,
        content=content,
        category=category,
        source_session_id="test-session",
    )


async def _seed_memory_body(
    user_id: str,
    persona_id: str,
    content: str = "Chris prefers dark mode and British English.",
    token_count: int = 12,
    entries_processed: int = 3,
) -> int:
    """Insert a memory body version directly via the repository and return the version number."""
    repo = MemoryRepository(get_db())
    return await repo.save_memory_body(
        user_id=user_id,
        persona_id=persona_id,
        content=content,
        token_count=token_count,
        entries_processed=entries_processed,
    )


# ---------------------------------------------------------------------------
# Journal: list
# ---------------------------------------------------------------------------


async def test_list_journal_entries_empty(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.get(f"/api/memory/{persona_id}/journal", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_journal_entries_returns_seeded(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    # Extract user_id from the token payload
    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    entry_id = await _seed_journal_entry(user_id, persona_id)

    resp = await client.get(f"/api/memory/{persona_id}/journal", headers=_auth(token))
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id
    assert entries[0]["state"] == "uncommitted"
    assert entries[0]["content"] == "User prefers dark mode"


async def test_list_journal_entries_filter_by_state(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    await _seed_journal_entry(user_id, persona_id, content="Entry A")
    entry_b_id = await _seed_journal_entry(user_id, persona_id, content="Entry B")

    # Commit entry B
    repo = MemoryRepository(get_db())
    await repo.commit_entry(entry_b_id, user_id)

    resp = await client.get(
        f"/api/memory/{persona_id}/journal?state=committed",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["id"] == entry_b_id
    assert entries[0]["state"] == "committed"


# ---------------------------------------------------------------------------
# Journal: patch/update
# ---------------------------------------------------------------------------


async def test_update_journal_entry(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    entry_id = await _seed_journal_entry(user_id, persona_id)

    resp = await client.patch(
        f"/api/memory/{persona_id}/journal/{entry_id}",
        json={"content": "User actually prefers light mode"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == entry_id
    assert data["content"] == "User actually prefers light mode"


async def test_update_journal_entry_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.patch(
        f"/api/memory/{persona_id}/journal/nonexistent-id",
        json={"content": "Updated content"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Journal: commit
# ---------------------------------------------------------------------------


async def test_commit_journal_entries(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    entry_id = await _seed_journal_entry(user_id, persona_id)

    resp = await client.post(
        f"/api/memory/{persona_id}/journal/commit",
        json={"entry_ids": [entry_id]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["committed"] == 1

    # Verify entry is now committed
    list_resp = await client.get(
        f"/api/memory/{persona_id}/journal?state=committed",
        headers=_auth(token),
    )
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == entry_id


async def test_commit_journal_entries_nonexistent(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.post(
        f"/api/memory/{persona_id}/journal/commit",
        json={"entry_ids": ["nonexistent-id"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["committed"] == 0


# ---------------------------------------------------------------------------
# Journal: delete
# ---------------------------------------------------------------------------


async def test_delete_journal_entries(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    entry_id = await _seed_journal_entry(user_id, persona_id)

    resp = await client.post(
        f"/api/memory/{persona_id}/journal/delete",
        json={"entry_ids": [entry_id]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    # Verify entry is gone
    list_resp = await client.get(f"/api/memory/{persona_id}/journal", headers=_auth(token))
    assert list_resp.json() == []


async def test_delete_journal_entries_nonexistent(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.post(
        f"/api/memory/{persona_id}/journal/delete",
        json={"entry_ids": ["nonexistent-id"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# Memory body: get current
# ---------------------------------------------------------------------------


async def test_get_memory_body_none(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.get(f"/api/memory/{persona_id}/body", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() is None


async def test_get_memory_body(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    await _seed_memory_body(user_id, persona_id)

    resp = await client.get(f"/api/memory/{persona_id}/body", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona_id"] == persona_id
    assert data["content"] == "Chris prefers dark mode and British English."
    assert data["token_count"] == 12
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# Memory body: list versions
# ---------------------------------------------------------------------------


async def test_list_memory_body_versions_empty(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.get(f"/api/memory/{persona_id}/body/versions", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_memory_body_versions(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    await _seed_memory_body(user_id, persona_id, content="Version 1")
    await _seed_memory_body(user_id, persona_id, content="Version 2")

    resp = await client.get(f"/api/memory/{persona_id}/body/versions", headers=_auth(token))
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2
    # Newest first
    assert versions[0]["version"] == 2
    assert versions[1]["version"] == 1


# ---------------------------------------------------------------------------
# Memory body: get specific version
# ---------------------------------------------------------------------------


async def test_get_memory_body_version(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    await _seed_memory_body(user_id, persona_id, content="First version")
    await _seed_memory_body(user_id, persona_id, content="Second version")

    resp = await client.get(f"/api/memory/{persona_id}/body/versions/1", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["content"] == "First version"
    assert resp.json()["version"] == 1


async def test_get_memory_body_version_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.get(f"/api/memory/{persona_id}/body/versions/999", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Memory body: rollback
# ---------------------------------------------------------------------------


async def test_rollback_memory_body(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    await _seed_memory_body(user_id, persona_id, content="Version 1 content")
    await _seed_memory_body(user_id, persona_id, content="Version 2 content")

    resp = await client.post(
        f"/api/memory/{persona_id}/body/rollback",
        json={"to_version": 1},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["new_version"] == 3

    # Verify the current body has the rolled-back content
    body_resp = await client.get(f"/api/memory/{persona_id}/body", headers=_auth(token))
    assert body_resp.json()["content"] == "Version 1 content"
    assert body_resp.json()["version"] == 3


async def test_rollback_memory_body_version_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.post(
        f"/api/memory/{persona_id}/body/rollback",
        json={"to_version": 999},
        headers=_auth(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Memory context
# ---------------------------------------------------------------------------


async def test_get_memory_context(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.get(f"/api/memory/{persona_id}/context", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona_id"] == persona_id
    assert data["uncommitted_count"] == 0
    assert data["committed_count"] == 0
    assert data["can_trigger_extraction"] is False


async def test_get_memory_context_with_entries(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    await _seed_journal_entry(user_id, persona_id, content="Entry A")
    entry_b_id = await _seed_journal_entry(user_id, persona_id, content="Entry B")

    repo = MemoryRepository(get_db())
    await repo.commit_entry(entry_b_id, user_id)

    resp = await client.get(f"/api/memory/{persona_id}/context", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["uncommitted_count"] == 1
    assert data["committed_count"] == 1


# ---------------------------------------------------------------------------
# Manual triggers: extraction
# ---------------------------------------------------------------------------


async def test_trigger_extraction_no_persona(client: AsyncClient):
    token = await _setup_and_login(client)

    resp = await client.post("/api/memory/nonexistent/extract", headers=_auth(token))
    assert resp.status_code == 404


async def test_trigger_extraction_no_sessions(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.post(f"/api/memory/{persona_id}/extract", headers=_auth(token))
    assert resp.status_code == 400
    assert "No chat sessions" in resp.json()["detail"]


async def test_trigger_extraction_success(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    # Create a session and add messages so extraction has data to work with
    session_resp = await client.post(
        "/api/chat/sessions",
        json={"persona_id": persona_id},
        headers=_auth(token),
    )
    session_id = session_resp.json()["id"]

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    # Seed user messages directly via the chat repository
    from backend.modules.chat._repository import ChatRepository
    chat_repo = ChatRepository(get_db())
    for i in range(5):
        await chat_repo.save_message(session_id, role="user", content=f"Test message {i}", token_count=10)

    with patch("backend.modules.memory._handlers.submit", new_callable=AsyncMock) as mock_submit:
        resp = await client.post(f"/api/memory/{persona_id}/extract", headers=_auth(token))

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "submitted"
    assert "correlation_id" in data
    mock_submit.assert_called_once()


# ---------------------------------------------------------------------------
# Manual triggers: dream/consolidation
# ---------------------------------------------------------------------------


async def test_trigger_dream_no_persona(client: AsyncClient):
    token = await _setup_and_login(client)

    resp = await client.post("/api/memory/nonexistent/dream", headers=_auth(token))
    assert resp.status_code == 404


async def test_trigger_dream_no_committed_entries(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    resp = await client.post(f"/api/memory/{persona_id}/dream", headers=_auth(token))
    assert resp.status_code == 400
    assert "No committed" in resp.json()["detail"]


async def test_trigger_dream_success(client: AsyncClient):
    token = await _setup_and_login(client)
    persona_id = await _create_persona(client, token)

    import jwt
    payload = jwt.decode(token, options={"verify_signature": False})
    user_id = payload["sub"]

    # Seed and commit a journal entry so dream has something to consolidate
    entry_id = await _seed_journal_entry(user_id, persona_id)
    repo = MemoryRepository(get_db())
    await repo.commit_entry(entry_id, user_id)

    with patch("backend.modules.memory._handlers.submit", new_callable=AsyncMock) as mock_submit:
        resp = await client.post(f"/api/memory/{persona_id}/dream", headers=_auth(token))

    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "submitted"
    assert "correlation_id" in data
    mock_submit.assert_called_once()
