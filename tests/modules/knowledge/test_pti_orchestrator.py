"""Integration test for PTI orchestrator. Hits MongoDB via the `db` fixture."""
from __future__ import annotations

import pytest

from backend.modules.knowledge import get_pti_injections
from backend.modules.knowledge._pti_index import PtiIndexCache


@pytest.fixture
def cache() -> PtiIndexCache:
    return PtiIndexCache()


@pytest.mark.asyncio
async def test_orchestrator_no_attached_libraries_returns_empty(db, cache):
    sess_id = "session-1"
    await db.chat_sessions.insert_one({
        "_id": sess_id,
        "user_id": "u1",
        "persona_id": "p1",
        "knowledge_library_ids": [],
        "user_message_counter": 0,
        "pti_last_inject": {},
    })
    items, overflow = await get_pti_injections(
        db=db, cache=cache, session_id=sess_id,
        message="andromedagalaxie", persona_library_ids=[],
    )
    assert items == []
    assert overflow is None


@pytest.mark.asyncio
async def test_orchestrator_full_path(db, cache):
    """End-to-end: library + doc with phrase, message matches, doc injected."""
    await db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore",
        "default_refresh": "standard",
    })
    await db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "Andromeda Mythos",
        "content": "Andromeda is far away.", "media_type": "text/markdown",
        "trigger_phrases": ["andromedagalaxie"], "refresh": None,
    })
    await db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
        "user_message_counter": 0, "pti_last_inject": {},
    })

    items, overflow = await get_pti_injections(
        db=db, cache=cache, session_id="s1",
        message="erzähl mir von der Andromedagalaxie", persona_library_ids=[],
    )
    assert len(items) == 1
    assert items[0].source == "trigger"
    assert items[0].triggered_by == "andromedagalaxie"
    assert items[0].document_title == "Andromeda Mythos"
    assert overflow is None

    sess = await db.chat_sessions.find_one({"_id": "s1"})
    assert sess["pti_last_inject"]["doc1"] == 1
    assert sess["user_message_counter"] == 1


@pytest.mark.asyncio
async def test_orchestrator_cooldown_blocks_second_call(db, cache):
    await db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore", "default_refresh": "often",
    })
    await db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "T",
        "content": "c", "media_type": "text/markdown",
        "trigger_phrases": ["foo"], "refresh": None,
    })
    await db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
        "user_message_counter": 0, "pti_last_inject": {},
    })

    items1, _ = await get_pti_injections(
        db=db, cache=cache, session_id="s1",
        message="foo", persona_library_ids=[],
    )
    assert len(items1) == 1

    items2, _ = await get_pti_injections(
        db=db, cache=cache, session_id="s1",
        message="foo again", persona_library_ids=[],
    )
    assert items2 == []
