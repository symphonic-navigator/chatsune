"""REST API endpoints for the memory page — journal, body, context, and triggers."""

import logging
from datetime import UTC, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session
from backend.jobs import JobType, submit
from backend.modules.chat._repository import ChatRepository
from backend.modules.memory._repository import MemoryRepository
from backend.modules.persona import get_persona as get_persona_fn
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.memory import (
    JournalEntryDto,
    MemoryBodyDto,
    MemoryBodyVersionDto,
    MemoryContextDto,
)
from shared.events.memory import (
    MemoryBodyRollbackEvent,
    MemoryEntryCommittedEvent,
    MemoryEntryDeletedEvent,
    MemoryEntryUpdatedEvent,
    MemoryExtractionStartedEvent,
    MemoryDreamStartedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory")

# Extraction cooldown: 30 minutes between runs, minimum 5 messages since last extraction
_EXTRACTION_COOLDOWN_SECONDS = 30 * 60
_EXTRACTION_MIN_MESSAGES = 5
_EXTRACTION_MESSAGE_COUNT = 20


def _memory_repo() -> MemoryRepository:
    return MemoryRepository(get_db())


def _chat_repo() -> ChatRepository:
    return ChatRepository(get_db())


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class UpdateEntryRequest(BaseModel):
    content: str


class CommitEntriesRequest(BaseModel):
    entry_ids: list[str]


class DeleteEntriesRequest(BaseModel):
    entry_ids: list[str]


class RollbackRequest(BaseModel):
    to_version: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_doc_to_dto(doc: dict) -> JournalEntryDto:
    return JournalEntryDto(
        id=doc["id"],
        persona_id=doc["persona_id"],
        content=doc["content"],
        category=doc.get("category"),
        state=doc["state"],
        is_correction=doc.get("is_correction", False),
        created_at=doc["created_at"],
        committed_at=doc.get("committed_at"),
        auto_committed=doc.get("auto_committed", False),
    )


def _body_doc_to_dto(doc: dict) -> MemoryBodyDto:
    return MemoryBodyDto(
        persona_id=doc["persona_id"],
        content=doc["content"],
        token_count=doc["token_count"],
        version=doc["version"],
        created_at=doc["created_at"],
    )


def _body_doc_to_version_dto(doc: dict) -> MemoryBodyVersionDto:
    return MemoryBodyVersionDto(
        version=doc["version"],
        token_count=doc["token_count"],
        entries_processed=doc.get("entries_processed", 0),
        created_at=doc["created_at"],
    )


# ---------------------------------------------------------------------------
# Journal Entries
# ---------------------------------------------------------------------------

@router.get("/{persona_id}/journal")
async def list_journal_entries(
    persona_id: str,
    state: str | None = Query(default=None),
    user: dict = Depends(require_active_session),
) -> list[JournalEntryDto]:
    repo = _memory_repo()
    docs = await repo.list_journal_entries(user["sub"], persona_id, state=state)
    return [_entry_doc_to_dto(d) for d in docs]


@router.patch("/{persona_id}/journal/{entry_id}")
async def update_journal_entry(
    persona_id: str,
    entry_id: str,
    body: UpdateEntryRequest,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> JournalEntryDto:
    repo = _memory_repo()
    updated = await repo.update_entry(entry_id, user["sub"], content=body.content)
    if not updated:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    # Re-fetch to return the updated entry
    entries = await repo.list_journal_entries(user["sub"], persona_id)
    entry_doc = next((e for e in entries if e["id"] == entry_id), None)
    if not entry_doc:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    dto = _entry_doc_to_dto(entry_doc)
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await event_bus.publish(
        Topics.MEMORY_ENTRY_UPDATED,
        MemoryEntryUpdatedEvent(
            entry=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return dto


@router.post("/{persona_id}/journal/commit")
async def commit_journal_entries(
    persona_id: str,
    body: CommitEntriesRequest,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    repo = _memory_repo()
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    committed_count = 0

    for entry_id in body.entry_ids:
        ok = await repo.commit_entry(entry_id, user["sub"])
        if ok:
            committed_count += 1
            # Re-fetch entry for the event
            entries = await repo.list_journal_entries(user["sub"], persona_id)
            entry_doc = next((e for e in entries if e["id"] == entry_id), None)
            if entry_doc:
                await event_bus.publish(
                    Topics.MEMORY_ENTRY_COMMITTED,
                    MemoryEntryCommittedEvent(
                        entry=_entry_doc_to_dto(entry_doc),
                        correlation_id=correlation_id,
                        timestamp=now,
                    ),
                    scope=f"persona:{persona_id}",
                    target_user_ids=[user["sub"]],
                    correlation_id=correlation_id,
                )

    return {"committed": committed_count}


@router.post("/{persona_id}/journal/delete")
async def delete_journal_entries(
    persona_id: str,
    body: DeleteEntriesRequest,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    repo = _memory_repo()
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    deleted_count = 0

    for entry_id in body.entry_ids:
        ok = await repo.delete_entry(entry_id, user["sub"])
        if ok:
            deleted_count += 1
            await event_bus.publish(
                Topics.MEMORY_ENTRY_DELETED,
                MemoryEntryDeletedEvent(
                    entry_id=entry_id,
                    persona_id=persona_id,
                    correlation_id=correlation_id,
                    timestamp=now,
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[user["sub"]],
                correlation_id=correlation_id,
            )

    return {"deleted": deleted_count}


# ---------------------------------------------------------------------------
# Memory Body
# ---------------------------------------------------------------------------

@router.get("/{persona_id}/body")
async def get_memory_body(
    persona_id: str,
    user: dict = Depends(require_active_session),
) -> MemoryBodyDto | None:
    repo = _memory_repo()
    doc = await repo.get_current_memory_body(user["sub"], persona_id)
    if not doc:
        return None
    return _body_doc_to_dto(doc)


@router.get("/{persona_id}/body/versions")
async def list_memory_body_versions(
    persona_id: str,
    user: dict = Depends(require_active_session),
) -> list[MemoryBodyVersionDto]:
    repo = _memory_repo()
    docs = await repo.list_memory_body_versions(user["sub"], persona_id)
    return [_body_doc_to_version_dto(d) for d in docs]


@router.get("/{persona_id}/body/versions/{version}")
async def get_memory_body_version(
    persona_id: str,
    version: int,
    user: dict = Depends(require_active_session),
) -> MemoryBodyDto:
    repo = _memory_repo()
    doc = await repo.get_memory_body_version(user["sub"], persona_id, version=version)
    if not doc:
        raise HTTPException(status_code=404, detail="Memory body version not found")
    return _body_doc_to_dto(doc)


@router.post("/{persona_id}/body/rollback")
async def rollback_memory_body(
    persona_id: str,
    body: RollbackRequest,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    repo = _memory_repo()
    try:
        new_version = await repo.rollback_memory_body(
            user["sub"], persona_id, to_version=body.to_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await event_bus.publish(
        Topics.MEMORY_BODY_ROLLBACK,
        MemoryBodyRollbackEvent(
            persona_id=persona_id,
            rolled_back_to_version=body.to_version,
            new_version=new_version,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"new_version": new_version}


# ---------------------------------------------------------------------------
# Context (for journal dropdown)
# ---------------------------------------------------------------------------

@router.get("/{persona_id}/context")
async def get_memory_context(
    persona_id: str,
    user: dict = Depends(require_active_session),
) -> MemoryContextDto:
    user_id = user["sub"]
    repo = _memory_repo()
    redis = get_redis()

    uncommitted_count = await repo.count_entries(user_id, persona_id, state="uncommitted")
    committed_count = await repo.count_entries(user_id, persona_id, state="committed")

    # Read extraction tracking state from Redis
    extraction_key = f"memory:extraction:{user_id}:{persona_id}"
    extraction_data = await redis.hgetall(extraction_key)

    last_extraction_at = None
    messages_since_extraction = 0
    if extraction_data:
        raw_ts = extraction_data.get("last_extraction_at")
        if raw_ts:
            try:
                last_extraction_at = datetime.fromisoformat(raw_ts)
            except (ValueError, TypeError):
                pass
        raw_count = extraction_data.get("messages_since_extraction")
        if raw_count:
            try:
                messages_since_extraction = int(raw_count)
            except (ValueError, TypeError):
                pass

    # Read dream tracking state from Redis
    dream_key = f"memory:dream:{user_id}:{persona_id}"
    dream_data = await redis.hgetall(dream_key)

    last_dream_at = None
    if dream_data:
        raw_ts = dream_data.get("last_dream_at")
        if raw_ts:
            try:
                last_dream_at = datetime.fromisoformat(raw_ts)
            except (ValueError, TypeError):
                pass

    # Determine whether extraction can be triggered:
    # 30 minutes since last extraction AND 5+ messages since
    can_trigger = messages_since_extraction >= _EXTRACTION_MIN_MESSAGES
    if can_trigger and last_extraction_at:
        elapsed = (datetime.now(UTC) - last_extraction_at.replace(tzinfo=UTC)).total_seconds()
        if elapsed < _EXTRACTION_COOLDOWN_SECONDS:
            can_trigger = False

    return MemoryContextDto(
        persona_id=persona_id,
        uncommitted_count=uncommitted_count,
        committed_count=committed_count,
        last_extraction_at=last_extraction_at,
        last_dream_at=last_dream_at,
        can_trigger_extraction=can_trigger,
    )


# ---------------------------------------------------------------------------
# Manual Triggers
# ---------------------------------------------------------------------------

@router.post("/{persona_id}/extract", status_code=202)
async def trigger_extraction(
    persona_id: str,
    user: dict = Depends(require_active_session),
) -> dict:
    user_id = user["sub"]

    # Verify persona exists and belongs to user
    persona = await get_persona_fn(persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    model_unique_id = persona.get("model_unique_id", "")

    # Fetch last 20 user messages from the most recent session for this persona
    chat_repo = _chat_repo()
    sessions = await chat_repo.list_sessions(user_id)
    persona_sessions = [s for s in sessions if s.get("persona_id") == persona_id]

    if not persona_sessions:
        raise HTTPException(status_code=400, detail="No chat sessions found for this persona")

    # Get messages from the latest session
    latest_session = persona_sessions[0]  # Already sorted by updated_at desc
    all_messages = await chat_repo.list_messages(latest_session["_id"])
    user_messages = [m for m in all_messages if m["role"] == "user"]
    recent_user_messages = user_messages[-_EXTRACTION_MESSAGE_COUNT:]

    if not recent_user_messages:
        raise HTTPException(status_code=400, detail="No user messages found in latest session")

    correlation_id = str(uuid4())

    await submit(
        job_type=JobType.MEMORY_EXTRACTION,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload={
            "persona_id": persona_id,
            "session_id": latest_session["_id"],
            "messages": [
                {"role": m["role"], "content": m["content"]}
                for m in recent_user_messages
            ],
        },
        correlation_id=correlation_id,
    )

    _log.info(
        "Manual extraction triggered for persona=%s user=%s correlation=%s",
        persona_id, user_id, correlation_id,
    )

    return {"status": "submitted", "correlation_id": correlation_id}


@router.post("/{persona_id}/dream", status_code=202)
async def trigger_dream(
    persona_id: str,
    user: dict = Depends(require_active_session),
) -> dict:
    user_id = user["sub"]

    # Verify persona exists and belongs to user
    persona = await get_persona_fn(persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    model_unique_id = persona.get("model_unique_id", "")

    # Verify committed entries exist
    repo = _memory_repo()
    committed_count = await repo.count_entries(user_id, persona_id, state="committed")
    if committed_count == 0:
        raise HTTPException(status_code=400, detail="No committed journal entries to consolidate")

    correlation_id = str(uuid4())

    await submit(
        job_type=JobType.MEMORY_CONSOLIDATION,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload={
            "persona_id": persona_id,
        },
        correlation_id=correlation_id,
    )

    _log.info(
        "Manual dream triggered for persona=%s user=%s committed_entries=%d correlation=%s",
        persona_id, user_id, committed_count, correlation_id,
    )

    return {"status": "submitted", "correlation_id": correlation_id}
