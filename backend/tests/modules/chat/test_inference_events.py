"""Unit tests for the timeline-entry construction inside _inference.py.

The inference loop itself is hard to exercise in isolation (it owns the
WebSocket emit_fn, the LLM stream, the cancel event, and the save callback),
so we test the pure helper ``make_timeline_entry`` that the loop now calls
once per completed tool. The helper covers the entire mapping table from
the spec, including the failure-path collapse to a generic ``tool_call``.
"""

from backend.modules.chat._inference import make_timeline_entry
from shared.dtos.chat import (
    ArtefactRefDto,
    KnowledgeContextItem,
    TimelineEntryArtefact,
    TimelineEntryImage,
    TimelineEntryKnowledgeSearch,
    TimelineEntryToolCall,
    TimelineEntryWebSearch,
    WebSearchContextItemDto,
)
from shared.dtos.images import ImageRefDto


# ---------------------------------------------------------------------------
# Per-tool kind mapping
# ---------------------------------------------------------------------------

def test_knowledge_search_maps_to_knowledge_entry() -> None:
    entry = make_timeline_entry(
        seq=0,
        tool_name="knowledge_search",
        tool_call_id="tc1",
        arguments={"query": "x"},
        success=True,
        knowledge_results=[
            {"library_name": "L", "document_title": "D",
             "heading_path": [], "content": "x"},
        ],
    )
    assert isinstance(entry, TimelineEntryKnowledgeSearch)
    assert entry.seq == 0
    assert len(entry.items) == 1
    assert entry.items[0].library_name == "L"


def test_knowledge_search_accepts_already_typed_items() -> None:
    item = KnowledgeContextItem(
        library_name="L", document_title="D",
        heading_path=[], content="x",
    )
    entry = make_timeline_entry(
        seq=1,
        tool_name="knowledge_search",
        tool_call_id="tc1",
        arguments={},
        success=True,
        knowledge_results=[item],
    )
    assert isinstance(entry, TimelineEntryKnowledgeSearch)
    assert entry.items[0] is item


def test_web_search_maps_to_web_entry() -> None:
    entry = make_timeline_entry(
        seq=2,
        tool_name="web_search",
        tool_call_id="tc1",
        arguments={"query": "x"},
        success=True,
        web_items=[
            {"title": "t", "url": "u", "snippet": "s", "source_type": "search"},
        ],
    )
    assert isinstance(entry, TimelineEntryWebSearch)
    assert entry.seq == 2
    assert entry.items[0].url == "u"


def test_web_fetch_maps_to_web_entry() -> None:
    entry = make_timeline_entry(
        seq=0,
        tool_name="web_fetch",
        tool_call_id="tc1",
        arguments={"url": "u"},
        success=True,
        web_items=[
            {"title": "t", "url": "u", "snippet": "s", "source_type": "fetch"},
        ],
    )
    assert isinstance(entry, TimelineEntryWebSearch)
    assert entry.items[0].source_type == "fetch"


def test_create_artefact_with_ref_maps_to_artefact_entry() -> None:
    ref = ArtefactRefDto(
        artefact_id="a1", handle="h", title="t",
        artefact_type="code", operation="create",
    )
    entry = make_timeline_entry(
        seq=3,
        tool_name="create_artefact",
        tool_call_id="tc1",
        arguments={"handle": "h"},
        success=True,
        artefact_ref=ref,
    )
    assert isinstance(entry, TimelineEntryArtefact)
    assert entry.seq == 3
    assert entry.ref is ref


def test_update_artefact_with_ref_maps_to_artefact_entry() -> None:
    ref = ArtefactRefDto(
        artefact_id="a1", handle="h", title="t",
        artefact_type="code", operation="update",
    )
    entry = make_timeline_entry(
        seq=0,
        tool_name="update_artefact",
        tool_call_id="tc1",
        arguments={"handle": "h"},
        success=True,
        artefact_ref=ref,
    )
    assert isinstance(entry, TimelineEntryArtefact)
    assert entry.ref.operation == "update"


