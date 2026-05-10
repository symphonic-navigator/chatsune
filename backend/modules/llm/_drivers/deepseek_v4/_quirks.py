"""DeepSeek V4 router-specific quirks.

Single source of truth for empirically-verified upstream bugs that the
driver layer has to work around. Each quirk has:
- a precise applicability check (adapter_type + slug pattern)
- a date when it was last probed
- a re-probe instruction (see ``backend/llm_harness/probes/``)

When a probe shows a quirk has been fixed upstream, drop the relevant
branch from this module and from any call site that consults it.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

# OR-quirk: DSv4 Flash + reasoning.effort=xhigh halves the reasoning
# budget instead of expanding it. Probed 2026-05-10 with the prime-
# infinitude prompt: high=4039 reasoning_tokens, xhigh=2300 (ratio 0.57).
# OR rejects effort="max" (HTTP 400) so xhigh is the only available
# mapping; there is no other path to try.
#
# Re-probe quarterly via:
#   uv run python -m backend.llm_harness.probes.dsv4_flash_or_drift
# Next due: 2026-08-10. Drop the branch (and the override in
# ``_capability.py`` and ``_builders.py``) when the probe verdict flips
# to FIXED.
OR_FLASH_QUIRK_PROBED_AT = "2026-05-10"


def _is_or_flash_quirk_applicable(adapter_type: str, slug: str) -> bool:
    """Return True iff the OR-Flash xhigh-broken quirk applies here.

    Slug match is fnmatch-basename, case-insensitive — covers both the
    OR-prefixed form ``deepseek/deepseek-v4-flash`` and the un-prefixed
    Ollama form ``deepseek-v4-flash``.
    """
    if adapter_type != "openrouter_http":
        return False
    basename = slug.split("/", 1)[-1].lower()
    return fnmatchcase(basename, "*flash*")
