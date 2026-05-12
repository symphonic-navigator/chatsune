"""Capability spec for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

See devdocs/research/kimi-k2-wire-shapes.md for the wire-shape probes
that produced this matrix.
"""
from __future__ import annotations

from backend.modules.llm._capabilities import ResolvedCapabilities


def kimi_k2_capability_spec(
    *, adapter_type: str, slug: str,
) -> ResolvedCapabilities:
    raise NotImplementedError("filled in Task 2")
