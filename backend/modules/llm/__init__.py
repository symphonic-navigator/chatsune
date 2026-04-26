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
from backend.modules.llm._csp._connection import SidecarConnection
from backend.modules.llm._csp._frames import (
    HandshakeAckFrame,
    HandshakeFrame,
    negotiate_version,
)
from backend.modules.llm._csp._registry import (
    SidecarRegistry,
    get_sidecar_registry,
    set_sidecar_registry,
)
from backend.modules.llm._handlers import router
from backend.modules.llm._homelab_handlers import router as homelab_router
from backend.modules.llm._homelab_tokens import HOST_KEY_PREFIX
from backend.modules.llm._homelabs import (
    ApiKeyNotFoundError,
    ApiKeyRepository,
    HomelabNotFoundError,
    HomelabRepository,
    HomelabService,
    HostSlugAlreadyExistsError,
    TooManyApiKeysError,
    TooManyHomelabsError,
)
from backend.modules.llm._image_normaliser import (
    ImageNormalisationError,
    normalise_for_llm,
)
from backend.modules.llm._metadata import (
    get_models_for_connection,
    get_premium_models,
    refresh_connection_models,
    refresh_premium_models,
)
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    _instantiate_adapter,
    get_adapter_class,
)
from backend.modules.llm._resolver import (
    _to_resolved,
    resolve_for_model,
    resolve_owned_connection_by_slug,
    resolve_premium_for_listing,
)

# Convenience alias — callers that split a model_unique_id pass a slug as the
# second argument; this name is kept for backwards compatibility.
resolve_owned_connection = resolve_owned_connection_by_slug
from backend.modules.llm._semaphores import get_semaphore_registry
from backend.modules.llm._token_estimate import DEFAULT_CONTEXT_WINDOW
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.modules.metrics import inference_duration_seconds, inference_total
from shared.dtos.debug import ActiveInferenceDto
from shared.dtos.images import (
    ConnectionImageGroupsDto,
    ImageGenItem,
    ImageGroupConfig,
)
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


class PremiumProviderUnknownError(Exception):
    """Unknown Premium Provider id — not in the registry."""

    def __init__(self, provider_id: str) -> None:
        super().__init__(f"Unknown premium provider: {provider_id}")
        self.provider_id = provider_id


class PremiumProviderAccountMissingError(Exception):
    """The provider is known, but the caller has no account configured."""

    def __init__(self, provider_id: str) -> None:
        super().__init__(f"No premium account configured: {provider_id}")
        self.provider_id = provider_id


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
    # Fail-fast format check — resolve_for_model would also raise, but this
    # preserves the historical LlmInvalidModelUniqueIdError signal that
    # downstream callers already special-case.
    parse_model_unique_id(model_unique_id)
    # Premium-aware resolve: routes reserved prefixes (``xai:``, ``ollama_cloud:``)
    # through PremiumProviderService and falls back to the user's Connection
    # repository otherwise.
    c = await resolve_for_model(user_id, model_unique_id)

    adapter_cls = get_adapter_class(c.adapter_type)
    if adapter_cls is None:
        raise LlmConnectionNotFoundError(model_unique_id)
    adapter = _instantiate_adapter(adapter_cls, get_redis())
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


async def list_premium_provider_models(
    user_id: str, provider_id: str,
) -> list[ModelMetaDto]:
    """Return the cached-or-fresh model list for a Premium Provider.

    Semantics match :func:`get_models_for_connection` on the user-facing
    Connections path: adapter failures degrade to an empty list, and a
    provider that has no LLM adapter (e.g. ``mistral`` today) also yields
    an empty list rather than an error — "no LLM models" is a structural
    fact, not a fault.

    Raises:
        PremiumProviderUnknownError: ``provider_id`` is not in the registry.
        PremiumProviderAccountMissingError: the user has no account
            configured for this provider.
    """
    from backend.modules.providers._registry import get as get_premium_definition

    if get_premium_definition(provider_id) is None:
        raise PremiumProviderUnknownError(provider_id)
    c = await resolve_premium_for_listing(user_id, provider_id)
    if c is None:
        # Two sub-cases:
        #   (a) provider has no LLM adapter entry — empty list is correct;
        #   (b) the user has no account — surface a distinct error.
        # resolve_premium_for_listing returns None for both. Disambiguate
        # by consulting the service layer directly.
        from backend.modules.providers import PremiumProviderService
        from backend.modules.providers._repository import (
            PremiumProviderAccountRepository,
        )

        svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
        if not await svc.has_account(user_id, provider_id):
            raise PremiumProviderAccountMissingError(provider_id)
        return []
    adapter_cls = get_adapter_class(c.adapter_type)
    if adapter_cls is None:
        return []
    return await get_premium_models(
        c, adapter_cls, get_redis(), user_id, provider_id,
    )


