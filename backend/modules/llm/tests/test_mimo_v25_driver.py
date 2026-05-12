"""Tests for MiMoV25Driver — capability spec, request body, chunk parsing.

Mirrors the structure of test_deepseek_v4_driver.py. MiMo v2.5 Pro is a
single-adapter (Novita) integration so the wire-coverage matrix is
narrower; tests for non-Novita adapters all assert
``NotImplementedError`` (matching the DSv4 convention for capability-only
adapters).
"""
from __future__ import annotations

import pytest

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._capabilities import (
    DEFAULT_CAPABILITIES,
    resolve_capabilities,
)
from backend.modules.llm._drivers import match_driver
from backend.modules.llm._drivers.mimo_v25 import MiMoV25Driver
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import (
    ReasoningCapability,
    ToolCapability,
)


_NOVITA_SLUG = "xiaomimimo/mimo-v2.5-pro"


class _NoOpAdapter:
    """Adapter that gives no capability hint — forces fallthrough."""

    def capability_hint(self, model_id: str):
        return None


def _make_request(
    *,
    reasoning_mode: str = "on",
    tools_enabled: bool = False,
    tools: list[ToolDefinition] | None = None,
) -> CompletionRequest:
    """Build a minimal CompletionRequest for builder tests."""
    return CompletionRequest(
        model=_NOVITA_SLUG,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="Hello")],
            )
        ],
        tools=tools,
        reasoning=ReasoningCapability(
            kind="optional",
            effort=None,
            default_on=True,
        ),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=tools_enabled,
            reasoning_mode=reasoning_mode,
            reasoning_effort=None,
        ),
    )


# --- match_driver ----------------------------------------------------------


def test_match_driver_with_publisher_prefix() -> None:
    assert match_driver(_NOVITA_SLUG) is MiMoV25Driver


def test_match_driver_basename_without_prefix() -> None:
    assert match_driver("mimo-v2.5-pro") is MiMoV25Driver


def test_match_driver_does_not_match_sibling_flash() -> None:
    """The driver targets v2.5-pro only. v2-flash on Novita is a separate,
    capability-only model and must not accidentally route through this driver."""
    assert match_driver("xiaomimimo/mimo-v2-flash") is not MiMoV25Driver


# --- capability_spec -------------------------------------------------------


def test_capability_spec_novita_first_class() -> None:
    driver = MiMoV25Driver()
    spec = driver.capability_spec(adapter_type="novita_http", slug=_NOVITA_SLUG)

    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    # MiMo on Novita does not expose effort buckets — probe 2026-05-12
    # found no documented effort spec.
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "ollama_http"],
)
def test_capability_spec_non_novita_raises(adapter_type: str) -> None:
    driver = MiMoV25Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.capability_spec(adapter_type=adapter_type, slug=_NOVITA_SLUG)


# --- build_request ---------------------------------------------------------


def test_build_request_novita_reasoning_on() -> None:
    """Reasoning on: body carries ``reasoning: {enabled: true}`` and no
    top-level ``enable_thinking`` key (default-on behaviour at Novita)."""
    driver = MiMoV25Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        request=_make_request(reasoning_mode="on"),
    )
    assert body["reasoning"] == {"enabled": True}
    assert "enable_thinking" not in body


def test_build_request_novita_reasoning_off_uses_enable_thinking_false() -> None:
    """Reasoning off: Novita's ``reasoning: {enabled: false}`` does NOT
    suppress MiMo reasoning (probed 2026-05-12: model still produces
    reasoning_content and reasoning_tokens). The wire-signal Novita
    honours is top-level ``enable_thinking: false``."""
    driver = MiMoV25Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        request=_make_request(reasoning_mode="off"),
    )
    assert body.get("enable_thinking") is False
    # The ineffective reasoning block must not coexist with enable_thinking
    # — we drop it to keep the wire shape unambiguous.
    assert "reasoning" not in body


def test_build_request_novita_includes_tools_when_enabled() -> None:
    """Tools work with reasoning both on and off; the wire only carries
    them when ``extras.tools_enabled`` is True AND the request supplies
    a tools list."""
    driver = MiMoV25Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        request=_make_request(tools_enabled=True, tools=tools),
    )
    assert "tools" in body
    assert body["tools"][0]["function"]["name"] == "get_time"


def test_build_request_novita_omits_tools_when_disabled() -> None:
    """``extras.tools_enabled=False`` suppresses tools even when the
    request carries a tool list — the session toggle is ground truth."""
    driver = MiMoV25Driver()
    tools = [
        ToolDefinition(
            name="get_time",
            description="Return the current time",
            parameters={"type": "object", "properties": {}},
        )
    ]
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        request=_make_request(tools_enabled=False, tools=tools),
    )
    assert "tools" not in body


