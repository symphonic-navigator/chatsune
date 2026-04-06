"""Knowledge module — libraries, documents, and vector search.

Public API: import only from this file.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.knowledge._handlers import router as knowledge_router, _trigger_embedding
from backend.modules.knowledge._repository import KnowledgeRepository
from backend.database import get_db
from shared.events.knowledge import (
    KnowledgeDocumentEmbeddedEvent,
    KnowledgeDocumentEmbedFailedEvent,
)
from shared.topics import Topics

_log = logging.getLogger("chatsune.knowledge")


async def init_indexes(db) -> None:
    await KnowledgeRepository(db).create_indexes()


async def handle_embedding_completed(event: dict) -> None:
    """Handle EmbeddingBatchCompleted — merge vectors into chunks and store them."""
    doc_id = event.get("reference_id")
    vectors: list[list[float]] = event.get("vectors", [])
    correlation_id = event.get("correlation_id", str(uuid4()))

    if not doc_id:
        _log.warning("handle_embedding_completed: missing reference_id in event")
        return

    db = get_db()
    repo = KnowledgeRepository(db)

    # Find the document across all users (embedding events carry no user_id)
    doc = await db["knowledge_documents"].find_one({"_id": doc_id})
    if not doc:
        _log.warning("handle_embedding_completed: document %s not found", doc_id)
        return

    user_id = doc["user_id"]
    library_id = doc["library_id"]
    chunk_data: list[dict] = doc.get("_chunk_data") or []

    if len(chunk_data) != len(vectors):
        _log.warning(
            "handle_embedding_completed: chunk/vector count mismatch for doc %s "
            "(chunks=%d vectors=%d) — skipping",
            doc_id, len(chunk_data), len(vectors),
        )
        return

    # Merge vector into each chunk record
    chunks = [
        {**c, "vector": v}
        for c, v in zip(chunk_data, vectors)
    ]

    await repo.upsert_chunks(
        user_id=user_id,
        document_id=doc_id,
        library_id=library_id,
        chunks=chunks,
    )

    # Clear temporary _chunk_data and mark as completed
    await db["knowledge_documents"].update_one(
        {"_id": doc_id},
        {"$unset": {"_chunk_data": ""}, "$set": {"embedding_status": "completed", "updated_at": datetime.now(timezone.utc)}},
    )

    from backend.ws.event_bus import get_event_bus
    event_bus = get_event_bus()
    now = datetime.now(timezone.utc)
    await event_bus.publish(
        Topics.KNOWLEDGE_DOCUMENT_EMBEDDED,
        KnowledgeDocumentEmbeddedEvent(
            document_id=doc_id,
            chunk_count=len(chunks),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    _log.info("knowledge: embedded doc=%s chunks=%d user=%s", doc_id, len(chunks), user_id)


async def handle_embedding_error(event: dict) -> None:
    """Handle EmbeddingError — retry or mark as permanently failed."""
    doc_id = event.get("reference_id")
    error_msg = event.get("error", "Unknown error")
    correlation_id = event.get("correlation_id", str(uuid4()))

    if not doc_id:
        _log.warning("handle_embedding_error: missing reference_id in event")
        return

    db = get_db()
    repo = KnowledgeRepository(db)

    doc = await db["knowledge_documents"].find_one({"_id": doc_id})
    if not doc:
        _log.warning("handle_embedding_error: document %s not found", doc_id)
        return

    user_id = doc["user_id"]

    retry_count = await repo.increment_retry_count(doc_id, user_id)

    if retry_count < 3:
        _log.info(
            "knowledge: embedding error for doc=%s (attempt %d/3), retrying — %s",
            doc_id, retry_count, error_msg,
        )
        # Reload doc with updated retry_count before re-triggering
        doc = await repo.get_document(doc_id, user_id)
        if doc:
            await _trigger_embedding(doc, user_id, repo, correlation_id)
    else:
        _log.warning(
            "knowledge: embedding permanently failed for doc=%s after %d attempts — %s",
            doc_id, retry_count, error_msg,
        )
        await repo.set_embedding_status(doc_id, user_id, "failed", error=error_msg)

        from backend.ws.event_bus import get_event_bus
        event_bus = get_event_bus()
        now = datetime.now(timezone.utc)
        await event_bus.publish(
            Topics.KNOWLEDGE_DOCUMENT_EMBED_FAILED,
            KnowledgeDocumentEmbedFailedEvent(
                document_id=doc_id,
                error=error_msg,
                retry_count=retry_count,
                recoverable=False,
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"user:{user_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )


__all__ = [
    "knowledge_router",
    "init_indexes",
    "handle_embedding_completed",
    "handle_embedding_error",
]
