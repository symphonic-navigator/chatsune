"""Test PTI cache invalidation handlers."""
from __future__ import annotations

import pytest

from backend.modules.knowledge._pti_index import PtiIndexCache, TriggerIndex
from backend.modules.knowledge._pti_invalidation import (
    on_document_created,
    on_document_deleted,
    on_document_updated,
    on_library_attached_to_persona,
    on_library_attached_to_session,
    on_library_detached_from_persona,
    on_library_detached_from_session,
)


def _seed(cache: PtiIndexCache, session_id: str, doc_id: str, phrase: str):
    idx = TriggerIndex()
    idx.add(phrase, doc_id)
    cache.set(session_id, idx)


@pytest.mark.asyncio
async def test_document_deleted_invalidates_all(db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "doc1", "phr")
    _seed(cache, "s2", "doc1", "phr")
    await on_document_deleted(cache=cache, db=db, payload={"document_id": "doc1"})
    assert cache.get("s1") is None
    assert cache.get("s2") is None


@pytest.mark.asyncio
async def test_document_updated_invalidates_sessions_with_library(db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "doc1", "phr")
    await db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "T",
        "content": "c", "media_type": "text/markdown",
        "trigger_phrases": ["phr"], "refresh": None,
    })
    await db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
    })
    await on_document_updated(cache=cache, db=db, payload={"document_id": "doc1"})
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_document_created_invalidates_for_attached_sessions(db):
    await db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
    })
    cache = PtiIndexCache()
    _seed(cache, "s1", "old", "p")
    await on_document_created(
        cache=cache, db=db,
        payload={"document_id": "doc-new", "library_id": "lib1"},
    )
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_library_attached_to_session(db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "old", "p")
    await on_library_attached_to_session(
        cache=cache, db=db,
        payload={"session_id": "s1", "library_id": "lib1"},
    )
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_library_detached_from_session(db):
    cache = PtiIndexCache()
    _seed(cache, "s1", "old", "p")
    await on_library_detached_from_session(
        cache=cache, db=db,
        payload={"session_id": "s1", "library_id": "lib1"},
    )
    assert cache.get("s1") is None


@pytest.mark.asyncio
async def test_library_attached_to_persona_invalidates_all_sessions_of_persona(db):
    await db.chat_sessions.insert_many([
        {"_id": "s1", "user_id": "u1", "persona_id": "p1", "knowledge_library_ids": []},
        {"_id": "s2", "user_id": "u1", "persona_id": "p1", "knowledge_library_ids": []},
        {"_id": "s3", "user_id": "u1", "persona_id": "other", "knowledge_library_ids": []},
    ])
    cache = PtiIndexCache()
    _seed(cache, "s1", "x", "p")
    _seed(cache, "s2", "x", "p")
    _seed(cache, "s3", "x", "p")
    await on_library_attached_to_persona(
        cache=cache, db=db,
        payload={"persona_id": "p1", "library_id": "lib1"},
    )
    assert cache.get("s1") is None
    assert cache.get("s2") is None
    assert cache.get("s3") is not None  # other persona untouched


@pytest.mark.asyncio
async def test_library_detached_from_persona(db):
    await db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1", "knowledge_library_ids": [],
    })
    cache = PtiIndexCache()
    _seed(cache, "s1", "x", "p")
    await on_library_detached_from_persona(
        cache=cache, db=db,
        payload={"persona_id": "p1", "library_id": "lib1"},
    )
    assert cache.get("s1") is None
