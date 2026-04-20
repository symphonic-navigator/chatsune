"""ADAPTER_REGISTRY contents — xai_http is Premium-only and not user-createable."""

from backend.modules.llm._registry import ADAPTER_REGISTRY


def test_xai_http_not_in_registry():
    # Premium resolver instantiates XaiHttpAdapter directly; the class stays
    # importable, but user connections cannot be created with this type.
    assert "xai_http" not in ADAPTER_REGISTRY


def test_ollama_http_still_in_registry():
    assert "ollama_http" in ADAPTER_REGISTRY


def test_xai_http_class_still_importable():
    from backend.modules.llm._adapters._xai_http import XaiHttpAdapter

    assert XaiHttpAdapter is not None
