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
from shared.events.project import ProjectDeletedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


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

    Emits ``PROJECT_DELETED`` once at the end. Per-session and per-persona
    events from the safe-delete branch will be added in Phase 3 alongside
    the in-chat switcher and persona overview surfaces — they are not
    required for the project cascade itself to function correctly.
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
        for sid in session_ids:
            await chat_service.set_session_project(sid, user_id, None)

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
