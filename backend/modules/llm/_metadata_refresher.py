"""Per-user background refresher for the LLM model metadata cache.

One `asyncio.Task` runs for every online user. It refreshes every
Connection and Premium Provider model list owned by the user on a fixed
cadence and replaces the Redis entry atomically on success. Failures are
logged and leave the prior cached value intact.

Lifecycle is driven by WebSocket presence: the ConnectionManager fires
`ensure_user_task` on the first-connect edge and `release_user_task` on
the last-disconnect edge. Both are idempotent and refcounted so multiple
tabs do not create multiple tasks.
"""

import asyncio
import json
import logging
import random
from datetime import UTC, datetime

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.llm import ModelMetaDto
from shared.events.llm import (
    LlmConnectionModelsRefreshedEvent,
    PremiumProviderModelsRefreshedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 30 * 60
REFRESH_JITTER_SECONDS = 60
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


class ModelCacheRefresher:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._refcounts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def has_active_task(self, user_id: str) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

    async def ensure_user_task(self, user_id: str) -> None:
        async with self._lock:
            self._refcounts[user_id] = self._refcounts.get(user_id, 0) + 1
            if user_id in self._tasks and not self._tasks[user_id].done():
                return
            self._tasks[user_id] = asyncio.create_task(
                self._user_loop(user_id),
                name=f"model-cache-refresher:{user_id}",
            )

    async def release_user_task(self, user_id: str) -> None:
        async with self._lock:
            current = self._refcounts.get(user_id, 0)
            if current <= 1:
                self._refcounts.pop(user_id, None)
                task = self._tasks.pop(user_id, None)
            else:
                self._refcounts[user_id] = current - 1
                task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception(
                "refresher task for user=%s raised on cancel", user_id,
            )

    async def _user_loop(self, user_id: str) -> None:
        """Background loop body — runs until cancelled."""
        while True:
            try:
                await self._run_user_iteration(user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception(
                    "refresher iteration crashed for user=%s — continuing",
                    user_id,
                )
            jitter = random.uniform(-REFRESH_JITTER_SECONDS, REFRESH_JITTER_SECONDS)
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS + jitter)

    async def _run_user_iteration(self, user_id: str) -> None:
        """Fetch and atomically replace every cache key owned by the user."""
        connections = await self._resolve_user_connections(user_id)
        premium = await self._resolve_user_premium_accounts(user_id)

        redis = self._get_redis()
        event_bus = self._get_event_bus()

        for conn in connections:
            adapter_cls = self._get_adapter_class(conn.adapter_type)
            if adapter_cls is None:
                continue
            try:
                await _refresh_connection_into_cache(conn, adapter_cls, redis)
            except Exception as exc:
                _log.warning(
                    "background refresh failed for connection=%s adapter=%s: %s",
                    conn.id, conn.adapter_type, exc,
                )
                continue
            await self._publish_connection_refreshed(event_bus, user_id, conn.id)

        for provider_id, resolved in premium:
            adapter_cls = self._get_adapter_class(resolved.adapter_type)
            if adapter_cls is None:
                continue
            try:
                await _refresh_premium_into_cache(
                    resolved, adapter_cls, redis, user_id, provider_id,
                )
            except Exception as exc:
                _log.warning(
                    "background refresh failed for premium provider=%s user=%s: %s",
                    provider_id, user_id, exc,
                )
                continue
            await self._publish_premium_refreshed(event_bus, user_id, provider_id)

    async def _resolve_user_connections(
        self, user_id: str,
    ) -> list[ResolvedConnection]:
        """Fetch all connections owned by ``user_id`` as ResolvedConnections."""
        from backend.database import get_db
        from backend.modules.llm._connections import ConnectionRepository
        from backend.modules.llm._resolver import _to_resolved

        repo = ConnectionRepository(get_db())
        docs = await repo.list_for_user(user_id)
        return [_to_resolved(d) for d in docs]

    async def _resolve_user_premium_accounts(
        self, user_id: str,
    ) -> list[tuple[str, ResolvedConnection]]:
        """For every Premium Provider account the user has, return
        ``(provider_id, ResolvedConnection)`` pairs ready to fetch models against.
        Providers without an LLM adapter mapping are silently skipped."""
        from backend.database import get_db
        from backend.modules.llm._resolver import resolve_premium_for_listing
        from backend.modules.providers import PremiumProviderService
        from backend.modules.providers._repository import (
            PremiumProviderAccountRepository,
        )

        svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
        accounts = await svc.list_for_user(user_id)
        out: list[tuple[str, ResolvedConnection]] = []
        for account in accounts:
            provider_id = account["provider_id"]
            resolved = await resolve_premium_for_listing(user_id, provider_id)
            if resolved is not None:
                out.append((provider_id, resolved))
        return out

    def _get_adapter_class(self, adapter_type: str) -> type[BaseAdapter] | None:
        from backend.modules.llm._registry import ADAPTER_REGISTRY
        return ADAPTER_REGISTRY.get(adapter_type)

    def _get_redis(self) -> Redis:
        from backend.database import get_redis
        return get_redis()

    def _get_event_bus(self):
        from backend.ws.event_bus import get_event_bus
        return get_event_bus()

    async def _publish_connection_refreshed(
        self, event_bus, user_id: str, connection_id: str,
    ) -> None:
        await event_bus.publish(
            Topics.LLM_CONNECTION_MODELS_REFRESHED,
            LlmConnectionModelsRefreshedEvent(
                connection_id=connection_id,
                success=True,
                error=None,
                timestamp=datetime.now(UTC),
            ),
            target_user_ids=[user_id],
        )

    async def _publish_premium_refreshed(
        self, event_bus, user_id: str, provider_id: str,
    ) -> None:
        await event_bus.publish(
            Topics.PREMIUM_PROVIDER_MODELS_REFRESHED,
            PremiumProviderModelsRefreshedEvent(
                provider_id=provider_id,
                success=True,
                error=None,
                timestamp=datetime.now(UTC),
            ),
            target_user_ids=[user_id],
        )


async def _refresh_connection_into_cache(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Fetch and write the connection-scoped cache. Raises on adapter failure."""
    from backend.modules.llm._metadata import _cache_key
    from backend.modules.llm._registry import _instantiate_adapter

    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _cache_key(c.id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=CACHE_TTL_SECONDS,
    )
    return models


async def _refresh_premium_into_cache(
    c: ResolvedConnection,
    adapter_cls: type[BaseAdapter],
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Fetch and write the user-scoped Premium Provider cache. Raises on failure."""
    from backend.modules.llm._metadata import _premium_cache_key
    from backend.modules.llm._registry import _instantiate_adapter

    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _premium_cache_key(user_id, provider_id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=CACHE_TTL_SECONDS,
    )
    return models


_refresher: ModelCacheRefresher | None = None


def get_model_cache_refresher() -> ModelCacheRefresher:
    global _refresher
    if _refresher is None:
        _refresher = ModelCacheRefresher()
    return _refresher


def reset_for_tests() -> None:
    """Test-only hook to reinitialise the singleton."""
    global _refresher
    _refresher = None
