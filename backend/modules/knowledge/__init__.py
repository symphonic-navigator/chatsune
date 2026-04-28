"""Knowledge module — libraries, documents, and vector search.

Public API: import only from this file.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.knowledge._cascade import cascade_delete_library
from backend.modules.knowledge._handlers import router as knowledge_router, _trigger_embedding
from backend.modules.knowledge._pti_index import PtiIndexCache
from backend.modules.knowledge._pti_orchestrator import get_pti_injections
from backend.modules.knowledge._repository import KnowledgeRepository
from backend.modules.knowledge._retrieval import search
from backend.database import get_db
from shared.events.knowledge import (
    KnowledgeDocumentEmbeddedEvent,
    KnowledgeDocumentEmbedFailedEvent,
)
from shared.topics import Topics

_log = logging.getLogger("chatsune.knowledge")

# Process-wide singleton.
pti_index_cache = PtiIndexCache()


async def init_indexes(db) -> None:
    await KnowledgeRepository(db).create_indexes()


async def handle_embedding_completed(event: dict) -> None:
    """Handle EmbeddingBatchCompleted — merge vectors into chunks and store them."""
    doc_id = event.get("reference_id")
    vectors: list[list[float]] = event.get("vectors", [])
    correlation_id = event.get("correlation_id", str(uuid4()))
    evt_user_id = event.get("user_id")

    if not doc_id:
        _log.warning("handle_embedding_completed: missing reference_id in event")
        return

    db = get_db()
    repo = KnowledgeRepository(db)

    # Scope the lookup by owner when the event carries a user_id. The fallback
    # to an unscoped find is a deploy-window backward-compat path: events
    # published by the previous code (still in Redis Streams during a rolling
    # deploy) have no user_id. Tighten this once we are confident no legacy
    # events remain — drop the None branch and require user_id on the event.
    if evt_user_id:
        query = {"_id": doc_id, "user_id": evt_user_id}
    else:
        _log.warning(
            "handle_embedding_completed: event missing user_id (legacy); "
            "falling back to unscoped lookup for doc=%s",
            doc_id,
        )
        query = {"_id": doc_id}
    doc = await db["knowledge_documents"].find_one(query)
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
    evt_user_id = event.get("user_id")

    if not doc_id:
        _log.warning("handle_embedding_error: missing reference_id in event")
        return

    db = get_db()
    repo = KnowledgeRepository(db)

    # Same deploy-window backward-compat as handle_embedding_completed: prefer
    # the owner-scoped lookup, fall back to unscoped if the event predates the
    # user_id field. Drop the fallback once legacy events have drained.
    if evt_user_id:
        query = {"_id": doc_id, "user_id": evt_user_id}
    else:
        _log.warning(
            "handle_embedding_error: event missing user_id (legacy); "
            "falling back to unscoped lookup for doc=%s",
            doc_id,
        )
        query = {"_id": doc_id}
    doc = await db["knowledge_documents"].find_one(query)
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


async def list_library_ids_for_user(user_id: str) -> list[str]:
    """Return every knowledge-library ``_id`` owned by ``user_id``.

    Used by the user self-delete cascade so the orchestrator can iterate
    through each library via :func:`cascade_delete_library` without ever
    touching the ``knowledge_libraries`` collection directly.
    """
    repo = KnowledgeRepository(get_db())
    libs = await repo.list_libraries(user_id)
    return [lib["_id"] for lib in libs]


async def verify_libraries_owned(user_id: str, library_ids: list[str]) -> bool:
    """Return True iff every id in library_ids is a library owned by user_id.

    Used by other modules to validate cross-references without reaching
    into knowledge internals. Empty list returns True.
    """
    if not library_ids:
        return True
    repo = KnowledgeRepository(get_db())
    owned = await repo.list_libraries(user_id)
    owned_ids = {lib["_id"] for lib in owned}
    return all(lid in owned_ids for lid in library_ids)


__all__ = [
    "knowledge_router",
    "init_indexes",
    "handle_embedding_completed",
    "handle_embedding_error",
    "search",
    "cascade_delete_library",
    "list_library_ids_for_user",
    "verify_libraries_owned",
    "get_pti_injections",
    "pti_index_cache",
]
