"""Unit tests for ChatRepository.synthesise_events.

These tests use plain dicts as input — no MongoDB, no mocks. The function
under test is a pure mapping from a legacy Mongo document shape to a list
of TimelineEntry* models, so we can exercise it directly.
"""

from backend.modules.chat._repository import ChatRepository, synthesise_events
from shared.dtos.chat import (
    TimelineEntryArtefact,
    TimelineEntryImage,
    TimelineEntryKnowledgeSearch,
    TimelineEntryToolCall,
    TimelineEntryWebSearch,
)


def _legacy_doc(**overrides) -> dict:
    """Minimal legacy assistant-message document with the keys we care about."""
    base: dict = {
        "_id": "msg-1",
        "session_id": "sess-1",
        "role": "assistant",
        "content": "ok",
        "token_count": 1,
        "created_at": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Returns None when nothing legacy is present
# ---------------------------------------------------------------------------

def test_returns_none_when_no_legacy_keys() -> None:
    doc = _legacy_doc()
    assert synthesise_events(doc) is None


# ---------------------------------------------------------------------------
# Single tools
# ---------------------------------------------------------------------------

def test_single_knowledge_search() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1",
            "tool_name": "knowledge_search",
            "arguments": {"query": "foo"},
            "success": True,
        }],
        knowledge_context=[{
            "library_name": "Lore", "document_title": "Doc",
            "heading_path": [], "content": "snippet",
        }],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, TimelineEntryKnowledgeSearch)
    assert e.seq == 0
    assert len(e.items) == 1
    assert e.items[0].library_name == "Lore"


def test_two_knowledge_search_calls_collapse_into_first() -> None:
    """Legacy data is lossy: both knowledge items are drained into the FIRST
    call's entry. The second call gets an empty list. Spec accepts this."""
    doc = _legacy_doc(
        tool_calls=[
            {"tool_call_id": "tc1", "tool_name": "knowledge_search",
             "arguments": {"query": "a"}, "success": True},
            {"tool_call_id": "tc2", "tool_name": "knowledge_search",
             "arguments": {"query": "b"}, "success": True},
        ],
        knowledge_context=[
            {"library_name": "L", "document_title": "D1",
             "heading_path": [], "content": "x"},
            {"library_name": "L", "document_title": "D2",
             "heading_path": [], "content": "y"},
        ],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 2
    assert isinstance(events[0], TimelineEntryKnowledgeSearch)
    assert events[0].seq == 0
    assert len(events[0].items) == 2
    assert isinstance(events[1], TimelineEntryKnowledgeSearch)
    assert events[1].seq == 1
    assert events[1].items == []


def test_web_search() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1", "tool_name": "web_search",
            "arguments": {"query": "x"}, "success": True,
        }],
        web_search_context=[
            {"title": "T", "url": "https://example.test", "snippet": "s",
             "source_type": "search"},
        ],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    assert isinstance(events[0], TimelineEntryWebSearch)
    assert events[0].seq == 0
    assert events[0].items[0].url == "https://example.test"


def test_create_artefact() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1", "tool_name": "create_artefact",
            "arguments": {"handle": "h", "title": "t"},
            "success": True,
        }],
        artefact_refs=[{
            "artefact_id": "a1", "handle": "h", "title": "t",
            "artefact_type": "code", "operation": "create",
        }],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    assert isinstance(events[0], TimelineEntryArtefact)
    assert events[0].seq == 0
    assert events[0].ref.handle == "h"


def test_generate_image() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1", "tool_name": "generate_image",
            "arguments": {"prompt": "a cat"}, "success": True,
            "moderated_count": 1,
        }],
        image_refs=[{
            "id": "img1", "blob_url": "/b/1", "thumb_url": "/t/1",
            "width": 64, "height": 64, "prompt": "a cat",
            "model_id": "m", "tool_call_id": "tc1",
        }],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    assert isinstance(events[0], TimelineEntryImage)
    assert events[0].seq == 0
    assert len(events[0].refs) == 1
    assert events[0].refs[0].id == "img1"
    assert events[0].moderated_count == 1


def test_unknown_tool_falls_through_to_generic() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1", "tool_name": "some_random_tool",
            "arguments": {"x": 1}, "success": True,
        }],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, TimelineEntryToolCall)
    assert e.tool_name == "some_random_tool"
    assert e.success is True


# ---------------------------------------------------------------------------
# Failure / missing data
# ---------------------------------------------------------------------------

