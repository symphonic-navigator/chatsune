"""LLM module — connection-scoped inference facade.

Public API: import only from this file.
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from backend.database import get_db, get_redis
from backend.modules.llm import _tracker
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import ConnectionRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._homelabs import (
    ApiKeyNotFoundError,
    ApiKeyRepository,
    HomelabNotFoundError,
    HomelabRepository,
    HomelabService,
    TooManyApiKeysError,
    TooManyHomelabsError,
)
from backend.modules.llm._metadata import (
    get_models_for_connection,
    refresh_connection_models,
)
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._resolver import resolve_owned_connection_by_slug

# Convenience alias — callers that split a model_unique_id pass a slug as the
# second argument; this name is kept for backwards compatibility.
resolve_owned_connection = resolve_owned_connection_by_slug
from backend.modules.llm._semaphores import get_semaphore_registry
from backend.modules.llm._token_estimate import DEFAULT_CONTEXT_WINDOW
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.modules.metrics import inference_duration_seconds, inference_total
from shared.dtos.debug import ActiveInferenceDto
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


_log = logging.getLogger(__name__)


class LlmConnectionNotFoundError(Exception):
    """Connection not found or not owned by the caller."""

    def __init__(self, connection_id: str) -> None:
        super().__init__(f"Connection not found: {connection_id}")
        self.connection_id = connection_id


class LlmInvalidModelUniqueIdError(Exception):
    """model_unique_id is not in ``<connection_slug>:<model_slug>`` format."""


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await ConnectionRepository(db).create_indexes()
    await UserModelConfigRepository(db).create_indexes()
    await HomelabRepository(db).create_indexes()
    await ApiKeyRepository(db).create_indexes()


def parse_model_unique_id(model_unique_id: str) -> tuple[str, str]:
    """Split ``<connection_slug>:<model_slug>`` into ``(connection_slug, model_slug)``."""
    if ":" not in model_unique_id:
        raise LlmInvalidModelUniqueIdError(model_unique_id)
    connection_slug, model_slug = model_unique_id.split(":", 1)
    if not connection_slug or not model_slug:
        raise LlmInvalidModelUniqueIdError(model_unique_id)
    return connection_slug, model_slug


async def stream_completion(
    user_id: str,
    model_unique_id: str,
    request: CompletionRequest,
    source: str = "chat",
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve the user's connection, enforce its per-connection semaphore,
    and stream adapter events.

    Raises:
        LlmInvalidModelUniqueIdError: ``model_unique_id`` is malformed.
        LlmConnectionNotFoundError: connection does not exist or is not owned
            by ``user_id``.
    """
    connection_slug, _ = parse_model_unique_id(model_unique_id)
    c = await resolve_owned_connection_by_slug(user_id, connection_slug)
    if c is None:
        raise LlmConnectionNotFoundError(connection_slug)

    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    adapter = adapter_cls()
    max_parallel = int(c.config.get("max_parallel") or 1)
    sem = get_semaphore_registry().get(c.id, max_parallel)

    inference_id = _tracker.register(
        user_id=user_id,
        connection_id=c.id,
        connection_slug=c.slug,
        adapter_type=c.adapter_type,
        model_slug=request.model,
        source=source,
    )
    await _publish_inference_started(
        inference_id=inference_id,
        user_id=user_id,
        connection_id=c.id,
        connection_slug=c.slug,
        adapter_type=c.adapter_type,
        model_slug=request.model,
        source=source,
    )
    started_perf = time.monotonic()
    inference_total.labels(
        model=request.model, provider=c.adapter_type, source=source,
    ).inc()
    try:
        async with sem:
            async for event in adapter.stream_completion(c, request):
                yield event
    finally:
        _tracker.unregister(inference_id)
        inference_duration_seconds.labels(
            model=request.model, provider=c.adapter_type,
        ).observe(time.monotonic() - started_perf)
        await _publish_inference_finished(
            inference_id=inference_id,
            user_id=user_id,
            duration_seconds=time.monotonic() - started_perf,
        )


