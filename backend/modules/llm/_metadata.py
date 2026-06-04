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


def _encode_cache(models: list[ModelMetaDto], extras: dict) -> str:
    """Encode the model list and adapter-internal extras into one JSON
    envelope. Both share a single Redis value, write, and TTL — so the
    model list and any adapter-specific sidecar data (e.g. the nano-gpt
    pair map) can never diverge in cache lifetime."""
    return json.dumps({
        "models": [m.model_dump(mode="json") for m in models],
        "adapter_extras": extras or {},
    })


def _decode_cache(raw: str | bytes) -> tuple[list[dict], dict]:
    """Decode a cached value into ``(model_dicts, adapter_extras)``.

    Tolerates a LEGACY bare-list value — a pre-envelope cache entry that
    is a plain JSON list of model dicts — by treating it as
    ``(list, {})``. This keeps a deploy safe: entries written before this
    change still read cleanly until the refresher rewrites them in the
    envelope shape.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        # Legacy bare-list value: no extras.
        return parsed, {}
    models = parsed.get("models") or []
    extras = parsed.get("adapter_extras") or {}
    return models, extras


async def _fetch_and_cache(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Fetch from upstream and write to Redis. Raises adapter exceptions."""
    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _cache_key(c.id),
        _encode_cache(models, adapter.cache_extras()),
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
        model_dicts, _extras = _decode_cache(cached)
        return [ModelMetaDto.model_validate(m) for m in model_dicts]
    except ValidationError as exc:
        _log.warning(
            "stale model cache for connection=%s — dropping: %s",
            c.id, exc,
        )
        await redis.delete(_cache_key(c.id))
        return []


async def get_connection_adapter_extras(
    redis: Redis, connection_id: str,
) -> dict:
    """Return the adapter-internal extras dict persisted alongside the
    cached model list under ``llm:models:{connection_id}``.

    Returns ``{}`` on cache miss, a legacy bare-list value, or any parse
    error — callers treat an empty result the same as a cold cache."""
    cached = await redis.get(_cache_key(connection_id))
    if cached is None:
        return {}
    try:
        _models, extras = _decode_cache(cached)
    except (json.JSONDecodeError, ValueError):
        return {}
    return extras


async def get_premium_adapter_extras(
    redis: Redis, user_id: str, provider_id: str,
) -> dict:
    """Return the adapter-internal extras dict persisted alongside the
    cached model list under ``llm:models:premium:{user_id}:{provider_id}``.

    The premium cache is user-scoped, so reading it requires both
    ``user_id`` and ``provider_id`` — unlike the connection-scoped
    ``get_connection_adapter_extras``, which keys off ``connection_id``
    alone. A premium-resolved connection has ``id = "premium:{provider_id}"``,
    which does NOT match the user-scoped premium key, so the connection
    helper must never be used for the premium path.

    Returns ``{}`` on cache miss, a legacy bare-list value, or any parse
    error — callers treat an empty result the same as a cold cache."""
    cached = await redis.get(_premium_cache_key(user_id, provider_id))
    if cached is None:
        return {}
    try:
        _models, extras = _decode_cache(cached)
    except (json.JSONDecodeError, ValueError):
        return {}
    return extras


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
        _encode_cache(models, adapter.cache_extras()),
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
        model_dicts, _extras = _decode_cache(cached)
        return [ModelMetaDto.model_validate(m) for m in model_dicts]
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
