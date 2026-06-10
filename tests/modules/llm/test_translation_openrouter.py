"""Translation-layer tests for the openrouter_http adapter.

Verify the new ``build_request_body`` shape: ``request.reasoning`` and
``request.extras`` translate into the appropriate body fields.

OpenRouter exposes reasoning via its unified ``reasoning`` object on the
OpenAI-compatible chat-completions endpoint. The translation rules are:

* ``reasoning.kind == "optional"``: body carries
  ``{"reasoning": {"enabled": <bool>}}`` plus ``"effort"`` when
  ``request.extras.reasoning_effort`` is set. The flag is always
  written explicitly (true or false) — vendors disagree on the default
  direction, so omitting the flag would surrender control. Per spec
  §6.3 we do NOT use the legacy ``reasoning: {exclude: true}`` shape.
* ``reasoning.kind == "no_reasoning"`` or ``"always_on"``: body must
  omit the ``reasoning`` field entirely.
"""

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

from backend.modules.llm._adapters._openrouter_http import build_request_body


def _user(text: str) -> CompletionMessage:
    return CompletionMessage(
        role="user", content=[ContentPart(type="text", text=text)],
    )


def _req(
    extras: ChatSessionExtras,
    reasoning: ReasoningCapability,
    model: str = "anthropic/claude-sonnet-4-6",
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[_user("hi")],
        reasoning=reasoning,
        tools_capability=ToolCapability(supported=True),
        extras=extras,
    )


def test_openrouter_optional_reasoning_off_sends_enabled_false_explicit():
    req = _req(
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("reasoning", {}).get("enabled") is False


def test_openrouter_optional_reasoning_on_with_effort_non_anthropic():
    """For non-Anthropic models, effort string is sent verbatim."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
        model="deepseek/deepseek-v4",
    )
    body = build_request_body(req)
    assert body["reasoning"]["effort"] == "medium"
    assert body["reasoning"]["enabled"] is True


def test_openrouter_no_reasoning_model_no_reasoning_field():
    req = _req(
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="no_reasoning"),
    )
    body = build_request_body(req)
    assert "reasoning" not in body


def test_openrouter_does_not_use_exclude_for_visibility_hide():
    """Per spec §2 non-goals: we never use reasoning.exclude to fake an off state."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("reasoning", {}).get("exclude") is None


def test_openrouter_anthropic_on_sends_only_enabled_no_effort():
    """For Anthropic models, effort is NOT sent (see INS-037).
    Cache_control survives, Sonnet's adaptive default-effort decides
    depth. Body is just ``{enabled: true}`` regardless of effort bucket."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort="low",
        ),
        ReasoningCapability(kind="optional"),
        model="anthropic/claude-sonnet-4.6",
    )
    body = build_request_body(req)
    assert body["reasoning"] == {"enabled": True}


def test_openrouter_anthropic_off_sends_only_enabled_false():
    req = _req(
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
        model="anthropic/claude-sonnet-4.6",
    )
    body = build_request_body(req)
    assert body["reasoning"] == {"enabled": False}


def test_openrouter_non_anthropic_keeps_effort_string():
    """For non-Anthropic models (OpenAI, DeepSeek, etc.), OpenRouter
    handles ``effort`` correctly — no need to translate to max_tokens."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
        model="openai/gpt-5",
    )
    body = build_request_body(req)
    assert body["reasoning"]["effort"] == "high"
    assert "max_tokens" not in body["reasoning"]


def test_openrouter_fable_keeps_effort():
    """Effort-based Claude (Fable) bypasses the INS-037 omission — the
    enabled flag alone is a silent no-op for this family (INS-055).
    Router-wide rule; Fable is first-class on nano-gpt only, but the
    wire shape must be correct on OpenRouter too."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
        model="anthropic/claude-fable-5",
    )
    body = build_request_body(req)
    assert body["reasoning"] == {"enabled": True, "effort": "medium"}


def test_openrouter_fable_off_sends_enabled_false_without_effort():
    """Off-path regression: the Fable exception must not leak effort
    into a reasoning-off body."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
        model="anthropic/claude-fable-5",
    )
    body = build_request_body(req)
    assert body["reasoning"] == {"enabled": False}
