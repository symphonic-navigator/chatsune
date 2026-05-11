"""REST API for /api/chatgpt-import/*."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.database import get_db
from backend.dependencies import require_active_session
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
    UploadResponse,
)

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

    correlation_id, job_pairs = await _service().trigger_conversation_imports(
        user_id=user_id,
        import_id=import_id,
        persona_id=body.persona_id,
        chatgpt_conversation_ids=body.chatgpt_conversation_ids,
    )
    return ImportTriggerResponse(
        correlation_id=correlation_id,
        jobs=[
            ImportTriggerJobInfo(chatgpt_conversation_id=cid, job_id=jid)
            for cid, jid in job_pairs
        ],
    )
