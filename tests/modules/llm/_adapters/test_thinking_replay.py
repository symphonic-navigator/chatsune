"""Parse + translate tests for the new thinking-block replay paths.

Spec: devdocs/specs/2026-05-17-reasoning-tool-replay-design.md §5.

Coverage:

* OpenRouter: ``reasoning_details`` parse emits ``ThinkingDelta`` with
  signature; ``_translate_message`` prepends Anthropic-shape thinking
  blocks for Claude models and falls back to ``reasoning_content`` for
  non-Anthropic models.
* nano-gpt: same as OpenRouter (Anthropic forwarded shape).
* xAI / Chutes / Tensorix / Novita: ``_translate_message`` emits
  ``reasoning_content`` for non-Anthropic routes.
* Mistral: ``_translate_message`` prepends ``{"type": "thinking", ...}``
  parts on the content array.
* Strip-and-retry helpers detect the rejection body and rewrite the
  payload in place.
"""

from backend.modules.llm._adapters import (
    _chutes_http,
    _mistral_http,
    _nano_gpt_http,
    _novita_http,
    _openrouter_http,
    _tensorix_http,
    _xai_http,
)
from backend.modules.llm._adapters._events import ThinkingDelta
from backend.modules.llm._adapters._openrouter_http import (
    _chunk_to_events,
    _ToolCallAccumulator,
)
from backend.modules.llm._adapters._openrouter_http import (
    _is_anthropic_signature_rejection as _or_is_sig_rej,
)
from backend.modules.llm._adapters._openrouter_http import (
    _strip_thinking_from_payload as _or_strip,
)
from backend.modules.llm._adapters._nano_gpt_http import (
    _is_anthropic_signature_rejection as _ng_is_sig_rej,
)
from backend.modules.llm._adapters._nano_gpt_http import (
    _strip_thinking_from_payload as _ng_strip,
)

from shared.dtos.inference import (
    CompletionMessage,
    ContentPart,
    ThinkingBlock,
)


# ---------------------------------------------------------------------------
# Parse path — OpenRouter reasoning_details emits signed ThinkingDelta
# ---------------------------------------------------------------------------


def test_openrouter_parse_reasoning_details_emits_signed_thinking_delta() -> None:
    acc = _ToolCallAccumulator()
    chunk = {
        "choices": [{
            "delta": {
                "reasoning_details": [
                    {
                        "type": "thinking",
                        "thinking": "I should reason carefully.",
                        "signature": "anthropic-sig-1",
                    },
                ],
            },
        }],
    }
    events = _chunk_to_events(chunk, acc)
    thinking_events = [e for e in events if isinstance(e, ThinkingDelta)]
    assert len(thinking_events) == 1
    td = thinking_events[0]
    assert td.delta == "I should reason carefully."
    assert td.signature == "anthropic-sig-1"
    assert td.raw is not None
    assert td.raw.get("type") == "thinking"


def test_openrouter_parse_reasoning_string_emits_unsigned_thinking_delta() -> None:
    acc = _ToolCallAccumulator()
    chunk = {
        "choices": [{"delta": {"reasoning": "soft-cot text"}}],
    }
    events = _chunk_to_events(chunk, acc)
    thinking_events = [e for e in events if isinstance(e, ThinkingDelta)]
    assert len(thinking_events) == 1
    assert thinking_events[0].signature is None


# ---------------------------------------------------------------------------
# Translate path — Anthropic models get typed thinking blocks
# ---------------------------------------------------------------------------


def _assistant_with_thinking() -> CompletionMessage:
    return CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="visible answer")],
        thinking_blocks=[
            ThinkingBlock(text="step 1", signature="sig-1"),
            ThinkingBlock(text="step 2", signature="sig-2"),
        ],
    )


def test_openrouter_translate_anthropic_prepends_typed_thinking_parts() -> None:
    msg = _openrouter_http._translate_message(
        _assistant_with_thinking(),
        model_id="anthropic/claude-opus-4.7",
    )
    content = msg["content"]
    assert isinstance(content, list)
    # First two parts are typed thinking with signatures, then text.
    assert content[0] == {
        "type": "thinking", "thinking": "step 1", "signature": "sig-1",
    }
    assert content[1] == {
        "type": "thinking", "thinking": "step 2", "signature": "sig-2",
    }
    assert content[2]["type"] == "text"
    assert "visible answer" in content[2]["text"]
    # No reasoning_content fallback for Anthropic routes.
    assert "reasoning_content" not in msg


def test_openrouter_translate_non_anthropic_uses_reasoning_content_string() -> None:
    msg = _openrouter_http._translate_message(
        _assistant_with_thinking(),
        model_id="openai/gpt-5",
    )
    # Plain string content (no typed thinking parts) and a
    # reasoning_content sibling holding the concat.
    assert isinstance(msg["content"], str)
    assert msg.get("reasoning_content") == "step 1step 2"


