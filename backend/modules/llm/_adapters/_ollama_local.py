from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter


class OllamaLocalAdapter(OllamaBaseAdapter):
    """Ollama Local adapter — talks to a self-hosted Ollama daemon, no API key."""

    provider_id = "ollama_local"
    provider_display_name = "Ollama Local"
    requires_key_for_listing: bool = False
    is_global: bool = True

    def _auth_headers(self, api_key: str | None) -> dict:
        return {}

    async def validate_key(self, api_key: str | None) -> bool:
        return True
