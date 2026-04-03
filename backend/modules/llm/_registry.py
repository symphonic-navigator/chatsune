from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_cloud": OllamaCloudAdapter,
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud": "Ollama Cloud",
}

PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud": "https://ollama.com",
}
