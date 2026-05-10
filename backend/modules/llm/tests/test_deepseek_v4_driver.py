"""Tests for DeepSeekV4Driver — capability spec, request body, chunk parsing."""
from __future__ import annotations

import pytest

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._drivers import match_driver
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)
from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_ollama_cloud,
    build_request_for_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_ollama_cloud,
    parse_chunk_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._quirks import (
    _is_or_flash_quirk_applicable,
)
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


def test_deepseek_v4_capability_spec_for_openrouter():
    spec = deepseek_v4_capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")

    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is not None
    assert spec.reasoning.effort.buckets == ["high", "max"]
    assert spec.reasoning.effort.default_bucket == "high"
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_deepseek_v4_capability_spec_is_router_agnostic_for_now():
    """Plan 1 ships only the OR builder; capability spec at this stage is
    identical regardless of (adapter_type, slug). Plans 2-4 may diverge it
    per router (e.g. Novita drops 'max' from effort buckets)."""
    or_spec = deepseek_v4_capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")
    nano_spec = deepseek_v4_capability_spec(adapter_type="nano_gpt_http", slug="deepseek/deepseek-v4-pro:thinking")
    assert or_spec == nano_spec


def _make_request(
    *, effort: str | None, reasoning_mode: str = "on",
) -> CompletionRequest:
    """Build a minimal CompletionRequest for builder tests.

    ``effort`` maps to ``extras.reasoning_effort``.
    ``reasoning_mode`` is "on" or "off" — maps to ``extras.reasoning_mode``.
    """
    return CompletionRequest(
        model="deepseek/deepseek-v4-pro",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="Hello")],
            )
        ],
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["high", "max"], default_bucket="high",
            ),
            default_on=True,
        ),
        tools_capability=ToolCapability(supported=False),
        extras=ChatSessionExtras(
            tools_enabled=False,
            reasoning_mode=reasoning_mode,
            reasoning_effort=effort,
        ),
    )


def test_builder_or_reasoning_off():
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="off"),
    )
    assert body["model"] == "deepseek/deepseek-v4-pro"
    assert body["stream"] is True
    assert body["reasoning"] == {"enabled": False}


def test_builder_or_reasoning_on_no_effort():
    """Reasoning on without explicit effort: pass through unchanged
    (existing builder emits {"enabled": True} with no effort field;
    OR uses its own default)."""
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="on"),
    )
    assert body["reasoning"] == {"enabled": True}


def test_builder_or_reasoning_high():
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert body["reasoning"] == {"enabled": True, "effort": "high"}


def test_builder_or_reasoning_max_translates_to_xhigh():
    """User-effort 'max' maps to OR's 'xhigh' (which OR translates to
    DeepSeek-native max upstream — see research doc)."""
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["reasoning"] == {"enabled": True, "effort": "xhigh"}


def test_builder_or_rejects_unknown_effort():
    with pytest.raises(ValueError, match="effort"):
        build_request_for_openrouter(
            slug="deepseek/deepseek-v4-pro",
            request=_make_request(effort="garbage_xyz"),
        )


def test_builder_or_inherits_message_translation():
    """The builder delegates to build_request_body, so ContentPart-to-string
    message translation is inherited automatically (the existing
    _translate_message helper converts list[ContentPart] to a string)."""
    body = build_request_for_openrouter(
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


def test_parser_or_extracts_visible_content():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{"index": 0, "delta": {"content": "Hello", "role": "assistant"}}],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    assert any(isinstance(e, ContentDelta) and e.delta == "Hello" for e in events)


def test_parser_or_extracts_reasoning_from_delta_reasoning():
    """OR's canonical CoT key is delta.reasoning (often paired with reasoning_details).
    The driver maps it to ThinkingDelta (the existing event class name; reasoning
    and thinking are used interchangeably in the codebase — INS-038)."""
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{"index": 0, "delta": {
            "content": "",
            "role": "assistant",
            "reasoning": "We need to think...",
            "reasoning_details": [
                {"type": "reasoning.text", "text": "We need to think...", "format": "unknown", "index": 0}
            ],
        }}],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    assert any(
        isinstance(e, ThinkingDelta) and e.delta == "We need to think..."
        for e in events
    )


def test_parser_or_emits_stream_done_with_usage_and_reasoning_tokens():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 800,
            "total_tokens": 819,
            "completion_tokens_details": {"reasoning_tokens": 360, "image_tokens": 0, "audio_tokens": 0},
        },
    }
    events = parse_chunk_openrouter(chunk=chunk)
    done = next((e for e in events if isinstance(e, StreamDone)), None)
    assert done is not None
    assert done.input_tokens == 19
    assert done.output_tokens == 800
    assert done.reasoning_tokens == 360


