"""Mindspace Phase 3 (task 16) — storage project_id query + counter.

The storage module gains a ``count_for_sessions`` public API and a
``project_id`` query param on ``GET /api/storage/files``. Files are
linked to sessions only via the chat-message ``attachment_ids`` /
``attachment_refs`` fields; the storage helpers walk those via the
chat module's public API to find the project's file set.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.dependencies import require_active_session
from backend.main import app
from backend.modules import storage as storage_service
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
    user_id = "u-storage-proj-test"
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
        "state": "idle",
        "project_id": project_id,
        "deleted_at": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return sid


async def _seed_file(db, *, user_id: str, name: str = "f.txt") -> str:
    fid = f"file-{uuid4().hex[:8]}"
    await db["storage_files"].insert_one({
        "_id": fid,
        "user_id": user_id,
        "persona_id": None,
        "original_name": name,
        "display_name": name,
        "media_type": "text/plain",
        "size_bytes": 12,
        "file_path": f"u/{user_id}/{fid}",
        "thumbnail_b64": None,
        "text_preview": "hello world!",
        "created_at": _now(),
        "updated_at": _now(),
    })
    return fid


async def _seed_message_with_attachment_ids(
    db, *, session_id: str, user_id: str, file_ids: list[str],
):
    await db["chat_messages"].insert_one({
        "_id": f"msg-{uuid4().hex[:8]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": "see attached",
        "token_count": 3,
        "attachment_ids": file_ids,
        "created_at": _now(),
    })


async def _seed_message_with_attachment_refs(
    db, *, session_id: str, user_id: str, file_ids: list[str],
):
    await db["chat_messages"].insert_one({
        "_id": f"msg-{uuid4().hex[:8]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": "see attached",
        "token_count": 3,
        "attachment_refs": [
            {
                "file_id": fid,
                "display_name": "f.txt",
                "media_type": "text/plain",
                "size_bytes": 12,
            }
            for fid in file_ids
        ],
        "created_at": _now(),
    })


# ---------------------------------------------------------------------------
# count_for_sessions
# ---------------------------------------------------------------------------


async def test_count_for_sessions_walks_attachment_ids(env):
    db = env
    sid = await _seed_session(db, user_id="u1", project_id="proj-A")
    f1 = await _seed_file(db, user_id="u1")
    f2 = await _seed_file(db, user_id="u1")
    await _seed_message_with_attachment_ids(
        db, session_id=sid, user_id="u1", file_ids=[f1, f2],
    )

    count = await storage_service.count_for_sessions([sid], "u1")
    assert count == 2


async def test_count_for_sessions_walks_attachment_refs(env):
    db = env
    sid = await _seed_session(db, user_id="u1", project_id="proj-A")
    f1 = await _seed_file(db, user_id="u1")
    await _seed_message_with_attachment_refs(
        db, session_id=sid, user_id="u1", file_ids=[f1],
    )
    count = await storage_service.count_for_sessions([sid], "u1")
    assert count == 1


async def test_count_for_sessions_dedupes_files_used_twice(env):
    db = env
    sid = await _seed_session(db, user_id="u1", project_id="proj-A")
    f1 = await _seed_file(db, user_id="u1")
    # Same file referenced from two different messages.
    await _seed_message_with_attachment_ids(
        db, session_id=sid, user_id="u1", file_ids=[f1],
    )
    await _seed_message_with_attachment_ids(
        db, session_id=sid, user_id="u1", file_ids=[f1],
    )
    count = await storage_service.count_for_sessions([sid], "u1")
    assert count == 1


async def test_count_for_sessions_empty_input(env):
    assert await storage_service.count_for_sessions([], "u1") == 0


# ---------------------------------------------------------------------------
# list_files endpoint with project_id
# ---------------------------------------------------------------------------


async def test_list_files_project_id_returns_only_in_project(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    in_proj = await _seed_session(
        db, user_id=auth_user_id, project_id="proj-A",
    )
    out_proj = await _seed_session(
        db, user_id=auth_user_id, project_id=None,
    )

    in_file = await _seed_file(db, user_id=auth_user_id, name="in.txt")
    out_file = await _seed_file(db, user_id=auth_user_id, name="out.txt")

    await _seed_message_with_attachment_ids(
        db, session_id=in_proj, user_id=auth_user_id, file_ids=[in_file],
    )
    await _seed_message_with_attachment_ids(
        db, session_id=out_proj, user_id=auth_user_id, file_ids=[out_file],
    )

    resp = await client.get("/api/storage/files?project_id=proj-A")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert in_file in ids
    assert out_file not in ids


async def test_list_files_project_id_empty_when_no_sessions(
    env, client: AsyncClient, auth_user_id,
):
    resp = await client.get("/api/storage/files?project_id=ghost")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_files_without_project_id_unchanged(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    f = await _seed_file(db, user_id=auth_user_id)
    resp = await client.get("/api/storage/files")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert f in ids
