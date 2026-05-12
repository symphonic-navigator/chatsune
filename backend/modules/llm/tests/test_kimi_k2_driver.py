"""Tests for KimiK2Driver — capability spec, request body, chunk parsing.

Mirrors the structure of test_mimo_v25_driver.py. Kimi K2 is a
two-adapter (Ollama Cloud + Novita) integration with per-(adapter, slug)
reasoning capability differences:

- Ollama Cloud (k2.5, k2.6): optional reasoning, ``think: true/false``
- Novita k2.5: no_reasoning (provider returns empty reasoning_content)
- Novita k2.6: always_on (provider ignores reasoning toggle)

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that motivate this matrix.
"""
from __future__ import annotations

import pytest

from backend.modules.llm._drivers import match_driver
from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver


_OLLAMA_K25 = "kimi-k2.5"
_OLLAMA_K26 = "kimi-k2.6"
_NOVITA_K25 = "moonshotai/kimi-k2.5"
_NOVITA_K26 = "moonshotai/kimi-k2.6"


# --- match_driver ----------------------------------------------------------


def test_match_driver_ollama_k25() -> None:
    assert match_driver(_OLLAMA_K25) is KimiK2Driver


def test_match_driver_ollama_k26() -> None:
    assert match_driver(_OLLAMA_K26) is KimiK2Driver


def test_match_driver_novita_k25_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_K25) is KimiK2Driver


def test_match_driver_novita_k26_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_K26) is KimiK2Driver


def test_match_driver_does_not_match_older_kimi() -> None:
    """K2.4 and earlier are not first-class — the driver targets K2.5+."""
    assert match_driver("kimi-k2.4") is None
    assert match_driver("moonshotai/kimi-k2") is None


def test_match_driver_does_not_match_unrelated_moonshot_model() -> None:
    assert match_driver("moonshotai/kimi-vl") is None


# --- capability_spec -------------------------------------------------------


def test_capability_spec_ollama_k25_optional_reasoning() -> None:
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="ollama_http", slug=_OLLAMA_K25)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_ollama_k26_optional_reasoning() -> None:
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="ollama_http", slug=_OLLAMA_K26)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_novita_k25_no_reasoning() -> None:
    """Probe 2026-05-12: K2.5 on Novita never returns reasoning_content.
    Surfaced as ``no_reasoning`` so UI hides the toggle entirely."""
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_K25)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "no_reasoning"
    assert spec.reasoning.default_on is False
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_capability_spec_novita_k26_always_on_reasoning() -> None:
    """Probe 2026-05-12: K2.6 on Novita always emits reasoning_content;
    the reasoning toggle is upstream-ignored. Surfaced as ``always_on``
    so UI hides the toggle and shows reasoning by default."""
    driver = KimiK2Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_K26)
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "always_on"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "gmi_http"],
)
def test_capability_spec_unsupported_adapters_raise(adapter_type: str) -> None:
    driver = KimiK2Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.capability_spec(adapter_type=adapter_type, slug=_OLLAMA_K25)


# --- builder helpers -------------------------------------------------------


from shared.dtos.chat import ChatSessionExtras  # noqa: E402
from shared.dtos.inference import (  # noqa: E402
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability  # noqa: E402


def _make_request(
    *,
    slug: str,
    kind: str = "optional",
    default_on: bool = True,
    reasoning_mode: str = "on",
    tools_enabled: bool = False,
    tools: list[ToolDefinition] | None = None,
) -> CompletionRequest:
    """Build a CompletionRequest for builder tests.

    The ``kind`` argument lets a test simulate the capability spec the
    resolver would have attached for a given (adapter, slug). For Kimi
    tests we pass:
      - kind='optional' for Ollama K2.5/K2.6
      - kind='no_reasoning' for Novita K2.5
      - kind='always_on' for Novita K2.6
    """
    return CompletionRequest(
        model=slug,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="Hello")],
            )
        ],
        tools=tools,
        reasoning=ReasoningCapability(
            kind=kind, effort=None, default_on=default_on,
        ),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=tools_enabled,
            reasoning_mode=reasoning_mode,
            reasoning_effort=None,
        ),
    )


# --- build_request: Ollama Cloud -------------------------------------------


