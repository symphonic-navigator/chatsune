"""Mindspace Phase 3 (task 13) — chat list filtering by project.

Two behaviours under test:

- ``list_sessions(user_id)`` defaults to excluding any session whose
  ``project_id`` is set, so the global history list defaults to
  "outside any project" — pre-Mindspace sessions (no field at all)
  always pass through, project-bound sessions are hidden by default
  but surface when the caller passes ``exclude_in_projects=False``.

- ``list_sessions_for_project(user_id, project_id)`` returns only
  sessions belonging to that project, sorted ``pinned desc,
  updated_at desc``.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository


@pytest_asyncio.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r._sessions.drop()  # noqa: SLF001 — test setup
    await r._messages.drop()  # noqa: SLF001 — test setup
    await r.create_indexes()
    yield r
    await r._sessions.drop()  # noqa: SLF001 — test teardown
    await r._messages.drop()  # noqa: SLF001 — test teardown
    await disconnect_db()


def _now(offset_seconds: int = 0) -> datetime:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).replace(tzinfo=None)


async def _seed_session(
    repo: ChatRepository, *, user_id: str, project_id: str | None | object,
    has_message: bool = True, omit_project_id: bool = False,
    updated_offset: int = 0,
) -> str:
    sid = f"sess-{uuid4().hex[:8]}"
    doc: dict = {
        "_id": sid,
        "user_id": user_id,
        "persona_id": "p1",
        "state": "idle",
        "deleted_at": None,
        "created_at": _now(updated_offset),
        "updated_at": _now(updated_offset),
    }
    if not omit_project_id:
        doc["project_id"] = project_id
    await repo._sessions.insert_one(doc)  # noqa: SLF001 — test seed
    if has_message:
        await repo._messages.insert_one({  # noqa: SLF001
            "_id": f"msg-{uuid4().hex[:8]}",
            "session_id": sid,
            "role": "user",
            "content": "hi",
            "token_count": 1,
            "created_at": _now(updated_offset),
        })
    return sid


# ---------------------------------------------------------------------------
# list_sessions — exclude_in_projects flag
# ---------------------------------------------------------------------------


async def test_legacy_session_without_project_id_field_is_listed(
    repo: ChatRepository,
):
    """A pre-Mindspace session has no ``project_id`` field at all; it
    must still show up in the global history default."""
    sid = await _seed_session(
        repo, user_id="u1", project_id=None, omit_project_id=True,
    )
    docs = await repo.list_sessions("u1")
    assert sid in [d["_id"] for d in docs]


async def test_session_with_null_project_id_is_listed(repo: ChatRepository):
    sid = await _seed_session(repo, user_id="u1", project_id=None)
    docs = await repo.list_sessions("u1")
    assert sid in [d["_id"] for d in docs]


async def test_project_session_excluded_by_default(repo: ChatRepository):
    sid = await _seed_session(repo, user_id="u1", project_id="proj-A")
    docs = await repo.list_sessions("u1")
    assert sid not in [d["_id"] for d in docs]


async def test_project_session_included_when_flag_off(repo: ChatRepository):
    sid = await _seed_session(repo, user_id="u1", project_id="proj-A")
    docs = await repo.list_sessions("u1", exclude_in_projects=False)
    assert sid in [d["_id"] for d in docs]


async def test_list_sessions_skips_sessions_without_messages(
    repo: ChatRepository,
):
    """The list_sessions aggregation already filters out empty sessions
    — this is preserved by the Mindspace addition."""
    sid_empty = await _seed_session(
        repo, user_id="u1", project_id=None, has_message=False,
    )
    sid_full = await _seed_session(
        repo, user_id="u1", project_id=None, has_message=True,
    )
    docs = await repo.list_sessions("u1")
    ids = [d["_id"] for d in docs]
    assert sid_empty not in ids
    assert sid_full in ids


# ---------------------------------------------------------------------------
# list_sessions_for_project
# ---------------------------------------------------------------------------


async def test_list_sessions_for_project_returns_only_matching(
    repo: ChatRepository,
):
    in_proj = await _seed_session(repo, user_id="u1", project_id="proj-A")
    other = await _seed_session(repo, user_id="u1", project_id="proj-B")
    detached = await _seed_session(repo, user_id="u1", project_id=None)

    docs = await repo.list_sessions_for_project("u1", "proj-A")
    ids = {d["_id"] for d in docs}
    assert ids == {in_proj}
    assert other not in ids
    assert detached not in ids


async def test_list_sessions_for_project_excludes_soft_deleted(
    repo: ChatRepository,
):
    sid = await _seed_session(repo, user_id="u1", project_id="proj-A")
    await repo._sessions.update_one(  # noqa: SLF001
        {"_id": sid},
        {"$set": {"deleted_at": _now()}},
    )
    docs = await repo.list_sessions_for_project("u1", "proj-A")
    assert docs == []


async def test_list_sessions_for_project_excludes_other_users(
    repo: ChatRepository,
):
    own = await _seed_session(repo, user_id="u1", project_id="proj-A")
    foreign = await _seed_session(repo, user_id="u2", project_id="proj-A")
    docs = await repo.list_sessions_for_project("u1", "proj-A")
    ids = {d["_id"] for d in docs}
    assert own in ids
    assert foreign not in ids
