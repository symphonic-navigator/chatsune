"""Tests for the driver registry and match_driver dispatch."""
from __future__ import annotations

from backend.modules.llm._drivers import DRIVER_REGISTRY, match_driver


class _StubDriver:
    PATTERNS = ["stub-model*"]
    # match_driver is adapter-aware (see _drivers/__init__.py and the
    # Driver protocol's SUPPORTED_ADAPTERS docstring); the stub claims
    # a single fake adapter_type so existing matching tests stay scoped.
    SUPPORTED_ADAPTERS = frozenset({"test_adapter"})

    def capability_spec(self, **_):
        raise NotImplementedError

    def build_request(self, **_):
        raise NotImplementedError

    def parse_chunk(self, **_):
        raise NotImplementedError


def test_registry_contains_dsv4():
    """After Task 7, DRIVER_REGISTRY contains DeepSeekV4Driver."""
    from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver
    assert DeepSeekV4Driver in DRIVER_REGISTRY


def test_registry_contains_kimi():
    """After Task 1 of kimi-k2 plan, DRIVER_REGISTRY contains KimiK2Driver."""
    from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver
    assert KimiK2Driver in DRIVER_REGISTRY


def test_match_driver_returns_none_for_unrecognised_slug():
    """Slug that does not match any registered driver's PATTERNS returns None."""
    # The adapter_type is irrelevant here — the slug never matches any
    # PATTERNS in the real registry, so no driver is returned regardless.
    assert match_driver(adapter_type="openrouter_http", slug="anything/at-all") is None


def test_match_driver_basename_fnmatch(monkeypatch):
    """Driver matching uses the slug basename, not the full slug."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDriver],
    )
    assert match_driver(adapter_type="test_adapter", slug="stub-model-pro") is _StubDriver
    assert match_driver(adapter_type="test_adapter", slug="vendor/stub-model-pro") is _StubDriver
    assert match_driver(adapter_type="test_adapter", slug="vendor/group/stub-model-pro") is _StubDriver
    assert match_driver(adapter_type="test_adapter", slug="stub-model-pro:thinking") is _StubDriver
    assert match_driver(adapter_type="test_adapter", slug="other-model") is None


def test_match_driver_first_match_wins(monkeypatch):
    class _A:
        PATTERNS = ["foo*"]
        SUPPORTED_ADAPTERS = frozenset({"test_adapter"})
        def capability_spec(self, **_): raise NotImplementedError
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    class _B:
        PATTERNS = ["foo-bar*"]
        SUPPORTED_ADAPTERS = frozenset({"test_adapter"})
        def capability_spec(self, **_): raise NotImplementedError
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_A, _B],
    )
    assert match_driver(adapter_type="test_adapter", slug="foo-bar-baz") is _A


def test_match_driver_returns_none_when_adapter_type_not_in_supported_adapters(monkeypatch):
    """Slug matches PATTERNS but adapter_type is not in SUPPORTED_ADAPTERS
    → fall through. This is the guard that prevents listing-time
    NotImplementedError crashes (e.g. MiMo on OpenRouter, Kimi on nano-gpt)."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDriver],
    )
    # Slug DOES match "stub-model*"; adapter_type does NOT match
    # SUPPORTED_ADAPTERS — driver is skipped, caller gets None.
    assert (
        match_driver(adapter_type="other_adapter", slug="stub-model-pro")
        is None
    )
