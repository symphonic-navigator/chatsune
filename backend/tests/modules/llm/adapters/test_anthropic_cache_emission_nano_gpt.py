"""Verify cache_control marker emission in the nano-gpt payload builder."""
from __future__ import annotations

from backend.modules.llm._adapters._nano_gpt_http import _build_chat_payload
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _msg(role: str, text: str = "x") -> CompletionMessage:
    return CompletionMessage(
        role=role, content=[ContentPart(type="text", text=text)],
    )


def _request(
    model: str, messages: list[CompletionMessage], ttl: str,
) -> CompletionRequest:
    # Cache-emission tests are concerned with messages-shaping, not
    # reasoning/tools — pass conservative defaults for the now-required
    # capability fields.
    return CompletionRequest(
        model=model,
        messages=messages,
        anthropic_cache_ttl=ttl,
        reasoning=ReasoningCapability(kind="no_reasoning"),
        tools_capability=ToolCapability(supported=False),
    )


def test_no_markers_when_ttl_off() -> None:
    msgs = [_msg("system"), _msg("user")] + [_msg("user")] * 20
    payload = _build_chat_payload(
        _request("claude-3-7-sonnet-20250219", msgs, "off"),
        upstream_slug="claude-3-7-sonnet-20250219",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_no_markers_for_non_anthropic_model() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("gpt-4o", msgs, "5m"),
        upstream_slug="gpt-4o",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_5m_emission_on_long_anthropic_conversation_no_prefix_slug() -> None:
    # nano-gpt slugs lack the "anthropic/" prefix.
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("claude-3-7-sonnet-20250219", msgs, "5m"),
        upstream_slug="claude-3-7-sonnet-20250219",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    expected = {
        0: {"type": "ephemeral", "ttl": "1h"},
        15: {"type": "ephemeral", "ttl": "1h"},
        20: {"type": "ephemeral"},
    }
    for i, m in enumerate(payload["messages"]):
        if i in expected:
            assert isinstance(m["content"], list)
            assert m["content"][-1].get("cache_control") == expected[i], i
        else:
            content = m["content"]
            if isinstance(content, list):
                for block in content:
                    assert "cache_control" not in block, i


def test_1h_tail_is_explicit() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("claude-haiku-4-5", msgs, "1h"),
        upstream_slug="claude-haiku-4-5",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    assert payload["messages"][20]["content"][-1].get("cache_control") == {
        "type": "ephemeral", "ttl": "1h",
    }
