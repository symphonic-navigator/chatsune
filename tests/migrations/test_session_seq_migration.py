"""Integration test for ``backend/migrations/0001_session_seq.py``.

Verifies the CLAUDE.md hard rule: the upgrade path is tested against
a fixture database that contains old-shape documents (no ``session_seq``
or ``last_message_seq`` fields).

Covers:

- Fresh migration over a 3-session × 5-message fixture.
- Idempotent re-run (no further writes).
- Out-of-band insert picked up on next run.
- Live ``save_message`` increments the counter after migration.
- Discovery: ``run_all`` actually finds and runs the 0001 module.
"""
from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings


pytestmark = pytest.mark.asyncio


def _make_motor_db():
    client = AsyncIOMotorClient(settings.mongodb_uri)
    return client, client.get_database()


async def _seed_old_shape(db, *, sessions: int, messages_per_session: int) -> list[str]:
    """Insert ``sessions`` sessions × ``messages_per_session`` messages.

    Documents have NO ``session_seq`` or ``last_message_seq`` fields,
    mimicking the pre-migration state. Created_at values are spread out
    enough that the migration's chronological sort is unambiguous.
    """
    session_ids: list[str] = []
    base = datetime(2025, 1, 1, tzinfo=UTC)
    for s in range(sessions):
        session_id = f"sess-{s}-{uuid4().hex[:8]}"
        session_ids.append(session_id)
        await db["chat_sessions"].insert_one({
            "_id": session_id,
            "user_id": "user-1",
            "persona_id": f"persona-{s}",
            "state": "idle",
            "created_at": base,
            "updated_at": base,
        })
        msg_docs = []
        for m in range(messages_per_session):
            msg_docs.append({
                "_id": f"msg-{s}-{m}-{uuid4().hex[:6]}",
                "session_id": session_id,
                "role": "user" if m % 2 == 0 else "assistant",
                "content": f"s{s}-m{m}",
                "thinking": None,
                "token_count": 1,
                "created_at": base + timedelta(seconds=m),
                "status": "completed",
            })
        await db["chat_messages"].insert_many(msg_docs)
    return session_ids


async def test_migration_backfills_old_shape(clean_db):
    client, db = _make_motor_db()
    try:
        session_ids = await _seed_old_shape(db, sessions=3, messages_per_session=5)

        # Pre-condition: no doc carries session_seq or last_message_seq.
        no_seq = await db["chat_messages"].count_documents(
            {"session_seq": {"$exists": True}},
        )
        assert no_seq == 0
        for sid in session_ids:
            sdoc = await db["chat_sessions"].find_one({"_id": sid})
            assert "last_message_seq" not in sdoc

        # Run the migration.
        migration_mod = importlib.import_module(
            "backend.migrations.0001_session_seq",
        )
        await migration_mod.run(db)

        # Every session has last_message_seq == 5.
        for sid in session_ids:
            sdoc = await db["chat_sessions"].find_one({"_id": sid})
            assert sdoc["last_message_seq"] == 5

        # Every session's messages carry seqs 1..5 in created_at order.
        for sid in session_ids:
            cursor = db["chat_messages"].find(
                {"session_id": sid},
            ).sort([("created_at", 1), ("_id", 1)])
            seqs = [m["session_seq"] async for m in cursor]
            assert seqs == [1, 2, 3, 4, 5]
    finally:
        client.close()


async def test_migration_idempotent_on_rerun(clean_db):
    client, db = _make_motor_db()
    try:
        session_ids = await _seed_old_shape(db, sessions=2, messages_per_session=4)

        migration_mod = importlib.import_module(
            "backend.migrations.0001_session_seq",
        )
        await migration_mod.run(db)

        # Snapshot every doc after first run.
        sessions_before = {
            sdoc["_id"]: sdoc
            async for sdoc in db["chat_sessions"].find({})
        }
        messages_before = {
            mdoc["_id"]: mdoc
            async for mdoc in db["chat_messages"].find({})
        }

        # Second run must not modify anything.
        await migration_mod.run(db)

        sessions_after = {
            sdoc["_id"]: sdoc
            async for sdoc in db["chat_sessions"].find({})
        }
        messages_after = {
            mdoc["_id"]: mdoc
            async for mdoc in db["chat_messages"].find({})
        }
        assert sessions_before == sessions_after
        assert messages_before == messages_after

        # Sanity: still 2 × 4 == 8 messages.
        assert len(messages_after) == 8
        assert len(session_ids) == 2
    finally:
        client.close()


async def test_migration_picks_up_out_of_band_inserts(clean_db):
    client, db = _make_motor_db()
    try:
        session_ids = await _seed_old_shape(db, sessions=1, messages_per_session=5)
        sid = session_ids[0]

        migration_mod = importlib.import_module(
            "backend.migrations.0001_session_seq",
        )
        await migration_mod.run(db)

        # Insert a 6th message out-of-band — no session_seq field, as if
        # something inserted while we were on the old code path.
        await db["chat_messages"].insert_one({
            "_id": f"msg-extra-{uuid4().hex[:6]}",
            "session_id": sid,
            "role": "user",
            "content": "oob",
            "thinking": None,
            "token_count": 1,
            "created_at": datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC),
            "status": "completed",
        })

        # Re-run: counter (5) no longer matches message count (6), so
        # the session is re-backfilled.
        await migration_mod.run(db)

        sdoc = await db["chat_sessions"].find_one({"_id": sid})
        assert sdoc["last_message_seq"] == 6

        oob_msg = await db["chat_messages"].find_one({"content": "oob"})
        # Oob was inserted with created_at past every seeded message so
        # it sorts last and gets seq 6.
        assert oob_msg["session_seq"] == 6
    finally:
        client.close()


async def test_save_message_after_migration_uses_new_counter(clean_db):
    """End-to-end: migration ran, then live insert via the new path."""
    client, db = _make_motor_db()
    try:
        session_ids = await _seed_old_shape(db, sessions=1, messages_per_session=3)
        sid = session_ids[0]

        migration_mod = importlib.import_module(
            "backend.migrations.0001_session_seq",
        )
        await migration_mod.run(db)

        # Now go through the live repo write path. Use connect_db() to
        # pick up the same connection settings the prod code uses.
        from backend.database import connect_db, disconnect_db, get_db
        from backend.modules.chat._repository import ChatRepository

        await connect_db()
        try:
            repo = ChatRepository(get_db())
            new_msg = await repo.save_message(
                session_id=sid, role="user", content="live", token_count=1,
            )
            assert new_msg["session_seq"] == 4

            sdoc = await get_db()["chat_sessions"].find_one({"_id": sid})
            assert sdoc["last_message_seq"] == 4
        finally:
            await disconnect_db()
    finally:
        client.close()


async def test_run_all_discovers_session_seq_migration(clean_db):
    client, db = _make_motor_db()
    try:
        await _seed_old_shape(db, sessions=1, messages_per_session=2)

        from backend.migrations import run_all
        await run_all(db)

        # Effect was the same as running 0001 directly.
        sdoc = await db["chat_sessions"].find_one({})
        assert sdoc["last_message_seq"] == 2
    finally:
        client.close()
