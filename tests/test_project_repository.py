import asyncio
from datetime import datetime

import pytest

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.project import ProjectRepository


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ProjectRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_create_and_find(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1",
        title="Writing",
        emoji="✏️",
        description="for writing things",
        nsfw=False,
    )
    assert doc["_id"]
    assert doc["title"] == "Writing"
    assert doc["emoji"] == "✏️"
    assert doc["pinned"] is False
    assert doc["sort_order"] == 0
    assert isinstance(doc["created_at"], datetime)

    fetched = await repo.find_by_id(doc["_id"], "u1")
    assert fetched is not None
    assert fetched["_id"] == doc["_id"]


async def test_find_other_user_returns_none(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.find_by_id(doc["_id"], "u2") is None


async def test_list_for_user_orders_newest_first(repo: ProjectRepository):
    a = await repo.create(user_id="u1", title="A", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    b = await repo.create(user_id="u1", title="B", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    c = await repo.create(user_id="u1", title="C", emoji=None, description="", nsfw=False)
    await repo.create(user_id="u2", title="other", emoji=None, description="", nsfw=False)

    docs = await repo.list_for_user("u1")
    ids = [d["_id"] for d in docs]
    assert ids == [c["_id"], b["_id"], a["_id"]]


async def test_update_partial_preserves_other_fields(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="Old", emoji="🔥", description="d", nsfw=False,
    )
    updated = await repo.update(doc["_id"], "u1", {"title": "New"})
    assert updated is not None
    assert updated["title"] == "New"
    assert updated["emoji"] == "🔥"
    assert updated["description"] == "d"
    assert updated["updated_at"] >= doc["updated_at"]


async def test_update_other_user_returns_none(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.update(doc["_id"], "u2", {"title": "Hacked"}) is None


async def test_update_can_clear_emoji(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji="🔥", description="", nsfw=False,
    )
    updated = await repo.update(doc["_id"], "u1", {"emoji": None})
    assert updated is not None
    assert updated["emoji"] is None


async def test_delete(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.delete(doc["_id"], "u1") is True
    assert await repo.find_by_id(doc["_id"], "u1") is None


async def test_delete_other_user_returns_false(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.delete(doc["_id"], "u2") is False
    assert await repo.find_by_id(doc["_id"], "u1") is not None
