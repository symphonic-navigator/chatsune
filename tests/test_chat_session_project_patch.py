"""Mindspace Phase 3 (task 14) — PATCH /api/chat/sessions/{id}/project.

Three behaviours are load-bearing:

1. Setting the field to a string assigns the project.
2. Setting the field to ``null`` detaches the session.
3. A non-existent / foreign session returns 404.

The endpoint also publishes ``CHAT_SESSION_PROJECT_UPDATED`` carrying
the new ``project_id`` so the sidebar / HistoryTab can re-classify
the session live without a follow-up GET.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient

from backend.dependencies import require_active_session
from backend.main import app
from backend.ws.event_bus import EventBus
from shared.topics import Topics


@pytest_asyncio.fixture
async def auth_user_id():
    user_id = "u-session-project-test"
    app.dependency_overrides[require_active_session] = lambda: {
        "sub": user_id,
        "role": "user",
        "session_id": "sess-test",
    }
    yield user_id
    app.dependency_overrides.pop(require_active_session, None)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_session(
    db, *, user_id: str, project_id: str | None = None,
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


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_patch_assigns_project_id(
    client: AsyncClient, auth_user_id, db,
):
    sid = await _seed_session(db, user_id=auth_user_id, project_id=None)

    resp = await client.patch(
        f"/api/chat/sessions/{sid}/project",
        json={"project_id": "proj-A"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == "proj-A"

    fetched = await db["chat_sessions"].find_one({"_id": sid})
    assert fetched["project_id"] == "proj-A"


async def test_patch_clears_project_id_with_null(
    client: AsyncClient, auth_user_id, db,
):
    sid = await _seed_session(db, user_id=auth_user_id, project_id="proj-A")

    resp = await client.patch(
        f"/api/chat/sessions/{sid}/project",
        json={"project_id": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] is None

    fetched = await db["chat_sessions"].find_one({"_id": sid})
    assert fetched["project_id"] is None


async def test_patch_unknown_session_returns_404(
    client: AsyncClient, auth_user_id,
):
    resp = await client.patch(
        "/api/chat/sessions/does-not-exist/project",
        json={"project_id": "x"},
    )
    assert resp.status_code == 404


async def test_patch_foreign_session_returns_404(
    client: AsyncClient, auth_user_id, db,
):
    sid = await _seed_session(db, user_id="someone-else", project_id=None)
    resp = await client.patch(
        f"/api/chat/sessions/{sid}/project",
        json={"project_id": "proj-A"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


async def test_patch_publishes_project_updated_event(
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

    sid = await _seed_session(db, user_id=auth_user_id, project_id=None)

    resp = await client.patch(
        f"/api/chat/sessions/{sid}/project",
        json={"project_id": "proj-A"},
    )
    assert resp.status_code == 200

    matches = [c for c in captured if c[0] == Topics.CHAT_SESSION_PROJECT_UPDATED]
    assert len(matches) == 1
    topic, event, scope, targets = matches[0]
    assert event.session_id == sid
    assert event.project_id == "proj-A"
    assert event.user_id == auth_user_id
    assert scope == f"session:{sid}"
    assert targets == [auth_user_id]


async def test_patch_null_publishes_with_null_project_id(
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

    sid = await _seed_session(db, user_id=auth_user_id, project_id="proj-A")

    resp = await client.patch(
        f"/api/chat/sessions/{sid}/project",
        json={"project_id": None},
    )
    assert resp.status_code == 200

    matches = [c for c in captured if c[0] == Topics.CHAT_SESSION_PROJECT_UPDATED]
    assert len(matches) == 1
    _, event, _, _ = matches[0]
    assert event.project_id is None
