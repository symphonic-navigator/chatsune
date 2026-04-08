from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter


class OllamaCloudAdapter(OllamaBaseAdapter):
    """Ollama Cloud inference adapter (BYOK, /api/me validation)."""

    provider_id = "ollama_cloud"
    provider_display_name = "Ollama Cloud"
    requires_key_for_listing: bool = False

    def _auth_headers(self, api_key: str | None) -> dict:
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}

    async def validate_key(self, api_key: str) -> bool:
        """POST /api/me. Returns True on 200, False on 401/403, raises otherwise."""
        resp = await self._client.post(
            f"{self.base_url}/api/me",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        resp.raise_for_status()
        return False
