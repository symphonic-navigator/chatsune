"""Mindspace Phase 3 (task 18) — images project_id query + counter.

The images module gains a ``count_for_sessions`` public API and a
``project_id`` query param on ``GET /api/images``. Generated images
have no ``session_id`` field, so the lookup walks
``chat_messages.image_refs`` (legacy) and ``events`` (new shape) via
the chat module's public API.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.dependencies import require_active_session
from backend.main import app
from backend.modules import images as images_service
from backend.modules.images import set_image_service
from backend.modules.images._service import ImageService
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
    # The images service needs a blob root + an LlmService stub. We
    # never read blobs in these tests — the gallery list path returns
    # ``thumbnail_b64`` from disk which is None when ``thumb_blob_id``
    # is None. So a no-arg construction with a temp blob_root is safe.
    db = get_db()
    svc = ImageService.__new__(ImageService)
    svc._gen = images_service.GeneratedImagesRepository(db)  # noqa: SLF001
    svc._blob_root = tmp_path  # noqa: SLF001
    set_image_service(svc)
    yield db
    await disconnect_db()


@pytest_asyncio.fixture
async def auth_user_id():
    user_id = "u-images-proj-test"
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


async def _seed_image(db, *, user_id: str, image_id: str | None = None) -> str:
    iid = image_id or f"img-{uuid4().hex[:8]}"
    await db["generated_images"].insert_one({
        "_id": iid,
        "id": iid,
        "user_id": user_id,
        "blob_id": "blob-x",
        "thumb_blob_id": None,
        "prompt": "a cat",
        "model_id": "test:test",
        "group_id": "g1",
        "connection_id": "c1",
        "config_snapshot": {},
        "width": 256,
        "height": 256,
        "content_type": "image/png",
        "moderated": False,
        "moderation_reason": None,
        "tags": [],
        "generated_at": _now(),
    })
    return iid


async def _seed_message_with_image_refs_legacy(
    db, *, session_id: str, user_id: str, image_ids: list[str],
):
    await db["chat_messages"].insert_one({
        "_id": f"msg-{uuid4().hex[:8]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "assistant",
        "content": "here you go",
        "token_count": 3,
        "image_refs": [
            {
                "id": iid,
                "blob_url": f"/api/images/{iid}/blob",
                "thumb_url": f"/api/images/{iid}/thumb",
                "width": 256,
                "height": 256,
                "prompt": "x",
                "model_id": "test:test",
                "tool_call_id": "tc1",
            }
            for iid in image_ids
        ],
        "created_at": _now(),
    })


async def _seed_message_with_image_events(
    db, *, session_id: str, user_id: str, image_ids: list[str],
):
    await db["chat_messages"].insert_one({
        "_id": f"msg-{uuid4().hex[:8]}",
        "session_id": session_id,
        "user_id": user_id,
        "role": "assistant",
        "content": "here you go",
        "token_count": 3,
        "events": [
            {
                "kind": "image",
                "seq": 0,
                "refs": [
                    {
                        "id": iid,
                        "blob_url": f"/api/images/{iid}/blob",
                        "thumb_url": f"/api/images/{iid}/thumb",
                        "width": 256,
                        "height": 256,
                        "prompt": "x",
                        "model_id": "test:test",
                        "tool_call_id": "tc1",
                    }
                    for iid in image_ids
                ],
                "moderated_count": 0,
            }
        ],
        "created_at": _now(),
    })


# ---------------------------------------------------------------------------
# count_for_sessions — both shapes
# ---------------------------------------------------------------------------


async def test_count_for_sessions_walks_legacy_image_refs(env):
    db = env
    s = await _seed_session(db, user_id="u1", project_id="proj-A")
    i1 = await _seed_image(db, user_id="u1")
    i2 = await _seed_image(db, user_id="u1")
    await _seed_message_with_image_refs_legacy(
        db, session_id=s, user_id="u1", image_ids=[i1, i2],
    )
    count = await images_service.count_for_sessions([s], "u1")
    assert count == 2


async def test_count_for_sessions_walks_events_timeline(env):
    db = env
    s = await _seed_session(db, user_id="u1", project_id="proj-A")
    i1 = await _seed_image(db, user_id="u1")
    await _seed_message_with_image_events(
        db, session_id=s, user_id="u1", image_ids=[i1],
    )
    count = await images_service.count_for_sessions([s], "u1")
    assert count == 1


async def test_count_for_sessions_dedupes_image_used_twice(env):
    db = env
    s = await _seed_session(db, user_id="u1", project_id="proj-A")
    i1 = await _seed_image(db, user_id="u1")
    await _seed_message_with_image_refs_legacy(
        db, session_id=s, user_id="u1", image_ids=[i1],
    )
    await _seed_message_with_image_events(
        db, session_id=s, user_id="u1", image_ids=[i1],
    )
    count = await images_service.count_for_sessions([s], "u1")
    assert count == 1


async def test_count_for_sessions_empty_input(env):
    assert await images_service.count_for_sessions([], "u1") == 0


# ---------------------------------------------------------------------------
# project_id endpoint
# ---------------------------------------------------------------------------


async def test_list_images_project_id_filters_by_project(
    env, client: AsyncClient, auth_user_id,
):
    db = env
    in_proj = await _seed_session(
        db, user_id=auth_user_id, project_id="proj-A",
    )
    out_proj = await _seed_session(
        db, user_id=auth_user_id, project_id=None,
    )
    in_img = await _seed_image(db, user_id=auth_user_id)
    out_img = await _seed_image(db, user_id=auth_user_id)

    await _seed_message_with_image_refs_legacy(
        db, session_id=in_proj, user_id=auth_user_id, image_ids=[in_img],
    )
    await _seed_message_with_image_refs_legacy(
        db, session_id=out_proj, user_id=auth_user_id, image_ids=[out_img],
    )

    resp = await client.get("/api/images?project_id=proj-A")
    assert resp.status_code == 200, resp.text
    ids = {r["id"] for r in resp.json()}
    assert in_img in ids
    assert out_img not in ids


async def test_list_images_project_id_empty_project_returns_empty(
    env, client: AsyncClient, auth_user_id,
):
    resp = await client.get("/api/images?project_id=ghost")
    assert resp.status_code == 200
    assert resp.json() == []
