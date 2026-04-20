# backend/tests/modules/llm/test_registry.py
from backend.modules.llm._registry import ADAPTER_REGISTRY


def test_registry_contains_xai_http():
    assert "xai_http" in ADAPTER_REGISTRY
    from backend.modules.llm._adapters._xai_http import XaiHttpAdapter
    assert ADAPTER_REGISTRY["xai_http"] is XaiHttpAdapter
