import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

import backend.modules.embedding as embedding
from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.knowledge._cascade import cascade_delete_library
from backend.modules.knowledge._chunker import chunk_document
from backend.modules.knowledge._repository import KnowledgeRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.knowledge import (
    CreateDocumentRequest,
    CreateLibraryRequest,
    KnowledgeDocumentDto,
    KnowledgeLibraryDto,
    UpdateDocumentRequest,
    UpdateLibraryRequest,
)
from shared.events.knowledge import (
    KnowledgeDocumentCreatedEvent,
    KnowledgeDocumentDeletedEvent,
    KnowledgeDocumentEmbeddingEvent,
    KnowledgeDocumentUpdatedEvent,
    KnowledgeLibraryCreatedEvent,
    KnowledgeLibraryDeletedEvent,
    KnowledgeLibraryUpdatedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge")

# 200 MB hard cap on uploads — mirrors the uncompressed cap inside _import.
_MAX_IMPORT_ARCHIVE_BYTES = 200 * 1024 * 1024


def _repo() -> KnowledgeRepository:
    return KnowledgeRepository(get_db())


async def _trigger_embedding(
    doc: dict,
    user_id: str,
    repo: KnowledgeRepository,
    correlation_id: str,
) -> None:
    """Chunk a document and submit it to the embedding queue.

    If the document produces no chunks (empty content), the status is set to
    'completed' immediately. Otherwise the status is set to 'processing', an
    embedding event is published, and the texts are submitted to the embedding
    module for background processing.
    """
    doc_id = doc["_id"]
    content = doc.get("content", "")
    chunks = chunk_document(content)

    if not chunks:
        await repo.set_embedding_status(doc_id, user_id, "completed", chunk_count=0)
        return

    # Store serialised chunk metadata on the document for the embedding callback
    chunk_data = [
        {
            "chunk_index": c.chunk_index,
            "text": c.text,
            "heading_path": c.heading_path,
            "preroll_text": c.preroll_text,
            "token_count": c.token_count,
        }
        for c in chunks
    ]
    await repo.update_document(doc_id, user_id, {"_chunk_data": chunk_data})
    await repo.set_embedding_status(doc_id, user_id, "processing", chunk_count=len(chunks))

    retry_count = doc.get("retry_count", 0)

    event_bus = get_event_bus()
    now = datetime.now(timezone.utc)
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_EMBEDDING,
        KnowledgeDocumentEmbeddingEvent(
            document_id=doc_id,
            chunk_count=len(chunks),
            retry_count=retry_count,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    texts = [c.text for c in chunks]
    await embedding.embed_texts(texts, reference_id=doc_id, correlation_id=correlation_id)


# ------------------------------------------------------------------
# Libraries
# ------------------------------------------------------------------


@router.get("/libraries")
async def list_libraries(
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    docs = await repo.list_libraries(user["sub"])
    return [KnowledgeRepository.to_library_dto(d) for d in docs]


@router.post("/libraries", status_code=201)
async def create_library(
    body: CreateLibraryRequest,
    user: dict = Depends(require_active_session),
):
    dto, _doc = await _create_library_internal(
        user_id=user["sub"],
        name=body.name,
        description=body.description,
        nsfw=body.nsfw,
        default_refresh=body.default_refresh,
    )
    return dto


@router.put("/libraries/{library_id}")
async def update_library(
    library_id: str,
    body: UpdateLibraryRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    existing = await repo.get_library(library_id, user["sub"])
    if not existing:
        raise HTTPException(status_code=404, detail="Library not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    doc = await repo.update_library(library_id, user["sub"], updates)
    if not doc:
        raise HTTPException(status_code=404, detail="Library not found")

    dto = KnowledgeRepository.to_library_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_LIBRARY_UPDATED,
        KnowledgeLibraryUpdatedEvent(
            library=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return dto


@router.delete("/libraries/{library_id}")
async def delete_library(
    library_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    # Verify library exists and belongs to user before running cascade,
    # so 404 still surfaces correctly when the id is bogus.
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    deleted, report = await cascade_delete_library(library_id=library_id, user_id=user["sub"])

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_LIBRARY_DELETED,
        KnowledgeLibraryDeletedEvent(
            library_id=library_id,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return report


# ------------------------------------------------------------------
# Documents
# ------------------------------------------------------------------


@router.get("/libraries/{library_id}/documents")
async def list_documents(
    library_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    docs = await repo.list_documents(library_id, user["sub"])
    return [KnowledgeRepository.to_document_dto(d) for d in docs]


async def _create_document_internal(
    user_id: str,
    library_id: str,
    title: str,
    content: str,
    media_type: str,
    trigger_phrases: list[str] | None = None,
    refresh: str | None = None,
    correlation_id: str | None = None,
) -> KnowledgeDocumentDto:
    """Core document-upload pipeline: insert document, publish created event,
    and trigger chunking + embedding. Used by both the HTTP handler and the
    library-import path so chunking/embedding logic is not duplicated.

    Caller MUST have already verified that the library exists and is owned
    by ``user_id``.
    """
    repo = _repo()
    doc = await repo.create_document(
        user_id=user_id,
        library_id=library_id,
        title=title,
        content=content,
        media_type=media_type,
        trigger_phrases=trigger_phrases,
        refresh=refresh,
    )
    await repo.increment_document_count(library_id, user_id, 1)

    dto = KnowledgeRepository.to_document_dto(doc)

    if correlation_id is None:
        correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_CREATED,
        KnowledgeDocumentCreatedEvent(
            document=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    await _trigger_embedding(doc, user_id, repo, correlation_id)

    return dto


async def _create_library_internal(
    user_id: str,
    name: str,
    description: str | None,
    nsfw: bool,
    default_refresh: str = "standard",
    correlation_id: str | None = None,
) -> tuple[KnowledgeLibraryDto, dict]:
    """Core library-creation pipeline: insert library and publish created event.

    Returns ``(dto, raw_doc)`` so callers (e.g. the import path) can reach
    the underlying ``library_id`` without an extra DB roundtrip.
    """
    repo = _repo()
    doc = await repo.create_library(
        user_id=user_id,
        name=name,
        description=description,
        nsfw=nsfw,
        default_refresh=default_refresh,
    )
    dto = KnowledgeRepository.to_library_dto(doc)

    if correlation_id is None:
        correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_LIBRARY_CREATED,
        KnowledgeLibraryCreatedEvent(
            library=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    return dto, doc


@router.post("/libraries/{library_id}/documents", status_code=201)
async def create_document(
    library_id: str,
    body: CreateDocumentRequest,
    user: dict = Depends(require_active_session),
):
    from backend.modules.knowledge._pti_normalisation import normalise
    from backend.modules.knowledge._pti_service import (
        PtiContentTooLargeError,
        validate_pti_eligibility,
    )

    repo = _repo()
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    normalised_phrases = [
        n for n in (normalise(p) for p in body.trigger_phrases) if n
    ]
    try:
        validate_pti_eligibility(
            content=body.content, trigger_phrases=normalised_phrases,
        )
    except PtiContentTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await _create_document_internal(
        user_id=user["sub"],
        library_id=library_id,
        title=body.title,
        content=body.content,
        media_type=body.media_type,
        trigger_phrases=normalised_phrases,
        refresh=body.refresh,
    )


@router.get("/libraries/{library_id}/documents/{doc_id}")
async def get_document(
    library_id: str,
    doc_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    doc = await repo.get_document(doc_id, user["sub"])
    if not doc or doc.get("library_id") != library_id:
        raise HTTPException(status_code=404, detail="Document not found")

    return KnowledgeRepository.to_document_detail_dto(doc)


@router.put("/libraries/{library_id}/documents/{doc_id}")
async def update_document(
    library_id: str,
    doc_id: str,
    body: UpdateDocumentRequest,
    user: dict = Depends(require_active_session),
):
    from backend.modules.knowledge._pti_normalisation import normalise
    from backend.modules.knowledge._pti_service import (
        PtiContentTooLargeError,
        validate_pti_eligibility,
    )

    repo = _repo()
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    existing = await repo.get_document(doc_id, user["sub"])
    if not existing or existing.get("library_id") != library_id:
        raise HTTPException(status_code=404, detail="Document not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "trigger_phrases" in updates:
        updates["trigger_phrases"] = [
            n for n in (normalise(p) for p in updates["trigger_phrases"]) if n
        ]

    new_content = updates.get("content", existing.get("content", ""))
    new_phrases = updates.get("trigger_phrases", existing.get("trigger_phrases", []))
    try:
        validate_pti_eligibility(content=new_content, trigger_phrases=new_phrases)
    except PtiContentTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    content_changed = "content" in updates

    if content_changed:
        # Remove existing chunks and reset retry count before update
        await repo.delete_chunks_for_document(doc_id, user["sub"])
        await repo.reset_retry_count(doc_id, user["sub"])

    doc = await repo.update_document(doc_id, user["sub"], updates)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    dto = KnowledgeRepository.to_document_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_UPDATED,
        KnowledgeDocumentUpdatedEvent(
            document=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    if content_changed:
        await _trigger_embedding(doc, user["sub"], repo, correlation_id)

    return dto


@router.delete("/libraries/{library_id}/documents/{doc_id}")
async def delete_document(
    library_id: str,
    doc_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    deleted_library_id = await repo.delete_document(doc_id, user["sub"])
    if not deleted_library_id:
        raise HTTPException(status_code=404, detail="Document not found")

    await repo.increment_document_count(deleted_library_id, user["sub"], -1)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_DELETED,
        KnowledgeDocumentDeletedEvent(
            library_id=deleted_library_id,
            document_id=doc_id,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"status": "ok"}


@router.post("/libraries/{library_id}/documents/{doc_id}/retry")
async def retry_document_embedding(
    library_id: str,
    doc_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    library = await repo.get_library(library_id, user["sub"])
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    doc = await repo.get_document(doc_id, user["sub"])
    if not doc or doc.get("library_id") != library_id:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.get("embedding_status") != "failed":
        raise HTTPException(
            status_code=409,
            detail="Document embedding is not in a failed state",
        )

    await repo.reset_retry_count(doc_id, user["sub"])
    # Reload doc after reset so retry_count reflects the reset value
    doc = await repo.get_document(doc_id, user["sub"])

    correlation_id = str(uuid4())
    await _trigger_embedding(doc, user["sub"], repo, correlation_id)

    return {"status": "ok"}


# ------------------------------------------------------------------
# Export / Import
# ------------------------------------------------------------------
#
# Archive format is documented in ``_export.py``. The routes live here so
# the module's full HTTP surface is in one place. Orchestration logic lives
# in the ``_export`` / ``_import`` helpers.


@router.get("/libraries/{library_id}/export")
async def export_library(
    library_id: str,
    user: dict = Depends(require_active_session),
):
    """Stream a ``.chatsune-knowledge.tar.gz`` download for the given library."""
    # Deferred import to avoid circular imports at module load.
    from backend.modules.knowledge._export import export_library_archive

    archive_bytes, filename = await export_library_archive(
        user_id=user["sub"],
        library_id=library_id,
    )
    return StreamingResponse(
        iter([archive_bytes]),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(archive_bytes)),
        },
    )


@router.post("/libraries/import", status_code=201)
async def import_library(
    file: UploadFile,
    user: dict = Depends(require_active_session),
) -> KnowledgeLibraryDto:
    """Accept a ``.chatsune-knowledge.tar.gz`` upload and create a new library."""
    # Deferred import to avoid circular imports at module load.
    from backend.modules.knowledge._import import import_library_archive

    data = await file.read()
    if len(data) > _MAX_IMPORT_ARCHIVE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Archive exceeds 200 MB upload limit",
        )

    return await import_library_archive(user_id=user["sub"], archive_bytes=data)