def test_failed_knowledge_search_becomes_generic_tool_call() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1", "tool_name": "knowledge_search",
            "arguments": {"query": "boom"}, "success": False,
        }],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, TimelineEntryToolCall)
    assert e.tool_name == "knowledge_search"
    assert e.success is False


def test_missing_artefact_ref_falls_back_to_generic() -> None:
    doc = _legacy_doc(
        tool_calls=[{
            "tool_call_id": "tc1", "tool_name": "create_artefact",
            "arguments": {"handle": "h"}, "success": True,
        }],
        # No artefact_refs key — legacy data was lossy.
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, TimelineEntryToolCall)
    assert e.tool_name == "create_artefact"


# ---------------------------------------------------------------------------
# No tool_calls but populated context (very early documents)
# ---------------------------------------------------------------------------

def test_orphan_knowledge_context_without_tool_calls() -> None:
    doc = _legacy_doc(
        knowledge_context=[
            {"library_name": "L", "document_title": "D",
             "heading_path": [], "content": "x"},
        ],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    assert isinstance(events[0], TimelineEntryKnowledgeSearch)
    assert events[0].seq == 0
    assert len(events[0].items) == 1


def test_orphan_web_search_context_without_tool_calls() -> None:
    doc = _legacy_doc(
        web_search_context=[
            {"title": "t", "url": "u", "snippet": "s", "source_type": "search"},
        ],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert len(events) == 1
    assert isinstance(events[0], TimelineEntryWebSearch)


# ---------------------------------------------------------------------------
# Mixed tools — order is preserved, seq is monotonic
# ---------------------------------------------------------------------------

def test_mixed_tools_preserve_order_and_assign_monotonic_seq() -> None:
    doc = _legacy_doc(
        tool_calls=[
            {"tool_call_id": "tc1", "tool_name": "knowledge_search",
             "arguments": {}, "success": True},
            {"tool_call_id": "tc2", "tool_name": "web_search",
             "arguments": {}, "success": True},
            {"tool_call_id": "tc3", "tool_name": "create_artefact",
             "arguments": {"handle": "h"}, "success": True},
        ],
        knowledge_context=[
            {"library_name": "L", "document_title": "D",
             "heading_path": [], "content": "x"},
        ],
        web_search_context=[
            {"title": "t", "url": "u", "snippet": "s", "source_type": "search"},
        ],
        artefact_refs=[{
            "artefact_id": "a1", "handle": "h", "title": "t",
            "artefact_type": "code", "operation": "create",
        }],
    )

    events = synthesise_events(doc)

    assert events is not None
    assert [e.seq for e in events] == [0, 1, 2]
    assert isinstance(events[0], TimelineEntryKnowledgeSearch)
    assert isinstance(events[1], TimelineEntryWebSearch)
    assert isinstance(events[2], TimelineEntryArtefact)


# ---------------------------------------------------------------------------
# Documents with `events` already present must NOT be synthesised
# ---------------------------------------------------------------------------

def test_message_to_dto_uses_existing_events_without_synthesising() -> None:
    """When the document already carries an ``events`` list, the read path
    must use it verbatim and never run synthesis."""
    from datetime import datetime, timezone
    doc = {
        "_id": "msg-1",
        "session_id": "sess-1",
        "role": "assistant",
        "content": "hello",
        "token_count": 1,
        "created_at": datetime.now(timezone.utc),
        "events": [
            {"kind": "web_search", "seq": 0, "items": []},
        ],
        # Legacy fields are also present but must be ignored — events wins.
        "tool_calls": [{
            "tool_call_id": "tc1", "tool_name": "knowledge_search",
            "arguments": {}, "success": True,
        }],
        "knowledge_context": [
            {"library_name": "L", "document_title": "D",
             "heading_path": [], "content": "x"},
        ],
    }

    dto = ChatRepository.message_to_dto(doc)

    assert dto.events is not None
    assert len(dto.events) == 1
    assert dto.events[0].kind == "web_search"


def test_synthesise_returns_none_for_doc_with_only_events_key() -> None:
    """Standalone synthesis call: a doc that has no legacy keys returns None,
    even if it has an ``events`` key — synthesis is for legacy data only."""
    doc = _legacy_doc(events=[
        {"kind": "web_search", "seq": 0, "items": []},
    ])
    # ``events`` key alone does not trigger synthesis.
    assert synthesise_events(doc) is None
