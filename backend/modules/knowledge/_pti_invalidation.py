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
    library_id = payload.get("library_id")
    if not library_id:
        return
    await _invalidate_sessions_with_library(cache, db, library_id)


async def on_document_updated(
    *, cache: PtiIndexCache, db: AsyncIOMotorDatabase, payload: dict
) -> None:
    document_id = payload.get("document_id")
    if not document_id:
        return
    doc = await db.knowledge_documents.find_one(
        {"_id": document_id}, projection={"library_id": 1}
    )
    if doc is None:
        await _invalidate_all(cache)
        return
    await _invalidate_sessions_with_library(cache, db, doc["library_id"])


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
    cache: PtiIndexCache, db: AsyncIOMotorDatabase, library_id: str
) -> None:
    cur = db.chat_sessions.find(
        {"knowledge_library_ids": library_id}, projection={"_id": 1}
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
