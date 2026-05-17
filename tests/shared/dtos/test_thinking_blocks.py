"""Tests for the new ``ThinkingBlock`` / ``CompletionMessage`` and
``ReasoningCapability.replay_reasoning`` / ``ChatSessionExtras.replay_tool_history``
fields introduced for the reasoning + tool re-injection spec
(devdocs/specs/2026-05-17-reasoning-tool-replay-design.md).

These are pure-DTO unit tests: no DB, no event-bus, no adapter. The
contract is the single source of truth — keep it healthy.
"""

from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    ContentPart,
    ThinkingBlock,
)
from shared.dtos.llm import ReasoningCapability


def test_thinking_block_roundtrips_text_signature_and_raw() -> None:
    block = ThinkingBlock(
        text="reasoning text",
        signature="sig-abc",
        raw={"type": "thinking", "thinking": "reasoning text"},
    )
    dumped = block.model_dump()
    rebuilt = ThinkingBlock.model_validate(dumped)
    assert rebuilt.text == "reasoning text"
    assert rebuilt.signature == "sig-abc"
    assert rebuilt.raw == {"type": "thinking", "thinking": "reasoning text"}


def test_thinking_block_defaults_to_no_signature() -> None:
    block = ThinkingBlock(text="hello")
    assert block.signature is None
    assert block.raw is None


def test_completion_message_accepts_thinking_blocks_list() -> None:
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="hi")],
        thinking_blocks=[
            ThinkingBlock(text="step 1", signature="s1"),
            ThinkingBlock(text="step 2"),
        ],
    )
    assert msg.thinking_blocks is not None
    assert len(msg.thinking_blocks) == 2
    assert msg.thinking_blocks[0].signature == "s1"
    assert msg.thinking_blocks[1].signature is None


def test_completion_message_omits_thinking_blocks_by_default() -> None:
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hi")],
    )
    assert msg.thinking_blocks is None


def test_reasoning_capability_replay_reasoning_defaults_false() -> None:
    cap = ReasoningCapability(kind="optional")
    assert cap.replay_reasoning is False


def test_reasoning_capability_replay_reasoning_can_be_enabled() -> None:
    cap = ReasoningCapability(kind="optional", replay_reasoning=True)
    assert cap.replay_reasoning is True


def test_reasoning_capability_legacy_payload_without_replay_reasoning() -> None:
    """Cached ``ReasoningCapability`` blobs in Redis pre-date this field.

    Default must be ``False`` so the deserialiser keeps reading them
    cleanly — see CLAUDE.md §Data-Model Migrations.
    """
    legacy = {"kind": "optional", "default_on": True}
    cap = ReasoningCapability.model_validate(legacy)
    assert cap.replay_reasoning is False


def test_chat_session_extras_replay_tool_history_defaults_true() -> None:
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
    )
    assert extras.replay_tool_history is True


def test_chat_session_extras_legacy_payload_without_replay_tool_history() -> None:
    """Cached extras documents pre-date this field — default keeps reads safe."""
    legacy = {
        "tools_enabled": False,
        "reasoning_mode": "off",
        "reasoning_effort": None,
    }
    extras = ChatSessionExtras.model_validate(legacy)
    assert extras.replay_tool_history is True


def test_chat_session_extras_replay_tool_history_can_be_disabled() -> None:
    extras = ChatSessionExtras(
        tools_enabled=False,
        reasoning_mode="off",
        reasoning_effort=None,
        replay_tool_history=False,
    )
    assert extras.replay_tool_history is False
