from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.chat._repository import ChatRepository
from backend.modules.persona._repository import PersonaRepository

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
    return ChatRepository.session_to_dto(doc)


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
    return {"status": "ok"}
