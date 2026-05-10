"""Result-content propagation through make_timeline_entry."""

from backend.modules.chat._inference import make_timeline_entry
from shared.dtos.chat import TimelineEntryToolCall


def test_make_timeline_entry_carries_result_content_on_success():
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_unknown_tool",   # falls through to generic tool_call branch
        tool_call_id="tc-1",
        arguments={"q": "x"},
        success=True,
        result_content="42",
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.result_content == "42"


def test_make_timeline_entry_carries_result_content_on_failure():
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_unknown_tool",
        tool_call_id="tc-2",
        arguments={"q": "x"},
        success=False,
        result_content="boom: tool not found",
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.result_content == "boom: tool not found"


def test_make_timeline_entry_defaults_result_content_to_none():
    """Old call sites without result_content keep working."""
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_unknown_tool",
        tool_call_id="tc-3",
        arguments={},
        success=True,
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.result_content is None
