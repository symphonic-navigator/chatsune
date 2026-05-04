"""Knowledge-library cascade-delete helper.

Mirrors ``backend/modules/persona/_cascade.py``: a single function that
performs every cleanup step a library deletion implies and returns a
structured ``DeletionReportDto`` so the user gets a transparent summary.

Steps:

1. Snapshot the library doc (for the human-readable target name).
2. Cascade-delete documents and chunks (incl. vector embeddings) via the
   knowledge repository's existing cascade logic.
3. Pull this library's id from every persona's ``knowledge_library_ids``
   array — n:m link cleanup, persona docs themselves are NEVER deleted.
4. Pull this library's id from every chat session's
   ``knowledge_library_ids`` array — same n:m semantics.

Cross-module reference cleanup goes through the **public APIs** of the
persona and chat modules so module boundaries stay intact.

Tolerance contract (same as persona cascade): every step is wrapped so
exceptions become warnings on the corresponding report row but never
abort the cascade.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from backend.database import get_db
from backend.modules.knowledge._repository import KnowledgeRepository
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
        _log.warning(
            "cascade_delete_library.step_failed label=%s error=%s", label, exc,
        )
        return None, [f"{label} failed: {exc}"]


async def cascade_delete_library(
    user_id: str, library_id: str,
) -> tuple[bool, DeletionReportDto]:
    """Cascade-delete a knowledge library and clean up all back-references.

    Returns ``(deleted, report)`` where ``deleted`` is ``True`` if the
    library document itself was removed and ``report`` is a structured
    summary of every cleanup step.
    """
    # Deferred imports to avoid circular dependencies during app startup
    # and to ensure we always go through the owning modules' public APIs.
    from backend.modules.chat import remove_library_from_all_sessions
    from backend.modules.persona import remove_library_from_all_personas
    from backend.modules.project import remove_library_from_all_projects

    repo = KnowledgeRepository(get_db())
    library = await repo.get_library(library_id, user_id)
    library_name = (library or {}).get("name") or "(unknown library)"

    steps: list[DeletionStepDto] = []

    # Step 1: documents + chunks (incl. vector embeddings).
    cascade_result, cascade_warnings = await _safe_call(
        "library cascade",
        repo.delete_library_with_counts(library_id, user_id),
    )
    documents_deleted = (cascade_result or {}).get("documents_deleted", 0)
    chunks_deleted = (cascade_result or {}).get("chunks_deleted", 0)
    library_deleted = (cascade_result or {}).get("library_deleted", False)

    steps.append(DeletionStepDto(
        label="documents",
        deleted_count=documents_deleted,
        warnings=[],
    ))
    steps.append(DeletionStepDto(
        label="chunks (incl. vector embeddings)",
        deleted_count=chunks_deleted,
        warnings=[],
    ))

    # Step 2: persona n:m link cleanup.
    persona_links_removed, persona_warnings = await _safe_call(
        "persona reference cleanup",
        remove_library_from_all_personas(user_id, library_id),
    )
    steps.append(DeletionStepDto(
        label="persona references unlinked",
        deleted_count=persona_links_removed or 0,
        warnings=persona_warnings,
    ))

    # Step 3: chat-session n:m link cleanup.
    session_links_removed, session_warnings = await _safe_call(
        "chat session reference cleanup",
        remove_library_from_all_sessions(user_id, library_id),
    )
    steps.append(DeletionStepDto(
        label="chat session references unlinked",
        deleted_count=session_links_removed or 0,
        warnings=session_warnings,
    ))

    # Step 4: project n:m link cleanup (Mindspace).
    # User-scoped to mirror ``remove_library_from_all_personas``: the
    # cascade only ever has authority over ``user_id``'s documents, so
    # the update-many is bounded accordingly.
    project_links_removed, project_warnings = await _safe_call(
        "project reference cleanup",
        remove_library_from_all_projects(user_id, library_id),
    )
    steps.append(DeletionStepDto(
        label="project references unlinked",
        deleted_count=project_links_removed or 0,
        warnings=project_warnings,
    ))

    # Step 5: report the library document itself.
    steps.append(DeletionStepDto(
        label="library document",
        deleted_count=1 if library_deleted else 0,
        warnings=cascade_warnings,
    ))

    report = DeletionReportDto(
        target_type="knowledge_library",
        target_id=library_id,
        target_name=library_name,
        success=library_deleted,
        steps=steps,
        timestamp=datetime.now(UTC),
    )

    _log.info(
        "cascade_delete_library.done user_id=%s library_id=%s "
        "documents=%d chunks=%d persona_refs=%d session_refs=%d "
        "project_refs=%d library_deleted=%s warnings=%d",
        user_id, library_id, documents_deleted, chunks_deleted,
        persona_links_removed or 0, session_links_removed or 0,
        project_links_removed or 0, library_deleted, report.total_warnings,
    )
    return library_deleted, report
