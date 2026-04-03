"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

from collections.abc import AsyncIterator

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_BASE_URLS
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.modules.llm._metadata import get_models
from backend.database import get_db, get_redis
from shared.dtos.inference import CompletionRequest


class LlmCredentialNotFoundError(Exception):
    """User has no API key configured for the requested provider."""


class LlmProviderNotFoundError(Exception):
    """Provider ID is not registered in the adapter registry."""


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await CredentialRepository(db).create_indexes()
    await CurationRepository(db).create_indexes()
    await UserModelConfigRepository(db).create_indexes()


def is_valid_provider(provider_id: str) -> bool:
    """Return True if provider_id is registered in the adapter registry."""
    return provider_id in ADAPTER_REGISTRY


async def stream_completion(
    user_id: str,
    provider_id: str,
    request: CompletionRequest,
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve user's API key, instantiate adapter, stream completion.

    Raises:
        LlmProviderNotFoundError: provider_id not in registry.
        LlmCredentialNotFoundError: user has no key for this provider.
    """
    if provider_id not in ADAPTER_REGISTRY:
        raise LlmProviderNotFoundError(f"Unknown provider: {provider_id}")

    repo = CredentialRepository(get_db())
    cred = await repo.find(user_id, provider_id)
    if not cred:
        raise LlmCredentialNotFoundError(
            f"No API key configured for provider '{provider_id}'"
        )

    api_key = repo.get_raw_key(cred)
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])

    async for event in adapter.stream_completion(api_key, request):
        yield event


async def get_model_context_window(provider_id: str, model_slug: str) -> int | None:
    """Return the context window size for a model, or None if not found."""
    if provider_id not in ADAPTER_REGISTRY:
        return None
    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    models = await get_models(provider_id, redis, adapter)
    for model in models:
        if model.model_id == model_slug:
            return model.context_window
    return None


__all__ = [
    "router",
    "init_indexes",
    "is_valid_provider",
    "stream_completion",
    "LlmCredentialNotFoundError",
    "LlmProviderNotFoundError",
    "UserModelConfigRepository",
    "get_model_context_window",
]