def test_parser_or_handles_chunk_with_no_actionable_delta():
    """Chunks with empty delta and no finish_reason produce no events."""
    chunk = {"id": "gen-1", "choices": [{"index": 0, "delta": {}}]}
    events = parse_chunk_openrouter(chunk=chunk)
    assert events == []


def test_dsv4_driver_class_matches_or_slugs():
    assert match_driver("deepseek/deepseek-v4-pro") is DeepSeekV4Driver
    assert match_driver("deepseek/deepseek-v4-flash") is DeepSeekV4Driver


def test_dsv4_driver_class_matches_unprefixed_ollama_slug():
    assert match_driver("deepseek-v4-pro") is DeepSeekV4Driver


def test_dsv4_driver_capability_spec_via_class():
    d = DeepSeekV4Driver()
    spec = d.capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")
    assert spec.reasoning.effort.buckets == ["high", "max"]


def test_dsv4_driver_build_request_via_class_for_or():
    d = DeepSeekV4Driver()
    body = d.build_request(
        adapter_type="openrouter_http",
        slug="deepseek/deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["reasoning"] == {"enabled": True, "effort": "xhigh"}


def test_dsv4_driver_build_request_for_unsupported_adapter_raises():
    """Plan 1 supports OR only; Plan 2 added Ollama. nano-gpt/Novita come in Plans 3-4."""
    d = DeepSeekV4Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        d.build_request(
            adapter_type="nano_gpt_http",
            slug="deepseek/deepseek-v4-pro:thinking",
            request=_make_request(effort="high"),
        )


def test_builder_ollama_reasoning_off():
    """reasoning_mode='off' → think=false, no effort translation."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="off"),
    )
    assert body["model"] == "deepseek/deepseek-v4-pro"
    assert body["stream"] is True
    assert body["think"] is False


def test_builder_ollama_reasoning_on_no_effort():
    """reasoning_mode='on' with no explicit effort: think=true (existing default)."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="on"),
    )
    assert body["think"] is True


def test_builder_ollama_reasoning_high():
    """user effort='high' → think=true (boolean, per research doc Probe B)."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert body["think"] is True


def test_builder_ollama_reasoning_max_translates_to_string():
    """user effort='max' → think='max' (STRING, not bool — per research doc Probe C)."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["think"] == "max"
    # Sanity: not the boolean True. (json.dumps would serialise True → 'true',
    # which Ollama Cloud accepts but treats as default 'high'-like — wrong.)
    assert body["think"] is not True


def test_builder_ollama_rejects_unknown_effort():
    """Silent degradation is the failure mode this driver layer prevents."""
    with pytest.raises(ValueError, match="effort"):
        build_request_for_ollama_cloud(
            slug="deepseek-v4-pro",
            request=_make_request(effort="garbage_xyz"),
        )


def test_builder_ollama_inherits_message_translation():
    """Delegate to existing build_request_body → ContentPart-to-string handled."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


def test_parser_ollama_extracts_visible_content():
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": "Hello"},
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    assert any(isinstance(e, ContentDelta) and e.delta == "Hello" for e in events)


def test_parser_ollama_extracts_thinking_from_message_thinking():
    """Ollama Cloud's CoT key is message.thinking (Anthropic-style on the
    Ollama native envelope; see research doc Probe B)."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": "", "thinking": "We need to think..."},
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    assert any(
        isinstance(e, ThinkingDelta) and e.delta == "We need to think..."
        for e in events
    )