async def _publish_inference_started(**fields) -> None:
    """Best-effort fan-out: never raise out of the inference path."""
    try:
        from backend.ws.event_bus import get_event_bus
        from shared.events.debug import DebugInferenceStartedEvent
        from shared.topics import Topics

        bus = get_event_bus()
        username = await _resolve_username(fields["user_id"])
        await bus.publish(
            Topics.DEBUG_INFERENCE_STARTED,
            DebugInferenceStartedEvent(
                inference_id=fields["inference_id"],
                user_id=fields["user_id"],
                username=username,
                connection_id=fields["connection_id"],
                connection_slug=fields["connection_slug"],
                adapter_type=fields["adapter_type"],
                model_slug=fields["model_slug"],
                model_unique_id=f"{fields['connection_slug']}:{fields['model_slug']}",
                source=fields["source"],
                started_at=datetime.now(timezone.utc),
                correlation_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        _log.warning("Failed to publish DEBUG_INFERENCE_STARTED", exc_info=True)


async def _publish_inference_finished(
    inference_id: str, user_id: str, duration_seconds: float,
) -> None:
    try:
        from backend.ws.event_bus import get_event_bus
        from shared.events.debug import DebugInferenceFinishedEvent
        from shared.topics import Topics

        bus = get_event_bus()
        await bus.publish(
            Topics.DEBUG_INFERENCE_FINISHED,
            DebugInferenceFinishedEvent(
                inference_id=inference_id,
                user_id=user_id,
                duration_seconds=duration_seconds,
                correlation_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        _log.warning("Failed to publish DEBUG_INFERENCE_FINISHED", exc_info=True)


async def _resolve_username(user_id: str) -> str | None:
    try:
        # Local import to avoid an import-time cycle (user → llm via handlers).
        from backend.modules.user import get_username

        return await get_username(user_id)
    except Exception:
        return None


def get_active_inferences(
    usernames: dict[str, str] | None = None,
) -> list[ActiveInferenceDto]:
    """Return a snapshot of every in-flight LLM inference inside this process.

    Used by the admin debug overlay. ``usernames`` enriches the records
    with display names — pass ``{user_id: username}``.
    """
    return _tracker.snapshot(usernames)


@asynccontextmanager
async def track_inference(
    user_id: str,
    connection_id: str,
    connection_slug: str,
    adapter_type: str,
    model_slug: str,
    source: str,
):
    """Context manager that registers/unregisters an inference and emits
    debug events. Use this from call sites that talk to an adapter directly
    instead of via :func:`stream_completion` (e.g. vision fallback).
    """
    inference_id = _tracker.register(
        user_id=user_id,
        connection_id=connection_id,
        connection_slug=connection_slug,
        adapter_type=adapter_type,
        model_slug=model_slug,
        source=source,
    )
    started_perf = time.monotonic()
    await _publish_inference_started(
        inference_id=inference_id,
        user_id=user_id,
        connection_id=connection_id,
        connection_slug=connection_slug,
        adapter_type=adapter_type,
        model_slug=model_slug,
        source=source,
    )
    try:
        yield inference_id
    finally:
        _tracker.unregister(inference_id)
        await _publish_inference_finished(
            inference_id=inference_id,
            user_id=user_id,
            duration_seconds=time.monotonic() - started_perf,
        )


def active_inference_count() -> int:
    """Return the number of in-flight LLM inferences."""
    return _tracker.active_count()


async def get_model_metadata(
    user_id: str, model_unique_id: str,
) -> ModelMetaDto | None:
    """Return full metadata for a single model, or ``None`` if not found."""
    connection_slug, model_slug = parse_model_unique_id(model_unique_id)
    c = await resolve_owned_connection_by_slug(user_id, connection_slug)
    if c is None:
        return None
    adapter_cls = ADAPTER_REGISTRY.get(c.adapter_type)
    if adapter_cls is None:
        return None
    models = await get_models_for_connection(c, adapter_cls, get_redis())
    for m in models:
        if m.model_id == model_slug:
            return m
    return None


async def get_model_context_window(
    user_id: str, model_unique_id: str,
) -> int | None:
    """Return the context-window size of a model, or ``None`` if unknown."""
    meta = await get_model_metadata(user_id, model_unique_id)
    return meta.context_window if meta else None


async def get_model_supports_vision(
    user_id: str, model_unique_id: str,
) -> bool:
    """Return ``True`` if the model supports vision/image input."""
    meta = await get_model_metadata(user_id, model_unique_id)
    return meta.supports_vision if meta else False


async def get_model_supports_reasoning(
    user_id: str, model_unique_id: str,
) -> bool:
    """Return ``True`` if the model supports reasoning/thinking."""
    meta = await get_model_metadata(user_id, model_unique_id)
    return meta.supports_reasoning if meta else False


async def get_effective_context_window(
    user_id: str, model_unique_id: str,
) -> int | None:
    """Return the effective context window:
    ``min(model_max, user_custom)`` if the user has a custom override.
    """
    model_max = await get_model_context_window(user_id, model_unique_id)
    if model_max is None:
        return None
    repo = UserModelConfigRepository(get_db())
    doc = await repo.find(user_id, model_unique_id)
    if doc and doc.get("custom_context_window"):
        return min(model_max, doc["custom_context_window"])
    return model_max


async def delete_all_for_user(user_id: str) -> dict:
    """Delete every LLM connection and user_model_config owned by ``user_id``.

    Also evicts their in-process concurrency semaphores and clears the
    ``llm:models:{connection_id}`` Redis cache keys for each deleted
    connection. The Redis cleanup is best-effort — an error here never
    causes the MongoDB deletions to fail.

    Called by the user self-delete (right-to-be-forgotten) cascade.

    Returns:
        A dict with keys ``connections_deleted``, ``user_model_configs_deleted``
        and ``model_cache_keys_cleared`` (all ``int``).
    """
    conn_repo = ConnectionRepository(get_db())
    cfg_repo = UserModelConfigRepository(get_db())

    # Capture the connection IDs BEFORE we delete them — we need them to
    # build the Redis cache keys afterwards.
    connection_ids = await conn_repo.list_ids_for_user(user_id)

    connections_deleted = await conn_repo.delete_all_for_user(user_id)
    user_model_configs_deleted = await cfg_repo.delete_all_for_user(user_id)

    # Evict in-process semaphores so lingering registry entries are freed.
    # Best-effort — never raise out of the deletion path.
    try:
        registry = get_semaphore_registry()
        for cid in connection_ids:
            registry.evict(cid)
    except Exception:
        _log.warning(
            "llm.delete_all_for_user.semaphore_evict_failed user_id=%s",
            user_id, exc_info=True,
        )

    # Clear the llm:models:{connection_id} Redis cache keys.
    # Best-effort: cache staleness is harmless, but a deletion failure must
    # not abort the overall user cascade.
    model_cache_keys_cleared = 0
    try:
        redis = get_redis()
        for cid in connection_ids:
            key = f"llm:models:{cid}"
            deleted = await redis.delete(key)
            # redis-py returns the number of keys actually deleted (0 or 1).
            model_cache_keys_cleared += int(deleted or 0)
    except Exception:
        _log.warning(
            "llm.delete_all_for_user.cache_clear_failed user_id=%s",
            user_id, exc_info=True,
        )

    _log.info(
        "llm.delete_all_for_user user_id=%s connections=%d "
        "user_model_configs=%d model_cache_keys=%d",
        user_id,
        connections_deleted,
        user_model_configs_deleted,
        model_cache_keys_cleared,
    )

    return {
        "connections_deleted": connections_deleted,
        "user_model_configs_deleted": user_model_configs_deleted,
        "model_cache_keys_cleared": model_cache_keys_cleared,
    }


__all__ = [
    "router",
    "init_indexes",
    "HomelabService",
    "HomelabNotFoundError",
    "ApiKeyNotFoundError",
    "TooManyHomelabsError",
    "TooManyApiKeysError",
    "stream_completion",
    "parse_model_unique_id",
    "ContentDelta",
    "ThinkingDelta",
    "StreamAborted",
    "StreamDone",
    "StreamError",
    "StreamRefused",
    "StreamSlow",
    "ProviderStreamEvent",
    "ToolCallEvent",
    "LlmConnectionNotFoundError",
    "LlmInvalidModelUniqueIdError",
    "UserModelConfigRepository",
    "get_model_context_window",
    "get_effective_context_window",
    "get_model_supports_vision",
    "get_model_supports_reasoning",
    "get_model_metadata",
    "get_active_inferences",
    "active_inference_count",
    "track_inference",
    "ModelMetaDto",
    "ResolvedConnection",
    "resolve_owned_connection",
    "refresh_connection_models",
    "delete_all_for_user",
    "ADAPTER_REGISTRY",
    "DEFAULT_CONTEXT_WINDOW",
]
