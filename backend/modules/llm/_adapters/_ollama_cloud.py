from shared.dtos.llm import ModelMetaDto
from backend.modules.llm._adapters._base import BaseAdapter


class OllamaCloudAdapter(BaseAdapter):
    """Ollama Cloud inference adapter. Full implementation is deferred."""

    DISPLAY_NAME = "Ollama Cloud"

    async def validate_key(self, api_key: str) -> bool:
        raise NotImplementedError("OllamaCloudAdapter.validate_key not yet implemented")

    async def fetch_models(self) -> list[ModelMetaDto]:
        raise NotImplementedError("OllamaCloudAdapter.fetch_models not yet implemented")
