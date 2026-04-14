"""Abstract base for upstream inference adapters (connections refactor)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from fastapi import APIRouter

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Stateless adapter — one class per backend-type, one instance per request."""

    # Subclasses MUST override
    adapter_type: str = ""
    display_name: str = ""
    view_id: str = ""
    secret_fields: frozenset[str] = frozenset()

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return []

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return []

    @classmethod
    def router(cls) -> APIRouter | None:
        """Optional adapter-specific sub-router (test, diagnostics, pair, ...)."""
        return None

    @abstractmethod
    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        ...

    @abstractmethod
    def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        ...
