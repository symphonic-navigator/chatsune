"""Clear the ``imported:*`` pseudo ``model_unique_id`` on imported sessions.

When the ChatGPT-import feature first shipped, imported sessions were
stamped with ``model_unique_id = "imported:chatgpt:<slug>"`` and a
connection-picker dialog asked the user to choose a real connection on
the first follow-up send. That extra step was redundant — the persona
already has a default connection and model — so the pseudo-id was
dropped: imported sessions now leave ``model_unique_id`` as ``None`` and
the orchestrator falls back to the persona default.

This migration backfills existing imported sessions that still carry a
``"imported:"`` value. Idempotent: re-running matches nothing on a
clean database.

Run with:

    uv run python -m backend.migrations.m_2026_05_12_imported_model_unique_id
"""
import asyncio
import logging

_log = logging.getLogger(__name__)


async def run() -> None:
    from backend.database import connect_db, get_db
    await connect_db()
    db = get_db()
    sessions = db["chat_sessions"]

    result = await sessions.update_many(
        {"model_unique_id": {"$regex": "^imported:"}},
        {"$set": {"model_unique_id": None}},
    )
    _log.info("Migration done: cleared=%d", result.modified_count)
    print(f"Migration done: cleared={result.modified_count}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
