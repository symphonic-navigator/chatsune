from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from backend.modules.llm._adapters._events import ProviderStreamEvent
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        """Return True if the key is valid for this provider."""
        ...

    @abstractmethod
    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch all available models with their capabilities."""
        ...

    @abstractmethod
    def stream_completion(
        self,
        api_key: str,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream inference events from the upstream provider."""
        ...