def test_create_artefact_without_ref_falls_back_to_generic() -> None:
    """If the artefact tool succeeded but no ref was produced (e.g. parse
    error), we still emit a generic tool_call so the pill renders."""
    entry = make_timeline_entry(
        seq=0,
        tool_name="create_artefact",
        tool_call_id="tc1",
        arguments={"handle": "h"},
        success=True,
        artefact_ref=None,
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.tool_name == "create_artefact"


def test_generate_image_maps_to_image_entry() -> None:
    ref = ImageRefDto(
        id="img1", blob_url="/b/1", thumb_url="/t/1",
        width=64, height=64, prompt="a cat",
        model_id="m", tool_call_id="tc1",
    )
    entry = make_timeline_entry(
        seq=4,
        tool_name="generate_image",
        tool_call_id="tc1",
        arguments={"prompt": "a cat"},
        success=True,
        image_refs=[ref],
        moderated_count=2,
    )
    assert isinstance(entry, TimelineEntryImage)
    assert entry.seq == 4
    assert entry.refs[0].id == "img1"
    assert entry.moderated_count == 2


def test_unknown_tool_maps_to_generic_tool_call() -> None:
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_random_tool",
        tool_call_id="tc1",
        arguments={"x": 1},
        success=True,
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.tool_name == "some_random_tool"
    assert entry.success is True


# ---------------------------------------------------------------------------
# Failure path always collapses to generic tool_call
# ---------------------------------------------------------------------------

def test_failed_knowledge_search_collapses_to_generic() -> None:
    entry = make_timeline_entry(
        seq=0,
        tool_name="knowledge_search",
        tool_call_id="tc1",
        arguments={"query": "boom"},
        success=False,
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.tool_name == "knowledge_search"
    assert entry.success is False


def test_failed_generate_image_collapses_to_generic() -> None:
    entry = make_timeline_entry(
        seq=0,
        tool_name="generate_image",
        tool_call_id="tc1",
        arguments={"prompt": "x"},
        success=False,
        moderated_count=4,
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.tool_name == "generate_image"
    assert entry.moderated_count == 4


# ---------------------------------------------------------------------------
# Sequence accumulation across a simulated tool sequence
# ---------------------------------------------------------------------------

def test_monotonic_seq_across_tool_sequence() -> None:
    """Mimic the inference loop: walk a list of tool completions, hand each
    to make_timeline_entry with the next seq, and verify the resulting list
    has [0, 1, 2, ...] in order with the right kinds."""
    tool_completions = [
        {"name": "knowledge_search", "tcid": "tc1", "success": True,
         "knowledge_results": []},
        {"name": "web_search", "tcid": "tc2", "success": True,
         "web_items": []},
        {"name": "create_artefact", "tcid": "tc3", "success": True,
         "artefact_ref": ArtefactRefDto(
             artefact_id="a", handle="h", title="t",
             artefact_type="code", operation="create",
         )},
        {"name": "knowledge_search", "tcid": "tc4", "success": True,
         "knowledge_results": [
             {"library_name": "L", "document_title": "D",
              "heading_path": [], "content": "x"},
         ]},
    ]

    events = []
    next_seq = 0
    for tc in tool_completions:
        events.append(make_timeline_entry(
            seq=next_seq,
            tool_name=tc["name"],
            tool_call_id=tc["tcid"],
            arguments={},
            success=tc["success"],
            knowledge_results=tc.get("knowledge_results"),
            web_items=tc.get("web_items"),
            artefact_ref=tc.get("artefact_ref"),
        ))
        next_seq += 1

    assert [e.seq for e in events] == [0, 1, 2, 3]
    assert isinstance(events[0], TimelineEntryKnowledgeSearch)
    assert isinstance(events[1], TimelineEntryWebSearch)
    assert isinstance(events[2], TimelineEntryArtefact)
    # Two knowledge_search calls produce TWO separate entries — provenance
    # is preserved for new documents (unlike the legacy synthesis path).
    assert isinstance(events[3], TimelineEntryKnowledgeSearch)
    assert len(events[3].items) == 1


# ---------------------------------------------------------------------------
# No legacy fields written: model_dump output keys
# ---------------------------------------------------------------------------

def test_dumped_events_have_no_legacy_field_keys() -> None:
    """When events are dumped for persistence, none of the legacy parallel
    field names should appear at the top level of any entry."""
    events = [
        make_timeline_entry(
            seq=0, tool_name="knowledge_search", tool_call_id="tc1",
            arguments={}, success=True, knowledge_results=[],
        ),
        make_timeline_entry(
            seq=1, tool_name="web_search", tool_call_id="tc2",
            arguments={}, success=True, web_items=[],
        ),
        make_timeline_entry(
            seq=2, tool_name="create_artefact", tool_call_id="tc3",
            arguments={}, success=True,
            artefact_ref=ArtefactRefDto(
                artefact_id="a", handle="h", title="t",
                artefact_type="code", operation="create",
            ),
        ),
    ]

    dumped = [e.model_dump() for e in events]

    legacy_keys = {
        "tool_calls", "knowledge_context", "web_search_context",
        "artefact_refs", "image_refs",
    }
    for entry in dumped:
        assert not (set(entry.keys()) & legacy_keys), (
            f"timeline entry leaked a legacy field name: {entry.keys()}"
        )


# Imports kept at module level for clarity but referenced here so flake8 /
# unused-import linters are happy if anyone runs them.
_ = WebSearchContextItemDto
