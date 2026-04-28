"""PTI orchestrator: load index, match, apply cooldown/caps, persist counter."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.knowledge._pti_index import (
    PtiIndexCache,
    TriggerIndex,
    match_phrases,
)
from backend.modules.knowledge._pti_normalisation import normalise
from backend.modules.knowledge._pti_service import (
    DocumentCandidate,
    apply_cooldown_and_caps,
)
from shared.dtos.chat import KnowledgeContextItem, PtiOverflow

MESSAGE_TOKEN_CAP = 8_000
MESSAGE_DOC_CAP = 10


async def get_pti_injections(
    db: AsyncIOMotorDatabase,
    cache: PtiIndexCache,
    session_id: str,
    message: str,
    persona_library_ids: list[str],
) -> tuple[list[KnowledgeContextItem], PtiOverflow | None]:
    """Match + filter + persist. Atomically updates session state."""
    session = await db.chat_sessions.find_one({"_id": session_id})
    if session is None:
        return [], None

    # Defense in depth: every subsequent find/update is filtered by the
    # session owner so a regression in upstream attach validation cannot
    # leak documents or libraries from another user's tenancy.
    user_id = session.get("user_id")
    if not user_id:
        return [], None

    session_lib_ids = session.get("knowledge_library_ids") or []
    all_lib_ids = list({*persona_library_ids, *session_lib_ids})
    if not all_lib_ids:
        return [], None

    index = cache.get(session_id)
    if index is None:
        index = await _build_index(db, all_lib_ids, user_id)
        cache.set(session_id, index)

    hits = match_phrases(message, index)
    if not hits:
        await db.chat_sessions.update_one(
            {"_id": session_id, "user_id": user_id},
            {"$inc": {"user_message_counter": 1}},
        )
        return [], None

    hit_doc_ids = list({h[0] for h in hits})
    docs_cur = db.knowledge_documents.find(
        {"_id": {"$in": hit_doc_ids}, "user_id": user_id}
    )
    docs_by_id = {d["_id"]: d async for d in docs_cur}

    libs_cur = db.knowledge_libraries.find(
        {"_id": {"$in": all_lib_ids}, "user_id": user_id}
    )
    libs_by_id = {l["_id"]: l async for l in libs_cur}

    candidates: list[DocumentCandidate] = []
    for doc_id, phrase, position in hits:
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue
        lib = libs_by_id.get(doc.get("library_id"))
        candidates.append(
            DocumentCandidate(
                doc_id=doc_id,
                title=doc.get("title", ""),
                library_name=(lib or {}).get("name", ""),
                triggered_by=phrase,
                position=position,
                content=doc.get("content", ""),
                token_count=_estimate_tokens(doc.get("content", "")),
                refresh=doc.get("refresh"),
                library_default_refresh=(lib or {}).get(
                    "default_refresh", "standard"
                ),
            )
        )

    new_counter = await _increment_counter(db, session_id, user_id)
    pti_last_inject = session.get("pti_last_inject") or {}

    items, overflow = apply_cooldown_and_caps(
        candidates=candidates,
        pti_last_inject=pti_last_inject,
        user_msg_index=new_counter,
        token_cap=MESSAGE_TOKEN_CAP,
        doc_cap=MESSAGE_DOC_CAP,
    )

    if items:
        injected_ids = [
            c.doc_id
            for c in candidates
            if any(
                i.document_title == c.title and i.triggered_by == c.triggered_by
                for i in items
            )
        ]
        update_fields = {
            f"pti_last_inject.{doc_id}": new_counter
            for doc_id in injected_ids
        }
        await db.chat_sessions.update_one(
            {"_id": session_id, "user_id": user_id},
            {"$set": update_fields},
        )

    return items, overflow


async def _build_index(
    db: AsyncIOMotorDatabase, library_ids: list[str], user_id: str
) -> TriggerIndex:
    """Load all trigger phrases of all documents in `library_ids`.

    Filtered by `user_id` so the index can never be poisoned with phrases
    from a foreign-tenant document if upstream attach validation regresses.
    """
    index = TriggerIndex()
    cur = db.knowledge_documents.find(
        {
            "library_id": {"$in": library_ids},
            "user_id": user_id,
            "trigger_phrases": {"$ne": []},
        },
        projection={"_id": 1, "trigger_phrases": 1},
    )
    async for doc in cur:
        for phrase in doc.get("trigger_phrases", []):
            normalised = normalise(phrase)
            if normalised:
                index.add(normalised, doc["_id"])
    return index


async def _increment_counter(
    db: AsyncIOMotorDatabase, session_id: str, user_id: str
) -> int:
    """Atomically increment user_message_counter and return the new value."""
    res = await db.chat_sessions.find_one_and_update(
        {"_id": session_id, "user_id": user_id},
        {"$inc": {"user_message_counter": 1}},
        return_document=True,
    )
    return (res or {}).get("user_message_counter", 1)


def _estimate_tokens(content: str) -> int:
    """Cheap token estimate: 4 chars per token. Good enough for caps."""
    return max(1, len(content) // 4)
