"""Capability resolution: YAML override -> adapter heuristic -> universal fallback.

See devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md §5.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


@dataclass(frozen=True)
class CapabilityHint:
    reasoning: ReasoningCapability
    tools: ToolCapability
    first_class_support: bool = False


@dataclass(frozen=True)
class ResolvedCapabilities:
    reasoning: ReasoningCapability
    tools: ToolCapability
    first_class_support: bool


class _AdapterCapabilityProvider(Protocol):
    def capability_hint(self, model_id: str) -> CapabilityHint | None: ...


_YAML_PATH = Path(__file__).parent / "data" / "model_capabilities.yaml"


def _load_yaml() -> list[dict]:
    """Read and parse the YAML on every call.

    Re-reading on every call (microseconds for ~75 lines) is cheaper than
    a stale cache. Editing the YAML during a dev session takes effect on
    the next request — no backend restart required. ``lru_cache`` was a
    correct optimisation in principle and a usability footgun in practice.
    """
    if not _YAML_PATH.exists():
        return []
    with _YAML_PATH.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get("models", []) or []


def _yaml_lookup(adapter_type: str, model_id: str) -> CapabilityHint | None:
    for entry in _load_yaml():
        if entry.get("adapter") != adapter_type:
            continue
        pattern = entry.get("pattern", "")
        if not fnmatch.fnmatch(model_id, pattern):
            continue
        r = entry["reasoning"]
        effort = None
        if r.get("effort"):
            effort = ReasoningEffortSpec(
                buckets=r["effort"]["buckets"],
                default_bucket=r["effort"]["default_bucket"],
            )
        reasoning = ReasoningCapability(
            kind=r["kind"],
            effort=effort,
            default_on=r.get("default_on", True),
        )
        t = entry.get("tools", {})
        tools = ToolCapability(
            supported=t.get("supported", True),
            exclusive_with_reasoning=t.get("exclusive_with_reasoning", False),
        )
        return CapabilityHint(
            reasoning=reasoning, tools=tools, first_class_support=True
        )
    return None


DEFAULT_CAPABILITIES = ResolvedCapabilities(
    reasoning=ReasoningCapability(kind="optional"),
    tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
    first_class_support=False,
)


def resolve_capabilities(
    *,
    adapter_type: str,
    model_id: str,
    adapter: _AdapterCapabilityProvider,
) -> ResolvedCapabilities:
    if hint := _yaml_lookup(adapter_type, model_id):
        return ResolvedCapabilities(
            reasoning=hint.reasoning,
            tools=hint.tools,
            first_class_support=True,
        )
    if hint := adapter.capability_hint(model_id):
        return ResolvedCapabilities(
            reasoning=hint.reasoning,
            tools=hint.tools,
            first_class_support=hint.first_class_support,
        )
    return DEFAULT_CAPABILITIES
