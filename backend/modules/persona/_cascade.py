"""Persona cascade-delete helper — shared between the DELETE handler and
the import rollback path.

Extracted so both call sites execute exactly the same cleanup sequence:

1. Collect session ids (for artefact cleanup — must happen BEFORE sessions
   are deleted, otherwise the artefact module cannot find them).
2. Delete artefacts (per-session).
3. Delete chat sessions + messages.
4. Delete memory (journal entries + memory bodies).
5. Delete storage files (DB rows + physical blobs).
6. Delete avatar file if present.
7. Delete the persona document itself.

Every step uses the owning module's public API — no cross-module DB access.

The function is tolerant: it deletes best-effort, logging but not raising
if the persona or any downstream data is missing. The import-rollback path
relies on this: if a partial import only created some of these artefacts,
we still want the rest of the cleanup to run.
"""

from __future__ import annotations

import logging

from backend.database import get_db
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._repository import PersonaRepository

_log = logging.getLogger(__name__)


async def cascade_delete_persona(user_id: str, persona_id: str) -> bool:
    """Cascade-delete a persona and all data owned by it.

    Returns ``True`` if the persona document itself was deleted, ``False``
    if it was not found.
    """
    # Deferred imports to keep module import order clean and avoid
    # circular dependencies during app startup.
    from backend.modules.artefact import delete_all_for_sessions
    from backend.modules.chat import (
        delete_all_for_persona as delete_chats,
    )
    from backend.modules.chat import list_session_ids_for_persona
    from backend.modules.memory import delete_by_persona as delete_memories
    from backend.modules.storage import delete_by_persona as delete_storage

    repo = PersonaRepository(get_db())
    persona = await repo.find_by_id(persona_id, user_id)

    # Step 1: collect session ids BEFORE chat delete.
    session_ids = await list_session_ids_for_persona(user_id, persona_id)

    # Step 2: artefacts (must happen before sessions are gone).
    if session_ids:
        await delete_all_for_sessions(session_ids)

    # Step 3: chat sessions + messages.
    await delete_chats(user_id, persona_id)

    # Step 4: memory.
    await delete_memories(user_id, persona_id)

    # Step 5: storage files.
    await delete_storage(user_id, persona_id)

    # Step 6: avatar file (best-effort; AvatarStore already swallows OSError).
    if persona and persona.get("profile_image"):
        try:
            AvatarStore().delete(persona["profile_image"])
        except Exception:
            _log.warning(
                "cascade_delete.avatar_failed user_id=%s persona_id=%s filename=%s",
                user_id, persona_id, persona["profile_image"],
            )

    # Step 7: persona doc itself.
    deleted = False
    if persona:
        deleted = await repo.delete(persona_id, user_id)

    _log.info(
        "cascade_delete.done user_id=%s persona_id=%s sessions=%d persona_deleted=%s",
        user_id, persona_id, len(session_ids), deleted,
    )
    return deleted
