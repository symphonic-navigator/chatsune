"""Promote ChatSession documents to the new toggle fields.

Idempotent: safe to re-run. For each session:

- Unsets ``disabled_tool_groups``.
- If ``tools_enabled`` is missing, sets it from the persona (tool-bringing
  integration => True, else False).
- If ``auto_read`` is missing, sets it from the persona (TTS provider and
  dialogue voice configured => True, else False).

Run with:

    uv run python -m backend.migrations.m_2026_04_24_session_toggles
"""
import asyncio
import logging
from typing import Any

from backend.modules.chat._toggle_defaults import compute_persona_toggle_defaults

_log = logging.getLogger(__name__)


async def migrate_one(
    session_doc: dict[str, Any], personas: Any,
) -> dict[str, Any]:
    update: dict[str, Any] = {}
    unset: dict[str, Any] = {}

    if "disabled_tool_groups" in session_doc:
        unset["disabled_tool_groups"] = ""

    needs_tools = "tools_enabled" not in session_doc
    needs_auto_read = "auto_read" not in session_doc
    if needs_tools or needs_auto_read:
        persona_id = session_doc.get("persona_id")
        persona = await personas.find_one({"_id": persona_id}) if persona_id else None
        defaults = (
            compute_persona_toggle_defaults(persona) if persona
            else {"tools_enabled": False, "auto_read": False}
        )
        if needs_tools:
            update["tools_enabled"] = defaults["tools_enabled"]
        if needs_auto_read:
            update["auto_read"] = defaults["auto_read"]

    if not update and not unset:
        return {"skipped": True}

    mutation: dict[str, Any] = {}
    if update:
        mutation["$set"] = update
    if unset:
        mutation["$unset"] = unset
    return mutation


async def run() -> None:
    from backend.database import connect_db, get_db
    await connect_db()
    db = get_db()
    sessions = db["chat_sessions"]
    personas = db["personas"]

    cursor = sessions.find({})
    migrated = 0
    skipped = 0
    async for doc in cursor:
        mutation = await migrate_one(doc, personas)
        if mutation.get("skipped"):
            skipped += 1
            continue
        await sessions.update_one({"_id": doc["_id"]}, mutation)
        migrated += 1
    _log.info("Migration done: migrated=%d skipped=%d", migrated, skipped)
    print(f"Migration done: migrated={migrated} skipped={skipped}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
