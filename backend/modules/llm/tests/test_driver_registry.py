"""Tests for the driver registry and match_driver dispatch."""
from __future__ import annotations

from backend.modules.llm._drivers import DRIVER_REGISTRY, match_driver


class _StubDriver:
    PATTERNS = ["stub-model*"]

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


def test_match_driver_returns_none_when_registry_empty():
    assert match_driver("anything/at-all") is None


def test_match_driver_basename_fnmatch(monkeypatch):
    """Driver matching uses the slug basename, not the full slug."""
    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_StubDriver],
    )
    assert match_driver("stub-model-pro") is _StubDriver
    assert match_driver("vendor/stub-model-pro") is _StubDriver
    assert match_driver("vendor/group/stub-model-pro") is _StubDriver
    assert match_driver("stub-model-pro:thinking") is _StubDriver
    assert match_driver("other-model") is None


def test_match_driver_first_match_wins(monkeypatch):
    class _A:
        PATTERNS = ["foo*"]
        def capability_spec(self, **_): raise NotImplementedError
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    class _B:
        PATTERNS = ["foo-bar*"]
        def capability_spec(self, **_): raise NotImplementedError
        def build_request(self, **_): raise NotImplementedError
        def parse_chunk(self, **_): raise NotImplementedError

    monkeypatch.setattr(
        "backend.modules.llm._drivers.DRIVER_REGISTRY",
        [_A, _B],
    )
    assert match_driver("foo-bar-baz") is _A
