import pytest

from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from backend.modules.llm._adapters._ollama_local import OllamaLocalAdapter
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    PROVIDER_BASE_URLS,
    PROVIDER_DISPLAY_NAMES,
)


def test_local_adapter_metadata():
    adapter = OllamaLocalAdapter(base_url="http://localhost:11434")
    assert adapter.provider_id == "ollama_local"
    assert adapter.provider_display_name == "Ollama Local"
    assert adapter.requires_key_for_listing is False
    assert adapter._auth_headers(None) == {}
    assert adapter._auth_headers("anything") == {}


@pytest.mark.asyncio
async def test_local_adapter_validate_key_is_noop():
    adapter = OllamaLocalAdapter(base_url="http://localhost:11434")
    assert await adapter.validate_key(None) is True
    assert await adapter.validate_key("ignored") is True


def test_local_adapter_registered():
    assert "ollama_local" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["ollama_local"] is OllamaLocalAdapter
    assert PROVIDER_DISPLAY_NAMES["ollama_local"] == "Ollama Local"
    assert PROVIDER_BASE_URLS["ollama_local"].startswith("http://")


def test_is_global_flags():
    assert OllamaLocalAdapter.is_global is True
    assert OllamaCloudAdapter.is_global is False
