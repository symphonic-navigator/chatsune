"""Event handlers that invalidate the PTI index cache.

Strategy: invalidate-on-event, lazy-reload on next match. We don't
pre-build the new index here — the orchestrator will rebuild on next
user message. Cheap, correct, and avoids a stale-index race.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.knowledge._pti_index import PtiIndexCache


async def on_document_created(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    # Event payload shape: {"type": ..., "document": KnowledgeDocumentDto, ...}
    # KnowledgeDocumentDto exposes id and library_id but NOT user_id, so we
    # source user_id from the DB record by document id. This keeps the
    # invalidation owner-scoped without changing the shared event contract.
    document = payload.get("document") or {}
    document_id = document.get("id")
    library_id = document.get("library_id")
    if not document_id or not library_id:
        return
    record = await db.knowledge_documents.find_one(
        {"_id": document_id}, projection={"user_id": 1}
    )
    if record is None:
        return
    user_id = record.get("user_id")
    if not user_id:
        return
    await _invalidate_sessions_with_library(cache, db, library_id, user_id)


async def on_document_updated(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    # Event payload shape: {"type": ..., "document": KnowledgeDocumentDto, ...}
    # The previous implementation read payload.get("document_id") which is
    # always None under the actual event shape — the handler was effectively
    # dead. Source document_id from the nested DTO, and read user_id from
    # the DB record so the chat-session scan is owner-bound.
    document = payload.get("document") or {}
    document_id = document.get("id")
    if not document_id:
        return
    doc = await db.knowledge_documents.find_one(
        {"_id": document_id}, projection={"library_id": 1, "user_id": 1}
    )
    if doc is None:
        await _invalidate_all(cache)
        return
    user_id = doc.get("user_id")
    library_id = doc.get("library_id")
    if not user_id or not library_id:
        return
    await _invalidate_sessions_with_library(cache, db, library_id, user_id)


async def on_document_deleted(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    # Document is gone, can't look up library — broad invalidation.
    await _invalidate_all(cache)


async def on_library_attached_to_session(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    session_id = payload.get("session_id")
    if session_id:
        cache.invalidate(session_id)


async def on_library_detached_from_session(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    session_id = payload.get("session_id")
    if session_id:
        cache.invalidate(session_id)


async def on_library_attached_to_persona(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    persona_id = payload.get("persona_id")
    if not persona_id:
        return
    await _invalidate_sessions_with_persona(cache, db, persona_id)


async def on_library_detached_from_persona(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    persona_id = payload.get("persona_id")
    if not persona_id:
        return
    await _invalidate_sessions_with_persona(cache, db, persona_id)


async def _invalidate_sessions_with_library(
    cache: PtiIndexCache,
    db: AsyncIOMotorDatabase,
    library_id: str,
    user_id: str,
) -> None:
    cur = db.chat_sessions.find(
        {"user_id": user_id, "knowledge_library_ids": library_id},
        projection={"_id": 1},
    )
    async for sess in cur:
        cache.invalidate(sess["_id"])


async def _invalidate_sessions_with_persona(
    cache: PtiIndexCache, db: AsyncIOMotorDatabase, persona_id: str
) -> None:
    cur = db.chat_sessions.find(
        {"persona_id": persona_id}, projection={"_id": 1}
    )
    async for sess in cur:
        cache.invalidate(sess["_id"])


async def _invalidate_all(cache: PtiIndexCache) -> None:
    for sess_id in cache.all_session_ids():
        cache.invalidate(sess_id)
