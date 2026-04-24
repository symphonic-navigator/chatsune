from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_db
from backend.dependencies import require_active_session
from shared.dtos.chat import ChatMessagesBundleDto
from shared.dtos.knowledge import SetKnowledgeLibrariesRequest
from backend.jobs import submit, JobType
from backend.modules.chat._repository import ChatRepository
from backend.modules.persona import get_persona as get_persona_fn
from backend.ws.event_bus import get_event_bus
from backend.modules.tools import get_all_groups
from shared.events.chat import (
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionPinnedUpdatedEvent,
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

    doc = await repo.create_session(
        user_id=user["sub"],
        persona_id=persona["_id"],
    )
    dto = ChatRepository.session_to_dto(doc)

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
async def list_sessions(user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    docs = await repo.list_sessions(user["sub"])
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
    await repo.update_session_knowledge_library_ids(session_id, body.library_ids)
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
    return get_all_groups()
