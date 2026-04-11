"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.llm import _tracker
from backend.modules.llm._concurrency import get_lock_registry
from backend.modules.llm._registry import ADAPTER_REGISTRY as _ADAPTER_REGISTRY_REF
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
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_BASE_URLS
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.modules.llm._metadata import get_models, refresh_all_providers
from backend.database import get_db, get_redis
from shared.dtos.debug import ActiveInferenceDto
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class LlmCredentialNotFoundError(Exception):
    """User has no API key configured for the requested provider."""


class LlmProviderNotFoundError(Exception):
    """Provider ID is not registered in the adapter registry."""


class LlmInferenceLockTimeoutError(Exception):
    """Timed out waiting for the provider's concurrency lock (5 minutes)."""

    def __init__(self, provider_id: str) -> None:
        super().__init__(
            f"Timed out waiting for inference lock on provider '{provider_id}'"
        )
        self.provider_id = provider_id


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
    source: str = "chat",
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve user's API key, instantiate adapter, stream completion.

    Wraps the adapter call in an adapter-declared concurrency lock
    (see :mod:`backend.modules.llm._concurrency`). For ``ollama_local``
    this serialises all inferences across the process — a new chat
    request waits until any in-flight generation finishes.

    Raises:
        LlmProviderNotFoundError: provider_id not in registry.
        LlmCredentialNotFoundError: user has no key for this provider.
        LlmInferenceLockTimeoutError: waited >5 minutes for the lock.
    """
    if provider_id not in ADAPTER_REGISTRY:
        raise LlmProviderNotFoundError(f"Unknown provider: {provider_id}")

    adapter_cls = ADAPTER_REGISTRY[provider_id]
    api_key: str | None = None
    if not adapter_cls.is_global:
        repo = CredentialRepository(get_db())
        cred = await repo.find(user_id, provider_id)
        if not cred:
            raise LlmCredentialNotFoundError(
                f"No API key configured for provider '{provider_id}'"
            )
        api_key = repo.get_raw_key(cred)

    adapter = adapter_cls(base_url=PROVIDER_BASE_URLS[provider_id])
    lock = get_lock_registry().lock_for(adapter_cls, user_id)

    inference_id = _tracker.register(
        user_id=user_id,
        provider_id=provider_id,
        model_slug=request.model,
        source=source,
    )
    # Publish "started" so the admin debug overlay can update without polling.
    # Done lazily to avoid pulling event-bus into the tracker module itself.
    await _publish_inference_started(
        inference_id=inference_id,
        user_id=user_id,
        provider_id=provider_id,
        model_slug=request.model,
        source=source,
    )
    started_at_perf = _now_perf()
    try:
        if lock is not None:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=300)
            except asyncio.TimeoutError as exc:
                raise LlmInferenceLockTimeoutError(
                    provider_id=provider_id,
                ) from exc
            try:
                async for event in adapter.stream_completion(api_key, request):
                    yield event
            finally:
                lock.release()
        else:
            async for event in adapter.stream_completion(api_key, request):
                yield event
    finally:
        _tracker.unregister(inference_id)
        await _publish_inference_finished(
            inference_id=inference_id,
            user_id=user_id,
            duration_seconds=_now_perf() - started_at_perf,
        )


_debug_log = logging.getLogger("chatsune.debug.inference_tracker")


def _now_perf() -> float:
    return time.monotonic()


async def _publish_inference_started(
    inference_id: str,
    user_id: str,
    provider_id: str,
    model_slug: str,
    source: str,
) -> None:
    """Best-effort fan-out: never raise out of the inference path."""
    try:
        from backend.ws.event_bus import get_event_bus
        from shared.events.debug import DebugInferenceStartedEvent
        from shared.topics import Topics

        bus = get_event_bus()
        username = await _resolve_username(user_id)
        await bus.publish(
            Topics.DEBUG_INFERENCE_STARTED,
            DebugInferenceStartedEvent(
                inference_id=inference_id,
                user_id=user_id,
                username=username,
                provider_id=provider_id,
                model_slug=model_slug,
                model_unique_id=f"{provider_id}:{model_slug}",
                source=source,
                started_at=datetime.now(timezone.utc),
                correlation_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        _debug_log.warning("Failed to publish DEBUG_INFERENCE_STARTED", exc_info=True)


async def _publish_inference_finished(
    inference_id: str,
    user_id: str,
    duration_seconds: float,
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
        _debug_log.warning("Failed to publish DEBUG_INFERENCE_FINISHED", exc_info=True)


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


from contextlib import asynccontextmanager


@asynccontextmanager
async def track_inference(
    user_id: str,
    provider_id: str,
    model_slug: str,
    source: str,
):
    """Context manager that registers/unregisters an inference + emits debug
    events. Use this from call sites that talk to an adapter directly
    instead of via :func:`stream_completion` (e.g. vision fallback).
    """
    inference_id = _tracker.register(
        user_id=user_id,
        provider_id=provider_id,
        model_slug=model_slug,
        source=source,
    )
    started_at_perf = _now_perf()
    await _publish_inference_started(
        inference_id=inference_id,
        user_id=user_id,
        provider_id=provider_id,
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
            duration_seconds=_now_perf() - started_at_perf,
        )


def active_inference_count() -> int:
    """Return the number of in-flight LLM inferences."""
    return _tracker.active_count()


def get_adapter_class(provider_id: str):
    """Return the adapter class for a provider_id, or None if not registered."""
    return _ADAPTER_REGISTRY_REF.get(provider_id)


def get_inference_lock(provider_id: str, user_id: str):
    """Return the asyncio.Lock for the provider's concurrency policy, or None.

    Public wrapper over the internal lock registry so callers that bypass
    :func:`stream_completion` (e.g. the vision fallback) can still honour
    the adapter's concurrency policy without reaching into module internals.
    """
    adapter_cls = _ADAPTER_REGISTRY_REF.get(provider_id)
    if adapter_cls is None:
        return None
    return get_lock_registry().lock_for(adapter_cls, user_id)


def is_inference_lock_held(provider_id: str, user_id: str) -> tuple[bool, str | None]:
    """Return (is_held, holder_source) for the provider's concurrency lock.

    ``holder_source`` is derived from the in-flight tracker on a best-effort
    basis (e.g. ``"chat"``, ``"job:memory_consolidation"``) and may be ``None``
    if no matching tracker record is found.
    """
    adapter_cls = _ADAPTER_REGISTRY_REF.get(provider_id)
    if adapter_cls is None:
        return (False, None)
    lock = get_lock_registry().lock_for(adapter_cls, user_id)
    if lock is None or not lock.locked():
        return (False, None)
    for record in _tracker.snapshot():
        if record.provider_id == provider_id:
            return (True, record.source)
    return (True, None)


async def get_model_metadata(
    provider_id: str, model_slug: str,
) -> ModelMetaDto | None:
    """Return full metadata for a single model, or None if not found."""
    if provider_id not in ADAPTER_REGISTRY:
        return None
    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    models = await get_models(provider_id, redis, adapter)
    for model in models:
        if model.model_id == model_slug:
            return model
    return None


async def get_model_context_window(provider_id: str, model_slug: str) -> int | None:
    """Return the context window size for a model, or None if not found."""
    meta = await get_model_metadata(provider_id, model_slug)
    return meta.context_window if meta else None


async def get_api_key(user_id: str, provider_id: str) -> str:
    """Return the decrypted API key for a user/provider pair.

    Intended for cross-module credential sharing (e.g. websearch reusing
    an LLM provider key).

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
    return repo.get_raw_key(cred)


