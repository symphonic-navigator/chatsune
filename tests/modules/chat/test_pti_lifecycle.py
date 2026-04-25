"""Test PTI hook in chat user-message lifecycle.

Bypasses the WebSocket layer — exercises handle_chat_send directly with
fixtures matching what a real WS call would set up.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_pti_injection_persists_to_message(db, monkeypatch):
    """User message containing a trigger phrase persists with knowledge_context."""
    # Seed library + doc + persona + session
    await db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore",
        "default_refresh": "standard",
    })
    await db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "title": "Andromeda",
        "content": "Andromeda lore.", "media_type": "text/markdown",
        "trigger_phrases": ["andromedagalaxie"], "refresh": None,
    })
    await db.personas.insert_one({
        "_id": "p1", "user_id": "u1", "name": "Test", "knowledge_library_ids": [],
    })
    await db.chat_sessions.insert_one({
        "_id": "s1", "user_id": "u1", "persona_id": "p1",
        "knowledge_library_ids": ["lib1"],
        "user_message_counter": 0, "pti_last_inject": {},
        "state": "idle",
    })

    # Stub out the inference run so we only test the persistence side.
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.run_inference",
        AsyncMock(return_value=None),
    )
    # Stub event_bus to avoid Redis / WS coupling.
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_event_bus",
        lambda: AsyncMock(),
    )
    # Stub cancel_all_for_user.
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.cancel_all_for_user",
        AsyncMock(return_value=0),
    )
    # Stub track_extraction_trigger.
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.track_extraction_trigger",
        AsyncMock(),
    )
    # Point get_db in the handler and in the persona module to the test db.
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_db",
        lambda: db,
    )
    monkeypatch.setattr(
        "backend.modules.persona.get_db",
        lambda: db,
    )

    from backend.modules.chat._handlers_ws import handle_chat_send

    await handle_chat_send(
        "u1",
        {
            "session_id": "s1",
            "content": [{"type": "text", "text": "Erzähl mir von der Andromedagalaxie"}],
        },
    )

    msg = await db.chat_messages.find_one({"session_id": "s1", "role": "user"})
    assert msg is not None
    kc = msg.get("knowledge_context") or []
    assert len(kc) == 1
    assert kc[0]["source"] == "trigger"
    assert kc[0]["triggered_by"] == "andromedagalaxie"
    assert kc[0]["document_title"] == "Andromeda"


@pytest.mark.asyncio
async def test_no_trigger_yields_no_knowledge_context(db, monkeypatch):
    """User message without trigger phrases doesn't get knowledge_context."""
    await db.personas.insert_one({
        "_id": "p2", "user_id": "u1", "name": "Test", "knowledge_library_ids": [],
    })
    await db.chat_sessions.insert_one({
        "_id": "s2", "user_id": "u1", "persona_id": "p2",
        "knowledge_library_ids": [],
        "user_message_counter": 0, "pti_last_inject": {},
        "state": "idle",
    })

    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.run_inference",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_event_bus",
        lambda: AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.cancel_all_for_user",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.track_extraction_trigger",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_db",
        lambda: db,
    )
    monkeypatch.setattr(
        "backend.modules.persona.get_db",
        lambda: db,
    )

    from backend.modules.chat._handlers_ws import handle_chat_send

    await handle_chat_send(
        "u1",
        {
            "session_id": "s2",
            "content": [{"type": "text", "text": "hello world"}],
        },
    )

    msg = await db.chat_messages.find_one({"session_id": "s2", "role": "user"})
    assert msg is not None
    assert msg.get("knowledge_context") is None or msg["knowledge_context"] == []
    assert msg.get("pti_overflow") is None
