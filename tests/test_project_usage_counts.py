"""Mindspace Phase 3 (task 11) — project usage counts.

``get_usage_counts(project_id, user_id)`` returns the four
"how much would a full-purge remove?" counts the delete modal shows,
sourced through each module's public API. ``GET /api/projects/{id}?include_usage=true``
returns the same DTO inline as a ``usage`` field next to the project
data.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from bson import ObjectId
from httpx import AsyncClient

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.dependencies import require_active_session
from backend.main import app
from backend.modules import project as project_service
from backend.modules.project import ProjectRepository
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest_asyncio.fixture
async def env(clean_db, tmp_path):
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    # Stand up the ImageService singleton just enough that the count
    # path can flow through it (it doesn't actually call the service —
    # it talks to the public API directly — but the in-memory state is
    # innocuous here either way).
    yield get_db()
    await disconnect_db()


@pytest_asyncio.fixture
async def auth_user_id():
    user_id = "u-usage-test"
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


async def _seed_file(db, *, user_id: str) -> str:
    fid = f"file-{uuid4().hex[:8]}"
    await db["storage_files"].insert_one({
        "_id": fid,
        "user_id": user_id,
        "persona_id": None,
        "original_name": "x.txt",
        "display_name": "x.txt",
        "media_type": "text/plain",
        "size_bytes": 1,
        "file_path": "u/x",
        "created_at": _now(),
        "updated_at": _now(),
    })
    return fid


async def _seed_artefact(db, *, user_id: str, session_id: str) -> str:
    aid = ObjectId()
    await db["artefacts"].insert_one({
        "_id": aid,
        "session_id": session_id,
        "user_id": user_id,
        "handle": f"h-{uuid4().hex[:6]}",
        "title": "T",
        "type": "markdown",
        "content": "x",
        "size_bytes": 1,
        "version": 1,
        "max_version": 1,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return str(aid)


async def _seed_image(db, *, user_id: str) -> str:
    iid = f"img-{uuid4().hex[:8]}"
    await db["generated_images"].insert_one({
        "_id": iid,
        "id": iid,
        "user_id": user_id,
        "blob_id": "x",
        "thumb_blob_id": None,
        "prompt": "x",
        "model_id": "test:test",
        "group_id": "g",
        "connection_id": "c",
        "config_snapshot": {},
        "width": 1,
        "height": 1,
        "content_type": "image/png",
        "moderated": False,
        "moderation_reason": None,
        "tags": [],
        "generated_at": _now(),
    })
    return iid


async def _seed_message_with_attachment(
    db, *, session_id: str, user_id: str, file_ids: list[str],
):
    await db["chat_messages"].insert_one({
        "_id": f"msg-{uuid4().hex[:8]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": "x",
        "token_count": 1,
        "attachment_ids": file_ids,
        "created_at": _now(),
    })


async def _seed_message_with_image_refs(
    db, *, session_id: str, user_id: str, image_ids: list[str],
):
    await db["chat_messages"].insert_one({
        "_id": f"msg-{uuid4().hex[:8]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "assistant",
        "content": "x",
        "token_count": 1,
        "image_refs": [
            {
                "id": iid,
                "blob_url": f"/api/images/{iid}/blob",
                "thumb_url": f"/api/images/{iid}/thumb",
                "width": 1,
                "height": 1,
                "prompt": "x",
                "model_id": "test:test",
                "tool_call_id": "tc1",
            }
            for iid in image_ids
        ],
        "created_at": _now(),
    })


# ---------------------------------------------------------------------------
# get_usage_counts (service)
# ---------------------------------------------------------------------------


async def test_usage_counts_empty_project(env):
    """A project with no sessions returns zeros across the board."""
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description=None, nsfw=False,
    )
    usage = await project_service.get_usage_counts(proj["_id"], "u1")
    assert usage.chat_count == 0
    assert usage.upload_count == 0
    assert usage.artefact_count == 0
    assert usage.image_count == 0


async def test_usage_counts_full_project(env):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description=None, nsfw=False,
    )
    pid = proj["_id"]

    s1 = await _seed_session(db, user_id="u1", project_id=pid)
    s2 = await _seed_session(db, user_id="u1", project_id=pid)
    # Session in another project (must not contribute).
    other_session = await _seed_session(
        db, user_id="u1", project_id="other",
    )

    f1 = await _seed_file(db, user_id="u1")
    f2 = await _seed_file(db, user_id="u1")
    f_other = await _seed_file(db, user_id="u1")

    a1 = await _seed_artefact(db, user_id="u1", session_id=s1)
    a2 = await _seed_artefact(db, user_id="u1", session_id=s2)
    _ = await _seed_artefact(db, user_id="u1", session_id=other_session)

    i1 = await _seed_image(db, user_id="u1")
    _ = await _seed_image(db, user_id="u1")  # not referenced anywhere

    await _seed_message_with_attachment(
        db, session_id=s1, user_id="u1", file_ids=[f1, f2],
    )
    await _seed_message_with_attachment(
        db, session_id=other_session, user_id="u1", file_ids=[f_other],
    )
    await _seed_message_with_image_refs(
        db, session_id=s2, user_id="u1", image_ids=[i1],
    )

    usage = await project_service.get_usage_counts(pid, "u1")
    assert usage.chat_count == 2
    assert usage.upload_count == 2
    assert usage.artefact_count == 2
    assert usage.image_count == 1


# ---------------------------------------------------------------------------
# include_usage=true endpoint
# ---------------------------------------------------------------------------


async def test_get_project_includes_usage_when_requested(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P", emoji=None, description=None,
        nsfw=False,
    )
    pid = proj["_id"]

    s = await _seed_session(db, user_id=auth_user_id, project_id=pid)
    a = await _seed_artefact(db, user_id=auth_user_id, session_id=s)

    resp = await client.get(f"/api/projects/{pid}?include_usage=true")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == pid
    assert "usage" in body
    assert body["usage"]["chat_count"] == 1
    assert body["usage"]["artefact_count"] == 1
    assert body["usage"]["upload_count"] == 0
    assert body["usage"]["image_count"] == 0


async def test_get_project_omits_usage_by_default(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P", emoji=None, description=None,
        nsfw=False,
    )
    resp = await client.get(f"/api/projects/{proj['_id']}")
    assert resp.status_code == 200
    assert "usage" not in resp.json()


async def test_get_project_include_usage_404_for_unknown(
    env, client: AsyncClient, auth_user_id,
):
    resp = await client.get("/api/projects/does-not-exist?include_usage=true")
    assert resp.status_code == 404
