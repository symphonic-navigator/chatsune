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

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)
_TTL_SECONDS = 30 * 60


def _cache_key(connection_id: str) -> str:
    return f"llm:models:{connection_id}"


def _premium_cache_key(user_id: str, provider_id: str) -> str:
    return f"llm:models:premium:{user_id}:{provider_id}"


async def _fetch_and_cache(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Fetch from upstream and write to Redis. Raises adapter exceptions."""
    adapter = adapter_cls()
    models = await adapter.fetch_models(c)
    await redis.set(
        _cache_key(c.id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=_TTL_SECONDS,
    )
    return models


async def get_models_for_connection(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Return cached or freshly-fetched models; swallow errors for UI calm."""
    cached = await redis.get(_cache_key(c.id))
    if cached:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    try:
        return await _fetch_and_cache(c, adapter_cls, redis)
    except NotImplementedError:
        return []
    except Exception as exc:
        _log.warning("fetch_models failed for connection=%s: %s", c.id, exc)
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
    adapter = adapter_cls()
    models = await adapter.fetch_models(c)
    await redis.set(
        _premium_cache_key(user_id, provider_id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=_TTL_SECONDS,
    )
    return models


async def get_premium_models(
    c: ResolvedConnection,
    adapter_cls: type[BaseAdapter],
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Cached-or-fresh premium-provider model listing for ``user_id``.

    Swallows adapter exceptions to keep the model-picker UI calm — the
    refresh endpoint is the explicit retry path.
    """
    cached = await redis.get(_premium_cache_key(user_id, provider_id))
    if cached:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    try:
        return await _fetch_and_cache_premium(
            c, adapter_cls, redis, user_id, provider_id,
        )
    except NotImplementedError:
        return []
    except Exception as exc:
        _log.warning(
            "fetch_models failed for premium provider=%s user=%s: %s",
            provider_id, user_id, exc,
        )
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