def test_parser_ollama_emits_stream_done_with_eval_counts():
    """Ollama returns prompt_eval_count + eval_count on the done chunk; eval_count
    bundles thinking + visible (no separate reasoning_tokens — see research doc)."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "stop",
        "total_duration": 615230395,
        "prompt_eval_count": 19,
        "eval_count": 789,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    done = next((e for e in events if isinstance(e, StreamDone)), None)
    assert done is not None
    assert done.input_tokens == 19
    assert done.output_tokens == 789
    # Ollama does not split reasoning out — it stays None.
    assert done.reasoning_tokens is None


def test_parser_ollama_emits_stream_refused_on_content_filter():
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "content_filter",
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "content_filter"
    # No StreamDone when refused — refusal is the terminal event.
    assert not any(isinstance(e, StreamDone) for e in events)


def test_parser_ollama_emits_stream_refused_with_refusal_text():
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": "", "refusal": "I cannot help with that."},
        "done": True,
        "done_reason": "refusal",
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "refusal"
    assert refused.refusal_text == "I cannot help with that."


def test_parser_ollama_handles_chunk_with_no_actionable_delta():
    """Empty message + done=False → no events."""
    chunk = {"model": "deepseek-v4-pro", "message": {"content": ""}, "done": False}
    events = parse_chunk_ollama_cloud(chunk=chunk)
    assert events == []


def test_parser_or_emits_stream_refused_on_content_filter():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{
            "index": 0,
            "delta": {"content": "", "role": "assistant"},
            "finish_reason": "content_filter",
        }],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "content_filter"


def test_parser_or_emits_stream_refused_with_refusal_text():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{
            "index": 0,
            "delta": {"content": "", "role": "assistant", "refusal": "Cannot help."},
            "finish_reason": "refusal",
        }],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "refusal"
    assert refused.refusal_text == "Cannot help."


def test_parser_or_does_not_emit_refused_on_normal_stop():
    """Sanity: finish_reason='stop' must NOT produce StreamRefused."""
    chunk = {
        "id": "gen-1",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19, "completion_tokens": 800, "total_tokens": 819,
            "completion_tokens_details": {"reasoning_tokens": 360},
        },
    }
    events = parse_chunk_openrouter(chunk=chunk)
    assert not any(isinstance(e, StreamRefused) for e in events)
    # Should still emit StreamDone.
    assert any(isinstance(e, StreamDone) for e in events)


def test_parser_or_refused_case_insensitive():
    """The driver normalises finish_reason to lowercase before checking
    _REFUSAL_REASONS — exercises the intentional widening over the
    legacy parser (which uses exact match)."""
    chunk = {
        "id": "gen-1",
        "choices": [{
            "index": 0,
            "delta": {"content": "", "role": "assistant"},
            "finish_reason": "Content_Filter",  # mixed case
        }],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    # Reason preserves the original casing — only the check is normalised.
    assert refused.reason == "Content_Filter"


def test_dsv4_driver_build_request_via_class_for_ollama_cloud():
    d = DeepSeekV4Driver()
    body = d.build_request(
        adapter_type="ollama_http",
        slug="deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["think"] == "max"
    # body["model"] comes from request.model, which the _make_request fixture
    # sets to "deepseek/deepseek-v4-pro" (prefixed). The driver's `slug`
    # parameter is for dispatch only — it does NOT override the body model.
    assert body["model"] == "deepseek/deepseek-v4-pro"


def test_dsv4_driver_parse_chunk_via_class_for_ollama_cloud():
    d = DeepSeekV4Driver()
    events = d.parse_chunk(
        adapter_type="ollama_http",
        slug="deepseek-v4-pro",
        chunk={
            "model": "deepseek-v4-pro",
            "message": {"role": "assistant", "content": "Hi"},
            "done": False,
        },
    )
    assert any(isinstance(e, ContentDelta) and e.delta == "Hi" for e in events)


def test_dsv4_driver_parse_chunk_for_unsupported_adapter_raises():
    """Symmetric to test_dsv4_driver_build_request_for_unsupported_adapter_raises
    (Gap C — Plan 1 only had this test for build_request)."""
    d = DeepSeekV4Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        d.parse_chunk(
            adapter_type="nano_gpt_http",
            slug="deepseek/deepseek-v4-pro:thinking",
            chunk={"id": "x", "choices": [{"index": 0, "delta": {"content": "Hi"}}]},
        )


def test_dsv4_driver_build_request_for_unsupported_adapter_still_raises_on_novita():
    """Plan 2 added Ollama, NOT Novita. Novita must still raise."""
    d = DeepSeekV4Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        d.build_request(
            adapter_type="novita_http",
            slug="deepseek/deepseek-v4-pro",
            request=_make_request(effort="high"),
        )


def test_parser_ollama_emits_tool_call_event_for_single_call():
    """Ollama Cloud delivers tool-calls atomically in a single NDJSON chunk
    (no streaming accumulation). One entry → one ToolCallEvent."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_5ysinpeh",
                "function": {
                    "index": 0,
                    "name": "get_time",
                    "arguments": {"timezone": "Asia/Tokyo"},
                },
            }],
        },
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1
    tc = tool_calls[0]
    assert tc.id == "call_5ysinpeh"
    assert tc.name == "get_time"
    # arguments is a JSON-encoded STRING per ToolCallEvent contract,
    # not the dict that Ollama delivers on the wire.
    assert tc.arguments == '{"timezone": "Asia/Tokyo"}'


