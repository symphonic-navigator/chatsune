"""Tests for MemoryRepository."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.memory._repository import MemoryRepository


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = MemoryRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


# ---------------------------------------------------------------------------
# Journal entry basics
# ---------------------------------------------------------------------------

async def test_create_journal_entry_and_list_uncommitted(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1",
        persona_id="p1",
        content="User prefers dark mode",
        category="preference",
        source_session_id="session-1",
    )
    assert entry_id is not None

    entries = await repo.list_journal_entries("u1", "p1", state="uncommitted")
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id
    assert entries[0]["state"] == "uncommitted"
    assert entries[0]["content"] == "User prefers dark mode"


async def test_list_journal_entries_no_state_filter(repo):
    await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="A", category=None, source_session_id="s1",
    )
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="B", category="fact", source_session_id="s1",
    )
    await repo.commit_entry(entry_id, "u1")

    all_entries = await repo.list_journal_entries("u1", "p1")
    assert len(all_entries) == 2


async def test_list_journal_entries_scoped_to_user_and_persona(repo):
    await repo.create_journal_entry(
        user_id="u1", persona_id="p1", content="A", category=None, source_session_id="s1",
    )
    await repo.create_journal_entry(
        user_id="u2", persona_id="p1", content="B", category=None, source_session_id="s1",
    )
    await repo.create_journal_entry(
        user_id="u1", persona_id="p2", content="C", category=None, source_session_id="s1",
    )
    entries = await repo.list_journal_entries("u1", "p1")
    assert len(entries) == 1
    assert entries[0]["content"] == "A"


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

async def test_commit_entry(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Test", category=None, source_session_id="s1",
    )
    ok = await repo.commit_entry(entry_id, "u1")
    assert ok is True

    committed = await repo.list_journal_entries("u1", "p1", state="committed")
    assert len(committed) == 1
    assert committed[0]["state"] == "committed"
    assert committed[0]["committed_at"] is not None
    assert committed[0]["auto_committed"] is False


async def test_commit_entry_wrong_user_returns_false(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Test", category=None, source_session_id="s1",
    )
    ok = await repo.commit_entry(entry_id, "other-user")
    assert ok is False


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def test_update_uncommitted_entry_content(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Original", category=None, source_session_id="s1",
    )
    ok = await repo.update_entry(entry_id, "u1", content="Updated")
    assert ok is True

    entries = await repo.list_journal_entries("u1", "p1")
    assert entries[0]["content"] == "Updated"


async def test_update_committed_entry_content(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Original", category=None, source_session_id="s1",
    )
    await repo.commit_entry(entry_id, "u1")
    ok = await repo.update_entry(entry_id, "u1", content="Updated after commit")
    assert ok is True

    entries = await repo.list_journal_entries("u1", "p1", state="committed")
    assert entries[0]["content"] == "Updated after commit"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def test_delete_entry_hard_delete(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Will be deleted", category=None, source_session_id="s1",
    )
    ok = await repo.delete_entry(entry_id, "u1")
    assert ok is True

    entries = await repo.list_journal_entries("u1", "p1")
    assert len(entries) == 0


async def test_delete_entry_wrong_user_returns_false(repo):
    entry_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Mine", category=None, source_session_id="s1",
    )
    ok = await repo.delete_entry(entry_id, "other-user")
    assert ok is False

    entries = await repo.list_journal_entries("u1", "p1")
    assert len(entries) == 1


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------

async def test_count_entries_by_state(repo):
    for _ in range(3):
        await repo.create_journal_entry(
            user_id="u1", persona_id="p1",
            content="entry", category=None, source_session_id="s1",
        )
    # Commit one.
    entries = await repo.list_journal_entries("u1", "p1", state="uncommitted")
    await repo.commit_entry(entries[0]["id"], "u1")

    uncommitted_count = await repo.count_entries("u1", "p1", state="uncommitted")
    committed_count = await repo.count_entries("u1", "p1", state="committed")
    assert uncommitted_count == 2
    assert committed_count == 1


# ---------------------------------------------------------------------------
# Auto-commit old entries
# ---------------------------------------------------------------------------

async def test_auto_commit_old_entries(repo):
    # Create a recent entry that should not be auto-committed.
    await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Recent", category=None, source_session_id="s1",
    )
    # Create an old entry by backdating directly.
    old_id = await repo.create_journal_entry(
        user_id="u1", persona_id="p1",
        content="Old entry", category=None, source_session_id="s1",
    )
    old_time = datetime.now(UTC) - timedelta(hours=50)
    await repo._entries.update_one({"_id": old_id}, {"$set": {"created_at": old_time}})

    committed = await repo.auto_commit_old_entries(max_age_hours=48)
    assert len(committed) == 1
    assert committed[0]["id"] == old_id
    assert committed[0]["state"] == "committed"
    assert committed[0]["auto_committed"] is True

    # Recent entry should still be uncommitted.
    uncommitted = await repo.list_journal_entries("u1", "p1", state="uncommitted")
    assert len(uncommitted) == 1
    assert uncommitted[0]["content"] == "Recent"


# ---------------------------------------------------------------------------
# Discard oldest uncommitted
# ---------------------------------------------------------------------------

async def test_discard_oldest_uncommitted(repo):
    # Create 5 entries. With cap=3, the 2 oldest should be discarded.
    ids = []
    for i in range(5):
        eid = await repo.create_journal_entry(
            user_id="u1", persona_id="p1",
            content=f"Entry {i}", category=None, source_session_id="s1",
        )
        ids.append(eid)
        # Stagger created_at so ordering is deterministic.
        backdated = datetime.now(UTC) - timedelta(minutes=5 - i)
        await repo._entries.update_one({"_id": eid}, {"$set": {"created_at": backdated}})

    discarded = await repo.discard_oldest_uncommitted("u1", "p1", max_count=3)
    assert discarded == 2

    remaining = await repo.list_journal_entries("u1", "p1", state="uncommitted")
    assert len(remaining) == 3


async def test_discard_oldest_uncommitted_no_excess(repo):
    for _ in range(2):
        await repo.create_journal_entry(
            user_id="u1", persona_id="p1",
            content="entry", category=None, source_session_id="s1",
        )
    discarded = await repo.discard_oldest_uncommitted("u1", "p1", max_count=5)
    assert discarded == 0


# ---------------------------------------------------------------------------
# Archive entries
# ---------------------------------------------------------------------------

async def test_archive_entries(repo):
    for _ in range(3):
        eid = await repo.create_journal_entry(
            user_id="u1", persona_id="p1",
            content="entry", category=None, source_session_id="s1",
        )
        await repo.commit_entry(eid, "u1")

    count = await repo.archive_entries("u1", "p1", dream_id="dream-42")
    assert count == 3

    archived = await repo.list_journal_entries("u1", "p1", state="archived")
    assert len(archived) == 3
    for entry in archived:
        assert entry["archived_by_dream_id"] == "dream-42"

    committed = await repo.list_journal_entries("u1", "p1", state="committed")
    assert len(committed) == 0


# ---------------------------------------------------------------------------
# Memory body — basic save and retrieve
# ---------------------------------------------------------------------------

async def test_save_memory_body_and_get_current(repo):
    version = await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="Memory content v1",
        token_count=100,
        entries_processed=5,
    )
    assert version == 1

    current = await repo.get_current_memory_body("u1", "p1")
    assert current is not None
    assert current["version"] == 1
    assert current["content"] == "Memory content v1"
    assert current["token_count"] == 100


async def test_get_current_memory_body_returns_none_when_empty(repo):
    result = await repo.get_current_memory_body("u1", "p1")
    assert result is None


# ---------------------------------------------------------------------------
# Memory body — version increments
# ---------------------------------------------------------------------------

async def test_version_increments_on_second_save(repo):
    await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="v1", token_count=10, entries_processed=1,
    )
    v2 = await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="v2", token_count=20, entries_processed=2,
    )
    assert v2 == 2

    current = await repo.get_current_memory_body("u1", "p1")
    assert current["version"] == 2
    assert current["content"] == "v2"


# ---------------------------------------------------------------------------
# Memory body — list versions
# ---------------------------------------------------------------------------

async def test_list_memory_body_versions_newest_first(repo):
    for i in range(1, 4):
        await repo.save_memory_body(
            user_id="u1", persona_id="p1",
            content=f"content v{i}", token_count=i * 10, entries_processed=i,
        )

    versions = await repo.list_memory_body_versions("u1", "p1")
    assert len(versions) == 3
    assert versions[0]["version"] == 3
    assert versions[1]["version"] == 2
    assert versions[2]["version"] == 1
    # Content must NOT be included in the listing.
    for v in versions:
        assert "content" not in v


# ---------------------------------------------------------------------------
# Memory body — max versions retained
# ---------------------------------------------------------------------------

async def test_max_versions_retained(repo):
    for i in range(7):
        await repo.save_memory_body(
            user_id="u1", persona_id="p1",
            content=f"content v{i + 1}", token_count=100, entries_processed=1,
        )

    versions = await repo.list_memory_body_versions("u1", "p1")
    assert len(versions) == 5
    # Latest version should be 7, oldest retained should be 3.
    version_numbers = {v["version"] for v in versions}
    assert max(version_numbers) == 7
    assert min(version_numbers) == 3


# ---------------------------------------------------------------------------
# Memory body — get specific version
# ---------------------------------------------------------------------------

async def test_get_memory_body_version_by_number(repo):
    await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="first", token_count=10, entries_processed=1,
    )
    await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="second", token_count=20, entries_processed=2,
    )

    v1 = await repo.get_memory_body_version("u1", "p1", version=1)
    assert v1 is not None
    assert v1["content"] == "first"

    v2 = await repo.get_memory_body_version("u1", "p1", version=2)
    assert v2 is not None
    assert v2["content"] == "second"


async def test_get_memory_body_version_missing_returns_none(repo):
    result = await repo.get_memory_body_version("u1", "p1", version=99)
    assert result is None


# ---------------------------------------------------------------------------
# Memory body — rollback
# ---------------------------------------------------------------------------

async def test_rollback_creates_new_version_with_old_content(repo):
    await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="Good content", token_count=50, entries_processed=3,
    )
    await repo.save_memory_body(
        user_id="u1", persona_id="p1",
        content="Bad content", token_count=60, entries_processed=4,
    )
    # Sanity check: current is v2 with bad content.
    current_before = await repo.get_current_memory_body("u1", "p1")
    assert current_before["version"] == 2
    assert current_before["content"] == "Bad content"

    new_version = await repo.rollback_memory_body("u1", "p1", to_version=1)
    assert new_version == 3

    current_after = await repo.get_current_memory_body("u1", "p1")
    assert current_after["version"] == 3
    assert current_after["content"] == "Good content"
