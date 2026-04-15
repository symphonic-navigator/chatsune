"""Persona cascade-delete helper — shared between the DELETE handler and
the import rollback path.

Extracted so both call sites execute exactly the same cleanup sequence:

1. Collect session ids (for artefact cleanup — must happen BEFORE sessions
   are deleted, otherwise the artefact module cannot find them).
2. Snapshot pre-delete counts (memory split, message totals) so the
   cascade-delete report can show meaningful numbers.
3. Delete artefacts (per-session).
4. Delete chat sessions + messages.
5. Delete memory (journal entries + memory bodies).
6. Delete storage files (DB rows + physical blobs).
7. Delete avatar file if present.
8. Delete the persona document itself.

Every step uses the owning module's public API — no cross-module DB access.

The function is tolerant: each step is wrapped so that an exception is
recorded as a warning on the corresponding report step but never aborts
the cascade. The import-rollback path relies on this: if a partial import
only created some of these artefacts, we still want the rest of the
cleanup to run.

A "file does not exist" condition is NOT a warning — see
``BlobStore.delete`` and ``AvatarStore.delete`` which already treat a
missing file as a successful deletion.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from backend.database import get_db
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._repository import PersonaRepository
from shared.dtos.deletion import DeletionReportDto, DeletionStepDto

_log = logging.getLogger(__name__)


async def _safe_call(label: str, coro):
    """Run ``coro`` returning ``(value, warnings)``.

    Any exception is captured as a single warning string and the value
    falls back to ``None`` so callers can still build a report row.
    """
    try:
        return await coro, []
    except Exception as exc:  # noqa: BLE001 — tolerant cascade by design
        _log.warning("cascade_delete.step_failed label=%s error=%s", label, exc)
        return None, [f"{label} failed: {exc}"]


async def cascade_delete_persona(
    user_id: str, persona_id: str,
) -> tuple[bool, DeletionReportDto]:
    """Cascade-delete a persona and all data owned by it.

    Returns a ``(deleted, report)`` tuple where ``deleted`` is ``True`` if
    the persona document itself was removed and ``report`` is a structured
    summary of every cleanup step (counts + warnings) suitable for direct
    return to the client.
    """
    # Deferred imports to keep module import order clean and avoid
    # circular dependencies during app startup.
    from backend.modules.artefact import delete_all_for_sessions
    from backend.modules.chat import (
        count_messages_for_persona,
        delete_all_for_persona as delete_chats,
        list_session_ids_for_persona,
    )
    from backend.modules.memory import (
        count_for_persona as count_memory,
        delete_by_persona as delete_memories,
    )
    from backend.modules.storage import delete_by_persona_with_warnings

    repo = PersonaRepository(get_db())
    persona = await repo.find_by_id(persona_id, user_id)
    persona_name = (persona or {}).get("name") or "(unknown persona)"

    steps: list[DeletionStepDto] = []

    # Step 1: collect session ids BEFORE chat delete (artefact cleanup needs them).
    session_ids = await list_session_ids_for_persona(user_id, persona_id)

    # Step 2: snapshot pre-delete counts for the report (memory split, messages).
    memory_counts = await count_memory(user_id, persona_id)
    pre_message_count = await count_messages_for_persona(user_id, persona_id)

    # Step 3: artefacts (must happen before sessions are gone).
    artefact_count, art_warnings = (0, [])
    if session_ids:
        artefact_count, art_warnings = await _safe_call(
            "artefact deletion", delete_all_for_sessions(session_ids),
        )
    steps.append(DeletionStepDto(
        label="artefacts (incl. version history)",
        deleted_count=artefact_count or 0,
        warnings=art_warnings,
    ))

    # Step 4: chat sessions + messages.
    session_count, sess_warnings = await _safe_call(
        "chat session deletion", delete_chats(user_id, persona_id),
    )
    steps.append(DeletionStepDto(
        label="chat sessions",
        deleted_count=session_count or 0,
        warnings=sess_warnings,
    ))
    steps.append(DeletionStepDto(
        label="chat messages",
        deleted_count=pre_message_count if not sess_warnings else 0,
        warnings=[],
    ))

    # Step 5: memory — committed / uncommitted / bodies as separate report rows.
    _entries_deleted, mem_warnings = await _safe_call(
        "memory deletion", delete_memories(user_id, persona_id),
    )
    steps.append(DeletionStepDto(
        label="committed memory journal entries",
        deleted_count=memory_counts["committed"] if not mem_warnings else 0,
        warnings=[],
    ))
    steps.append(DeletionStepDto(
        label="uncommitted memory journal entries",
        deleted_count=memory_counts["uncommitted"] if not mem_warnings else 0,
        warnings=[],
    ))
    steps.append(DeletionStepDto(
        label="memory body versions",
        deleted_count=memory_counts["memory_bodies"] if not mem_warnings else 0,
        warnings=mem_warnings,
    ))

    # Step 6: storage files (DB rows + physical blobs).
    storage_result, storage_outer_warnings = await _safe_call(
        "uploaded files deletion",
        delete_by_persona_with_warnings(user_id, persona_id),
    )
    if storage_result is None:
        file_count, blob_warnings = 0, []
    else:
        file_count, blob_warnings = storage_result
    steps.append(DeletionStepDto(
        label="uploaded files",
        deleted_count=file_count,
        warnings=storage_outer_warnings + blob_warnings,
    ))

    # Step 7: avatar file (best-effort).
    avatar_warnings: list[str] = []
    avatar_deleted = 0
    if persona and persona.get("profile_image"):
        try:
            warning = AvatarStore().delete(persona["profile_image"])
            if warning:
                avatar_warnings.append(warning)
            else:
                avatar_deleted = 1
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "cascade_delete.avatar_failed user_id=%s persona_id=%s error=%s",
                user_id, persona_id, exc,
            )
            avatar_warnings.append(f"avatar deletion failed: {exc}")
    steps.append(DeletionStepDto(
        label="avatar file",
        deleted_count=avatar_deleted,
        warnings=avatar_warnings,
    ))

    # Step 8: persona doc itself.
    deleted = False
    persona_warnings: list[str] = []
    if persona:
        try:
            deleted = await repo.delete(persona_id, user_id)
        except Exception as exc:  # noqa: BLE001
            persona_warnings.append(f"persona document deletion failed: {exc}")
            _log.warning(
                "cascade_delete.persona_doc_failed user_id=%s persona_id=%s error=%s",
                user_id, persona_id, exc,
            )
    steps.append(DeletionStepDto(
        label="persona document",
        deleted_count=1 if deleted else 0,
        warnings=persona_warnings,
    ))

    report = DeletionReportDto(
        target_type="persona",
        target_id=persona_id,
        target_name=persona_name,
        success=deleted,
        steps=steps,
        timestamp=datetime.now(UTC),
    )

    _log.info(
        "cascade_delete.done user_id=%s persona_id=%s sessions=%d persona_deleted=%s warnings=%d",
        user_id, persona_id, len(session_ids), deleted, report.total_warnings,
    )
    return deleted, report
