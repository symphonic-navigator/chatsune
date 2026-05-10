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


# Slugs the chatsune product treats as first-class for DSv4 on nano-gpt.
# The two upstream paths we deliberately exclude:
#   * ``TEE/deepseek-v4-*`` — TEE is an incomplete vLLM-derived upstream;
#     quirks are not worth chatsune support burden.
#   * ``deepseek/deepseek-v4-*-cheaper`` — routes via the Chinese DeepSeek
#     upstream; privacy-first product stance keeps these visible (users
#     may opt in) but off the curated/recommended path.
# Both classes remain streamable via the regular nano-gpt adapter; they
# simply do not get the ``first_class_support=True`` UI signal.
def _is_nano_gpt_first_class(slug: str) -> bool:
    """Return True for the curated DSv4 family on nano-gpt.

    Curated set: ``deepseek/deepseek-v4-pro`` and ``deepseek/deepseek-v4-flash``,
    with optional ``:thinking`` pair-suffix. Excluded: ``TEE/*`` and
    ``*-cheaper`` variants. Case-insensitive on the upstream prefix to
    survive any future casing drift in nano-gpt's catalogue (the
    ``-cheaper`` token is also matched case-insensitively).
    """
    lower = slug.lower()
    if lower.startswith("tee/"):
        return False
    if "-cheaper" in lower:
        return False
    # Strip optional :thinking pair-suffix before matching the family.
    base = lower[: -len(":thinking")] if lower.endswith(":thinking") else lower
    return base in (
        "deepseek/deepseek-v4-pro",
        "deepseek/deepseek-v4-flash",
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

    nano-gpt: on/off only — no effort buckets exposed (slug-pair
    switching at the adapter layer encodes thinking mode). Slug-based
    ``first_class_support`` differentiation: curated DSv4 family yes,
    ``TEE/*`` and ``*-cheaper`` no.
    """
    if adapter_type == "nano_gpt_http":
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="optional",
                effort=None,
                default_on=True,
            ),
            tools=ToolCapability(
                supported=True,
                exclusive_with_reasoning=False,
            ),
            first_class_support=_is_nano_gpt_first_class(slug),
        )

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
