import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import ModelMetaDto
from shared.events.llm import LlmModelsRefreshedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def get_models(
    provider_id: str,
    redis: Redis,
    adapter: BaseAdapter,
    event_bus=None,
) -> list[ModelMetaDto]:
    """Return cached model list or fetch from adapter on cache miss (TTL 30 min).

    Returns [] if the adapter is not yet implemented (NotImplementedError).
    See INSIGHTS.md INS-001 for the design reasoning.

    If event_bus is provided, publishes LLM_MODELS_REFRESHED on cache refresh.
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

    if event_bus is not None:
        try:
            await event_bus.publish(
                Topics.LLM_MODELS_REFRESHED,
                LlmModelsRefreshedEvent(
                    provider_id=provider_id,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        except Exception:
            _log.warning("Failed to publish models_refreshed event for %s", provider_id)

    return models
