"""Request-body builders for DeepSeek V4.

Plan 1 ships only the OpenRouter builder, which delegates to the
existing OpenAI-compat builder in ``_openrouter_http.build_request_body``
after translating user-facing effort vocabulary into OR's wire
vocabulary.

User-facing effort vocabulary (per DeepSeek's thinking-mode docs):
    [high, max]

OR wire vocabulary (per OR's ``reasoning.effort``):
    [none, minimal, low, medium, high, xhigh]

DSv4-specific translation (Plan 1):
    user "high" -> wire "high"
    user "max"  -> wire "xhigh"
                   (OR's xhigh maps to DeepSeek-native max via upstream
                   system-prompt injection — see research doc)
"""
from __future__ import annotations

from typing import Any

from shared.dtos.inference import CompletionRequest


# User-effort -> OR wire effort. ``None`` and reasoning_mode="off" are
# handled separately (no translation, delegate unchanged).
_OR_EFFORT_MAP: dict[str, str] = {
    "high": "high",
    "max": "xhigh",
}


def build_request_for_openrouter(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the OR request body for DeepSeek V4 with effort translation.

    Strategy: translate the user-effort if needed, then delegate to the
    existing ``build_request_body`` so cache-marker, tool, message-content
    handling are inherited automatically.

    Raises ``ValueError`` when ``extras.reasoning_effort`` is set to a
    value outside the DSv4 supported buckets ``[high, max]``. Silent
    degradation is the exact failure mode this driver layer is meant to
    prevent.
    """
    # Local import to avoid a circular dependency at module load time
    # (drivers depend on adapter helpers; adapter consults drivers at
    # call time).
    from backend.modules.llm._adapters._openrouter_http import (
        build_request_body,
    )

    # Reasoning off OR no explicit effort: delegate unchanged.
    if (
        request.extras.reasoning_mode == "off"
        or request.extras.reasoning_effort is None
    ):
        return build_request_body(request)

    # Reasoning on AND effort explicit: translate or reject.
    user_effort = request.extras.reasoning_effort
    if user_effort not in _OR_EFFORT_MAP:
        raise ValueError(
            f"DeepSeek V4 effort {user_effort!r} not in supported "
            f"buckets {list(_OR_EFFORT_MAP.keys())}; cannot translate "
            f"for OpenRouter"
        )

    # Substitute the effort in extras and delegate. Pydantic v2 model_copy.
    translated = request.model_copy(
        update={
            "extras": request.extras.model_copy(
                update={"reasoning_effort": _OR_EFFORT_MAP[user_effort]},
            ),
        },
    )
    return build_request_body(translated)
