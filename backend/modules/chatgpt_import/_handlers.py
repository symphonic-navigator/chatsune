"""REST API for /api/chatgpt-import/*."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.jobs._dedup import (
    memory_extraction_slot_key,
    release_inflight_slot,
)
from backend.modules.chatgpt_import._memory_batch_repository import (
    ChatGptImportMemoryBatchRepository,
)
from backend.modules.chatgpt_import._service import (
    ChatGptImportService,
    ImportConflictError,
    ImportNotFoundError,
)
from backend.modules.persona import get_persona
from backend.modules.persona._repository import PersonaRepository
from shared.dtos.chatgpt_import import (
    ConversationItemDto,
    ImportDto,
    ImportTriggerJobInfo,
    ImportTriggerRequest,
    ImportTriggerResponse,
    MemoryBatchDiscardRequest,
    MemoryBatchDto,
    MemoryBatchPausedAtDto,
    MemoryBatchResumeRequest,
    UploadResponse,
)
from shared.events.chatgpt_import import ChatGptImportMemoryBatchDoneEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chatgpt-import")

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _service() -> ChatGptImportService:
    return ChatGptImportService(get_db())


@router.post("/uploads", status_code=201, response_model=UploadResponse)
async def upload(
    request: Request,
    filename: str = Query(default="conversations.json"),
    replace: bool = Query(default=False),
    user: dict = Depends(require_active_session),
) -> UploadResponse:
    """Stream-upload a ChatGPT conversations.json export.

    The body is streamed straight to a temp file (no buffer in RAM) and
    hashed on the fly so we can dedupe duplicate uploads of the same file.
    The actual parsing is queued as a background job.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="File too large")
        except ValueError:
            pass

    user_id = user["sub"]
    service = _service()
    try:
        import_id, duplicate = await service.upload_streaming(
            user_id=user_id,
            stream=request.stream(),
            filename=filename,
            replace_existing=replace,
        )
    except ImportConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "existing_import_id": exc.existing_import_id,
            },
        )
    status_text = "ready" if duplicate else "parsing"
    return UploadResponse(
        import_id=import_id,
        status=status_text,
        duplicate=duplicate,
    )


@router.get("/uploads/active", response_model=ImportDto | None)
async def get_active(
    user: dict = Depends(require_active_session),
) -> ImportDto | None:
    return await _service().get_active_import_dto(user_id=user["sub"])


@router.delete("/uploads/{import_id}", status_code=204)
async def delete_active(
    import_id: str,
    user: dict = Depends(require_active_session),
) -> None:
    try:
        await _service().delete_import(user_id=user["sub"], import_id=import_id)
    except ImportNotFoundError:
        raise HTTPException(status_code=404, detail="Import not found")


@router.get(
    "/uploads/{import_id}/conversations",
    response_model=list[ConversationItemDto],
)
async def list_conversations(
    import_id: str,
    title_search: str | None = Query(default=None),
    sort: str = Query(default="create_time_desc"),
    user: dict = Depends(require_active_session),
) -> list[ConversationItemDto]:
    """List the parsed conversations under an import, with persona-name lookup.

    The persona-name map is built once per request so the badges in the UI
    can render "imported into <name>" without a separate fetch per row.
    """
    user_id = user["sub"]
    # Build persona-name map locally. The persona module exposes get_persona
    # but no list-all helper that returns names; we read the collection via
    # the repository to keep this O(1) round-trip rather than per-conversation.
    persona_repo = PersonaRepository(get_db())
    persona_docs = await persona_repo.list_for_user(user_id)
    persona_names = {p["_id"]: p.get("name", "") for p in persona_docs}

    return await _service().list_conversations_for_ui(
        user_id=user_id,
        import_id=import_id,
        persona_names=persona_names,
        title_search=title_search,
        sort=sort,
    )


