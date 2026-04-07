"""Integration tests for GET /api/artefacts/ — global artefact list endpoint."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from bson import ObjectId
from httpx import AsyncClient

from backend.database import get_db


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _setup_and_login(client: AsyncClient) -> tuple[str, str]:
    """Bootstrap the instance and return (user_id, access_token) for master admin."""
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "alice",
            "email": "alice@example.com",
            "password": "AlicePass123",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["user"]["id"], body["access_token"]


async def _create_user(client: AsyncClient, admin_token: str, username: str) -> tuple[str, str]:
    """Create a regular user via the admin API and return (user_id, access_token)."""
    resp = await client.post(
        "/api/admin/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "display_name": username.capitalize(),
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["user"]["id"]
    generated_pw = resp.json()["generated_password"]

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": username, "password": generated_pw},
    )
    assert login_resp.status_code == 200, login_resp.text
    return user_id, login_resp.json()["access_token"]


async def _seed_persona(user_id: str, name: str, monogram: str, colour_scheme: str) -> str:
    """Insert a persona document directly into MongoDB and return its id."""
    db = get_db()
    persona_id = str(uuid4())
    now = datetime.now(UTC)
    await db["personas"].insert_one({
        "_id": persona_id,
        "user_id": user_id,
        "name": name,
        "tagline": f"{name} tagline",
        "model_unique_id": "ollama_cloud:llama3.2",
        "system_prompt": "You are helpful.",
        "temperature": 0.7,
        "reasoning_enabled": False,
        "nsfw": False,
        "colour_scheme": colour_scheme,
        "display_order": 0,
        "monogram": monogram,
        "pinned": False,
        "profile_image": None,
        "created_at": now,
        "updated_at": now,
    })
    return persona_id


async def _seed_session(user_id: str, persona_id: str, title: str | None) -> str:
    """Insert a chat session document directly into MongoDB and return its id."""
    db = get_db()
    session_id = str(uuid4())
    now = datetime.now(UTC)
    await db["chat_sessions"].insert_one({
        "_id": session_id,
        "user_id": user_id,
        "persona_id": persona_id,
        "model_unique_id": "ollama_cloud:llama3.2",
        "title": title,
        "state": "idle",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    })
    return session_id


async def _seed_artefact(user_id: str, session_id: str, handle: str, updated_at: datetime) -> str:
    """Insert an artefact document directly into MongoDB and return its str id."""
    db = get_db()
    artefact_id = ObjectId()
    now = datetime.now(UTC)
    await db["artefacts"].insert_one({
        "_id": artefact_id,
        "user_id": user_id,
        "session_id": session_id,
        "handle": handle,
        "title": f"Title for {handle}",
        "type": "markdown",
        "language": None,
        "content": f"# {handle}",
        "size_bytes": len(f"# {handle}".encode()),
        "version": 1,
        "max_version": 1,
        "created_at": now,
        "updated_at": updated_at,
    })
    return str(artefact_id)


async def test_list_user_artefacts_returns_all_and_sorted(client: AsyncClient):
    """GET /api/artefacts/ returns alice's three artefacts, sorted updated_at desc."""
    alice_id, alice_token = await _setup_and_login(client)

    # Seed alice's two personas
    p1_id = await _seed_persona(alice_id, "Aria", "AR", "solar")
    p2_id = await _seed_persona(alice_id, "Zara", "ZA", "lunar")

    # Seed two sessions (one per persona)
    s1_id = await _seed_session(alice_id, p1_id, "Session One")
    s2_id = await _seed_session(alice_id, p2_id, "Session Two")

    # Seed three artefacts with staggered updated_at
    now = datetime.now(UTC)
    a1_id = await _seed_artefact(alice_id, s1_id, "first-doc", now - timedelta(hours=2))
    a2_id = await _seed_artefact(alice_id, s1_id, "second-doc", now - timedelta(hours=1))
    a3_id = await _seed_artefact(alice_id, s2_id, "third-doc", now)

    # Seed bob and his artefact — must not appear in alice's response
    bob_id, _bob_token = await _create_user(client, alice_token, "bob")
    bob_p = await _seed_persona(bob_id, "Boris", "BO", "neon")
    bob_s = await _seed_session(bob_id, bob_p, "Bob Session")
    bob_a = await _seed_artefact(bob_id, bob_s, "bob-doc", now)

    resp = await client.get("/api/artefacts/", headers=_auth(alice_token))
    assert resp.status_code == 200, resp.text
    rows = resp.json()

    # Exactly three rows for alice
    assert len(rows) == 3

    # Sorted by updated_at desc: a3, a2, a1
    assert rows[0]["id"] == a3_id
    assert rows[1]["id"] == a2_id
    assert rows[2]["id"] == a1_id

    # Verify session and persona enrichment on each row
    assert rows[0]["session_id"] == s2_id
    assert rows[0]["session_title"] == "Session Two"
    assert rows[0]["persona_id"] == p2_id
    assert rows[0]["persona_name"] == "Zara"
    assert rows[0]["persona_monogram"] == "ZA"
    assert rows[0]["persona_colour_scheme"] == "lunar"

    assert rows[1]["session_id"] == s1_id
    assert rows[1]["session_title"] == "Session One"
    assert rows[1]["persona_id"] == p1_id
    assert rows[1]["persona_name"] == "Aria"
    assert rows[1]["persona_monogram"] == "AR"
    assert rows[1]["persona_colour_scheme"] == "solar"

    assert rows[2]["session_id"] == s1_id
    assert rows[2]["persona_id"] == p1_id

    # Bob's artefact must not appear
    returned_ids = {r["id"] for r in rows}
    assert bob_a not in returned_ids


async def test_list_user_artefacts_empty(client: AsyncClient):
    """GET /api/artefacts/ returns empty list when the user has no artefacts."""
    _alice_id, alice_token = await _setup_and_login(client)

    resp = await client.get("/api/artefacts/", headers=_auth(alice_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_list_user_artefacts_unauthenticated(client: AsyncClient):
    """GET /api/artefacts/ returns 401 when no token is provided."""
    resp = await client.get("/api/artefacts/")
    assert resp.status_code == 401
