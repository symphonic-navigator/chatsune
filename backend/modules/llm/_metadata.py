import json

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import ModelMetaDto


async def get_models(
    provider_id: str, redis: Redis, adapter: BaseAdapter
) -> list[ModelMetaDto]:
    """Return cached model list or fetch from adapter on cache miss (TTL 30 min).

    Returns [] if the adapter is not yet implemented (NotImplementedError).
    See INSIGHTS.md INS-001 for the design reasoning.
    """
    cache_key = f"llm:models:{provider_id}"
    cached = await redis.get(cache_key)
    if cached:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]

    try:
        models = await adapter.fetch_models()
    except NotImplementedError:
        return []

    await redis.set(
        cache_key,
        json.dumps([m.model_dump() for m in models]),
        ex=1800,  # 30 minutes TTL
    )
    return models
