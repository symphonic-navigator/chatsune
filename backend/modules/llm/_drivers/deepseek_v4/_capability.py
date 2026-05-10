"""DeepSeek V4 capability spec.

Effort vocabulary is ``[high, max]`` per DeepSeek's official thinking-mode
docs (https://api-docs.deepseek.com/guides/thinking_mode): "low and medium
are mapped to high". We expose those two and only those two — router
extensions (OR's minimal/low/medium, Novita's silent-low) are not exposed
because their behaviour is not specified by DeepSeek.

Per-adapter override: see ``_quirks.py``. As of probe 2026-05-10, the
OR-Flash xhigh path halves reasoning instead of expanding it, so we
drop "max" from the buckets list for that combination only.
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers.deepseek_v4._quirks import (
    _is_or_flash_quirk_applicable,
)
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

    Default: ``buckets=["high","max"]``. Override: when the OR-Flash
    quirk applies (see ``_quirks.py``), drop ``"max"`` from the buckets
    list. Re-probe quarterly; drop the override branch when fixed.
    """
    if _is_or_flash_quirk_applicable(adapter_type, slug):
        # OR-quirk override (probed 2026-05-10): xhigh halves Flash
        # reasoning. Re-probe via dsv4_flash_or_drift.py; next due
        # 2026-08-10. Drop this branch when the probe flips to FIXED.
        buckets = ["high"]
    else:
        buckets = ["high", "max"]

    return ResolvedCapabilities(
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=buckets,
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