def test_build_request_ollama_reasoning_on_writes_think_true() -> None:
    """Optional kind + reasoning_mode='on' -> body['think'] is True.
    The base ``_ollama_http.build_request_body`` already handles this
    when ``reasoning.kind == 'optional'`` — the driver just delegates."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(slug=_OLLAMA_K25, kind="optional", reasoning_mode="on"),
    )
    assert body["think"] is True


def test_build_request_ollama_reasoning_off_writes_think_false() -> None:
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(slug=_OLLAMA_K25, kind="optional", reasoning_mode="off"),
    )
    assert body["think"] is False


def test_build_request_ollama_k26_reasoning_on_writes_think_true() -> None:
    """K2.6 on Ollama Cloud uses the same wire shape as K2.5."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K26,
        request=_make_request(slug=_OLLAMA_K26, kind="optional", reasoning_mode="on"),
    )
    assert body["think"] is True


def test_build_request_ollama_includes_tools_when_enabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(
            slug=_OLLAMA_K25, kind="optional",
            tools_enabled=True, tools=tools,
        ),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


def test_build_request_ollama_omits_tools_when_disabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="ollama_http",
        slug=_OLLAMA_K25,
        request=_make_request(
            slug=_OLLAMA_K25, kind="optional",
            tools_enabled=False, tools=tools,
        ),
    )
    assert "tools" not in body


# --- build_request: Novita -------------------------------------------------


def test_build_request_novita_k25_omits_reasoning_block() -> None:
    """K2.5 on Novita is no_reasoning — the base Novita builder only adds
    a ``reasoning`` block when kind=='optional', so this should already
    be absent. The driver delegates unchanged.
    """
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        request=_make_request(
            slug=_NOVITA_K25, kind="no_reasoning", default_on=False,
            reasoning_mode="off",
        ),
    )
    assert "reasoning" not in body
    assert "enable_thinking" not in body


def test_build_request_novita_k26_omits_reasoning_block() -> None:
    """K2.6 on Novita is always_on — the base Novita builder omits the
    reasoning block (only set for kind=='optional'). The provider
    ignores the toggle anyway."""
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K26,
        request=_make_request(
            slug=_NOVITA_K26, kind="always_on", default_on=True,
            reasoning_mode="on",
        ),
    )
    assert "reasoning" not in body
    assert "enable_thinking" not in body


def test_build_request_novita_inherits_message_translation() -> None:
    driver = KimiK2Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        request=_make_request(slug=_NOVITA_K25, kind="no_reasoning"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


def test_build_request_novita_includes_tools_when_enabled() -> None:
    driver = KimiK2Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_K26,
        request=_make_request(
            slug=_NOVITA_K26, kind="always_on",
            tools_enabled=True, tools=tools,
        ),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


# --- build_request: unsupported adapters -----------------------------------


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "gmi_http"],
)
def test_build_request_unsupported_adapter_raises(adapter_type: str) -> None:
    driver = KimiK2Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.build_request(
            adapter_type=adapter_type,
            slug=_OLLAMA_K25,
            request=_make_request(slug=_OLLAMA_K25, kind="optional"),
        )


# --- parse_chunk: Ollama Cloud ---------------------------------------------


from backend.modules.llm._adapters._events import (  # noqa: E402
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)


def test_parse_chunk_ollama_emits_content_delta() -> None:
    driver = KimiK2Driver()
    chunk = {"message": {"content": "hi"}, "done": False}
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    assert events == [ContentDelta(delta="hi")]


def test_parse_chunk_ollama_emits_thinking_delta() -> None:
    """Ollama Cloud uses ``message.thinking`` for CoT, mapped to
    ThinkingDelta per INS-038."""
    driver = KimiK2Driver()
    chunk = {"message": {"thinking": "let me think"}, "done": False}
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    assert events == [ThinkingDelta(delta="let me think")]


def test_parse_chunk_ollama_emits_atomic_tool_call() -> None:
    """Ollama delivers tool_calls atomically (full call per chunk; no
    incremental accumulation). Arguments arrive as an object and must be
    JSON-stringified to match the ToolCallEvent.arguments: str contract."""
    driver = KimiK2Driver()
    chunk = {
        "message": {
            "tool_calls": [
                {
                    "id": "functions.get_weather:0",
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Berlin"},
                    },
                }
            ]
        },
        "done": False,
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K26, chunk=chunk,
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id == "functions.get_weather:0"
    assert tool_event.name == "get_weather"
    # Arguments are JSON-stringified — exact match on the serialised dict
    # is brittle (key order) but the field carries valid JSON.
    import json
    assert json.loads(tool_event.arguments) == {"city": "Berlin"}


