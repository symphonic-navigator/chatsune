"""Integration test for ``backend/migrations/0002_assistant_correlation_id.py``.

Verifies the CLAUDE.md hard rule: the upgrade path is tested against
a fixture database that contains old-shape documents (assistant docs
with ``correlation_id=None``, plus imported sessions where every doc
has ``correlation_id=None`` by design).

Covers:

- Legacy session: assistants inherit the preceding user's cid.
- Imported session: each pair gets a synthetic ``imported-{sid}-{idx}`` id.
- Orphan user in legacy session: stays untouched, pair-builder skips it.
- Idempotent re-run: second invocation is a no-op.
- Imported session with two users in a row: first user marked orphan,
  second user paired with the following assistant.
- Discovery: ``run_all`` finds and runs the 0002 module.
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


async def _seed_session(
    db, *, session_id: str, imported_from: str | None = None,
) -> None:
    base = datetime(2025, 1, 1, tzinfo=UTC)
    doc = {
        "_id": session_id,
        "user_id": "user-1",
        "persona_id": "persona-1",
        "state": "idle",
        "created_at": base,
        "updated_at": base,
        "last_message_seq": 0,
    }
    if imported_from:
        doc["imported_from"] = imported_from
    await db["chat_sessions"].insert_one(doc)


async def _seed_msg(
    db, *, session_id: str, role: str, content: str, seq: int,
    correlation_id: str | None,
    status: str = "completed",
) -> str:
    msg_id = f"msg-{seq}-{uuid4().hex[:6]}"
    base = datetime(2025, 1, 1, tzinfo=UTC)
    doc = {
        "_id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "thinking": None,
        "token_count": 1,
        "created_at": base + timedelta(seconds=seq),
        "session_seq": seq,
        "status": status,
        "correlation_id": correlation_id,
    }
    await db["chat_messages"].insert_one(doc)
    return msg_id


async def test_legacy_session_assistants_inherit_preceding_user_cid(clean_db):
    client, db = _make_motor_db()
    try:
        sid = f"sess-legacy-{uuid4().hex[:8]}"
        await _seed_session(db, session_id=sid)

        # 3 user/assistant pairs. Users carry cids; assistants carry None.
        user_ids = {}
        asst_ids = {}
        for i, cid in enumerate(["cid-1", "cid-2", "cid-3"]):
            user_ids[cid] = await _seed_msg(
                db, session_id=sid, role="user", content=f"u-{i}",
                seq=2 * i + 1, correlation_id=cid,
            )
            asst_ids[cid] = await _seed_msg(
                db, session_id=sid, role="assistant", content=f"a-{i}",
                seq=2 * i + 2, correlation_id=None,
            )

        migration_mod = importlib.import_module(
            "backend.migrations.0002_assistant_correlation_id",
        )
        await migration_mod.run(db)

        # Each assistant now carries its preceding user's cid.
        for cid, aid in asst_ids.items():
            doc = await db["chat_messages"].find_one({"_id": aid})
            assert doc["correlation_id"] == cid

        # User cids remain untouched.
        for cid, uid in user_ids.items():
            doc = await db["chat_messages"].find_one({"_id": uid})
            assert doc["correlation_id"] == cid
    finally:
        client.close()


async def test_imported_session_gets_synthetic_correlation_ids(clean_db):
    client, db = _make_motor_db()
    try:
        sid = f"sess-imp-{uuid4().hex[:8]}"
        await _seed_session(db, session_id=sid, imported_from="chatgpt")

        # 2 pairs, every doc has correlation_id=None.
        ids = []
        for i, (role, content) in enumerate([
            ("user", "imp-u-0"),
            ("assistant", "imp-a-0"),
            ("user", "imp-u-1"),
            ("assistant", "imp-a-1"),
        ]):
            ids.append(await _seed_msg(
                db, session_id=sid, role=role, content=content,
                seq=i + 1, correlation_id=None,
            ))

        migration_mod = importlib.import_module(
            "backend.migrations.0002_assistant_correlation_id",
        )
        await migration_mod.run(db)

        docs_by_id = {
            d["_id"]: d
            async for d in db["chat_messages"].find({"session_id": sid})
        }

        # First pair shares cid imported-{sid}-0; second imported-{sid}-1.
        assert docs_by_id[ids[0]]["correlation_id"] == f"imported-{sid}-0"
        assert docs_by_id[ids[1]]["correlation_id"] == f"imported-{sid}-0"
        assert docs_by_id[ids[2]]["correlation_id"] == f"imported-{sid}-1"
        assert docs_by_id[ids[3]]["correlation_id"] == f"imported-{sid}-1"
    finally:
        client.close()


async def test_orphan_user_in_legacy_session_left_untouched(clean_db):
    """``user → assistant → user`` (cancelled before reply). Trailing
    user stays with its existing cid; pair-builder will skip it.
    """
    client, db = _make_motor_db()
    try:
        sid = f"sess-orphan-{uuid4().hex[:8]}"
        await _seed_session(db, session_id=sid)

        u1 = await _seed_msg(
            db, session_id=sid, role="user", content="u-0",
            seq=1, correlation_id="cid-1",
        )
        a1 = await _seed_msg(
            db, session_id=sid, role="assistant", content="a-0",
            seq=2, correlation_id=None,
        )
        u2 = await _seed_msg(
            db, session_id=sid, role="user", content="u-1",
            seq=3, correlation_id="cid-2",
        )

        migration_mod = importlib.import_module(
            "backend.migrations.0002_assistant_correlation_id",
        )
        await migration_mod.run(db)

        # First assistant inherits cid-1.
        a1_doc = await db["chat_messages"].find_one({"_id": a1})
        assert a1_doc["correlation_id"] == "cid-1"

        # Orphan user keeps cid-2 — it's not the migration's job to
        # delete or relabel it.
        u2_doc = await db["chat_messages"].find_one({"_id": u2})
        assert u2_doc["correlation_id"] == "cid-2"

        # Original user is untouched.
        u1_doc = await db["chat_messages"].find_one({"_id": u1})
        assert u1_doc["correlation_id"] == "cid-1"
    finally:
        client.close()


async def test_migration_idempotent_on_rerun(clean_db):
    """Second run must be a no-op — every doc already has a cid."""
    client, db = _make_motor_db()
    try:
        sid = f"sess-idem-{uuid4().hex[:8]}"
        await _seed_session(db, session_id=sid)

        await _seed_msg(
            db, session_id=sid, role="user", content="u",
            seq=1, correlation_id="cid-1",
        )
        await _seed_msg(
            db, session_id=sid, role="assistant", content="a",
            seq=2, correlation_id=None,
        )

        migration_mod = importlib.import_module(
            "backend.migrations.0002_assistant_correlation_id",
        )
        await migration_mod.run(db)

        snapshot_before = {
            d["_id"]: dict(d)
            async for d in db["chat_messages"].find({"session_id": sid})
        }

        await migration_mod.run(db)

        snapshot_after = {
            d["_id"]: dict(d)
            async for d in db["chat_messages"].find({"session_id": sid})
        }

        assert snapshot_before == snapshot_after
    finally:
        client.close()


async def test_imported_two_users_in_a_row_first_is_orphan(clean_db):
    """Edge case from broken imports: user → user → assistant.

    First user becomes ``imported-{sid}-orphan-0`` (synthetic orphan id).
    Second user pairs with the assistant under ``imported-{sid}-1``.
    """
    client, db = _make_motor_db()
    try:
        sid = f"sess-imp-2u-{uuid4().hex[:8]}"
        await _seed_session(db, session_id=sid, imported_from="chatgpt")

        u_orphan = await _seed_msg(
            db, session_id=sid, role="user", content="u-orphan",
            seq=1, correlation_id=None,
        )
        u_paired = await _seed_msg(
            db, session_id=sid, role="user", content="u-paired",
            seq=2, correlation_id=None,
        )
        a_paired = await _seed_msg(
            db, session_id=sid, role="assistant", content="a-paired",
            seq=3, correlation_id=None,
        )

        migration_mod = importlib.import_module(
            "backend.migrations.0002_assistant_correlation_id",
        )
        await migration_mod.run(db)

        u_orphan_doc = await db["chat_messages"].find_one({"_id": u_orphan})
        u_paired_doc = await db["chat_messages"].find_one({"_id": u_paired})
        a_paired_doc = await db["chat_messages"].find_one({"_id": a_paired})

        assert u_orphan_doc["correlation_id"] == f"imported-{sid}-orphan-0"
        # After the orphan eats pair_idx 0, the next pair gets idx 1.
        assert u_paired_doc["correlation_id"] == f"imported-{sid}-1"
        assert a_paired_doc["correlation_id"] == f"imported-{sid}-1"
    finally:
        client.close()


async def test_run_all_discovers_correlation_id_migration(clean_db):
    """``run_all`` (the auto-runner) must pick up 0002."""
    client, db = _make_motor_db()
    try:
        sid = f"sess-runall-{uuid4().hex[:8]}"
        await _seed_session(db, session_id=sid)

        await _seed_msg(
            db, session_id=sid, role="user", content="u",
            seq=1, correlation_id="cid-X",
        )
        await _seed_msg(
            db, session_id=sid, role="assistant", content="a",
            seq=2, correlation_id=None,
        )

        from backend.migrations import run_all
        await run_all(db)

        asst = await db["chat_messages"].find_one(
            {"session_id": sid, "role": "assistant"},
        )
        assert asst["correlation_id"] == "cid-X"
    finally:
        client.close()
