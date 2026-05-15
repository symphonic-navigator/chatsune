"""Backfill ``token_count`` on messages of imported sessions.

The original ``create_imported_session`` path stamped every imported
message with ``token_count = 0``. The follow-up inference never
recomputed older messages — only new ones — so all historical messages
on every previously-imported session sit at zero. That broke the chat
compaction trigger (which has a ``total_tokens > 4000`` minimum-size
precondition) and produced misleading context-pill readings.

This migration walks every message that still has ``token_count = 0``
and recomputes it using ``count_tokens`` (cl100k_base via tiktoken). It
also re-seeds the session-level ``context_used_tokens`` from the new
per-message totals, so the UI shows a realistic fill before the next
inference.

Idempotent: a second run matches nothing (all messages already have a
non-zero token count) and updates no sessions whose recomputed total
matches what is stored.

Run with:

    uv run python -m backend.migrations.m_2026_05_15_imported_token_counts
"""
import asyncio
import logging

from backend.token_counter import count_tokens

_log = logging.getLogger(__name__)


async def run() -> None:
    from backend.database import connect_db, get_db
    await connect_db()
    db = get_db()
    messages = db["chat_messages"]
    sessions = db["chat_sessions"]

    updated_messages = 0
    affected_sessions: set[str] = set()

    cursor = messages.find({"token_count": 0})
    async for doc in cursor:
        content = doc.get("content") or ""
        new_count = count_tokens(content)
        if new_count == 0:
            # Genuinely empty message — skip, leaves the value untouched.
            continue
        await messages.update_one(
            {"_id": doc["_id"]},
            {"$set": {"token_count": new_count}},
        )
        updated_messages += 1
        affected_sessions.add(doc["session_id"])

    updated_sessions = 0
    for session_id in affected_sessions:
        agg = messages.aggregate([
            {"$match": {"session_id": session_id}},
            {"$group": {"_id": None, "total": {"$sum": "$token_count"}}},
        ])
        total = 0
        async for row in agg:
            total = int(row.get("total") or 0)
        result = await sessions.update_one(
            {"_id": session_id},
            {"$set": {"context_used_tokens": total}},
        )
        if result.modified_count:
            updated_sessions += 1

    print(
        f"Migration done: messages_updated={updated_messages} "
        f"sessions_resynced={updated_sessions}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
