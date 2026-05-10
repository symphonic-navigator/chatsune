"""Tests verifying resolve_capabilities consults the driver registry
before falling through to YAML and adapter heuristics.
"""
from __future__ import annotations

import pytest

from backend.modules.llm._capabilities import (
    DEFAULT_CAPABILITIES,
    ResolvedCapabilities,
    resolve_capabilities,
)
from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


class _NoOpAdapter:
    """Adapter that gives no capability hint — forces fallthrough."""
    def capability_hint(self, model_id: str):
        return None


_DSv4_DRIVER_SPEC = ResolvedCapabilities(
    reasoning=ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(buckets=["high", "max"], default_bucket="high"),
        default_on=True,
    ),
    tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
    first_class_support=True,
)


class _StubDSv4Driver:
    PATTERNS = ["deepseek-v4*"]

    def capability_spec(self, *, adapter_type: str, slug: str):
        return _DSv4_DRIVER_SPEC

    def build_request(self, **_):
        raise NotImplementedError

    def parse_chunk(self, **_):
        raise NotImplementedError


def test_no_driver_match_falls_through_to_default(monkeypatch):
    """When no driver matches and no yaml entry matches, behaviour is unchanged."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY", [],
    )
    result = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="some/random-model-no-yaml-match",
        adapter=_NoOpAdapter(),
    )
    assert result == DEFAULT_CAPABILITIES


def test_driver_match_wins_over_yaml(monkeypatch):
    """A matching driver beats a yaml entry that would also match."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDSv4Driver],
    )
    # Even if a yaml entry existed for deepseek-v4, the driver wins.
    result = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="deepseek/deepseek-v4-pro",
        adapter=_NoOpAdapter(),
    )
    assert result == _DSv4_DRIVER_SPEC
    assert result.first_class_support is True


def test_driver_basename_match_works_for_unprefixed_slug(monkeypatch):
    """Ollama-Cloud-style unprefixed slugs are matched on the bare basename."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDSv4Driver],
    )
    result = resolve_capabilities(
        adapter_type="ollama_http",
        model_id="deepseek-v4-pro",  # no namespace prefix
        adapter=_NoOpAdapter(),
    )
    assert result == _DSv4_DRIVER_SPEC


def test_driver_passes_adapter_type_and_slug(monkeypatch):
    """The driver receives the adapter_type and slug it was matched against
    (so it can branch internally per-router)."""
    captured = {}

    class _CapturingDriver:
        PATTERNS = ["captured-model*"]
        def capability_spec(self, *, adapter_type: str, slug: str):
            captured["adapter_type"] = adapter_type
            captured["slug"] = slug
            return DEFAULT_CAPABILITIES
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_CapturingDriver],
    )
    resolve_capabilities(
        adapter_type="some_adapter",
        model_id="vendor/captured-model-x",
        adapter=_NoOpAdapter(),
    )
    assert captured == {
        "adapter_type": "some_adapter",
        "slug": "vendor/captured-model-x",
    }