def test_nano_gpt_translate_anthropic_prepends_typed_thinking_parts() -> None:
    msg = _nano_gpt_http._translate_message(
        _assistant_with_thinking(),
        model_id="claude-sonnet-4-6",
    )
    content = msg["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "thinking"
    assert content[0]["signature"] == "sig-1"


def test_nano_gpt_translate_non_anthropic_uses_reasoning_content_string() -> None:
    msg = _nano_gpt_http._translate_message(
        _assistant_with_thinking(),
        model_id="openai/gpt-5",
    )
    assert msg.get("reasoning_content") == "step 1step 2"


def test_xai_translate_concats_thinking_blocks_to_reasoning_content() -> None:
    msg = _xai_http._translate_message(_assistant_with_thinking())
    assert msg.get("reasoning_content") == "step 1step 2"


def test_chutes_translate_concats_thinking_blocks_to_reasoning_content() -> None:
    msg = _chutes_http._translate_message(_assistant_with_thinking())
    assert msg.get("reasoning_content") == "step 1step 2"


def test_tensorix_translate_concats_thinking_blocks_to_reasoning_content() -> None:
    msg = _tensorix_http._translate_message(_assistant_with_thinking())
    assert msg.get("reasoning_content") == "step 1step 2"


def test_novita_translate_concats_thinking_blocks_to_reasoning_content() -> None:
    msg = _novita_http._translate_message(_assistant_with_thinking())
    assert msg.get("reasoning_content") == "step 1step 2"


def test_mistral_translate_prepends_typed_thinking_parts() -> None:
    msg = _mistral_http._translate_message(_assistant_with_thinking())
    content = msg["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "thinking", "text": "step 1"}
    assert content[1] == {"type": "thinking", "text": "step 2"}


def test_assistant_without_thinking_blocks_stays_plain_string() -> None:
    """No regression for the common-case plain assistant message."""
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="hello")],
    )
    out_or = _openrouter_http._translate_message(
        msg, model_id="openai/gpt-5",
    )
    out_xai = _xai_http._translate_message(msg)
    assert isinstance(out_or["content"], str)
    assert "reasoning_content" not in out_or
    assert isinstance(out_xai["content"], str)
    assert "reasoning_content" not in out_xai


# ---------------------------------------------------------------------------
# Anthropic strip-and-retry helpers
# ---------------------------------------------------------------------------


def test_openrouter_signature_rejection_detector_matches_signature_body() -> None:
    body = (
        '{"error":{"type":"invalid_request_error",'
        '"message":"messages.1: missing thinking signature"}}'
    )
    assert _or_is_sig_rej(400, body) is True


def test_openrouter_signature_rejection_detector_rejects_non_400() -> None:
    body = "irrelevant"
    assert _or_is_sig_rej(500, body) is False


def test_openrouter_signature_rejection_detector_requires_thinking_or_signature() -> None:
    body = '{"error":{"type":"invalid_request_error","message":"bad model"}}'
    assert _or_is_sig_rej(400, body) is False


def test_openrouter_strip_removes_thinking_parts_and_reasoning_content() -> None:
    payload = {
        "messages": [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "x", "signature": "s"},
                    {"type": "text", "text": "visible"},
                ],
                "reasoning_content": "ignore me",
            },
        ],
    }
    _or_strip(payload)
    asst = payload["messages"][1]
    assert "reasoning_content" not in asst
    assert all(
        not (isinstance(c, dict) and c.get("type") == "thinking")
        for c in asst["content"]
    )
    # Visible text retained.
    assert any(
        isinstance(c, dict) and c.get("type") == "text" and c.get("text") == "visible"
        for c in asst["content"]
    )


def test_openrouter_strip_keeps_assistant_non_empty_with_placeholder() -> None:
    """Stripping a thinking-only assistant must leave a valid wire shape."""
    payload = {
        "messages": [{
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "x", "signature": "s"},
            ],
        }],
    }
    _or_strip(payload)
    asst = payload["messages"][0]
    # One placeholder text block kept so the wire shape stays valid.
    assert asst["content"] == [{"type": "text", "text": ""}]


def test_nano_gpt_signature_rejection_detector_matches_signature_body() -> None:
    body = (
        '{"error":{"type":"invalid_request_error",'
        '"message":"signature mismatch"}}'
    )
    assert _ng_is_sig_rej(400, body) is True


def test_nano_gpt_strip_mirrors_openrouter() -> None:
    payload = {
        "messages": [{
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "x", "signature": "s"},
                {"type": "text", "text": "visible"},
            ],
        }],
    }
    _ng_strip(payload)
    asst = payload["messages"][0]
    assert all(
        not (isinstance(c, dict) and c.get("type") == "thinking")
        for c in asst["content"]
    )
