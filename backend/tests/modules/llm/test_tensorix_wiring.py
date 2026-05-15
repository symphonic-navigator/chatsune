"""End-to-end wiring tests for Tensorix in the LLM registry + resolver."""
from __future__ import annotations

from backend.modules.llm._registry import (
    _PREMIUM_ONLY_ADAPTERS,
    ADAPTER_REGISTRY,
    get_adapter_class,
)


def test_tensorix_is_premium_only_not_user_creatable():
    assert "tensorix_http" not in ADAPTER_REGISTRY
    assert "tensorix_http" in _PREMIUM_ONLY_ADAPTERS


def test_get_adapter_class_resolves_tensorix():
    cls = get_adapter_class("tensorix_http")
    assert cls is not None
    assert cls.__name__ == "TensorixHttpAdapter"


def test_resolver_premium_map_includes_tensorix():
    from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE
    assert _PREMIUM_ADAPTER_TYPE["tensorix"] == "tensorix_http"