def test_parser_ollama_emits_multiple_tool_call_events_for_parallel_calls():
    """Multiple parallel tool-calls arrive as a single chunk with a list of
    entries; the parser emits one ToolCallEvent per entry, in order."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_iprdkyx2", "function": {"index": 0, "name": "get_weather", "arguments": {"city": "Berlin"}}},
                {"id": "call_idgrvibj", "function": {"index": 1, "name": "get_weather", "arguments": {"city": "Tokyo"}}},
            ],
        },
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 2
    assert tool_calls[0].id == "call_iprdkyx2"
    assert tool_calls[0].name == "get_weather"
    assert tool_calls[0].arguments == '{"city": "Berlin"}'
    assert tool_calls[1].id == "call_idgrvibj"
    assert tool_calls[1].name == "get_weather"
    assert tool_calls[1].arguments == '{"city": "Tokyo"}'


def test_parser_ollama_synthesises_id_when_missing():
    """Defence in depth: if Ollama ever omits tool_call.id, the parser
    synthesises a stable-shape ID rather than crashing or sending an
    empty string downstream."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {"name": "noop", "arguments": {}},
            }],
        },
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].id.startswith("call_")
    assert len(tool_calls[0].id) == len("call_") + 12  # 12 hex chars after the prefix


def test_parser_ollama_thinking_and_content_chunks_emit_no_tool_calls():
    """Sanity: chunks that carry only thinking or content (no tool_calls
    key) MUST NOT emit any ToolCallEvent. Probe C confirmed Ollama never
    sends thinking + tool_calls in the same chunk; this guard ensures the
    parser stays correct if that invariant ever shifts."""
    thinking_chunk = {"message": {"thinking": "let me think"}, "done": False}
    content_chunk = {"message": {"content": "hello"}, "done": False}
    assert not any(
        isinstance(e, ToolCallEvent)
        for e in parse_chunk_ollama_cloud(chunk=thinking_chunk)
    )
    assert not any(
        isinstance(e, ToolCallEvent)
        for e in parse_chunk_ollama_cloud(chunk=content_chunk)
    )


def test_parser_or_accumulates_streamed_tool_call_fragments():
    """OR streams tool-calls incrementally — first chunk has id+name with
    empty args, subsequent chunks add args fragments. The accumulator
    builds the full call; emission happens on finish_reason='tool_calls'."""
    acc = ToolCallAccumulator()

    # Header chunk: id + name, empty args
    chunk_header = {
        "id": "gen-1", "provider": "Novita",
        "choices": [{"index": 0, "delta": {
            "content": None, "role": "assistant",
            "tool_calls": [{
                "index": 0, "id": "call_00_xyz", "type": "function",
                "function": {"name": "get_time", "arguments": ""},
            }],
        }, "finish_reason": None}],
    }
    events = parse_chunk_openrouter(chunk=chunk_header, tool_acc=acc)
    # Header chunk yields no event yet — args still streaming.
    assert events == []

    # Args fragments
    for frag in ('{', '"', 'tz', '"', ': ', '"', 'UTC', '"', '}'):
        chunk_frag = {
            "choices": [{"index": 0, "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": frag},
                }],
            }, "finish_reason": None}],
        }
        assert parse_chunk_openrouter(chunk=chunk_frag, tool_acc=acc) == []

    # Terminal chunk: finish_reason='tool_calls' triggers emission
    chunk_done = {
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                  "completion_tokens_details": {"reasoning_tokens": 0}},
    }
    events = parse_chunk_openrouter(chunk=chunk_done, tool_acc=acc)
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_00_xyz"
    assert tool_calls[0].name == "get_time"
    assert tool_calls[0].arguments == '{"tz": "UTC"}'
    # Usage in same chunk → also emit StreamDone (NOT mutually exclusive
    # with ToolCallEvent — only mutual with StreamRefused).
    assert any(isinstance(e, StreamDone) for e in events)


