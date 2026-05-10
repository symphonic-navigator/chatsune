"""Tests for DeepSeekV4Driver — capability spec, request body, chunk parsing."""
from __future__ import annotations

import pytest

from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
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

from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_openrouter,
)


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
