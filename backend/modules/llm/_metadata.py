import json
import logging
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import FaultyProviderDto, ModelMetaDto
from shared.events.llm import (
    LlmModelsFetchCompletedEvent,
    LlmModelsFetchStartedEvent,
    LlmModelsRefreshedEvent,
)
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


async def _fetch_and_cache_provider(
    provider_id: str,
    redis: Redis,
    adapter: BaseAdapter,
) -> list[ModelMetaDto]:
    """Fetch models from upstream (bypassing cache) and store in Redis."""
    models = await adapter.fetch_models()
    cache_key = f"llm:models:{provider_id}"
    await redis.set(
        cache_key,
        json.dumps([m.model_dump() for m in models]),
        ex=1800,
    )
    return models


async def refresh_all_providers(
    redis: Redis,
    registry: dict[str, type[BaseAdapter]],
    base_urls: dict[str, str],
    display_names: dict[str, str],
    event_bus,
    target_user_ids: list[str] | None = None,
) -> list[ModelMetaDto]:
    """Fetch models from all registered upstream providers, bypassing cache.

    Publishes LLM_MODELS_FETCH_STARTED before fetching and
    LLM_MODELS_FETCH_COMPLETED when done (with per-provider error details).
    """
    provider_ids = list(registry.keys())
    correlation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await event_bus.publish(
        Topics.LLM_MODELS_FETCH_STARTED,
        LlmModelsFetchStartedEvent(
            provider_ids=provider_ids,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        target_user_ids=target_user_ids,
    )

    all_models: list[ModelMetaDto] = []
    faulty: list[FaultyProviderDto] = []

    for provider_id in provider_ids:
        adapter = registry[provider_id](base_url=base_urls[provider_id])
        try:
            models = await _fetch_and_cache_provider(provider_id, redis, adapter)
            all_models.extend(models)
        except NotImplementedError:
            _log.debug("Provider %s has not implemented fetch_models", provider_id)
        except Exception as exc:
            _log.warning("Failed to fetch models from %s: %s", provider_id, exc)
            faulty.append(FaultyProviderDto(
                provider_id=provider_id,
                display_name=display_names.get(provider_id, provider_id),
                error_message=str(exc),
            ))

    if not faulty:
        status = "success"
    elif len(faulty) < len(provider_ids):
        status = "partial"
    else:
        status = "failed"

    await event_bus.publish(
        Topics.LLM_MODELS_FETCH_COMPLETED,
        LlmModelsFetchCompletedEvent(
            status=status,
            total_models=len(all_models),
            faulty_providers=faulty,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=target_user_ids,
    )

    return all_models
