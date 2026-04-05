from backend.modules.websearch._adapters._base import BaseSearchAdapter
from backend.modules.websearch._adapters._ollama_cloud import OllamaCloudSearchAdapter

SEARCH_ADAPTER_REGISTRY: dict[str, type[BaseSearchAdapter]] = {
    "ollama_cloud": OllamaCloudSearchAdapter,
}

SEARCH_PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud": "https://ollama.com",
}

SEARCH_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud": "Ollama Cloud",
}

# Maps search provider → credential source.
#
# Format: "llm:<provider_id>"  → reuse the API key from that LLM provider
#         None                 → provider has its own credential (stored in
#                                this module's own credential collection, TBD)
#
# Examples:
#   "ollama_cloud": "llm:ollama_cloud"   — shared with LLM inference key
#   "brave":        None                  — own API key
#   "openrouter":   "llm:openrouter"     — shared with OpenRouter inference key
KEY_SOURCES: dict[str, str | None] = {
    "ollama_cloud": "llm:ollama_cloud",
}
