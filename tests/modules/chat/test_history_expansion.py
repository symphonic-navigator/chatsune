"""Tests for the orchestrator's ``_expand_history_doc`` helper.

Spec: devdocs/specs/2026-05-17-reasoning-tool-replay-design.md §4.2.
Per-turn tool-replay flag: devdocs/specs/2026-05-17-replay-tool-history-per-turn-flag-design.md.

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
* the four ``(replay_reasoning, tool_replay_at_save)`` combinations
  with a thinking+tools-bearing document. ``tool_replay_at_save`` is
  read off the document itself rather than passed as a kwarg.
* legacy documents (no ``tool_replay_at_save`` key) default to
  replay-on, matching pre-2026-05-17 behaviour.
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
        _user_doc(), replay_reasoning=False,
    )
    assert len(out) == 1
    assert out[0].role == "user"
    assert out[0].content[0].text == "Hello there."


def test_user_message_with_attachment_and_snapshot_expands_placeholders() -> None:
    out = _expand_history_doc(
        _user_doc_with_attachment_and_snapshot(),
        replay_reasoning=False,
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
        {**_bare_assistant_doc(), "tool_replay_at_save": True},
        replay_reasoning=True,
    )
    assert len(out) == 1
    assert out[0].role == "assistant"
    assert out[0].thinking_blocks is None
    assert out[0].tool_calls is None


def test_assistant_with_legacy_thinking_wraps_as_anonymous_block() -> None:
    out = _expand_history_doc(
        {**_legacy_thinking_doc(), "tool_replay_at_save": False},
        replay_reasoning=True,
    )
    assert len(out) == 1
    blocks = out[0].thinking_blocks
    assert blocks is not None and len(blocks) == 1
    assert blocks[0].text == "I reasoned carefully."
    assert blocks[0].signature is None


def test_assistant_with_new_thinking_blocks_roundtrips_signatures() -> None:
    out = _expand_history_doc(
        {**_new_thinking_blocks_doc(), "tool_replay_at_save": False},
        replay_reasoning=True,
    )
    blocks = out[0].thinking_blocks
    assert blocks is not None and len(blocks) == 2
    assert blocks[0].signature == "sig-1"
    assert blocks[1].signature == "sig-2"


def test_assistant_with_tools_emits_tool_calls_plus_tool_messages() -> None:
    out = _expand_history_doc(
        {**_tool_use_doc(), "tool_replay_at_save": True},
        replay_reasoning=False,
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
            {**_orphan_tool_call_doc(), "tool_replay_at_save": True},
            replay_reasoning=False,
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
        {**_full_assistant_doc(), "tool_replay_at_save": False},
        replay_reasoning=False,
    )
    assert len(out) == 1
    assert out[0].thinking_blocks is None
    assert out[0].tool_calls is None


def test_combo_replay_reasoning_only() -> None:
    out = _expand_history_doc(
        {**_full_assistant_doc(), "tool_replay_at_save": False},
        replay_reasoning=True,
    )
    # Reasoning present, tools collapsed away.
    assert len(out) == 1
    assert out[0].thinking_blocks is not None
    assert len(out[0].thinking_blocks) == 1
    assert out[0].tool_calls is None


def test_combo_replay_tools_only() -> None:
    out = _expand_history_doc(
        {**_full_assistant_doc(), "tool_replay_at_save": True},
        replay_reasoning=False,
    )
    # No thinking; one assistant(tool_calls) + one tool message.
    assert len(out) == 2
    assert out[0].thinking_blocks is None
    assert out[0].tool_calls is not None and len(out[0].tool_calls) == 1
    assert out[1].role == "tool"


def test_combo_replay_both() -> None:
    out = _expand_history_doc(
        {**_full_assistant_doc(), "tool_replay_at_save": True},
        replay_reasoning=True,
    )
    assert len(out) == 2
    assert out[0].thinking_blocks is not None
    assert out[0].tool_calls is not None


def test_per_doc_flag_respected_across_two_assistant_docs() -> None:
    """Two assistant docs in the same history, one with the per-turn
    flag on and one with it off. The doc with ``True`` expands its
    tool triplet; the doc with ``False`` collapses to a single
    assistant message even though the call site does not pass a
    global flag any more.
    """
    on_doc = {**_full_assistant_doc(), "tool_replay_at_save": True}
    off_doc = {**_full_assistant_doc(), "tool_replay_at_save": False}

    out_on = _expand_history_doc(on_doc, replay_reasoning=False)
    out_off = _expand_history_doc(off_doc, replay_reasoning=False)

    # Replay-on: assistant(tool_calls) + tool result.
    assert len(out_on) == 2
    assert out_on[0].tool_calls is not None and len(out_on[0].tool_calls) == 1
    assert out_on[1].role == "tool"
    # Replay-off: single assistant, no tool_calls.
    assert len(out_off) == 1
    assert out_off[0].tool_calls is None


def test_legacy_doc_without_flag_defaults_to_replay_on() -> None:
    """Documents written before the per-turn flag landed lack the
    ``tool_replay_at_save`` key entirely. ``doc.get(...)`` falls back
    to ``True`` (matching the Pydantic model default), preserving
    pre-2026-05-17 behaviour."""
    legacy = _full_assistant_doc()  # NO tool_replay_at_save key
    assert "tool_replay_at_save" not in legacy
    out = _expand_history_doc(legacy, replay_reasoning=False)
    # Two messages: assistant(tool_calls) + tool result — replay-on.
    assert len(out) == 2
    assert out[0].tool_calls is not None and len(out[0].tool_calls) == 1
    assert out[1].role == "tool"