@router.post(
    "/uploads/{import_id}/import",
    response_model=ImportTriggerResponse,
    status_code=202,
)
async def trigger_import(
    import_id: str,
    body: ImportTriggerRequest,
    user: dict = Depends(require_active_session),
) -> ImportTriggerResponse:
    """Queue per-conversation import jobs into the given persona."""
    user_id = user["sub"]
    persona = await get_persona(body.persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    if not body.chatgpt_conversation_ids:
        raise HTTPException(status_code=400, detail="No conversations selected")

    from backend.modules.chatgpt_import._memory_batch_repository import (
        BatchInProgressError,
    )
    try:
        correlation_id, job_pairs = await _service().trigger_conversation_imports(
            user_id=user_id,
            import_id=import_id,
            persona_id=body.persona_id,
            chatgpt_conversation_ids=body.chatgpt_conversation_ids,
        )
    except BatchInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A memory-extraction batch is already in progress for this "
                f"persona (state={exc.current_state}). Wait for it to finish "
                f"or discard it before importing more conversations."
            ),
        ) from exc
    return ImportTriggerResponse(
        correlation_id=correlation_id,
        jobs=[
            ImportTriggerJobInfo(chatgpt_conversation_id=cid, job_id=jid)
            for cid, jid in job_pairs
        ],
    )


# --- Memory-batch endpoints ------------------------------------------------


