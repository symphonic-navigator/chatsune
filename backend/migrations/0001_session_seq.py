"""Backfill ``session_seq`` on every chat message and ``last_message_seq``
on every chat session.

See ``devdocs/specs/2026-05-17-session-seq-migration-design.md`` for the
design rationale. The short version: message ordering used to key off
``created_at`` (microsecond timestamps) which collide under same-tick
concurrent inserts and have no stable lineage semantics. This migration
introduces a per-session monotonic integer counter that is atomically
reserved at ``save_message`` time.

This script runs at every backend startup via
``backend/migrations/__init__.py:run_all``. Idempotency is non-negotiable:

- Sessions whose ``last_message_seq`` already matches the message count
  for that session are skipped wholesale.
- Sessions whose counter is non-zero but no longer matches the message
  count (e.g. an out-of-band insert before the next startup) are
  re-backfilled from scratch. Existing seqs that already line up with
  the recomputed ordering are left untouched (the per-message
  ``$set`` is guarded by a value comparison).
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


async def run(db: Any) -> None:
    sessions = db["chat_sessions"]
    messages = db["chat_messages"]

    session_count = 0
    backfilled_sessions = 0
    backfilled_messages = 0
    skipped_sessions = 0

    async for session in sessions.find({}):
        session_count += 1
        session_id = session["_id"]
        existing_counter = int(session.get("last_message_seq", 0) or 0)
        message_count = await messages.count_documents({"session_id": session_id})

        # Fast-path idempotency: counter already matches message count
        # AND every message carries a non-zero ``session_seq``. We only
        # need the existence check for non-zero seqs because the
        # migration assigns 1..N — if any doc still has 0 we must
        # re-backfill.
        if existing_counter == message_count and message_count > 0:
            missing = await messages.count_documents({
                "session_id": session_id,
                "$or": [
                    {"session_seq": {"$exists": False}},
                    {"session_seq": 0},
                ],
            })
            if missing == 0:
                skipped_sessions += 1
                continue

        # Empty session: ensure the counter is 0 (legacy docs may lack
        # the field entirely) and move on.
        if message_count == 0:
            if "last_message_seq" not in session:
                await sessions.update_one(
                    {"_id": session_id},
                    {"$set": {"last_message_seq": 0}},
                )
            skipped_sessions += 1
            continue

        # Backfill: walk every message in chronological order and stamp
        # session_seq = 1..N. Tiebreak by ``_id`` so the ordering is
        # deterministic for documents that share a created_at.
        cursor = messages.find(
            {"session_id": session_id},
        ).sort([("created_at", 1), ("_id", 1)])

        seq = 0
        async for msg in cursor:
            seq += 1
            if msg.get("session_seq") == seq:
                # Already correct — skip the write.
                continue
            await messages.update_one(
                {"_id": msg["_id"]},
                {"$set": {"session_seq": seq}},
            )
            backfilled_messages += 1

        await sessions.update_one(
            {"_id": session_id},
            {"$set": {"last_message_seq": seq}},
        )
        backfilled_sessions += 1

    _log.info(
        "migrations.0001_session_seq complete sessions_total=%d "
        "sessions_backfilled=%d sessions_skipped=%d messages_backfilled=%d",
        session_count, backfilled_sessions, skipped_sessions, backfilled_messages,
    )
