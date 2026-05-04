"""Mindspace Phase 2 — project handler endpoints.

Covers:
- DELETE /api/projects/{id}?purge_data=true|false (cascade safe-delete + full-purge)
- PATCH /api/projects/{id}/pinned (dedicated pinned endpoint)
- PATCH /api/projects/{id} now accepting knowledge_library_ids (already
  shipped in Phase 1; covered here too to lock the behaviour in alongside
  the new endpoints).

Uses the FastAPI dependency-override pattern so the tests don't need to
go through the master-admin setup flow (the older
``tests/test_project_handlers.py`` is broken on that path — its helper
hits ``/api/setup`` instead of ``/api/auth/setup`` — so we sidestep it).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient

from backend.dependencies import require_active_session
from backend.main import app
from backend.modules.project import ProjectRepository
from backend.ws.event_bus import EventBus
from shared.topics import Topics


@pytest_asyncio.fixture
async def auth_user_id():
    user_id = "u-project-handlers-test"
    app.dependency_overrides[require_active_session] = lambda: {
        "sub": user_id,
        "role": "user",
        "session_id": "sess-project-handlers-test",
    }
    yield user_id
    app.dependency_overrides.pop(require_active_session, None)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_session(
    db, *, user_id: str, project_id: str | None,
) -> str:
    sid = f"sess-{uuid4().hex[:8]}"
    await db["chat_sessions"].insert_one({
        "_id": sid,
        "user_id": user_id,
        "persona_id": "p-fixed",
        "title": "T",
        "project_id": project_id,
        "deleted_at": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return sid


# ---------------------------------------------------------------------------
# DELETE — cascade variants
# ---------------------------------------------------------------------------

async def test_delete_default_is_safe_delete(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    sid = await _seed_session(db, user_id=auth_user_id, project_id=pid)

    resp = await client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204, resp.text

    # Project gone.
    assert await repo.find_by_id(pid, auth_user_id) is None
    # Session still alive but detached (returns to global history).
    s_doc = await db["chat_sessions"].find_one({"_id": sid})
    assert s_doc is not None
    assert s_doc["project_id"] is None
    assert s_doc["deleted_at"] is None


async def test_delete_with_purge_data_true_soft_deletes_sessions(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    sid = await _seed_session(db, user_id=auth_user_id, project_id=pid)

    resp = await client.delete(f"/api/projects/{pid}?purge_data=true")
    assert resp.status_code == 204, resp.text

    assert await repo.find_by_id(pid, auth_user_id) is None
    s_doc = await db["chat_sessions"].find_one({"_id": sid})
    assert s_doc is not None
    assert s_doc["deleted_at"] is not None


async def test_delete_unknown_returns_404(
    client: AsyncClient, auth_user_id, db,
):
    resp = await client.delete("/api/projects/does-not-exist")
    assert resp.status_code == 404


async def test_delete_publishes_project_deleted_event(
    client: AsyncClient, auth_user_id, db, monkeypatch,
):
    captured: list[tuple] = []
    original_publish = EventBus.publish

    async def capturing_publish(
        self, topic, event,
        scope="global", target_user_ids=None, correlation_id=None,
    ):
        captured.append((topic, event, scope, target_user_ids))
        return await original_publish(
            self, topic, event,
            scope=scope, target_user_ids=target_user_ids,
            correlation_id=correlation_id,
        )

    monkeypatch.setattr(EventBus, "publish", capturing_publish)

    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]

    resp = await client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204

    deleted_events = [c for c in captured if c[0] == Topics.PROJECT_DELETED]
    assert len(deleted_events) == 1
    _, ev, scope, targets = deleted_events[0]
    assert ev.project_id == pid
    assert ev.user_id == auth_user_id
    assert scope == f"user:{auth_user_id}"
    assert targets == [auth_user_id]


# ---------------------------------------------------------------------------
# PATCH /pinned
# ---------------------------------------------------------------------------

async def test_patch_pinned_true_then_false(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]

    resp = await client.patch(
        f"/api/projects/{pid}/pinned", json={"pinned": True},
    )
    assert resp.status_code == 200, resp.text
    fetched = await repo.find_by_id(pid, auth_user_id)
    assert fetched is not None
    assert fetched["pinned"] is True

    resp = await client.patch(
        f"/api/projects/{pid}/pinned", json={"pinned": False},
    )
    assert resp.status_code == 200, resp.text
    fetched = await repo.find_by_id(pid, auth_user_id)
    assert fetched["pinned"] is False


async def test_patch_pinned_unknown_returns_404(
    client: AsyncClient, auth_user_id, db,
):
    resp = await client.patch(
        "/api/projects/does-not-exist/pinned", json={"pinned": True},
    )
    assert resp.status_code == 404


async def test_patch_pinned_publishes_event(
    client: AsyncClient, auth_user_id, db, monkeypatch,
):
    captured: list[tuple] = []
    original_publish = EventBus.publish

    async def capturing_publish(
        self, topic, event,
        scope="global", target_user_ids=None, correlation_id=None,
    ):
        captured.append((topic, event, scope, target_user_ids))
        return await original_publish(
            self, topic, event,
            scope=scope, target_user_ids=target_user_ids,
            correlation_id=correlation_id,
        )

    monkeypatch.setattr(EventBus, "publish", capturing_publish)

    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]

    resp = await client.patch(
        f"/api/projects/{pid}/pinned", json={"pinned": True},
    )
    assert resp.status_code == 200

    pinned_events = [
        c for c in captured if c[0] == Topics.PROJECT_PINNED_UPDATED
    ]
    assert len(pinned_events) == 1
    _, ev, scope, targets = pinned_events[0]
    assert ev.project_id == pid
    assert ev.user_id == auth_user_id
    assert ev.pinned is True
    assert scope == f"user:{auth_user_id}"
    assert targets == [auth_user_id]


async def test_patch_pinned_invalid_body_rejected(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    resp = await client.patch(
        f"/api/projects/{pid}/pinned", json={"pinned": "yes-please"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /{id} with knowledge_library_ids
# ---------------------------------------------------------------------------

async def test_patch_replaces_knowledge_library_ids(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a"],
    )
    pid = proj["_id"]

    resp = await client.patch(
        f"/api/projects/{pid}",
        json={"knowledge_library_ids": ["lib-b", "lib-c"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["knowledge_library_ids"] == ["lib-b", "lib-c"]


async def test_patch_can_clear_knowledge_library_ids(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a", "lib-b"],
    )
    pid = proj["_id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"knowledge_library_ids": []},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["knowledge_library_ids"] == []


async def test_patch_omitting_knowledge_library_ids_preserves(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a"],
    )
    pid = proj["_id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "P2"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "P2"
    assert body["knowledge_library_ids"] == ["lib-a"]
