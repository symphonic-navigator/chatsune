"""Capability spec for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that produced this matrix:

| Slug basename | adapter_type    | reasoning.kind | tools |
|---------------|-----------------|----------------|-------|
| kimi-k2.5*    | ollama_http     | optional       | true  |
| kimi-k2.6*    | ollama_http     | optional       | true  |
| kimi-k2.5*    | novita_http     | no_reasoning   | true  |
| kimi-k2.6*    | novita_http     | always_on      | true  |

``first_class_support = true`` and ``tools.supported = true`` on every
cell. ``effort = None`` everywhere — Kimi has no documented effort
buckets and probes did not surface a working knob on either provider.
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers.kimi_k2._helpers import (
    _kimi_version,
    _unsupported_adapter,
)
from shared.dtos.llm import (
    ReasoningCapability,
    ToolCapability,
)


def kimi_k2_capability_spec(
    *, adapter_type: str, slug: str,
) -> ResolvedCapabilities:
    """Return the (adapter, slug)-specific capability spec for Kimi K2."""

    tools = ToolCapability(supported=True, exclusive_with_reasoning=False)

    if adapter_type == "ollama_http":
        # K2.5 and K2.6 both honour the ``think: true/false`` flag at
        # Ollama Cloud (probe 2026-05-12). Default-on matches the K2
        # family branding as a reasoning model.
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="optional", effort=None, default_on=True,
            ),
            tools=tools,
            first_class_support=True,
        )

    if adapter_type == "novita_http":
        version = _kimi_version(slug)
        if version == "k2.5":
            # Novita K2.5 never populates reasoning_content regardless of
            # the ``reasoning.enabled`` flag (probe 2026-05-12). Treat as
            # a non-reasoning model on this provider.
            return ResolvedCapabilities(
                reasoning=ReasoningCapability(
                    kind="no_reasoning", effort=None, default_on=False,
                ),
                tools=tools,
                first_class_support=True,
            )
        # version == "k2.6"
        # Novita K2.6 always emits reasoning_content; the toggle is
        # ignored upstream (probe 2026-05-12). ``always_on`` keeps the
        # UI honest — no toggle shown for a knob that does nothing.
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="always_on", effort=None, default_on=True,
            ),
            tools=tools,
            first_class_support=True,
        )

    raise _unsupported_adapter(adapter_type)
