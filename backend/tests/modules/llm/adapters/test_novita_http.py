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
    _build_chat_payload,
    _chunk_to_events,
    _parse_sse_line,
    _ToolCallAccumulator,
    _translate_message,
)
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    _PREMIUM_ONLY_ADAPTERS,
    get_adapter_class,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
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


def test_translate_text_only_user_message():
    msg = CompletionMessage(role="user",
                            content=[ContentPart(type="text", text="hi")])
    assert _translate_message(msg) == {"role": "user", "content": "hi"}


def test_translate_image_message_uses_openai_image_url_format():
    msg = CompletionMessage(role="user", content=[
        ContentPart(type="text", text="describe"),
        ContentPart(type="image", data="aGVsbG8=", media_type="image/png"),
    ])
    out = _translate_message(msg)
    assert out["role"] == "user"
    assert isinstance(out["content"], list)
    assert out["content"][0] == {"type": "text", "text": "describe"}
    assert out["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
    }


def test_build_payload_passes_model_through():
    req = CompletionRequest(
        model="xiaomimimo/mimo-v2.5-pro",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["model"] == "xiaomimimo/mimo-v2.5-pro"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_includes_temperature_when_set():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        temperature=0.4,
    )
    assert _build_chat_payload(req)["temperature"] == 0.4


def test_build_payload_omits_temperature_when_none():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    assert "temperature" not in _build_chat_payload(req)


def test_build_payload_translates_tools():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        tools=[ToolDefinition(
            name="lookup", description="d", parameters={"type": "object"},
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "lookup", "description": "d",
            "parameters": {"type": "object"},
        },
    }]


def test_reasoning_field_omitted_when_enabled_and_supported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=True, reasoning_enabled=True,
    )
    assert "reasoning" not in _build_chat_payload(req)


def test_reasoning_field_set_to_exclude_when_disabled_and_supported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=True, reasoning_enabled=False,
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning"] == {"exclude": True}


def test_reasoning_field_omitted_when_unsupported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=False, reasoning_enabled=True,
    )
    assert "reasoning" not in _build_chat_payload(req)


def test_translate_assistant_with_tool_calls():
    from shared.dtos.inference import ToolCallResult
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="")],
        tool_calls=[ToolCallResult(id="c1", name="lookup", arguments='{"q":1}')],
    )
    out = _translate_message(msg)
    assert out["tool_calls"] == [{
        "id": "c1", "type": "function",
        "function": {"name": "lookup", "arguments": '{"q":1}'},
    }]


def test_translate_tool_message_carries_tool_call_id():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text="42")],
        tool_call_id="c1",
    )
    out = _translate_message(msg)
    assert out["tool_call_id"] == "c1"
