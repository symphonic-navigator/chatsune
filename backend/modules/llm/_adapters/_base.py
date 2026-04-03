from abc import ABC, abstractmethod

from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        """Return True if the key is valid for this provider."""
        ...

    @abstractmethod
    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch all available models with their capabilities."""
        ...
