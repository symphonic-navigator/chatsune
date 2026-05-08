"""Tests for the Novita AI HTTP adapter.

Mirrors `test_openrouter_http.py`; coverage grows task by task.
"""

from __future__ import annotations

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
)
from backend.modules.llm._adapters._novita_http import (
    _SSE_DONE,
    NovitaHttpAdapter,
    _chunk_to_events,
    _parse_sse_line,
    _ToolCallAccumulator,
)
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    _PREMIUM_ONLY_ADAPTERS,
    get_adapter_class,
)


def test_adapter_identity():
    a = NovitaHttpAdapter()
    assert a.adapter_type == "novita_http"
    assert a.display_name == "Novita AI"
    assert a.view_id == "novita_http"
    assert a.secret_fields == frozenset({"api_key"})


def test_adapter_is_premium_only_not_user_creatable():
    # User-facing registry must NOT contain novita — it is premium-only.
    assert "novita_http" not in ADAPTER_REGISTRY
    # But the resolver helper should find it.
    assert get_adapter_class("novita_http") is NovitaHttpAdapter


def test_adapter_registered_in_premium_only_map():
    assert "novita_http" in _PREMIUM_ONLY_ADAPTERS
    assert _PREMIUM_ONLY_ADAPTERS["novita_http"] is NovitaHttpAdapter


def test_parse_sse_line_returns_dict_for_data_line():
    out = _parse_sse_line('data: {"a":1}')
    assert out == {"a": 1}


def test_parse_sse_line_returns_done_sentinel_for_done_marker():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_returns_none_for_empty_or_malformed():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("data: not json") is None


def test_chunk_emits_content_delta():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"content": "hi"}}]}, acc,
    )
    assert events == [ContentDelta(delta="hi")]


def test_chunk_emits_thinking_delta_for_reasoning_content():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning_content": "hmm"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="hmm")]


def test_chunk_emits_thinking_delta_for_plain_reasoning_key():
    """Some upstream models stream their thinking under a bare
    ``reasoning`` field. Adapter must produce a ThinkingDelta for either
    field (defensive — providers in the wild use either)."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning": "thinking"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking")]


def test_chunk_emits_stream_done_on_usage_chunk():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }, acc,
    )
    assert events == [StreamDone(input_tokens=10, output_tokens=20)]


def test_chunk_emits_refusal_on_content_filter():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"finish_reason": "content_filter", "delta": {}}]},
        acc,
    )
    assert any(isinstance(e, StreamRefused) for e in events)


def test_accumulator_collects_tool_call_across_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1",
                 "function": {"name": "lookup", "arguments": '{"q":'}}])
    acc.ingest([{"index": 0,
                 "function": {"arguments": '"hello"}'}}])
    finalised = acc.finalised()
    assert finalised == [{
        "id": "call_1", "name": "lookup", "arguments": '{"q":"hello"}',
    }]


def test_accumulator_finalised_is_idempotent():
    """Some upstreams emit two finish_reason="tool_calls" chunks for the
    same call. _chunk_to_events re-invokes finalised(), so a non-
    idempotent finalised() surfaces the same call as two ToolCallStarted
    events downstream."""
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1",
                 "function": {"name": "lookup", "arguments": "{}"}}])
    first = acc.finalised()
    second = acc.finalised()
    assert len(first) == 1
    assert second == []
