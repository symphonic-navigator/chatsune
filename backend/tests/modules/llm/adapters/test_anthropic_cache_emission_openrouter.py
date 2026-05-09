"""Verify cache_control marker emission in the OpenRouter payload builder."""
from __future__ import annotations

from backend.modules.llm._adapters._openrouter_http import (
    _ANTHROPIC_REASONING_BUDGET,
    build_request_body,
)
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
    payload = build_request_body(
        _request("anthropic/claude-sonnet-4.5", msgs, "off"),
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_no_markers_for_non_anthropic_model() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = build_request_body(
        _request("openai/gpt-4o", msgs, "5m"),
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_5m_emission_on_long_anthropic_conversation() -> None:
    # 22 messages → System(0, 1h) + Block(15, 1h) + Tail(20, 5m).
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = build_request_body(
        _request("anthropic/claude-sonnet-4.5", msgs, "5m"),
    )
    expected = {
        0: {"type": "ephemeral", "ttl": "1h"},
        15: {"type": "ephemeral", "ttl": "1h"},
        20: {"type": "ephemeral"},
    }
    for i, m in enumerate(payload["messages"]):
        if i in expected:
            assert isinstance(m["content"], list), (
                f"index {i} content must be list to carry cache_control"
            )
            assert m["content"][-1].get("cache_control") == expected[i], i
        else:
            content = m["content"]
            if isinstance(content, list):
                for block in content:
                    assert "cache_control" not in block, i


def test_1h_emission_makes_tail_1h() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = build_request_body(
        _request("anthropic/claude-sonnet-4.5", msgs, "1h"),
    )
    tail = payload["messages"][20]
    assert tail["content"][-1].get("cache_control") == {
        "type": "ephemeral", "ttl": "1h",
    }


def test_marker_attaches_to_last_content_block_with_image() -> None:
    # Tail position must carry cache_control on the LAST block when
    # both text and image are present.
    msgs = [_msg("system")]
    for _ in range(20):
        msgs.append(_msg("user"))
    image_msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="hi"),
            ContentPart(
                type="image",
                data="aGVsbG8=",  # base64 'hello'
                media_type="image/png",
            ),
        ],
    )
    msgs.insert(20, image_msg)  # tail_index becomes 20
    assert len(msgs) == 22
    payload = build_request_body(
        _request("anthropic/claude-sonnet-4.5", msgs, "5m"),
    )
    tail_blocks = payload["messages"][20]["content"]
    assert tail_blocks[-1]["type"] == "image_url"
    assert tail_blocks[-1].get("cache_control") == {"type": "ephemeral"}


# --- OR-bug workaround: cache_control suppressed when explicit effort dialled ---


def _request_with_extras(
    model: str,
    messages: list[CompletionMessage],
    ttl: str,
    *,
    reasoning_mode: str,
    reasoning_effort: str | None,
) -> CompletionRequest:
    from shared.dtos.chat import ChatSessionExtras
    from shared.dtos.llm import ReasoningEffortSpec
    return CompletionRequest(
        model=model,
        messages=messages,
        anthropic_cache_ttl=ttl,
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=True,
            reasoning_mode=reasoning_mode,
            reasoning_effort=reasoning_effort,
        ),
    )


def test_cache_markers_suppressed_when_explicit_effort_set() -> None:
    """OpenRouter's translator silently discards reasoning.max_tokens when
    cache_control markers are present in the same body. The user's
    explicit effort choice wins: drop cache markers so the budget
    actually enforces."""
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = build_request_body(
        _request_with_extras(
            "anthropic/claude-sonnet-4.6", msgs, "5m",
            reasoning_mode="on", reasoning_effort="low",
        ),
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block, (
                    "cache_control must be stripped when explicit reasoning "
                    "effort is set, otherwise OR ignores reasoning.max_tokens"
                )
    # The reasoning budget itself MUST be present — that's the whole point.
    assert payload["reasoning"] == {
        "max_tokens": _ANTHROPIC_REASONING_BUDGET["low"],
    }


def test_cache_markers_kept_when_no_explicit_effort() -> None:
    """When the user hasn't dialled in a specific effort, cache markers
    stay on — the bug only fires when both fields collide. We pay the
    cache savings on every turn except those where the user explicitly
    dialled an effort bucket."""
    from shared.dtos.chat import ChatSessionExtras
    msgs = [_msg("system")] + [_msg("user")] * 21
    req = CompletionRequest(
        model="anthropic/claude-sonnet-4.6",
        messages=msgs,
        anthropic_cache_ttl="5m",
        reasoning=ReasoningCapability(kind="optional"),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort=None,
        ),
    )
    payload = build_request_body(req)
    # At least one message should still carry cache_control.
    found_cc = any(
        isinstance(m.get("content"), list)
        and any(b.get("cache_control") for b in m["content"])
        for m in payload["messages"]
    )
    assert found_cc, "cache markers should remain when effort is unset"


def test_cache_markers_kept_when_reasoning_off_even_with_effort() -> None:
    """Effort is dialled but reasoning is OFF — body sends enabled:false,
    no max_tokens collision possible, so cache markers stay on."""
    from shared.dtos.chat import ChatSessionExtras
    msgs = [_msg("system")] + [_msg("user")] * 21
    req = CompletionRequest(
        model="anthropic/claude-sonnet-4.6",
        messages=msgs,
        anthropic_cache_ttl="5m",
        reasoning=ReasoningCapability(kind="optional"),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort="low",
        ),
    )
    payload = build_request_body(req)
    found_cc = any(
        isinstance(m.get("content"), list)
        and any(b.get("cache_control") for b in m["content"])
        for m in payload["messages"]
    )
    assert found_cc, "cache markers should remain when reasoning is off"
