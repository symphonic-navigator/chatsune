"""Per-connection model listing: Redis cache (30min TTL) + adapter fallback."""

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


async def get_models_for_connection(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    cached = await redis.get(_cache_key(c.id))
    if cached:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    try:
        adapter = adapter_cls()
        models = await adapter.fetch_models(c)
    except NotImplementedError:
        return []
    except Exception as exc:
        _log.warning("fetch_models failed for connection=%s: %s", c.id, exc)
        return []
    await redis.set(
        _cache_key(c.id),
        json.dumps([m.model_dump() for m in models]),
        ex=_TTL_SECONDS,
    )
    return models


async def refresh_connection_models(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    await redis.delete(_cache_key(c.id))
    return await get_models_for_connection(c, adapter_cls, redis)
