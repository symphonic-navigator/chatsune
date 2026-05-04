from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_db
from backend.dependencies import require_active_session
from shared.dtos.chat import ChatMessagesBundleDto, SessionProjectUpdateDto
from shared.dtos.knowledge import SetKnowledgeLibrariesRequest
from backend.jobs import submit, JobType
from backend.modules.chat._repository import ChatRepository
from backend.modules.chat._toggle_defaults import compute_persona_toggle_defaults
from backend.modules.knowledge import verify_libraries_owned
from backend.modules.persona import get_persona as get_persona_fn
from backend.modules.persona import bump_last_used as bump_persona_last_used
from backend.ws.event_bus import get_event_bus
from backend.modules.tools import get_all_groups
from shared.events.chat import (
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionPinnedUpdatedEvent,
    ChatSessionProjectUpdatedEvent,
    ChatSessionRestoredEvent,
    ChatSessionTitleUpdatedEvent,
    ChatSessionTogglesUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/chat")


def _chat_repo() -> ChatRepository:
    return ChatRepository(get_db())


class CreateSessionRequest(BaseModel):
    persona_id: str
    # Mindspace: when the persona has a default project AND the trigger
    # is neutral (sidebar pin, persona overlay "New chat", PersonasTab
    # "Start chat"), the frontend forwards the persona's
    # ``default_project_id`` so the new session lands inside that
    # project from the very first turn. Optional and nullable —
    # context-bound triggers (project-detail-overlay) keep using the
    # subsequent ``PATCH /sessions/{id}/project`` flow.
    project_id: str | None = None


@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(require_active_session),
):
    persona = await get_persona_fn(body.persona_id, user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    repo = _chat_repo()

    # Clean up previous empty sessions for the same user+persona
    stale_ids = await repo.find_empty_sessions(
        user_id=user["sub"], persona_id=persona["_id"],
    )

    toggle_defaults = compute_persona_toggle_defaults(persona)
    doc = await repo.create_session(
        user_id=user["sub"],
        persona_id=persona["_id"],
        tools_enabled=toggle_defaults["tools_enabled"],
        auto_read=toggle_defaults["auto_read"],
        project_id=body.project_id,
    )
    dto = ChatRepository.session_to_dto(doc)

    try:
        await bump_persona_last_used(persona["_id"], user["sub"])
    except Exception as exc:  # pragma: no cover - logged, never raised
        import structlog
        structlog.get_logger().warning(
            "persona_last_used_bump_failed",
            persona_id=persona["_id"],
            user_id=user["sub"],
            error=str(exc),
        )

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()

    # Emit delete events for cleaned-up empty sessions
    if stale_ids:
        await repo.delete_sessions_by_ids(stale_ids)
        for stale_id in stale_ids:
            await event_bus.publish(
                Topics.CHAT_SESSION_DELETED,
                ChatSessionDeletedEvent(
                    session_id=stale_id,
                    correlation_id=correlation_id,
                    timestamp=now,
                ),
                scope=f"session:{stale_id}",
                target_user_ids=[user["sub"]],
                correlation_id=correlation_id,
            )

    await event_bus.publish(
        Topics.CHAT_SESSION_CREATED,
        ChatSessionCreatedEvent(
            session_id=dto.id,
            user_id=dto.user_id,
            persona_id=dto.persona_id,
            title=dto.title,
            created_at=dto.created_at,
            updated_at=dto.updated_at,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{dto.id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return dto


@router.get("/sessions")
async def list_sessions(
    project_id: str | None = Query(default=None),
    include_project_chats: bool = Query(default=False),
    user: dict = Depends(require_active_session),
):
    """List the user's chat sessions.

    Mindspace:
      - Default behaviour (no params) excludes project-bound sessions
        — the Sidebar / global HistoryTab show only out-of-project
        chats, matching the pre-Mindspace experience.
      - ``include_project_chats=true`` returns every session including
        project-bound ones. Used by the UserModal HistoryTab "Include
        project chats" toggle.
      - ``project_id=<id>`` returns only sessions belonging to that
        project (and ignores ``include_project_chats``). Used by the
        Project-Detail-Overlay Chats tab.
    """
    repo = _chat_repo()
    if project_id is not None:
        docs = await repo.list_sessions_for_project(user["sub"], project_id)
    else:
        docs = await repo.list_sessions(
            user["sub"], exclude_in_projects=not include_project_chats,
        )
    return [ChatRepository.session_to_dto(d) for d in docs]


@router.get("/sessions/search")
async def search_sessions(
    q: str = Query(min_length=1, max_length=200, strip_whitespace=True),
    persona_id: str | None = Query(default=None),
    exclude_persona_ids: str | None = Query(default=None),
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    excluded = (
        [pid.strip() for pid in exclude_persona_ids.split(",") if pid.strip()]
        if exclude_persona_ids
        else None
    )
    docs = await repo.search_sessions(
        user_id=user["sub"],
        query=q,
        persona_id=persona_id,
        exclude_persona_ids=excluded,
    )
    return [ChatRepository.session_to_dto(d) for d in docs]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    doc = await repo.get_session(session_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found")
    return ChatRepository.session_to_dto(doc)


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str, user: dict = Depends(require_active_session),
) -> ChatMessagesBundleDto:
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await repo.list_messages(session_id)
    # Back-fill thumbnail_b64 on image_refs from older messages that were
    # persisted before the inline-base64 path landed. Silent no-op when
    # ImageService isn't initialised (script contexts) or no refs need it.
    try:
        from backend.modules.images import get_image_service
        await get_image_service().enrich_image_refs_in_messages(
            user_id=user["sub"], messages=messages,
        )
    except RuntimeError:
        pass
    return ChatMessagesBundleDto(
        messages=[ChatRepository.message_to_dto(m) for m in messages],
        context_status=session.get("context_status", "green"),
        context_fill_percentage=float(session.get("context_fill_percentage", 0.0)),
        context_used_tokens=int(session.get("context_used_tokens", 0)),
        context_max_tokens=int(session.get("context_max_tokens", 0)),
    )


@router.get("/sessions/{session_id}/knowledge")
async def get_session_knowledge(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"library_ids": session.get("knowledge_library_ids", [])}


@router.put("/sessions/{session_id}/knowledge")
async def set_session_knowledge(
    session_id: str,
    body: SetKnowledgeLibrariesRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not await verify_libraries_owned(user["sub"], body.library_ids):
        raise HTTPException(status_code=404, detail="Library not found")

    old_ids = set(session.get("knowledge_library_ids") or [])
    new_ids = set(body.library_ids)

    await repo.update_session_knowledge_library_ids(session_id, body.library_ids)

    attached = new_ids - old_ids
    detached = old_ids - new_ids
    if attached or detached:
        from shared.events.knowledge import (
            LibraryAttachedToSessionEvent,
            LibraryDetachedFromSessionEvent,
        )
        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()
        for lib_id in attached:
            await event_bus.publish(
                Topics.LIBRARY_ATTACHED_TO_SESSION,
                LibraryAttachedToSessionEvent(
                    session_id=session_id,
                    library_id=lib_id,
                    correlation_id=correlation_id,
                    timestamp=now,
                ),
                scope=f"session:{session_id}",
                target_user_ids=[user["sub"]],
                correlation_id=correlation_id,
            )
        for lib_id in detached:
            await event_bus.publish(
                Topics.LIBRARY_DETACHED_FROM_SESSION,
                LibraryDetachedFromSessionEvent(
                    session_id=session_id,
                    library_id=lib_id,
                    correlation_id=correlation_id,
                    timestamp=now,
                ),
                scope=f"session:{session_id}",
                target_user_ids=[user["sub"]],
                correlation_id=correlation_id,
            )

    return {"status": "ok"}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    deleted = await repo.soft_delete_session(session_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_DELETED,
        ChatSessionDeletedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"status": "ok"}


@router.post("/sessions/{session_id}/restore")
async def restore_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    doc = await repo.restore_session(session_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found or not deleted")

    dto = ChatRepository.session_to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_RESTORED,
        ChatSessionRestoredEvent(
            session_id=dto.id,
            session=dto.model_dump(mode="json"),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{dto.id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"status": "ok"}


@router.post("/sessions/{session_id}/resume", status_code=204)
async def resume_session(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    """Bump the session's persona last_used_at. No-op if session missing.

    Fire-and-forget from the frontend: opening any /chat/{persona}/{session}
    route hits this once. Failures are logged and never returned as 5xx
    so a sidebar-LRU error cannot break chat load.
    """
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        return
    try:
        await bump_persona_last_used(session["persona_id"], user["sub"])
    except Exception as exc:  # pragma: no cover - logged, never raised
        import structlog
        structlog.get_logger().warning(
            "persona_last_used_bump_failed",
            persona_id=session["persona_id"],
            user_id=user["sub"],
            session_id=session_id,
            error=str(exc),
        )


class UpdateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200, strip_whitespace=True)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update_session_title(session_id, body.title)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_TITLE_UPDATED,
        ChatSessionTitleUpdatedEvent(
            session_id=session_id,
            title=body.title,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    doc = await repo.get_session(session_id, user["sub"])
    return ChatRepository.session_to_dto(doc)


class UpdateSessionPinnedRequest(BaseModel):
    pinned: bool


@router.patch("/sessions/{session_id}/pinned")
async def update_session_pinned(
    session_id: str,
    body: UpdateSessionPinnedRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update_session_pinned(session_id, body.pinned)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_PINNED_UPDATED,
        ChatSessionPinnedUpdatedEvent(
            session_id=session_id,
            pinned=body.pinned,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    doc = await repo.get_session(session_id, user["sub"])
    return ChatRepository.session_to_dto(doc)


@router.patch("/sessions/{session_id}/project")
async def update_session_project(
    session_id: str,
    body: SessionProjectUpdateDto,
    user: dict = Depends(require_active_session),
):
    """Mindspace: assign or clear a session's owning project.

    Body: ``{"project_id": "<id>"}`` to assign, ``{"project_id": null}``
    to detach (returns the session to the global history bucket). The
    HTTP method is PATCH because only the project field changes; other
    session attributes are untouched.

    Emits ``CHAT_SESSION_PROJECT_UPDATED`` carrying the new
    ``project_id`` so the sidebar / HistoryTab can re-classify the
    session live without a follow-up GET.
    """
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.set_session_project(session_id, user["sub"], body.project_id)

    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_PROJECT_UPDATED,
        ChatSessionProjectUpdatedEvent(
            session_id=session_id,
            project_id=body.project_id,
            user_id=user["sub"],
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
    )

    doc = await repo.get_session(session_id, user["sub"])
    return ChatRepository.session_to_dto(doc)


@router.post("/sessions/{session_id}/generate-title", status_code=202)
async def generate_title(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await repo.list_messages(session_id)
    if len(messages) < 2:
        raise HTTPException(status_code=400, detail="Session needs at least 2 messages")

    first_user = next((m for m in messages if m["role"] == "user"), None)
    first_assistant = next((m for m in messages if m["role"] == "assistant"), None)
    if not first_user or not first_assistant:
        raise HTTPException(status_code=400, detail="Session needs at least one user and one assistant message")

    persona = await get_persona_fn(session["persona_id"], user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    model_unique_id = persona.get("model_unique_id", "")
    correlation_id = str(uuid4())

    await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id=user["sub"],
        model_unique_id=model_unique_id,
        payload={
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": first_user["content"]},
                {"role": "assistant", "content": first_assistant["content"]},
            ],
        },
        correlation_id=correlation_id,
    )

    return {"status": "submitted"}


class UpdateSessionReasoningRequest(BaseModel):
    reasoning_override: bool | None = None


@router.patch("/sessions/{session_id}/reasoning")
async def update_session_reasoning(
    session_id: str,
    body: UpdateSessionReasoningRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update_session_reasoning_override(
        session_id, body.reasoning_override,
    )

    doc = await repo.get_session(session_id, user["sub"])
    return ChatRepository.session_to_dto(doc)


class UpdateSessionTogglesRequest(BaseModel):
    tools_enabled: bool | None = None
    auto_read: bool | None = None


@router.patch("/sessions/{session_id}/toggles")
async def update_session_toggles(
    session_id: str,
    body: UpdateSessionTogglesRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.tools_enabled is not None:
        session = await repo.update_session_tools_enabled(session_id, body.tools_enabled)
    if body.auto_read is not None:
        session = await repo.update_session_auto_read(session_id, body.auto_read)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_TOGGLES_UPDATED,
        ChatSessionTogglesUpdatedEvent(
            session_id=session_id,
            tools_enabled=session.get("tools_enabled", False),
            auto_read=session.get("auto_read", False),
            reasoning_override=session.get("reasoning_override"),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    doc = await repo.get_session(session_id, user["sub"])
    return ChatRepository.session_to_dto(doc)


@router.get("/tools")
async def list_tool_groups(user: dict = Depends(require_active_session)):
    """Return all available tool groups for the frontend."""
    return await get_all_groups(user_id=user["sub"])
