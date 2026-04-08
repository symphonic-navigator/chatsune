import os

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from backend.modules.llm._adapters._ollama_local import OllamaLocalAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_cloud": OllamaCloudAdapter,
    "ollama_local": OllamaLocalAdapter,
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud": "Ollama Cloud",
    "ollama_local": "Ollama Local",
}

PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud": "https://ollama.com",
    "ollama_local": os.environ.get("OLLAMA_LOCAL_BASE_URL", "http://localhost:11434"),
}