async def get_model_supports_vision(provider_id: str, model_slug: str) -> bool:
    """Return True if the model supports vision/image input."""
    meta = await get_model_metadata(provider_id, model_slug)
    return meta.supports_vision if meta else False


async def get_model_supports_reasoning(provider_id: str, model_slug: str) -> bool:
    """Return True if the model supports reasoning/thinking."""
    meta = await get_model_metadata(provider_id, model_slug)
    return meta.supports_reasoning if meta else False


async def get_effective_context_window(
    user_id: str, provider_id: str, model_slug: str,
) -> int | None:
    """Return the effective context window: min(model_max, user_custom) if set."""
    model_max = await get_model_context_window(provider_id, model_slug)
    if model_max is None:
        return None
    db = get_db()
    repo = UserModelConfigRepository(db)
    unique_id = f"{provider_id}:{model_slug}"
    config = await repo.find(user_id, unique_id)
    if config and config.get("custom_context_window"):
        return min(model_max, config["custom_context_window"])
    return model_max


__all__ = [
    "router",
    "init_indexes",
    "is_valid_provider",
    "stream_completion",
    "ContentDelta",
    "ThinkingDelta",
    "StreamAborted",
    "StreamDone",
    "StreamError",
    "StreamRefused",
    "StreamSlow",
    "ProviderStreamEvent",
    "ToolCallEvent",
    "LlmCredentialNotFoundError",
    "LlmProviderNotFoundError",
    "LlmInferenceLockTimeoutError",
    "UserModelConfigRepository",
    "get_model_context_window",
    "get_api_key",
    "get_effective_context_window",
    "get_model_supports_vision",
    "get_model_supports_reasoning",
    "get_model_metadata",
    "get_active_inferences",
    "active_inference_count",
    "track_inference",
    "ModelMetaDto",
    "refresh_all_providers",
    "get_adapter_class",
    "is_inference_lock_held",
    "get_inference_lock",
]
