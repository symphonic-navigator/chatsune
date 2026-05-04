"""Mindspace Phase 2 (task 12) — knowledge-library cascade pulls projects.

The knowledge cascade already strips deleted-library refs from personas
and chat sessions; with Mindspace the third n:m link is project →
library. Deleting a library must therefore also pull the id from every
project's ``knowledge_library_ids`` so no orphan references survive.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.knowledge._cascade import cascade_delete_library
from backend.modules.project import ProjectRepository
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager


@pytest_asyncio.fixture
async def env(clean_db):
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield get_db()
    await disconnect_db()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_library(db, *, user_id: str, name: str = "lib") -> str:
    lib_id = f"lib-{uuid4().hex[:8]}"
    await db["knowledge_libraries"].insert_one({
        "_id": lib_id,
        "user_id": user_id,
        "name": name,
        "description": "",
        "created_at": _now(),
        "updated_at": _now(),
    })
    return lib_id


async def test_library_cascade_pulls_id_from_projects(env):
    db = env
    repo = ProjectRepository(db)

    lib_id = await _seed_library(db, user_id="u1", name="Klingon")
    other_lib = await _seed_library(db, user_id="u1", name="Other")

    a = await repo.create(
        user_id="u1", title="A", emoji=None, description="", nsfw=False,
        knowledge_library_ids=[lib_id, other_lib],
    )
    b = await repo.create(
        user_id="u1", title="B", emoji=None, description="", nsfw=False,
        knowledge_library_ids=[lib_id],
    )
    c = await repo.create(
        user_id="u1", title="C", emoji=None, description="", nsfw=False,
        knowledge_library_ids=[other_lib],
    )

    deleted, report = await cascade_delete_library(
        user_id="u1", library_id=lib_id,
    )
    assert deleted is True

    # The cascade reports the project step too.
    project_step = next(
        (s for s in report.steps if s.label == "project references unlinked"),
        None,
    )
    assert project_step is not None
    assert project_step.deleted_count == 2

    # Verify on disk: the deleted library is gone from A and B; C is
    # untouched; ``other_lib`` still wired in A.
    assert await repo.get_library_ids(a["_id"], "u1") == [other_lib]
    assert await repo.get_library_ids(b["_id"], "u1") == []
    assert await repo.get_library_ids(c["_id"], "u1") == [other_lib]