async def refresh_premium_provider_models(
    user_id: str, provider_id: str,
) -> list[ModelMetaDto]:
    """Drop the user-scoped cache and re-fetch.

    Raises on upstream adapter errors so the HTTP layer can surface them
    — matches :func:`refresh_connection_models`.

    Raises:
        PremiumProviderUnknownError: unknown ``provider_id``.
        PremiumProviderAccountMissingError: user has no account.
        Exception: any adapter-level fetch error.
    """
    from backend.modules.providers._registry import get as get_premium_definition

    if get_premium_definition(provider_id) is None:
        raise PremiumProviderUnknownError(provider_id)
    c = await resolve_premium_for_listing(user_id, provider_id)
    if c is None:
        from backend.modules.providers import PremiumProviderService
        from backend.modules.providers._repository import (
            PremiumProviderAccountRepository,
        )

        svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
        if not await svc.has_account(user_id, provider_id):
            raise PremiumProviderAccountMissingError(provider_id)
        return []
    adapter_cls = get_adapter_class(c.adapter_type)
    if adapter_cls is None:
        return []
    return await refresh_premium_models(
        c, adapter_cls, get_redis(), user_id, provider_id,
    )


async def get_model_metadata(
    user_id: str, model_unique_id: str,
) -> ModelMetaDto | None:
    """Return full metadata for a single model, or ``None`` if not found."""
    _, model_slug = parse_model_unique_id(model_unique_id)
    # Premium-aware resolve so ``xai:grok-3``-style ids hit the Premium
    # Provider repository. A missing premium account or a missing user
    # Connection both surface as LlmConnectionNotFoundError; we swallow it
    # here because the caller contract is "None on not-found".
    try:
        c = await resolve_for_model(user_id, model_unique_id)
    except LlmConnectionNotFoundError:
        return None
    adapter_cls = get_adapter_class(c.adapter_type)
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
    """Return ``True`` if the model supports reasoning/thinking.

    A per-user override (``UserModelConfig.custom_supports_reasoning``) takes
    precedence over the upstream-reported capability — this lets the user
    flag a community/homelab model as thinker when the sidecar has not yet
    learned to detect it.
    """
    repo = UserModelConfigRepository(get_db())
    doc = await repo.find(user_id, model_unique_id)
    if doc is not None:
        override = doc.get("custom_supports_reasoning")
        if override is not None:
            return bool(override)
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


