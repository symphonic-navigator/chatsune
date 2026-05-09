"""Translation-layer tests for the nano_gpt adapter.

Verify the new ``build_request_body`` shape: ``request.reasoning`` and
``request.extras`` translate into the appropriate body fields per
dispatch mode (slug / flag / none).

The adapter has three dispatch modes captured by the per-connection
pair_map:

* ``slug``: pick a different upstream slug. Body must NOT carry the
  reasoning field.
* ``flag``: same slug, body carries ``{"reasoning": {"enabled": …}}``
  plus optional ``effort``.
* ``none``: same slug, no reasoning field.

When called without a ``pair`` argument, ``build_request_body``
defaults to flag-mode behaviour for ``reasoning.kind=optional`` and
no-reasoning behaviour otherwise — this matches what the adapter
emits for any model whose pair entry has ``switching_mode='flag'``.
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

from backend.modules.llm._adapters._nano_gpt_http import build_request_body


def _user(text: str) -> CompletionMessage:
    return CompletionMessage(
        role="user", content=[ContentPart(type="text", text=text)],
    )


def _req(
    model: str,
    extras: ChatSessionExtras,
    reasoning: ReasoningCapability,
    tool_supported: bool = True,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[_user("hi")],
        reasoning=reasoning,
        tools_capability=ToolCapability(supported=tool_supported),
        extras=extras,
    )


# ----- flag-mode (default when no pair is supplied) -----


def test_nano_gpt_flag_mode_reasoning_on_sends_enabled_true():
    req = _req(
        "claude-sonnet-4-6",
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort="medium",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
    )
    body, _slug = build_request_body(req)
    assert body.get("reasoning", {}).get("enabled") is True


def test_nano_gpt_flag_mode_reasoning_off_sends_enabled_false_explicit():
    req = _req(
        "claude-sonnet-4-6",
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
    )
    body, _slug = build_request_body(req)
    assert body.get("reasoning", {}).get("enabled") is False


def test_nano_gpt_effort_passed_when_set():
    req = _req(
        "gpt-5",
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["minimal", "low", "medium", "high"],
                default_bucket="medium",
            ),
        ),
    )
    body, _slug = build_request_body(req)
    assert body.get("reasoning", {}).get("effort") == "high"


# ----- explicit pair argument exercises slug / flag / none dispatch -----


def test_nano_gpt_slug_pair_swaps_slug_and_omits_reasoning_field():
    pair = {
        "non_thinking_slug": "anthropic/claude-opus-4.6",
        "thinking_slug": "anthropic/claude-opus-4.6:thinking",
        "switching_mode": "slug",
    }
    req = _req(
        "anthropic/claude-opus-4.6",
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
    )
    body, slug = build_request_body(req, pair)
    assert slug == "anthropic/claude-opus-4.6:thinking"
    assert body["model"] == "anthropic/claude-opus-4.6:thinking"
    forbidden = {"reasoning", "reasoning_effort", "reasoning_content", "thinking"}
    assert not (forbidden & set(body.keys()))


def test_nano_gpt_slug_pair_off_picks_non_thinking_slug():
    pair = {
        "non_thinking_slug": "anthropic/claude-opus-4.6",
        "thinking_slug": "anthropic/claude-opus-4.6:thinking",
        "switching_mode": "slug",
    }
    req = _req(
        "anthropic/claude-opus-4.6",
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
    )
    body, slug = build_request_body(req, pair)
    assert slug == "anthropic/claude-opus-4.6"
    assert body["model"] == "anthropic/claude-opus-4.6"


def test_nano_gpt_none_pair_omits_reasoning_even_when_user_toggles_on():
    pair = {
        "non_thinking_slug": "vendor/plain",
        "thinking_slug": None,
        "switching_mode": "none",
    }
    req = _req(
        "vendor/plain",
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort=None,
        ),
        ReasoningCapability(kind="optional"),
    )
    body, slug = build_request_body(req, pair)
    assert slug == "vendor/plain"
    forbidden = {"reasoning", "reasoning_effort", "reasoning_content", "thinking"}
    assert not (forbidden & set(body.keys()))


def test_nano_gpt_flag_pair_carries_reasoning_object():
    pair = {
        "non_thinking_slug": "openai/gpt-5",
        "thinking_slug": "openai/gpt-5",
        "switching_mode": "flag",
    }
    req = _req(
        "openai/gpt-5",
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["minimal", "low", "medium", "high"],
                default_bucket="medium",
            ),
        ),
    )
    body, slug = build_request_body(req, pair)
    assert slug == "openai/gpt-5"
    assert body["reasoning"] == {"enabled": True, "effort": "medium"}


# ----- tools / no-reasoning gating -----


def test_nano_gpt_tools_omitted_when_session_has_tools_disabled():
    from shared.dtos.inference import ToolDefinition
    req = CompletionRequest(
        model="some-model",
        messages=[_user("hi")],
        reasoning=ReasoningCapability(kind="no_reasoning"),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
        tools=[ToolDefinition(
            name="t", description="d", parameters={"type": "object"},
        )],
    )
    body, _slug = build_request_body(req)
    assert "tools" not in body


def test_nano_gpt_no_reasoning_kind_omits_reasoning_field():
    req = _req(
        "plain-llm",
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
        ReasoningCapability(kind="no_reasoning"),
    )
    body, _slug = build_request_body(req)
    assert "reasoning" not in body


def test_nano_gpt_anthropic_model_uses_explicit_max_tokens():
    """For Anthropic models, nano-gpt (like OpenRouter) interprets the
    universal ``effort`` string as a percentage of response max_tokens.
    Send explicit max_tokens from the spec §6.4 budget table instead."""
    req = _req(
        "claude-sonnet-4-6",
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort="low",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
    )
    body, _slug = build_request_body(req)
    assert body["reasoning"]["max_tokens"] == 2048
    assert "effort" not in body["reasoning"]


def test_nano_gpt_non_anthropic_keeps_effort_string():
    req = _req(
        "gpt-5",
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["minimal", "low", "medium", "high"],
                default_bucket="medium",
            ),
        ),
    )
    body, _slug = build_request_body(req)
    assert body["reasoning"]["effort"] == "medium"
    assert "max_tokens" not in body["reasoning"]
