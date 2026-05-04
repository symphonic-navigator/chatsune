"""Mindspace Phase 3 (task 17) — artefact project_id query + counter.

The artefact module gains a ``count_for_sessions`` public API and a
``project_id`` query param on ``GET /api/artefacts``. Artefacts carry
a ``session_id`` field directly so the lookup is a straight ``$in``;
the user-ownership filter is still applied defensively.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from bson import ObjectId
from httpx import AsyncClient

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.dependencies import require_active_session
from backend.main import app
from backend.modules import artefact as artefact_service
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest_asyncio.fixture
async def env(clean_db):
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield get_db()
    await disconnect_db()


@pytest_asyncio.fixture
async def auth_user_id():
    user_id = "u-artefact-proj-test"
    app.dependency_overrides[require_active_session] = lambda: {
        "sub": user_id,
        "role": "user",
        "session_id": "sess-test",
    }
    yield user_id
    app.dependency_overrides.pop(require_active_session, None)


async def _seed_session(
    db, *, user_id: str, project_id: str | None,
) -> str:
    sid = f"sess-{uuid4().hex[:8]}"
    await db["chat_sessions"].insert_one({
        "_id": sid,
        "user_id": user_id,
        "persona_id": "p1",
        "title": "T",
        "state": "idle",
        "project_id": project_id,
        "deleted_at": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return sid


async def _seed_persona(db, *, user_id: str) -> str:
    pid = f"pers-{uuid4().hex[:8]}"
    await db["personas"].insert_one({
        "_id": pid,
        "user_id": user_id,
        "name": "X",
        "tagline": "x",
        "model_unique_id": None,
        "system_prompt": "...",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "soft_cot_enabled": False,
        "vision_fallback_model": None,
        "nsfw": False,
        "use_memory": True,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "XX",
        "pinned": False,
        "profile_image": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return pid


async def _seed_artefact(
    db, *, user_id: str, session_id: str, handle: str = "x",
) -> str:
    aid = ObjectId()
    await db["artefacts"].insert_one({
        "_id": aid,
        "session_id": session_id,
        "user_id": user_id,
        "handle": handle,
        "title": "Title",
        "type": "markdown",
        "language": None,
        "content": "## hi",
        "size_bytes": 5,
        "version": 1,
        "max_version": 1,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return str(aid)


# ---------------------------------------------------------------------------
# count_for_sessions
# ---------------------------------------------------------------------------


async def test_count_for_sessions_counts_owned_artefacts(env):
    db = env
    s = await _seed_session(db, user_id="u1", project_id="proj-A")
    await _seed_artefact(db, user_id="u1", session_id=s, handle="a")
    await _seed_artefact(db, user_id="u1", session_id=s, handle="b")
    # Foreign artefact in same session — defensive filter excludes it.
    await _seed_artefact(db, user_id="u2", session_id=s, handle="c")

    count = await artefact_service.count_for_sessions([s], "u1")
    assert count == 2


async def test_count_for_sessions_empty_input(env):
    assert await artefact_service.count_for_sessions([], "u1") == 0


# ---------------------------------------------------------------------------
# project_id endpoint
# ---------------------------------------------------------------------------


async def test_list_artefacts_project_id_filters_by_project(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    persona = await _seed_persona(db, user_id=auth_user_id)

    in_proj = await _seed_session(
        db, user_id=auth_user_id, project_id="proj-A",
    )
    out_proj = await _seed_session(
        db, user_id=auth_user_id, project_id=None,
    )
    # Patch persona_id onto each session for the enrichment pass.
    await db["chat_sessions"].update_many(
        {"_id": {"$in": [in_proj, out_proj]}},
        {"$set": {"persona_id": persona}},
    )

    in_art = await _seed_artefact(
        db, user_id=auth_user_id, session_id=in_proj, handle="in",
    )
    out_art = await _seed_artefact(
        db, user_id=auth_user_id, session_id=out_proj, handle="out",
    )

    resp = await client.get("/api/artefacts/?project_id=proj-A")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()}
    assert in_art in ids
    assert out_art not in ids


async def test_list_artefacts_project_id_empty_project_returns_empty(
    env, client: AsyncClient, auth_user_id,
):
    resp = await client.get("/api/artefacts/?project_id=ghost")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_artefacts_without_project_id_unchanged(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    persona = await _seed_persona(db, user_id=auth_user_id)
    s = await _seed_session(db, user_id=auth_user_id, project_id=None)
    await db["chat_sessions"].update_one(
        {"_id": s}, {"$set": {"persona_id": persona}},
    )
    a = await _seed_artefact(db, user_id=auth_user_id, session_id=s)

    resp = await client.get("/api/artefacts/")
    assert resp.status_code == 200
    ids = {x["id"] for x in resp.json()}
    assert a in ids