class LlmService:
    """Service facade for image-generation operations on the LLM module.

    Keeps the ``images`` module's call surface clean: it imports only
    ``LlmService`` from this public API — never reaches into adapters, the
    connection repo, or the resolver directly.

    The three image methods are the only reason this class exists. All
    inference-related helpers remain module-level functions (the existing
    pattern); a class is used here because ``validate_image_config`` must
    be safely callable without a live DB connection (tests bypass
    ``__init__`` via ``LlmService.__new__(LlmService)``).
    """

    async def list_image_groups(
        self, *, user_id: str,
    ) -> list[ConnectionImageGroupsDto]:
        """Return one entry per image-capable source the user owns.

        Two sources contribute:

        1. Regular per-user Connections (``connections`` collection). For
           each, the registered adapter class is consulted; if it declares
           ``supports_image_generation`` and exposes any group ids for the
           resolved Connection, an entry is produced with the Connection's
           own ``_id``.
        2. Premium Provider accounts (``premium_provider_accounts``
           collection). For each Premium Provider whose adapter supports
           image generation AND for which the user has stored an API key,
           a synthetic entry is produced with ``connection_id``
           ``"premium:<provider_id>"`` (matching the resolver convention).

        The synthetic id is round-trippable: ``generate_images`` and the
        ``user_image_configs`` collection both treat it as an opaque
        connection identifier.
        """
        out: list[ConnectionImageGroupsDto] = []

        # 1. Regular Connections.
        conn_repo = ConnectionRepository(get_db())
        raw_connections = await conn_repo.list_for_user(user_id)

        for doc in raw_connections:
            adapter_cls = get_adapter_class(doc["adapter_type"])
            if adapter_cls is None or not adapter_cls.supports_image_generation:
                continue
            resolved = _to_resolved(doc)
            adapter = _instantiate_adapter(adapter_cls, get_redis())
            groups = await adapter.image_groups(resolved)
            if groups:
                out.append(ConnectionImageGroupsDto(
                    connection_id=doc["_id"],
                    connection_display_name=doc["display_name"],
                    group_ids=groups,
                ))

        # 2. Premium Provider accounts.
        from backend.modules.llm._resolver import (
            _PREMIUM_ADAPTER_TYPE,
            resolve_premium_for_listing,
        )

        for provider_id, adapter_type in _PREMIUM_ADAPTER_TYPE.items():
            adapter_cls = get_adapter_class(adapter_type)
            if adapter_cls is None or not adapter_cls.supports_image_generation:
                continue
            resolved = await resolve_premium_for_listing(user_id, provider_id)
            if resolved is None:
                continue  # user has no account for this provider
            adapter = _instantiate_adapter(adapter_cls, get_redis())
            groups = await adapter.image_groups(resolved)
            if groups:
                out.append(ConnectionImageGroupsDto(
                    connection_id=resolved.id,
                    connection_display_name=resolved.display_name,
                    group_ids=groups,
                ))

        _log.info(
            "llm.list_image_groups user_id=%s "
            "regular_connections=%d image_capable_sources=%d",
            user_id, len(raw_connections), len(out),
        )
        return out

    async def validate_image_config(
        self, *, group_id: str, config: dict,
    ) -> ImageGroupConfig:
        """Parse and validate ``config`` against the typed schema for ``group_id``.

        Does not require a live DB connection — safe to call on a bare
        ``LlmService.__new__(LlmService)`` instance in tests.

        Raises:
            ValueError: the config does not match the group's schema.
        """
        from pydantic import TypeAdapter, ValidationError

        try:
            return TypeAdapter(ImageGroupConfig).validate_python(
                {**config, "group_id": group_id}
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    async def generate_images(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        """Resolve the connection (with ownership check), instantiate the adapter,
        and invoke ``adapter.generate_images``.

        Persistence of the results is the caller's responsibility
        (``ImageService`` handles that).

        ``connection_id`` may be either a regular Connection id (UUID) or a
        synthetic Premium Provider id of the form ``"premium:<provider_id>"``
        (as returned by :meth:`list_image_groups`). The two paths are
        resolved transparently.

        Raises:
            PermissionError: ``connection_id`` is not owned by ``user_id``
                or no Premium Provider account exists for the given id.
            ValueError: the adapter does not support image generation.
        """
        if connection_id.startswith("premium:"):
            from backend.modules.llm._resolver import (
                _PREMIUM_ADAPTER_TYPE,
                resolve_premium_for_listing,
            )

            provider_id = connection_id[len("premium:"):]
            adapter_type = _PREMIUM_ADAPTER_TYPE.get(provider_id)
            if adapter_type is None:
                _log.warning(
                    "llm.generate_images user_id=%s connection_id=%s "
                    "reason=unknown_premium_provider",
                    user_id, connection_id,
                )
                raise PermissionError(
                    f"unknown premium provider {provider_id!r}"
                )
            adapter_cls = get_adapter_class(adapter_type)
            if adapter_cls is None or not adapter_cls.supports_image_generation:
                _log.warning(
                    "llm.generate_images user_id=%s connection_id=%s "
                    "adapter_type=%s reason=no_image_support",
                    user_id, connection_id, adapter_type,
                )
                raise ValueError(
                    f"adapter {adapter_type!r} does not support image generation"
                )
            resolved = await resolve_premium_for_listing(user_id, provider_id)
            if resolved is None:
                _log.warning(
                    "llm.generate_images user_id=%s connection_id=%s "
                    "reason=no_premium_account",
                    user_id, connection_id,
                )
                raise PermissionError(
                    f"no premium provider account for {provider_id!r}"
                )
        else:
            conn_repo = ConnectionRepository(get_db())
            doc = await conn_repo.find(user_id, connection_id)
            if doc is None:
                _log.warning(
                    "llm.generate_images user_id=%s connection_id=%s "
                    "reason=not_found_or_not_owned",
                    user_id, connection_id,
                )
                raise PermissionError("connection not found or not owned by user")

            adapter_cls = get_adapter_class(doc["adapter_type"])
            if adapter_cls is None or not adapter_cls.supports_image_generation:
                _log.warning(
                    "llm.generate_images user_id=%s connection_id=%s "
                    "adapter_type=%s reason=no_image_support",
                    user_id, connection_id, doc.get("adapter_type"),
                )
                raise ValueError(
                    f"adapter {doc.get('adapter_type')!r} does not support image generation"
                )

            resolved = _to_resolved(doc)
        adapter = _instantiate_adapter(adapter_cls, get_redis())

        n = getattr(config, "n", None)
        _log.info(
            "llm.generate_images user_id=%s connection_id=%s "
            "group_id=%s n=%s",
            user_id, connection_id, group_id, n,
        )
        return await adapter.generate_images(
            connection=resolved,
            group_id=group_id,
            config=config,
            prompt=prompt,
        )


__all__ = [
    "router",
    "homelab_router",
    "init_indexes",
    "HomelabService",
    "HomelabNotFoundError",
    "ApiKeyNotFoundError",
    "TooManyHomelabsError",
    "TooManyApiKeysError",
    "HostSlugAlreadyExistsError",
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
    "PremiumProviderUnknownError",
    "PremiumProviderAccountMissingError",
    "list_premium_provider_models",
    "refresh_premium_provider_models",
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
    "resolve_for_model",
    "refresh_connection_models",
    "delete_all_for_user",
    "ADAPTER_REGISTRY",
    "DEFAULT_CONTEXT_WINDOW",
    "SidecarRegistry",
    "SidecarConnection",
    "HandshakeFrame",
    "HandshakeAckFrame",
    "negotiate_version",
    "HOST_KEY_PREFIX",
    "get_sidecar_registry",
    "set_sidecar_registry",
    "LlmService",
    "ImageNormalisationError",
    "normalise_for_llm",
]
