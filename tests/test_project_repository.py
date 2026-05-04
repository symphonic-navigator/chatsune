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
    # Mindspace: sort is now ``[(pinned, -1), (updated_at, -1)]``. With no
    # pinned projects the relative order falls back to most-recently-
    # updated first — for newly created projects that's the same as
    # "newest first".
    a = await repo.create(user_id="u1", title="A", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    b = await repo.create(user_id="u1", title="B", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    c = await repo.create(user_id="u1", title="C", emoji=None, description="", nsfw=False)
    await repo.create(user_id="u2", title="other", emoji=None, description="", nsfw=False)

    docs = await repo.list_for_user("u1")
    ids = [d["_id"] for d in docs]
    assert ids == [c["_id"], b["_id"], a["_id"]]


async def test_list_for_user_pinned_first_then_updated(repo: ProjectRepository):
    """Pinned projects always come before unpinned ones, regardless of age."""
    a = await repo.create(user_id="u1", title="A", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    b = await repo.create(user_id="u1", title="B", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    c = await repo.create(user_id="u1", title="C", emoji=None, description="", nsfw=False)

    # Pin the *oldest* — it should still surface first.
    assert await repo.set_pinned(a["_id"], "u1", True) is True

    docs = await repo.list_for_user("u1")
    ids = [d["_id"] for d in docs]
    # ``a`` is pinned and was just touched (set_pinned bumps updated_at),
    # so it sits first. The remaining two follow in newest-first order.
    assert ids[0] == a["_id"]
    assert set(ids[1:]) == {b["_id"], c["_id"]}
    assert ids[1] == c["_id"]
    assert ids[2] == b["_id"]


async def test_list_for_user_two_pinned_orders_by_updated_at(
    repo: ProjectRepository,
):
    a = await repo.create(user_id="u1", title="A", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    b = await repo.create(user_id="u1", title="B", emoji=None, description="", nsfw=False)
    await asyncio.sleep(0.005)
    await repo.set_pinned(a["_id"], "u1", True)
    await asyncio.sleep(0.005)
    await repo.set_pinned(b["_id"], "u1", True)
    docs = await repo.list_for_user("u1")
    ids = [d["_id"] for d in docs]
    # Both pinned, b's updated_at is newer → first.
    assert ids == [b["_id"], a["_id"]]


async def test_get_library_ids_returns_field(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a", "lib-b"],
    )
    assert await repo.get_library_ids(doc["_id"], "u1") == ["lib-a", "lib-b"]


async def test_get_library_ids_missing_project_returns_empty(
    repo: ProjectRepository,
):
    assert await repo.get_library_ids("nonexistent", "u1") == []


async def test_get_library_ids_wrong_user_returns_empty(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a"],
    )
    assert await repo.get_library_ids(doc["_id"], "u2") == []


async def test_remove_library_from_all_projects(repo: ProjectRepository):
    a = await repo.create(
        user_id="u1", title="A", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a", "lib-b"],
    )
    b = await repo.create(
        user_id="u1", title="B", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a"],
    )
    c = await repo.create(
        user_id="u1", title="C", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-b"],
    )

    modified = await repo.remove_library_from_all_projects("u1", "lib-a")
    assert modified == 2
    assert await repo.get_library_ids(a["_id"], "u1") == ["lib-b"]
    assert await repo.get_library_ids(b["_id"], "u1") == []
    # Untouched project is unchanged.
    assert await repo.get_library_ids(c["_id"], "u1") == ["lib-b"]


async def test_remove_library_from_all_projects_no_match_is_noop(
    repo: ProjectRepository,
):
    a = await repo.create(
        user_id="u1", title="A", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-a"],
    )
    modified = await repo.remove_library_from_all_projects(
        "u1", "lib-not-attached",
    )
    assert modified == 0
    assert await repo.get_library_ids(a["_id"], "u1") == ["lib-a"]


async def test_remove_library_from_all_projects_scoped_to_user(
    repo: ProjectRepository,
):
    """Other users' projects must not be touched even if they reference the
    same library id (parity with the persona-side equivalent)."""
    mine = await repo.create(
        user_id="u1", title="Mine", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-shared"],
    )
    foreign = await repo.create(
        user_id="u2", title="Foreign", emoji=None, description="", nsfw=False,
        knowledge_library_ids=["lib-shared"],
    )

    modified = await repo.remove_library_from_all_projects("u1", "lib-shared")
    assert modified == 1
    assert await repo.get_library_ids(mine["_id"], "u1") == []
    # u2's project is untouched even though it references the same id.
    assert await repo.get_library_ids(foreign["_id"], "u2") == ["lib-shared"]


async def test_set_pinned_toggles(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert doc["pinned"] is False

    assert await repo.set_pinned(doc["_id"], "u1", True) is True
    refreshed = await repo.find_by_id(doc["_id"], "u1")
    assert refreshed is not None
    assert refreshed["pinned"] is True
    assert refreshed["updated_at"] >= doc["updated_at"]

    assert await repo.set_pinned(doc["_id"], "u1", False) is True
    refreshed = await repo.find_by_id(doc["_id"], "u1")
    assert refreshed is not None
    assert refreshed["pinned"] is False


async def test_set_pinned_unknown_project_returns_false(repo: ProjectRepository):
    assert await repo.set_pinned("nonexistent", "u1", True) is False


async def test_set_pinned_other_user_returns_false(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.set_pinned(doc["_id"], "u2", True) is False
    refreshed = await repo.find_by_id(doc["_id"], "u1")
    assert refreshed is not None
    assert refreshed["pinned"] is False


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
