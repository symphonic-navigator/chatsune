"""Verify cache_control marker emission in the OpenRouter payload builder."""
from __future__ import annotations

from backend.modules.llm._adapters._openrouter_http import build_request_body
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
