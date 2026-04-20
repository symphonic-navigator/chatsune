from backend.modules.websearch._adapters._base import BaseSearchAdapter
from backend.modules.websearch._adapters._ollama_cloud import OllamaCloudSearchAdapter

SEARCH_ADAPTER_REGISTRY: dict[str, type[BaseSearchAdapter]] = {
    "ollama_cloud_search": OllamaCloudSearchAdapter,
}

SEARCH_PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud_search": "https://ollama.com",
}

SEARCH_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud_search": "Ollama Web Search",
}

# Mapping from websearch provider_id → premium provider id whose account
# holds the API key used by the adapter. Task 13: all websearch API keys
# are now sourced via ``PremiumProviderService`` instead of a dedicated
# websearch credentials store.
WEBSEARCH_PROVIDER_TO_PREMIUM: dict[str, str] = {
    "ollama_cloud_search": "ollama_cloud",
}
