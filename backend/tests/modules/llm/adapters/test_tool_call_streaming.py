from backend.modules.llm._adapters._events import ToolCallArgsDelta
from backend.modules.llm._adapters._tool_call_streaming import (
    fragments_to_delta_events,
)


class _FakeAccumulator:
    """Minimal stand-in for _ToolCallAccumulator, exposing the slot dict and
    capturing ingested fragments. Real accumulators live per-adapter; the
    helper only touches `_by_index` for read access and calls `.ingest()`."""

    def __init__(self):
        self._by_index: dict[int, dict] = {}
        self.ingested: list[list[dict]] = []

    def ingest(self, frags: list[dict]) -> None:
        self.ingested.append(frags)
        for f in frags:
            idx = f.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(
                idx, {"id": None, "name": "", "args": ""},
            )
            if f.get("id"):
                slot["id"] = f["id"]
            fn = f.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]


def test_emits_one_event_per_fragment_with_args():
    acc = _FakeAccumulator()
    frags = [
        {"index": 0, "id": "call_x", "function": {"name": "search", "arguments": '{"q'}},
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]
    events = fragments_to_delta_events(frags, acc)
    assert len(events) == 2
    assert events[0] == ToolCallArgsDelta(
        index=0, id="call_x", name="search", arguments_delta='{"q',
    )
    assert events[1] == ToolCallArgsDelta(
        index=0, id="call_x", name="search", arguments_delta='":"x"}',
    )
    # accumulator was fed
    assert acc.ingested == [frags]


def test_emits_for_id_or_name_even_without_args():
    """First fragment often carries only id and name, no arguments yet."""
    acc = _FakeAccumulator()
    frags = [
        {"index": 0, "id": "call_x", "function": {"name": "search"}},
    ]
    events = fragments_to_delta_events(frags, acc)
    assert len(events) == 1
    assert events[0].arguments_delta == ""
    assert events[0].id == "call_x"
    assert events[0].name == "search"


def test_skips_fragments_without_index():
    """Some upstream chunks contain top-level tool_calls but no per-index
    fragments (e.g. heartbeats). Skip them entirely."""
    acc = _FakeAccumulator()
    frags = [{"function": {"arguments": "x"}}]
    events = fragments_to_delta_events(frags, acc)
    assert events == []


def test_resolves_id_from_accumulator_state_when_fragment_omits_it():
    acc = _FakeAccumulator()
    # First fragment seeds the id.
    fragments_to_delta_events(
        [{"index": 0, "id": "call_x", "function": {"name": "s"}}], acc,
    )
    # Second fragment omits id — helper resolves from accumulator state.
    events = fragments_to_delta_events(
        [{"index": 0, "function": {"arguments": "y"}}], acc,
    )
    assert events[0].id == "call_x"


def test_parallel_calls_separate_indices():
    acc = _FakeAccumulator()
    frags = [
        {"index": 0, "id": "a", "function": {"name": "f", "arguments": "1"}},
        {"index": 1, "id": "b", "function": {"name": "g", "arguments": "2"}},
    ]
    events = fragments_to_delta_events(frags, acc)
    assert len(events) == 2
    assert events[0].index == 0 and events[0].id == "a"
    assert events[1].index == 1 and events[1].id == "b"
