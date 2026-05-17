"""Unit-ish tests for the ``session_seq`` monotonic ordering work.

These tests talk to a live MongoDB via the shared ``clean_db`` fixture
(same pattern as ``tests/test_chat_repository.py``). They verify the
atomic counter increment, the new sort/delete paths, and the
``next_session_seq`` helper that branching will use later.

See ``devdocs/specs/2026-05-17-session-seq-migration-design.md``.
"""
import asyncio

import pytest

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_save_message_increments_counter_once_per_insert(repo):
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]

    # Fresh session starts at 0; first insert lands at 1.
    m1 = await repo.save_message(session_id=sid, role="user", content="a", token_count=1)
    m2 = await repo.save_message(session_id=sid, role="assistant", content="b", token_count=1)
    m3 = await repo.save_message(session_id=sid, role="user", content="c", token_count=1)

    assert m1["session_seq"] == 1
    assert m2["session_seq"] == 2
    assert m3["session_seq"] == 3

    session_doc = await repo._sessions.find_one({"_id": sid})
    assert session_doc["last_message_seq"] == 3


async def test_concurrent_save_messages_get_distinct_seqs(repo):
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]

    # Fire 10 inserts concurrently. find_one_and_update is atomic at
    # the Mongo level so each call must receive a distinct seq even
    # though the coroutines interleave freely.
    docs = await asyncio.gather(*[
        repo.save_message(session_id=sid, role="user", content=str(i), token_count=1)
        for i in range(10)
    ])
    seqs = sorted(d["session_seq"] for d in docs)
    assert seqs == list(range(1, 11))

    session_doc = await repo._sessions.find_one({"_id": sid})
    assert session_doc["last_message_seq"] == 10


async def test_list_messages_tail_sorts_by_session_seq(repo):
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]
    for i in range(5):
        await repo.save_message(
            session_id=sid, role="user", content=f"m{i}", token_count=1,
        )

    tail = await repo.list_messages_tail(sid)
    assert [m["session_seq"] for m in tail] == [1, 2, 3, 4, 5]
    assert [m["content"] for m in tail] == ["m0", "m1", "m2", "m3", "m4"]


async def test_list_messages_tail_max_count_keeps_newest(repo):
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]
    for i in range(8):
        await repo.save_message(
            session_id=sid, role="user", content=f"m{i}", token_count=1,
        )

    tail = await repo.list_messages_tail(sid, max_count=3)
    # Newest three returned in ascending order.
    assert [m["session_seq"] for m in tail] == [6, 7, 8]


async def test_delete_messages_from_removes_target_and_higher(repo):
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]
    msgs = []
    for i in range(5):
        msgs.append(await repo.save_message(
            session_id=sid, role="user", content=f"m{i}", token_count=1,
        ))

    # Delete from seq=3 onwards (msgs[2]).
    ok = await repo.delete_messages_from(sid, msgs[2]["_id"])
    assert ok is True

    remaining = await repo.list_messages_tail(sid)
    assert [m["session_seq"] for m in remaining] == [1, 2]
    assert [m["content"] for m in remaining] == ["m0", "m1"]


async def test_delete_messages_from_does_not_rewind_counter(repo):
    """Gaps after deletion are intentional — the high-water mark stays."""
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]
    msgs = []
    for i in range(4):
        msgs.append(await repo.save_message(
            session_id=sid, role="user", content=f"m{i}", token_count=1,
        ))

    await repo.delete_messages_from(sid, msgs[1]["_id"])

    session_doc = await repo._sessions.find_one({"_id": sid})
    # Counter still reflects the pre-deletion high-water mark.
    assert session_doc["last_message_seq"] == 4

    # The next insert gets seq 5, leaving a gap (1, 5).
    next_msg = await repo.save_message(
        session_id=sid, role="user", content="after-delete", token_count=1,
    )
    assert next_msg["session_seq"] == 5

    remaining = await repo.list_messages_tail(sid)
    assert [m["session_seq"] for m in remaining] == [1, 5]


async def test_next_session_seq_returns_and_increments(repo):
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]
    await repo.save_message(session_id=sid, role="user", content="a", token_count=1)

    reserved = await repo.next_session_seq(sid)
    # Counter was 1 after the save; next_session_seq reserves 2.
    assert reserved == 2

    again = await repo.next_session_seq(sid)
    assert again == 3

    session_doc = await repo._sessions.find_one({"_id": sid})
    assert session_doc["last_message_seq"] == 3


async def test_next_session_seq_unknown_session_raises(repo):
    with pytest.raises(ValueError):
        await repo.next_session_seq("does-not-exist")


async def test_edit_message_atomic_truncates_by_seq(repo):
    """Editing keeps the target and drops everything after by seq."""
    session = await repo.create_session("u-1", "p-1")
    sid = session["_id"]
    msgs = []
    for i in range(5):
        msgs.append(await repo.save_message(
            session_id=sid, role="user", content=f"m{i}", token_count=1,
        ))

    ok = await repo.edit_message_atomic(
        sid, msgs[2]["_id"], new_content="edited", token_count=2,
    )
    assert ok is True

    remaining = await repo.list_messages_tail(sid)
    # Target preserved (with new content); msgs[3] and msgs[4] gone.
    assert [m["session_seq"] for m in remaining] == [1, 2, 3]
    assert remaining[-1]["content"] == "edited"
