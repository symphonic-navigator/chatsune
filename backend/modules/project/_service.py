"""Project orchestration service.

Business logic that needs to talk to other modules' public APIs lives
here, so the project module's ``__init__.py`` stays a thin facade and
``_handlers.py`` stays focused on HTTP concerns.

Strict module-boundary rule: this file imports only from other modules'
``__init__.py`` (their public API). It must never reach into another
module's ``_repository.py`` / ``_handlers.py`` / ``_models.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.database import get_db
from backend.modules.project._repository import ProjectRepository
from shared.dtos.project import ProjectUsageDto
from shared.events.chat import ChatSessionProjectUpdatedEvent
from shared.events.project import ProjectDeletedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def get_usage_counts(project_id: str, user_id: str) -> ProjectUsageDto:
    """Aggregate usage counts for a project across the four owning modules.

    Used by ``GET /api/projects/{id}?include_usage=true`` so the
    delete-modal can show how many chats / uploads / artefacts /
    images would be affected by a full-purge. The lookup is cheap —
    each module's count is a single ``count_documents`` (or an in-
    memory filter for artefacts) — and is intentionally not cached:
    the modal only opens after a deliberate user action and the
    counts must be live.
    """
    # Deferred imports keep startup-time module graphs simple and
    # prove every cross-module call goes through public APIs.
    from backend.modules import artefact as artefact_service
    from backend.modules import chat as chat_service
    from backend.modules import images as images_service
    from backend.modules import storage as storage_service

    session_ids = await chat_service.list_session_ids_for_project(
        project_id, user_id,
    )
    if not session_ids:
        return ProjectUsageDto()
    return ProjectUsageDto(
        chat_count=len(session_ids),
        upload_count=await storage_service.count_for_sessions(
            session_ids, user_id,
        ),
        artefact_count=await artefact_service.count_for_sessions(
            session_ids, user_id,
        ),
        image_count=await images_service.count_for_sessions(
            session_ids, user_id,
        ),
    )


async def cascade_delete_project(
    project_id: str,
    user_id: str,
    *,
    purge_data: bool,
) -> bool:
    """Delete a project plus its dependent state.

    Two modes (per spec §9):

    - ``purge_data=False`` (safe-delete, the default UI choice) — every
      session belonging to the project has its ``project_id`` cleared so
      it returns to the global history; persona defaults pointing at this
      project are cleared; the project document is removed.

    - ``purge_data=True`` (full-purge, the explicit-checkbox variant) —
      every session belonging to the project is soft-deleted (the
      existing chat cleanup job hard-deletes it plus its messages,
      attachments, artefacts, and images an hour later); persona
      defaults are still cleared; the project document is removed.

    Returns ``True`` iff the project document existed and was removed.
    A missing/foreign project is a no-op so callers can be idempotent.

    Emits ``PROJECT_DELETED`` once at the end. The safe-delete branch
    additionally emits one ``CHAT_SESSION_PROJECT_UPDATED`` per detached
    session — ``set_session_project`` is event-free by design (the HTTP
    PATCH handler emits the event), so the cascade has to mirror that
    behaviour explicitly to keep the sidebar / HistoryTab live.
    """
    # Deferred imports keep startup-time module graphs simple and prove
    # we go through public APIs only.
    from backend.modules import chat as chat_service
    from backend.modules import persona as persona_service
    from backend.ws.event_bus import get_event_bus

    repo = ProjectRepository(get_db())
    project = await repo.find_by_id(project_id, user_id)
    if project is None:
        _log.info(
            "project.cascade_delete.skip project_id=%s user_id=%s "
            "reason=not_found_or_foreign",
            project_id, user_id,
        )
        return False

    session_ids = await chat_service.list_session_ids_for_project(
        project_id, user_id,
    )

    if purge_data:
        for sid in session_ids:
            await chat_service.delete_session(sid, user_id)
    else:
        event_bus = get_event_bus()
        for sid in session_ids:
            await chat_service.set_session_project(sid, user_id, None)
            await event_bus.publish(
                Topics.CHAT_SESSION_PROJECT_UPDATED,
                ChatSessionProjectUpdatedEvent(
                    session_id=sid,
                    project_id=None,
                    user_id=user_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"session:{sid}",
                target_user_ids=[user_id],
            )

    affected_personas = await persona_service.clear_default_project_for_all(
        user_id, project_id,
    )

    deleted = await repo.delete(project_id, user_id)

    _log.info(
        "project.cascade_delete.done project_id=%s user_id=%s "
        "purge_data=%s sessions_processed=%d personas_cleared=%d "
        "project_deleted=%s",
        project_id, user_id, purge_data, len(session_ids),
        len(affected_personas), deleted,
    )

    if deleted:
        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.PROJECT_DELETED,
            ProjectDeletedEvent(
                project_id=project_id,
                user_id=user_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"user:{user_id}",
            target_user_ids=[user_id],
        )

    return deleted
