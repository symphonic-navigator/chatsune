"""Verifies the resolver maps the openrouter premium id to its adapter."""

from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE


def test_openrouter_maps_to_openrouter_http_adapter():
    assert _PREMIUM_ADAPTER_TYPE["openrouter"] == "openrouter_http"
