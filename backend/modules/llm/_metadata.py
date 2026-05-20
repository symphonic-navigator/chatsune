"""Model listing + cache.

Two flavours live here side by side:

* **Connection-scoped** — keyed by ``llm:models:{connection_id}``. Used by
  the per-user LLM Connections path.

* **Premium-provider-scoped** — keyed by
  ``llm:models:premium:{user_id}:{provider_id}``. Used by the Premium
  Provider Accounts path. The key is *user-scoped* so that future provider
  integrations (dynamic Mistral listings, per-user xAI fine-tunes, etc.)
  never leak one user's model list into another user's cache.
"""

import json
import logging

from pydantic import ValidationError
from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._registry import _instantiate_adapter
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)
_TTL_SECONDS = 7 * 24 * 60 * 60


def _cache_key(connection_id: str) -> str:
    return f"llm:models:{connection_id}"


def _premium_cache_key(user_id: str, provider_id: str) -> str:
    return f"llm:models:premium:{user_id}:{provider_id}"


async def _fetch_and_cache(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Fetch from upstream and write to Redis. Raises adapter exceptions."""
    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _cache_key(c.id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=_TTL_SECONDS,
    )
    return models


async def get_models_for_connection(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,  # noqa: ARG001
) -> list[ModelMetaDto]:
    """Return cached models or an empty list. The background refresher owns
    cache population; this read path no longer fetches synchronously."""
    cached = await redis.get(_cache_key(c.id))
    if cached is None:
        return []
    try:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    except ValidationError as exc:
        _log.warning(
            "stale model cache for connection=%s — dropping: %s",
            c.id, exc,
        )
        await redis.delete(_cache_key(c.id))
        return []


async def refresh_connection_models(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Drop cache and re-fetch. Raises on upstream failure so the caller
    can surface the error (rather than silently reporting success)."""
    await redis.delete(_cache_key(c.id))
    return await _fetch_and_cache(c, adapter_cls, redis)


# --- Premium Provider model listing ---------------------------------------


async def _fetch_and_cache_premium(
    c: ResolvedConnection,
    adapter_cls: type[BaseAdapter],
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Fetch from upstream and write to the user-scoped premium cache."""
    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _premium_cache_key(user_id, provider_id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=_TTL_SECONDS,
    )
    return models


async def get_premium_models(
    c: ResolvedConnection,  # noqa: ARG001
    adapter_cls: type[BaseAdapter],  # noqa: ARG001
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Return cached premium-provider models or empty. The background
    refresher owns cache population; no synchronous fetch on miss."""
    cached = await redis.get(_premium_cache_key(user_id, provider_id))
    if cached is None:
        return []
    try:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    except ValidationError as exc:
        _log.warning(
            "stale premium model cache for provider=%s user=%s — dropping: %s",
            provider_id, user_id, exc,
        )
        await redis.delete(_premium_cache_key(user_id, provider_id))
        return []


async def refresh_premium_models(
    c: ResolvedConnection,
    adapter_cls: type[BaseAdapter],
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Drop the user-scoped premium cache and re-fetch. Raises on upstream
    failure so the caller can surface the error."""
    await redis.delete(_premium_cache_key(user_id, provider_id))
    return await _fetch_and_cache_premium(
        c, adapter_cls, redis, user_id, provider_id,
    )
