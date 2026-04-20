"""Adapter registry — maps adapter_type string to adapter class."""

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._community import CommunityAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "xai_http": XaiHttpAdapter,
}
