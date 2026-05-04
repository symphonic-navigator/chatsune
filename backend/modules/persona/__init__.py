"""Persona module — user-owned AI personas.

Public API: import only from this file.
"""

from backend.modules.persona._avatar_url import sign_avatar_url
from backend.modules.persona._cascade import cascade_delete_persona
from backend.modules.persona._clone import clone_persona
from backend.modules.persona._handlers import router
from backend.modules.persona._repository import PersonaRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the persona module collections."""
    await PersonaRepository(db).create_indexes()


async def get_persona(persona_id: str, user_id: str) -> dict | None:
    """Get a persona by ID, scoped to the owning user."""
    db = get_db()
    repo = PersonaRepository(db)
    return await repo.find_by_id(persona_id, user_id)


async def remove_library_from_all_personas(
    user_id: str, library_id: str,
) -> int:
    """Pull a deleted knowledge-library id from every persona of this user.

    Returns the number of persona documents that were updated. Called by
    the knowledge-library cascade so that orphan library references never
    survive a delete.
    """
    db = get_db()
    repo = PersonaRepository(db)
    return await repo.remove_library_from_all_personas(user_id, library_id)


async def clear_default_project_for_all(
    user_id: str, project_id: str,
) -> list[str]:
    """Clear ``default_project_id`` on every persona pointing at ``project_id``.

    Returns the list of affected persona ids. Called by the project
    cascade-delete (both safe-delete and full-purge) so that a deleted
    project never leaves dangling default-project references on personas.
    Mindspace Phase 3: in addition to the bulk update, this publishes one
    ``PERSONA_UPDATED`` event per affected persona so every personas
    surface (sidebar, persona overview default-project selector,
    project-detail-overlay personas tab) updates live without a follow-up
    GET. Event publishing is best-effort — a failure here must not roll
    back the data write the cascade depends on.
    """
    from datetime import datetime, timezone

    from backend.ws.event_bus import get_event_bus
    from shared.events.persona import PersonaUpdatedEvent
    from shared.topics import Topics

    db = get_db()
    repo = PersonaRepository(db)
    affected_ids = await repo.clear_default_project_for_all(user_id, project_id)
    if not affected_ids:
        return []

    event_bus = get_event_bus()
    now = datetime.now(timezone.utc)
    for persona_id in affected_ids:
        doc = await repo.find_by_id(persona_id, user_id)
        if doc is None:
            # Persona vanished between bulk update and event emission;
            # nothing meaningful to publish.
            continue
        try:
            dto = PersonaRepository.to_dto(doc)
            await event_bus.publish(
                Topics.PERSONA_UPDATED,
                PersonaUpdatedEvent(
                    persona_id=persona_id,
                    user_id=user_id,
                    persona=dto,
                    timestamp=now,
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[user_id],
            )
        except Exception:  # pragma: no cover — emit-side failures logged
            import structlog
            structlog.get_logger().warning(
                "persona_default_project_event_failed",
                persona_id=persona_id,
                user_id=user_id,
            )
    return affected_ids


async def unwire_personas_for_connection(user_id: str, connection_id: str) -> list[str]:
    """Null ``model_unique_id`` on every persona of this user that references
    the given Connection. Returns the list of affected persona IDs.

    Used by the LLM module when a Connection is deleted, so orphaned personas
    surface a "model not available" banner in the UI.
    """
    db = get_db()
    prefix = f"{connection_id}:"
    cursor = db["personas"].find(
        {
            "user_id": user_id,
            "model_unique_id": {"$regex": f"^{prefix}"},
        },
        {"_id": 1},
    )
    ids = [d["_id"] async for d in cursor]
    if ids:
        await db["personas"].update_many(
            {"_id": {"$in": ids}},
            {"$set": {"model_unique_id": None}},
        )
    return ids


async def list_persona_ids_for_user(user_id: str) -> list[str]:
    """Return every persona ``_id`` owned by ``user_id``.

    Used by the user self-delete cascade so the orchestrator can iterate
    through each persona via :func:`cascade_delete_persona` without ever
    touching the ``personas`` collection directly.
    """
    db = get_db()
    repo = PersonaRepository(db)
    personas = await repo.list_for_user(user_id)
    return [p["_id"] for p in personas]


async def bump_last_used(persona_id: str, user_id: str) -> None:
    """Stamp the persona's last_used_at to now. Fire-and-forget.

    Called from the chat module when a session is created or resumed.
    Failures are logged and swallowed by the caller — sidebar LRU is
    cosmetic and must never break the chat write path.
    """
    db = get_db()
    repo = PersonaRepository(db)
    await repo.bump_last_used(persona_id, user_id)


__all__ = [
    "router",
    "init_indexes",
    "get_persona",
    "bump_last_used",
    "sign_avatar_url",
    "unwire_personas_for_connection",
    "remove_library_from_all_personas",
    "cascade_delete_persona",
    "clone_persona",
    "list_persona_ids_for_user",
    "clear_default_project_for_all",
]
