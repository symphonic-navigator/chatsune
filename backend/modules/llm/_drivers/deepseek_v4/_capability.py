"""DeepSeek V4 capability spec.

Effort vocabulary is ``[high, max]`` per DeepSeek's official thinking-mode
docs (https://api-docs.deepseek.com/guides/thinking_mode): "low and medium
are mapped to high". We expose those two and only those two — router
extensions (OR's minimal/low/medium, Novita's silent-low) are not exposed
because their behaviour is not specified by DeepSeek.

Plan 1 returns a single capability spec regardless of (adapter_type, slug).
Plans 2-4 may diverge per router (e.g. Novita drops "max" from buckets).
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


def deepseek_v4_capability_spec(
    *,
    adapter_type: str,
    slug: str,
) -> ResolvedCapabilities:
    """Return the DeepSeek V4 capability spec for (adapter_type, slug).

    Plan 1: capability is router-agnostic — same spec for OR, nano-gpt,
    Novita, Ollama Cloud. Plans 2+ may branch on adapter_type when the
    Novita "max-rejected" rule lands.
    """
    return ResolvedCapabilities(
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["high", "max"],
                default_bucket="high",
            ),
            default_on=True,
        ),
        tools=ToolCapability(
            supported=True,
            exclusive_with_reasoning=False,
        ),
        first_class_support=True,
    )
