from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_DISPLAY_NAMES
from backend.modules.llm._adapters._base import BaseAdapter


def test_ollama_cloud_is_registered():
    assert "ollama_cloud" in ADAPTER_REGISTRY


def test_all_registered_adapters_extend_base():
    for provider_id, adapter_class in ADAPTER_REGISTRY.items():
        assert issubclass(adapter_class, BaseAdapter), (
            f"{provider_id}: {adapter_class} does not extend BaseAdapter"
        )


def test_all_registered_adapters_have_display_name():
    for provider_id in ADAPTER_REGISTRY:
        assert provider_id in PROVIDER_DISPLAY_NAMES, (
            f"{provider_id} missing from PROVIDER_DISPLAY_NAMES"
        )
