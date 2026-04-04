from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.jobs import submit, JobType
from backend.modules.chat._repository import ChatRepository
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import get_event_bus
from shared.events.chat import (
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionTitleUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/chat")


def _chat_repo() -> ChatRepository:
    return ChatRepository(get_db())


def _persona_repo() -> PersonaRepository:
    return PersonaRepository(get_db())


class CreateSessionRequest(BaseModel):
    persona_id: str


@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(require_active_session),
):
    persona_repo = _persona_repo()
    persona = await persona_repo.find_by_id(body.persona_id, user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    repo = _chat_repo()
    doc = await repo.create_session(
        user_id=user["sub"],
        persona_id=persona["_id"],
        model_unique_id=persona["model_unique_id"],
    )
    dto = ChatRepository.session_to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_CREATED,
        ChatSessionCreatedEvent(
            session_id=dto.id,
            user_id=dto.user_id,
            persona_id=dto.persona_id,
            model_unique_id=dto.model_unique_id,
            title=dto.title,
            created_at=dto.created_at.isoformat(),
            updated_at=dto.updated_at.isoformat(),
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


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    doc = await repo.get_session(session_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found")
    return ChatRepository.session_to_dto(doc)


@router.get("/sessions/{session_id}/messages")
async def list_messages(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await repo.list_messages(session_id)
    return [ChatRepository.message_to_dto(m) for m in messages]


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    deleted = await repo.delete_session(session_id, user["sub"])
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


class UpdateSessionRequest(BaseModel):
    title: str


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

    model_unique_id = session.get("model_unique_id", "")
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
