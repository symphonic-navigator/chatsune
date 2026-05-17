"""Tests for the orchestrator's ``_expand_history_doc`` helper.

Spec: devdocs/specs/2026-05-17-reasoning-tool-replay-design.md §4.2.

The helper walks a single stored message document and emits the
0..N ``CompletionMessage``s that get fed into the next inference. We
exercise:

* plain user message — round-trips content + attachment / vision
  placeholders.
* plain assistant message with no thinking / no tools — no-op shape.
* assistant with legacy ``thinking: str`` — wrapped as one anonymous
  ThinkingBlock when ``replay_reasoning`` is on.
* assistant with new ``thinking_blocks: list[dict]`` — round-trips
  verbatim including signatures.
* assistant with tool calls + matching results — emits one assistant
  message with ``tool_calls`` plus N ``role=tool`` messages.
* assistant with an orphan tool_call (no result event) — call is
  dropped from the replay.
* all four ``(replay_reasoning, replay_tool_history)`` combinations
  with a thinking+tools-bearing document.
"""

import logging

import pytest

from backend.modules.chat._orchestrator import _expand_history_doc


def _user_doc() -> dict:
    return {
        "role": "user",
        "content": "Hello there.",
    }


def _user_doc_with_attachment_and_snapshot() -> dict:
    return {
        "role": "user",
        "content": "Body text.",
        "attachment_refs": [{"display_name": "photo.jpg"}],
        "vision_descriptions_used": [
            {
                "display_name": "photo.jpg",
                "model_id": "llama-vision",
                "text": "A red kite over a meadow.",
            },
        ],
    }


def _bare_assistant_doc() -> dict:
    return {
        "role": "assistant",
        "content": "Sure, here is the answer.",
    }


def _legacy_thinking_doc() -> dict:
    return {
        "role": "assistant",
        "content": "Final answer.",
        "thinking": "I reasoned carefully.",
    }


def _new_thinking_blocks_doc() -> dict:
    return {
        "role": "assistant",
        "content": "Final answer.",
        "thinking_blocks": [
            {"text": "step 1", "signature": "sig-1", "raw": None},
            {"text": "step 2", "signature": "sig-2", "raw": None},
        ],
    }


def _tool_use_doc() -> dict:
    return {
        "role": "assistant",
        "content": "Looked it up.",
        "events": [
            {
                "kind": "tool_call",
                "seq": 0,
                "tool_call_id": "call-1",
                "tool_name": "web_search",
                "arguments": {"q": "rust ownership"},
                "success": True,
                "result_content": "<results>…</results>",
            },
        ],
    }


def _orphan_tool_call_doc() -> dict:
    """Assistant with a tool_call event that lacks a result_content.

    Simulates a cancelled mid-turn tool execution where persistence
    truncated before the result event was written. Spec §4.2 says
    drop the orphan from the replayed ``tool_calls`` list.
    """
    return {
        "role": "assistant",
        "content": "",
        "events": [
            {
                "kind": "tool_call",
                "seq": 0,
                "tool_call_id": "call-orphan",
                "tool_name": "web_search",
                "arguments": {"q": "?"},
                "success": False,
                "result_content": None,
            },
        ],
    }


def _full_assistant_doc() -> dict:
    """Combined thinking_blocks + tool-call/result triplet."""
    return {
        "role": "assistant",
        "content": "Final answer.",
        "thinking_blocks": [
            {"text": "I should search.", "signature": "sig-x", "raw": None},
        ],
        "events": [
            {
                "kind": "tool_call",
                "seq": 0,
                "tool_call_id": "call-2",
                "tool_name": "web_search",
                "arguments": {"q": "anything"},
                "success": True,
                "result_content": "results",
            },
        ],
    }


def test_user_message_roundtrips_content() -> None:
    out = _expand_history_doc(
        _user_doc(), replay_reasoning=False, replay_tool_history=False,
    )
    assert len(out) == 1
    assert out[0].role == "user"
    assert out[0].content[0].text == "Hello there."


