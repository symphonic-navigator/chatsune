"""Knowledge retrieval — vector search and tool executor for knowledge_search."""

import json
import logging

from backend.database import get_db
from backend.modules.knowledge._repository import KnowledgeRepository
from shared.dtos.knowledge import RetrievedChunkDto

_log = logging.getLogger(__name__)

_MAX_CONTENT_LENGTH = 8000


async def search(
    user_id: str,
    query: str,
    persona_library_ids: list[str],
    session_library_ids: list[str],
    sanitised: bool = False,
    top_k: int = 5,
) -> list[RetrievedChunkDto]:
    from backend.modules.embedding import query_embed

    effective_ids = list(set(persona_library_ids + session_library_ids))
    _log.info(
        "knowledge search: query=%r, persona_libs=%s, session_libs=%s, effective=%s, sanitised=%s",
        query[:80], persona_library_ids, session_library_ids, effective_ids, sanitised,
    )
    if not effective_ids:
        _log.warning("knowledge search: no effective library IDs — returning empty")
        return []

    repo = KnowledgeRepository(get_db())

    # Filter out NSFW libraries if sanitised
    if sanitised:
        filtered: list[str] = []
        for lib_id in effective_ids:
            lib = await repo.get_library(lib_id, user_id)
            if lib and not lib.get("nsfw", False):
                filtered.append(lib_id)
        effective_ids = filtered

    if not effective_ids:
        _log.warning("knowledge search: all libraries filtered by sanitised mode")
        return []

    query_vector = await query_embed(query)
    _log.info("knowledge search: query embedded, vector dim=%d", len(query_vector))
    raw_results = await repo.vector_search(user_id, effective_ids, query_vector, top_k)
    _log.info("knowledge search: vector search returned %d results", len(raw_results))

    results: list[RetrievedChunkDto] = []
    for r in raw_results:
        lib = await repo.get_library(r["library_id"], user_id)
        doc = await repo.get_document(r["document_id"], user_id)
        if not lib or not doc:
            continue

        content = r.get("text", "")
        if len(content) > _MAX_CONTENT_LENGTH:
            content = content[:_MAX_CONTENT_LENGTH] + "..."

        results.append(RetrievedChunkDto(
            library_name=lib["name"],
            document_title=doc["title"],
            heading_path=r.get("heading_path", []),
            preroll_text=r.get("preroll_text", ""),
            content=content,
            score=r.get("score", 0.0),
        ))

    return results
