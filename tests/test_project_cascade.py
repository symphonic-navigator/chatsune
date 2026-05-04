"""Mindspace Phase 2 — project cascade-delete service.

Two delete modes are exercised here (spec §9):

- ``purge_data=False`` (safe-delete) detaches every session in the
  project — they reappear in the global history with ``project_id=None``
  — and clears any persona's ``default_project_id`` that pointed at the
  project.
- ``purge_data=True`` (full-purge) soft-deletes every session in the
  project; the existing chat-cleanup job hard-deletes the rest of the
  per-session graph an hour later.

In both modes the project document itself is removed and a single
``PROJECT_DELETED`` event is published.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules import project as project_service
from backend.modules.project import ProjectRepository
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from shared.topics import Topics


@pytest_asyncio.fixture
async def env(clean_db):
    """Bring up the DB + a real event bus and tear down after the test."""
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield get_db()
    await disconnect_db()


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


async def _seed_persona(
    db, *, user_id: str, default_project_id: str | None,
) -> str:
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
        "monogram": "",
        "pinned": False,
        "profile_image": None,
        "default_project_id": default_project_id,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return pid


async def test_safe_delete_detaches_sessions_and_removes_project(env):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    s1 = await _seed_session(db, user_id="u1", project_id=pid)
    s2 = await _seed_session(db, user_id="u1", project_id=pid)
    s_other = await _seed_session(db, user_id="u1", project_id="other-proj")

    deleted = await project_service.cascade_delete_project(
        pid, "u1", purge_data=False,
    )
    assert deleted is True

    # Project gone.
    assert await repo.find_by_id(pid, "u1") is None

    # Sessions in the project are detached but still alive.
    sessions = {
        d["_id"]: d
        async for d in db["chat_sessions"].find({"user_id": "u1"})
    }
    assert sessions[s1]["project_id"] is None
    assert sessions[s1]["deleted_at"] is None
    assert sessions[s2]["project_id"] is None
    assert sessions[s2]["deleted_at"] is None
    # Sessions in another project untouched.
    assert sessions[s_other]["project_id"] == "other-proj"


async def test_full_purge_soft_deletes_sessions(env):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    s1 = await _seed_session(db, user_id="u1", project_id=pid)
    s2 = await _seed_session(db, user_id="u1", project_id=pid)
    s_other = await _seed_session(db, user_id="u1", project_id=None)

    deleted = await project_service.cascade_delete_project(
        pid, "u1", purge_data=True,
    )
    assert deleted is True

    assert await repo.find_by_id(pid, "u1") is None

    # Each session in the project is soft-deleted (chat cleanup job
    # hard-deletes it plus messages/attachments later).
    s1_doc = await db["chat_sessions"].find_one({"_id": s1})
    s2_doc = await db["chat_sessions"].find_one({"_id": s2})
    assert s1_doc is not None and s1_doc["deleted_at"] is not None
    assert s2_doc is not None and s2_doc["deleted_at"] is not None

    # Session outside the project is untouched.
    s_other_doc = await db["chat_sessions"].find_one({"_id": s_other})
    assert s_other_doc is not None
    assert s_other_doc["deleted_at"] is None


async def test_cascade_clears_persona_defaults(env):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]

    target = await _seed_persona(db, user_id="u1", default_project_id=pid)
    other_default = await _seed_persona(
        db, user_id="u1", default_project_id="other-proj",
    )
    no_default = await _seed_persona(
        db, user_id="u1", default_project_id=None,
    )
    foreign_user = await _seed_persona(
        db, user_id="u2", default_project_id=pid,
    )

    deleted = await project_service.cascade_delete_project(
        pid, "u1", purge_data=False,
    )
    assert deleted is True

    target_doc = await db["personas"].find_one({"_id": target})
    other_doc = await db["personas"].find_one({"_id": other_default})
    none_doc = await db["personas"].find_one({"_id": no_default})
    foreign_doc = await db["personas"].find_one({"_id": foreign_user})

    assert target_doc["default_project_id"] is None
    assert other_doc["default_project_id"] == "other-proj"
    assert none_doc["default_project_id"] is None
    # Cross-user persona is untouched even though it pointed at the same id.
    assert foreign_doc["default_project_id"] == pid


async def test_missing_project_is_noop(env):
    deleted = await project_service.cascade_delete_project(
        "nonexistent", "u1", purge_data=False,
    )
    assert deleted is False


async def test_foreign_owner_is_noop(env):
    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )
    sid = await _seed_session(db, user_id="u1", project_id=proj["_id"])

    deleted = await project_service.cascade_delete_project(
        proj["_id"], "u2", purge_data=True,
    )
    assert deleted is False

    # Project still there, session untouched.
    assert await repo.find_by_id(proj["_id"], "u1") is not None
    s_doc = await db["chat_sessions"].find_one({"_id": sid})
    assert s_doc is not None
    assert s_doc["project_id"] == proj["_id"]
    assert s_doc["deleted_at"] is None


async def test_publishes_project_deleted_event(env, monkeypatch):
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

    repo = ProjectRepository(env)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )

    deleted = await project_service.cascade_delete_project(
        proj["_id"], "u1", purge_data=False,
    )
    assert deleted is True

    matches = [c for c in captured if c[0] == Topics.PROJECT_DELETED]
    assert len(matches) == 1
    topic, event, scope, targets = matches[0]
    assert event.project_id == proj["_id"]
    assert event.user_id == "u1"
    assert scope == "user:u1"
    assert targets == ["u1"]


async def test_safe_delete_emits_session_project_updated_per_session(
    env, monkeypatch,
):
    """Spec parity: ``set_session_project`` is event-free by design — the
    PATCH handler emits ``CHAT_SESSION_PROJECT_UPDATED``. The cascade has
    to mirror that behaviour so the sidebar / HistoryTab re-classify the
    detached sessions live, without a manual reload.
    """
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

    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    s1 = await _seed_session(db, user_id="u1", project_id=pid)
    s2 = await _seed_session(db, user_id="u1", project_id=pid)

    deleted = await project_service.cascade_delete_project(
        pid, "u1", purge_data=False,
    )
    assert deleted is True

    session_events = [
        c for c in captured if c[0] == Topics.CHAT_SESSION_PROJECT_UPDATED
    ]
    assert len(session_events) == 2
    detached_sids = {ev.session_id for _, ev, _, _ in session_events}
    assert detached_sids == {s1, s2}
    for _topic, event, scope, targets in session_events:
        assert event.project_id is None
        assert event.user_id == "u1"
        assert scope == f"session:{event.session_id}"
        assert targets == ["u1"]


async def test_full_purge_does_not_emit_session_project_updated(
    env, monkeypatch,
):
    """Full-purge soft-deletes sessions; they leave the user's view via
    ``CHAT_SESSION_DELETED``, not a project-detach event. We pin that
    contract here so the safe-delete fix above does not bleed into the
    purge branch.
    """
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

    db = env
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id="u1", title="P", emoji=None, description="", nsfw=False,
    )
    pid = proj["_id"]
    await _seed_session(db, user_id="u1", project_id=pid)
    await _seed_session(db, user_id="u1", project_id=pid)

    deleted = await project_service.cascade_delete_project(
        pid, "u1", purge_data=True,
    )
    assert deleted is True

    session_events = [
        c for c in captured if c[0] == Topics.CHAT_SESSION_PROJECT_UPDATED
    ]
    assert len(session_events) == 0