def test_build_request_novita_inherits_message_translation() -> None:
    """Delegate to existing build_request_body → ContentPart-to-string handled."""
    driver = MiMoV25Driver()
    body = driver.build_request(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        request=_make_request(),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "ollama_http"],
)
def test_build_request_non_novita_raises(adapter_type: str) -> None:
    driver = MiMoV25Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.build_request(
            adapter_type=adapter_type,
            slug=_NOVITA_SLUG,
            request=_make_request(),
        )


# --- parse_chunk -----------------------------------------------------------


def test_parse_chunk_novita_emits_content_delta() -> None:
    driver = MiMoV25Driver()
    chunk = {
        "choices": [
            {"delta": {"content": "hi"}, "finish_reason": None}
        ]
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_SLUG, chunk=chunk,
    )
    assert events == [ContentDelta(delta="hi")]


def test_parse_chunk_novita_emits_thinking_delta_from_reasoning_content() -> None:
    """MiMo on Novita uses the DeepSeek-style ``delta.reasoning_content``
    key (probed 2026-05-12)."""
    driver = MiMoV25Driver()
    chunk = {
        "choices": [
            {"delta": {"reasoning_content": "thinking"}, "finish_reason": None}
        ]
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_SLUG, chunk=chunk,
    )
    assert events == [ThinkingDelta(delta="thinking")]


def test_parse_chunk_novita_emits_stream_done_with_usage() -> None:
    driver = MiMoV25Driver()
    chunk = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19,
            "completion_tokens": 312,
            "completion_tokens_details": {"reasoning_tokens": 220},
        },
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_SLUG, chunk=chunk,
    )
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 19
    assert done.output_tokens == 312
    assert done.reasoning_tokens == 220


def test_parse_chunk_novita_accumulates_streamed_tool_call_fragments() -> None:
    driver = MiMoV25Driver()
    # First chunk: id + name, no args yet
    driver.parse_chunk(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        chunk={
            "choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": "call_aa_bb", "type": "function",
                "function": {"name": "get_time"},
            }]}, "finish_reason": None}],
        },
    )
    # Args fragments
    for frag in ['{', '"', 'tz', '"', ': ', '"', 'UTC', '"', '}']:
        driver.parse_chunk(
            adapter_type="novita_http",
            slug=_NOVITA_SLUG,
            chunk={
                "choices": [{"delta": {"tool_calls": [{
                    "index": 0, "function": {"arguments": frag},
                }]}, "finish_reason": None}],
            },
        )
    # Terminal: finish_reason=tool_calls + usage block
    events = driver.parse_chunk(
        adapter_type="novita_http",
        slug=_NOVITA_SLUG,
        chunk={
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {
                "prompt_tokens": 80, "completion_tokens": 24,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.id == "call_aa_bb"
    assert tool_event.name == "get_time"
    assert tool_event.arguments == '{"tz": "UTC"}'
    done = next(e for e in events if isinstance(e, StreamDone))
    assert done.input_tokens == 80
    assert done.output_tokens == 24


def test_parse_chunk_novita_emits_stream_refused_on_content_filter() -> None:
    driver = MiMoV25Driver()
    chunk = {
        "choices": [{
            "delta": {"refusal": "I cannot help with that"},
            "finish_reason": "content_filter",
        }],
    }
    events = driver.parse_chunk(
        adapter_type="novita_http", slug=_NOVITA_SLUG, chunk=chunk,
    )
    refused = next(e for e in events if isinstance(e, StreamRefused))
    assert refused.reason == "content_filter"
    assert refused.refusal_text == "I cannot help with that"
    # StreamRefused and StreamDone are mutually exclusive terminals.
    assert not any(isinstance(e, StreamDone) for e in events)


@pytest.mark.parametrize(
    "adapter_type",
    ["openrouter_http", "nano_gpt_http", "ollama_http"],
)
def test_parse_chunk_non_novita_raises(adapter_type: str) -> None:
    driver = MiMoV25Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        driver.parse_chunk(
            adapter_type=adapter_type,
            slug=_NOVITA_SLUG,
            chunk={"choices": [{"delta": {"content": "x"}}]},
        )


# --- integration with resolve_capabilities ---------------------------------


def test_resolve_capabilities_returns_driver_spec_for_novita() -> None:
    """Driver match wins over YAML and adapter heuristic — the resolver
    must hand back exactly what MiMoV25Driver returns."""
    spec = resolve_capabilities(
        adapter_type="novita_http",
        model_id=_NOVITA_SLUG,
        adapter=_NoOpAdapter(),
    )
    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.effort is None
    assert spec.reasoning.default_on is True
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False
    # Sanity: this is NOT the universal default — proves the driver fired.
    assert spec != DEFAULT_CAPABILITIES


# --- per-instance state ----------------------------------------------------


def test_driver_novita_accumulator_is_per_instance() -> None:
    """Each MiMoV25Driver instance must own a private Novita accumulator
    so concurrent streams don't cross-contaminate."""
    a = MiMoV25Driver()
    b = MiMoV25Driver()
    assert a._novita_tool_acc is not b._novita_tool_acc