def test_parser_or_accumulates_parallel_tool_calls_with_distinct_indices():
    """Parallel tool-calls arrive sequentially per-index (all index=0
    fragments first, then all index=1). The accumulator keys on `index`,
    so the order doesn't matter — but we verify the OR wire-shape ordering."""
    acc = ToolCallAccumulator()

    # index=0 header + args
    parse_chunk_openrouter(chunk={
        "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "call_00_a", "type": "function",
            "function": {"name": "get_weather", "arguments": ""},
        }]}, "finish_reason": None}],
    }, tool_acc=acc)
    for frag in ('{"city": "', 'Berlin', '"}'):
        parse_chunk_openrouter(chunk={
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": frag},
            }]}, "finish_reason": None}],
        }, tool_acc=acc)

    # index=1 header + args
    parse_chunk_openrouter(chunk={
        "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 1, "id": "call_01_b", "type": "function",
            "function": {"name": "get_weather", "arguments": ""},
        }]}, "finish_reason": None}],
    }, tool_acc=acc)
    for frag in ('{"city": "', 'Tokyo', '"}'):
        parse_chunk_openrouter(chunk={
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 1, "function": {"arguments": frag},
            }]}, "finish_reason": None}],
        }, tool_acc=acc)

    # Terminal
    events = parse_chunk_openrouter(chunk={
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }, tool_acc=acc)
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 2
    # Sorted by index in finalised()
    assert tool_calls[0].id == "call_00_a"
    assert tool_calls[0].arguments == '{"city": "Berlin"}'
    assert tool_calls[1].id == "call_01_b"
    assert tool_calls[1].arguments == '{"city": "Tokyo"}'


def test_parser_or_without_accumulator_silently_skips_tool_calls():
    """Back-compat: when caller passes no accumulator, tool_call fragments
    are silently skipped. Used by callers that genuinely don't care
    (today: no caller; this is defence-in-depth for future code paths)."""
    chunk = {
        "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "call_x", "function": {"name": "noop", "arguments": "{}"},
        }]}, "finish_reason": "tool_calls"}],
    }
    # No tool_acc passed — should not crash, should emit no tool events
    events = parse_chunk_openrouter(chunk=chunk)
    assert not any(isinstance(e, ToolCallEvent) for e in events)


def test_parser_or_accumulator_idempotent_finalise():
    """If finalised() runs twice (e.g. provider sends two finish chunks
    with finish_reason='tool_calls'), no duplicate ToolCallEvent."""
    acc = ToolCallAccumulator()
    parse_chunk_openrouter(chunk={
        "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "call_x", "type": "function",
            "function": {"name": "noop", "arguments": "{}"},
        }]}, "finish_reason": None}],
    }, tool_acc=acc)
    first = parse_chunk_openrouter(chunk={
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }, tool_acc=acc)
    second = parse_chunk_openrouter(chunk={
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }, tool_acc=acc)
    assert sum(1 for e in first if isinstance(e, ToolCallEvent)) == 1
    assert sum(1 for e in second if isinstance(e, ToolCallEvent)) == 0


def test_dsv4_driver_accumulator_is_per_instance():
    """A fresh DeepSeekV4Driver instance gets a fresh accumulator. Two
    instances (e.g. two parallel inference iterations) do not share state."""
    d1 = DeepSeekV4Driver()
    d2 = DeepSeekV4Driver()
    assert d1._or_tool_acc is not d2._or_tool_acc
    # And the same instance reuses the same accumulator across parse_chunk calls
    d3 = DeepSeekV4Driver()
    acc_ref = d3._or_tool_acc
    d3.parse_chunk(adapter_type="openrouter_http", slug="deepseek-v4-pro", chunk={
        "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "call_x", "type": "function",
            "function": {"name": "noop", "arguments": ""},
        }]}, "finish_reason": None}],
    })
    assert d3._or_tool_acc is acc_ref


@pytest.mark.parametrize(
    "adapter_type,slug,expected",
    [
        # OR + Flash variants: quirk applies
        ("openrouter_http", "deepseek/deepseek-v4-flash", True),
        ("openrouter_http", "deepseek-v4-flash", True),
        ("openrouter_http", "DEEPSEEK/DEEPSEEK-V4-FLASH", True),
        # OR + non-Flash: quirk does not apply
        ("openrouter_http", "deepseek/deepseek-v4-pro", False),
        ("openrouter_http", "deepseek-v4-pro", False),
        # Ollama + Flash: quirk does not apply (Ollama path works)
        ("ollama_http", "deepseek-v4-flash", False),
        ("ollama_http", "deepseek/deepseek-v4-flash", False),
        # Other adapters + Flash: quirk does not apply
        ("nano_gpt_http", "deepseek/deepseek-v4-flash", False),
        ("novita_http", "deepseek/deepseek-v4-flash", False),
    ],
)
def test_or_flash_quirk_applicable(adapter_type: str, slug: str, expected: bool) -> None:
    assert _is_or_flash_quirk_applicable(adapter_type, slug) is expected