def test_user_message_with_attachment_and_snapshot_expands_placeholders() -> None:
    out = _expand_history_doc(
        _user_doc_with_attachment_and_snapshot(),
        replay_reasoning=False,
        replay_tool_history=False,
    )
    assert len(out) == 1
    parts = out[0].content
    # Three text parts: body, attachment placeholder, vision snapshot.
    assert len(parts) == 3
    assert "Body text." in (parts[0].text or "")
    assert "[Attachment: photo.jpg]" in (parts[1].text or "")
    assert "Image description for photo.jpg" in (parts[2].text or "")


def test_bare_assistant_emits_single_assistant_message() -> None:
    out = _expand_history_doc(
        _bare_assistant_doc(),
        replay_reasoning=True,
        replay_tool_history=True,
    )
    assert len(out) == 1
    assert out[0].role == "assistant"
    assert out[0].thinking_blocks is None
    assert out[0].tool_calls is None


def test_assistant_with_legacy_thinking_wraps_as_anonymous_block() -> None:
    out = _expand_history_doc(
        _legacy_thinking_doc(),
        replay_reasoning=True,
        replay_tool_history=False,
    )
    assert len(out) == 1
    blocks = out[0].thinking_blocks
    assert blocks is not None and len(blocks) == 1
    assert blocks[0].text == "I reasoned carefully."
    assert blocks[0].signature is None


def test_assistant_with_new_thinking_blocks_roundtrips_signatures() -> None:
    out = _expand_history_doc(
        _new_thinking_blocks_doc(),
        replay_reasoning=True,
        replay_tool_history=False,
    )
    blocks = out[0].thinking_blocks
    assert blocks is not None and len(blocks) == 2
    assert blocks[0].signature == "sig-1"
    assert blocks[1].signature == "sig-2"


def test_assistant_with_tools_emits_tool_calls_plus_tool_messages() -> None:
    out = _expand_history_doc(
        _tool_use_doc(),
        replay_reasoning=False,
        replay_tool_history=True,
    )
    # assistant(tool_calls) + one role=tool message
    assert len(out) == 2
    assistant_msg = out[0]
    tool_msg = out[1]
    assert assistant_msg.role == "assistant"
    assert assistant_msg.tool_calls is not None
    assert len(assistant_msg.tool_calls) == 1
    assert assistant_msg.tool_calls[0].id == "call-1"
    assert assistant_msg.tool_calls[0].name == "web_search"
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == "call-1"
    assert (tool_msg.content[0].text or "") == "<results>…</results>"


def test_orphan_tool_call_is_dropped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        out = _expand_history_doc(
            _orphan_tool_call_doc(),
            replay_reasoning=False,
            replay_tool_history=True,
        )
    # Single assistant message, no tool_calls (orphan dropped).
    assert len(out) == 1
    assert out[0].tool_calls is None
    assert any(
        "history_expand.orphan_tool_call" in r.message
        or "orphan_tool_call" in r.message
        for r in caplog.records
    )


def test_combo_no_replay_anywhere_collapses_to_plain_assistant() -> None:
    out = _expand_history_doc(
        _full_assistant_doc(),
        replay_reasoning=False,
        replay_tool_history=False,
    )
    assert len(out) == 1
    assert out[0].thinking_blocks is None
    assert out[0].tool_calls is None


def test_combo_replay_reasoning_only() -> None:
    out = _expand_history_doc(
        _full_assistant_doc(),
        replay_reasoning=True,
        replay_tool_history=False,
    )
    # Reasoning present, tools collapsed away.
    assert len(out) == 1
    assert out[0].thinking_blocks is not None
    assert len(out[0].thinking_blocks) == 1
    assert out[0].tool_calls is None


def test_combo_replay_tools_only() -> None:
    out = _expand_history_doc(
        _full_assistant_doc(),
        replay_reasoning=False,
        replay_tool_history=True,
    )
    # No thinking; one assistant(tool_calls) + one tool message.
    assert len(out) == 2
    assert out[0].thinking_blocks is None
    assert out[0].tool_calls is not None and len(out[0].tool_calls) == 1
    assert out[1].role == "tool"


def test_combo_replay_both() -> None:
    out = _expand_history_doc(
        _full_assistant_doc(),
        replay_reasoning=True,
        replay_tool_history=True,
    )
    assert len(out) == 2
    assert out[0].thinking_blocks is not None
    assert out[0].tool_calls is not None
