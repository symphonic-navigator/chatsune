from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from backend.modules.llm._adapters._events import ProviderStreamEvent
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    requires_key_for_listing: bool = True

    # If True, this provider needs user-facing setup (API key configuration).
    # Providers that work transparently (e.g. local daemons) set this to False
    # and are hidden from the API-Keys UI.
    requires_setup: bool = True

    # If True, the provider has no per-user credential and is shared across
    # all users (e.g. a self-hosted local daemon). When set, neither listing
    # nor inference performs a credential lookup.
    is_global: bool = False

    # Concurrency: adapters opt into serialisation by setting this.
    # Default NONE — adapter handles as many parallel inferences as the
    # caller throws at it (cloud providers, for example).
    from backend.modules.llm._concurrency import ConcurrencyPolicy
    concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.NONE

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