def test_parse_chunk_ollama_tool_call_without_id_gets_synthetic_id() -> None:
    """Ollama responses sometimes omit the tool_call id. Fallback is a
    synthetic ``call_<hex>`` id so the continuation turn has something
    to echo. Same logic as the DSv4 Ollama parser."""
    driver = KimiK2Driver()
    chunk = {
        "message": {
            "tool_calls": [{
                "function": {
                    "name": "get_weather",
                    "arguments": {"city": "Berlin"},
                },
            }]
        },
        "done": False,
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id.startswith("call_")
    assert len(tool_event.id) == 5 + 12  # "call_" + 12 hex chars


def test_parse_chunk_ollama_emits_stream_done_on_terminal() -> None:
    driver = KimiK2Driver()
    chunk = {
        "message": {},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 14,
        "eval_count": 71,
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 14
    assert done.output_tokens == 71
    # Ollama Cloud bundles reasoning into eval_count — no separate
    # reasoning_tokens field on the wire.
    assert done.reasoning_tokens is None


def test_parse_chunk_ollama_emits_stream_refused_on_content_filter() -> None:
    driver = KimiK2Driver()
    chunk = {
        "message": {"refusal": "I cannot help with that"},
        "done": True,
        "done_reason": "content_filter",
    }
    events = driver.parse_chunk(
        adapter_type="ollama_http", slug=_OLLAMA_K25, chunk=chunk,
    )
    refused = next(e for e in events if isinstance(e, StreamRefused))
    assert refused.reason == "content_filter"
    assert refused.refusal_text == "I cannot help with that"
    # Mutually exclusive: no StreamDone alongside StreamRefused.
    assert not any(isinstance(e, StreamDone) for e in events)


# --- parse_chunk: Novita ---------------------------------------------------


def test_parse_chunk_novita_emits_content_delta() -> None:
    driver = KimiK2Driver()
    chunk = {"choices": [{"delta": {"content": "1,"}, "finish_reason": None}]}
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K25, chunk=chunk,
    )
    assert events == [ContentDelta(delta="1,")]


def test_parse_chunk_novita_emits_thinking_delta_from_reasoning_content() -> None:
    """Novita uses DeepSeek-native ``delta.reasoning_content`` (also for K2.6
    — probe 2026-05-12). Mapped to ThinkingDelta per INS-038."""
    driver = KimiK2Driver()
    chunk = {
        "choices": [{
            "delta": {"reasoning_content": "The user"}, "finish_reason": None,
        }]
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K26, chunk=chunk,
    )
    assert events == [ThinkingDelta(delta="The user")]


def test_parse_chunk_novita_accumulates_fragmented_tool_call() -> None:
    """Novita streams tool calls OpenAI-style: id+name in the first chunk,
    then string arguments fragments under index:0. Final ``finish_reason:
    tool_calls`` finalises the accumulator into a ToolCallEvent."""
    driver = KimiK2Driver()
    # First chunk: id + name, no args yet
    driver.parse_chunk(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        chunk={
            "choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "functions.get_weather:0", "type": "function",
                "function": {"name": "get_weather"},
            }]}, "finish_reason": None}],
        },
    )
    # Args fragments
    for frag in ['{"', 'city', '": ', '"Berlin', '"}']:
        driver.parse_chunk(
            adapter_type="novita_http",
            slug=_NOVITA_K25,
            chunk={
                "choices": [{"delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": frag},
                }]}, "finish_reason": None}],
            },
        )
    # Terminal: finish_reason=tool_calls + usage block
    events = driver.parse_chunk(
        adapter_type="novita_http",
        slug=_NOVITA_K25,
        chunk={
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {
                "prompt_tokens": 80, "completion_tokens": 24,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id == "functions.get_weather:0"
    assert tool_event.name == "get_weather"
    assert tool_event.arguments == '{"city": "Berlin"}'
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 80
    assert done.output_tokens == 24


def test_parse_chunk_novita_emits_stream_done_with_reasoning_tokens() -> None:
    """K2.6 on Novita populates completion_tokens_details.reasoning_tokens
    (probe 2026-05-12). StreamDone must carry it through."""
    driver = KimiK2Driver()
    chunk = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 312,
            "completion_tokens_details": {"reasoning_tokens": 220},
        },
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K26, chunk=chunk,
    )
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 19
    assert done.output_tokens == 312
    assert done.reasoning_tokens == 220


def test_parse_chunk_novita_emits_stream_refused_on_content_filter() -> None:
    driver = KimiK2Driver()
    chunk = {
        "choices": [{
            "delta": {"refusal": "I cannot help with that"},
            "finish_reason": "content_filter",
        }],
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_K26, chunk=chunk,
    )
    refused = next(e for e in events if isinstance(e, StreamRefused))
    assert refused.reason == "content_filter"
    assert refused.refusal_text == "I cannot help with that"
    # Mutually exclusive with StreamDone.
    assert not any(isinstance(e, StreamDone) for e in events)