def _batch_doc_to_dto(doc: dict) -> MemoryBatchDto:
    """Map a raw batch document to its public DTO shape."""
    paused_at_raw = doc.get("paused_at")
    paused_at_dto: MemoryBatchPausedAtDto | None = None
    if paused_at_raw:
        paused_at_dto = MemoryBatchPausedAtDto(
            session_index=int(paused_at_raw["session_index"]),
            session_id=paused_at_raw["session_id"],
            reason=paused_at_raw["reason"],
            user_message=paused_at_raw["user_message"],
            detail=paused_at_raw.get("detail"),
            at=paused_at_raw["at"],
        )
    return MemoryBatchDto(
        import_id=doc["import_id"],
        persona_id=doc["persona_id"],
        state=doc["state"],
        target_count=int(doc.get("target_count", 0)),
        conversations_imported=int(doc.get("conversations_imported", 0)),
        permanent_failures=int(doc.get("permanent_failures", 0)),
        session_ids=list(doc.get("session_ids") or []),
        paused_at=paused_at_dto,
        total_entries_created=int(doc.get("total_entries_created", 0)),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post(
    "/uploads/{import_id}/memory_batch/resume",
    response_model=MemoryBatchDto,
    status_code=202,
)
async def resume_memory_batch(
    import_id: str,
    body: MemoryBatchResumeRequest,
    user: dict = Depends(require_active_session),
) -> MemoryBatchDto:
    """Re-submit a paused memory-extraction batch.

    409 if the batch is not in ``paused`` state. ``force_budget=true``
    propagates into the job payload so the batch handler skips the
    daily-budget gate inside the extraction core. The override is one-
    shot; it is **not** persisted as a user preference.
    """
    user_id = user["sub"]
    persona = await get_persona(body.persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    batch_repo = ChatGptImportMemoryBatchRepository(get_db())
    batch = await batch_repo.get(import_id, body.persona_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.get("user_id") != user_id:
        # Defence-in-depth: even though ownership is implicit via
        # require_active_session + persona ownership, also confirm the
        # batch row's user matches.
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["state"] != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"Batch is not paused (state={batch['state']})",
        )

    claimed = await batch_repo.claim_resume(
        import_id=import_id, persona_id=body.persona_id,
    )
    if claimed is None:
        # Lost a race with another resume / discard. Re-read for the
        # error response so the client sees the current state.
        current = await batch_repo.get(import_id, body.persona_id)
        raise HTTPException(
            status_code=409,
            detail=f"Batch state changed (state={current['state'] if current else 'unknown'})",
        )

    # Release the held slot before submitting. While paused we keep the
    # slot held with a 7-day TTL to gate live-flow extraction, but the
    # incoming batch job will try to re-acquire via SET NX — that fails
    # if the key is still there. Releasing here closes that window;
    # the batch handler re-acquires cleanly on its next run.
    from backend.database import get_redis

    redis = get_redis()
    try:
        await release_inflight_slot(
            redis,
            memory_extraction_slot_key(user_id, body.persona_id),
        )
    except Exception:
        _log.exception(
            "chatgpt_import.memory.batch.resume.slot_release_failed",
            extra={"user_id": user_id, "persona_id": body.persona_id},
        )

    from backend.jobs import submit
    from backend.jobs._models import JobType

    await submit(
        JobType.CHATGPT_IMPORT_MEMORY_BATCH,
        user_id=user_id,
        model_unique_id=claimed["model_unique_id"],
        payload={
            "import_id": import_id,
            "persona_id": body.persona_id,
            "force_budget": body.force_budget,
        },
        correlation_id=f"memory-batch-resume-{import_id}-{body.persona_id}",
    )
    return _batch_doc_to_dto(claimed)


@router.post(
    "/uploads/{import_id}/memory_batch/discard",
    response_model=MemoryBatchDto,
)
async def discard_memory_batch(
    import_id: str,
    body: MemoryBatchDiscardRequest,
    user: dict = Depends(require_active_session),
) -> MemoryBatchDto:
    """Discard the remaining sessions of a paused batch.

    Does **not** touch the journal entries that were already produced;
    only the paused-state UI dismissal. The in-flight slot is released
    so the live-flow extractor can resume normal operation. Emits
    :class:`ChatGptImportMemoryBatchDoneEvent` reflecting the work done
    so far, so the frontend's done-handler can collapse the panel via
    the same observer.
    """
    user_id = user["sub"]
    persona = await get_persona(body.persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    batch_repo = ChatGptImportMemoryBatchRepository(get_db())
    batch = await batch_repo.get(import_id, body.persona_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["state"] != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"Batch is not paused (state={batch['state']})",
        )

    updated = await batch_repo.mark_discarded(
        import_id=import_id,
        persona_id=body.persona_id,
        only_if_paused=True,
    )
    if updated is None:
        current = await batch_repo.get(import_id, body.persona_id)
        raise HTTPException(
            status_code=409,
            detail=f"Batch state changed (state={current['state'] if current else 'unknown'})",
        )

    # Release the in-flight slot so live-flow extraction is not blocked
    # for the persona any longer.
    from backend.database import get_redis
    from backend.ws.event_bus import get_event_bus

    redis = get_redis()
    try:
        await release_inflight_slot(
            redis,
            memory_extraction_slot_key(user_id, body.persona_id),
        )
    except Exception:
        _log.exception(
            "chatgpt_import.memory.batch.discard.slot_release_failed",
            extra={"user_id": user_id, "persona_id": body.persona_id},
        )

    # Re-use the BatchDone event so the UI collapses the panel without a
    # second observer. ``total_entries_created`` reflects what completed
    # before the user discarded.
    correlation_id = f"memory-batch-discard-{import_id}-{body.persona_id}"
    event = ChatGptImportMemoryBatchDoneEvent(
        import_id=import_id,
        persona_id=body.persona_id,
        total=len(list(updated.get("session_ids") or [])),
        total_entries_created=int(updated.get("total_entries_created", 0)),
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )
    event_bus = get_event_bus()
    for scope in (
        f"chatgpt_import:{import_id}",
        f"persona:{body.persona_id}",
    ):
        await event_bus.publish(
            Topics.CHATGPT_IMPORT_MEMORY_DONE,
            event,
            scope=scope,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    return _batch_doc_to_dto(updated)


@router.get(
    "/uploads/{import_id}/memory_batch",
    response_model=MemoryBatchDto,
)
async def get_memory_batch(
    import_id: str,
    persona_id: str = Query(..., description="Persona id"),
    user: dict = Depends(require_active_session),
) -> MemoryBatchDto:
    """Return the current memory-batch state for a persona within an import.

    Used by the frontend on persona-detail load to rehydrate paused-state
    UI without depending on WS replay. 404 if no batch exists for the
    given pair.
    """
    user_id = user["sub"]
    batch_repo = ChatGptImportMemoryBatchRepository(get_db())
    batch = await batch_repo.get(import_id, persona_id)
    if batch is None or batch.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    return _batch_doc_to_dto(batch)
