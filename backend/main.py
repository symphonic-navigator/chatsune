import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

# Configure structured logging before any module-level loggers are created
# by imports further down. Without this, early imports create loggers that
# cache the default handler and INFO lines from those modules get silently
# dropped.
from backend.config import settings
from backend._logging import configure_logging

configure_logging(
    level=settings.log_level,
    console=settings.log_console,
    console_format=settings.log_console_format,
    file=settings.log_file,
    file_path=settings.log_file_path,
    file_backup_count=settings.log_file_backup_count,
    uvicorn_access_level=settings.log_level_uvicorn_access,
    third_party_level=settings.log_level_third_party,
)

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.user import router as user_router, init_indexes as user_init_indexes
from backend.modules.llm import (
    router as llm_router,
    init_indexes as llm_init_indexes,
    homelab_router as llm_homelab_router,
)
from backend.modules.persona import router as persona_router, init_indexes as persona_init_indexes
from backend.modules.settings import router as settings_router, init_indexes as settings_init_indexes
from backend.modules.chat import router as chat_router, init_indexes as chat_init_indexes, cleanup_stale_empty_sessions, cleanup_soft_deleted_sessions
from backend.modules.bookmark import bookmark_router, init_indexes as bookmark_init_indexes
from backend.modules.storage import router as storage_router, init_indexes as storage_init_indexes
from backend.modules.memory import router as memory_router, init_indexes as memory_init_indexes
from backend.modules.embedding import router as embedding_router, startup as embedding_startup, shutdown as embedding_shutdown
from backend.modules.knowledge import (
    knowledge_router,
    init_indexes as knowledge_init_indexes,
    handle_embedding_completed,
    handle_embedding_error,
)
from backend.modules.artefact import router as artefact_router, global_router as artefact_global_router, init_indexes as artefact_init_indexes
from backend.modules.project import router as project_router, init_indexes as project_init_indexes
from backend.modules.integrations import router as integrations_router, init_indexes as integrations_init_indexes
from backend.modules.providers import (
    router as providers_router,
    PremiumProviderAccountRepository,
)
from backend.modules.debug import router as debug_router
from backend.modules.metrics import router as metrics_router
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from backend.ws.router import ws_router, get_background_tasks
from backend.ws.sidecar_router import router as sidecar_router
from backend.modules.llm import SidecarRegistry, set_sidecar_registry
from backend.jobs import consumer_loop, jobs_http_router
from backend.modules.llm._migration_connections_refactor import (
    run_if_needed as run_connections_refactor_cleanup,
)
from backend.modules.integrations._voice_adapters._client import (
    init_voice_http_client, close_voice_http_client,
)
from backend.modules.integrations._registry import _register_builtin_voice_adapters


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    redis = get_redis()
    # Hard-cut migration: must run before any module init so that index
    # creation and module bootstrapping see a consistent post-refactor state.
    # Intentionally not wrapped in try/except — if this fails, startup fails.
    await run_connections_refactor_cleanup(db, redis)
    await user_init_indexes(db)
    await llm_init_indexes(db)
    await persona_init_indexes(db)
    await settings_init_indexes(db)
    await chat_init_indexes(db)
    await bookmark_init_indexes(db)
    await storage_init_indexes(db)
    await memory_init_indexes(db)
    await knowledge_init_indexes(db)
    await artefact_init_indexes(db)
    await project_init_indexes(db)
    await integrations_init_indexes(db)
    await PremiumProviderAccountRepository(db).create_indexes()
    manager = ConnectionManager()
    set_manager(manager)
    event_bus = EventBus(redis=redis, manager=manager)
    set_event_bus(event_bus)

    # Community provisioning: process-local sidecar registry. Holds
    # in-memory state for the lifetime of this backend process — every
    # sidecar reconnect on restart is expected and normal.
    sidecar_registry = SidecarRegistry(event_bus=event_bus)
    set_sidecar_registry(sidecar_registry)

    # Load embedding model and start worker (blocking on first download)
    embedding_model_dir = os.environ.get("EMBEDDING_MODEL_DIR", "./data/models")
    embedding_batch_size = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))
    await embedding_startup(event_bus, embedding_model_dir, embedding_batch_size)

    # Initialise shared httpx client for voice adapters
    init_voice_http_client()
    _register_builtin_voice_adapters()
    from backend.modules.integrations._voice_adapters import _registry as _voice_adapter_registry
    logging.getLogger("chatsune.lifecycle").info(
        "voice adapters registered: %s", sorted(_voice_adapter_registry.keys())
    )

    # Subscribe knowledge module to embedding completion events
    from shared.topics import Topics
    event_bus.subscribe(Topics.EMBEDDING_BATCH_COMPLETED, handle_embedding_completed)
    event_bus.subscribe(Topics.EMBEDDING_ERROR, handle_embedding_error)

    _lifecycle_log = logging.getLogger("chatsune.lifecycle")

    # Start background job consumer
    _lifecycle_log.info("starting job consumer_loop")
    consumer_task = asyncio.create_task(consumer_loop(redis, event_bus))

    # Start periodic Redis Stream trimming (BD-024)
    _lifecycle_log.info("starting periodic redis stream trim")
    trim_task = await event_bus.start_periodic_trim()

    _cleanup_log = logging.getLogger("chatsune.cleanup")
    _memory_log = logging.getLogger("chatsune.memory_auto_commit")
    _dream_log = logging.getLogger("chatsune.dreaming")

    # Periodic session cleanup (every 10 minutes) — stale empty + soft-deleted sessions only.
    async def _session_cleanup_loop() -> None:
        _lifecycle_log.info("starting session_cleanup_loop")
        try:
            while True:
                await asyncio.sleep(600)
                try:
                    await cleanup_stale_empty_sessions()
                except Exception:
                    _cleanup_log.warning("cleanup_stale_empty_sessions failed", exc_info=True)
                try:
                    await cleanup_soft_deleted_sessions()
                except Exception:
                    _cleanup_log.warning("cleanup_soft_deleted_sessions failed", exc_info=True)
        except asyncio.CancelledError:
            _lifecycle_log.info("cancelled session_cleanup_loop")
            raise
        finally:
            _lifecycle_log.info("stopped session_cleanup_loop")

    # Auto-commit memory journal entries older than 48h (every 10 minutes).
    async def _memory_auto_commit_loop() -> None:
        _lifecycle_log.info("starting memory_auto_commit_loop")
        try:
            while True:
                await asyncio.sleep(600)
                try:
                    from backend.modules.memory import MemoryRepository
                    from shared.events.memory import MemoryEntryAutoCommittedEvent
                    from shared.dtos.memory import JournalEntryDto
                    from shared.topics import Topics

                    repo = MemoryRepository(get_db())
                    auto_committed = await repo.auto_commit_old_entries(max_age_hours=48)
                    batch_correlation_id = str(uuid4())
                    for entry in auto_committed:
                        try:
                            entry_dto = JournalEntryDto(
                                id=entry["id"],
                                persona_id=entry["persona_id"],
                                content=entry["content"],
                                category=entry.get("category"),
                                state=entry["state"],
                                is_correction=entry.get("is_correction", False),
                                created_at=entry["created_at"],
                                committed_at=entry.get("committed_at"),
                                auto_committed=entry.get("auto_committed", True),
                            )
                            evt = MemoryEntryAutoCommittedEvent(
                                entry=entry_dto,
                                correlation_id=batch_correlation_id,
                                timestamp=datetime.now(timezone.utc),
                            )
                            await event_bus.publish(
                                Topics.MEMORY_ENTRY_AUTO_COMMITTED,
                                evt,
                                scope=f"persona:{entry['persona_id']}",
                                target_user_ids=[entry["user_id"]],
                            )
                        except Exception:
                            _memory_log.warning(
                                "Failed to publish auto-commit event for entry %s",
                                entry.get("id"),
                                exc_info=True,
                            )
                    if auto_committed:
                        _memory_log.info(
                            "Auto-committed %d memory journal entries", len(auto_committed),
                        )
                except Exception:
                    _memory_log.warning("Memory auto-commit cycle failed", exc_info=True)
        except asyncio.CancelledError:
            _lifecycle_log.info("cancelled memory_auto_commit_loop")
            raise
        finally:
            _lifecycle_log.info("stopped memory_auto_commit_loop")

    # Dreaming auto-trigger: consolidate committed journal entries (every 10 minutes).
    async def _dreaming_trigger_loop() -> None:
        _lifecycle_log.info("starting dreaming_trigger_loop")
        try:
            while True:
                await asyncio.sleep(600)
                try:
                    from backend.modules.memory import MemoryRepository as _DreamRepo
                    from backend.modules.persona import get_persona as _get_persona
                    from backend.jobs._submit import submit as _dream_submit
                    from backend.jobs._models import JobType as _DreamJobType

                    dream_repo = _DreamRepo(get_db())
                    dream_redis = get_redis()

                    # Aggregate (user_id, persona_id) pairs with committed entry counts
                    pairs = await dream_repo.get_committed_entry_counts()

                    now = datetime.now(timezone.utc)
                    for pair in pairs:
                        uid = pair["user_id"]
                        pid = pair["persona_id"]
                        count = pair["count"]

                        try:
                            should_dream = False

                            if count >= 25:
                                # Hard limit — immediate dream
                                should_dream = True
                                _dream_log.info(
                                    "Dreaming trigger (hard limit): %d committed entries for user %s, persona %s",
                                    count, uid, pid,
                                )
                            elif count >= 10:
                                # Soft limit — only if 6h since last dream
                                dream_key = f"memory:dream:{uid}:{pid}"
                                last_dream_str = await dream_redis.hget(dream_key, "last_dream_at")
                                if last_dream_str:
                                    from datetime import datetime as _dt
                                    last_dream = _dt.fromisoformat(last_dream_str)
                                    hours_since = (now - last_dream).total_seconds() / 3600
                                    if hours_since >= 6:
                                        should_dream = True
                                        _dream_log.info(
                                            "Dreaming trigger (soft limit): %d entries, %.1fh since last dream for user %s, persona %s",
                                            count, hours_since, uid, pid,
                                        )
                                else:
                                    # Never dreamed before — trigger
                                    should_dream = True
                                    _dream_log.info(
                                        "Dreaming trigger (soft limit, first dream): %d entries for user %s, persona %s",
                                        count, uid, pid,
                                    )

                            if should_dream:
                                persona = await _get_persona(pid, uid)
                                if persona and persona.get("model_unique_id"):
                                    await _dream_submit(
                                        job_type=_DreamJobType.MEMORY_CONSOLIDATION,
                                        user_id=uid,
                                        model_unique_id=persona["model_unique_id"],
                                        payload={"persona_id": pid},
                                    )
                                    _dream_log.info(
                                        "Submitted dreaming job for user %s, persona %s",
                                        uid, pid,
                                    )
                                else:
                                    _dream_log.warning(
                                        "Cannot trigger dream for persona %s: no model_unique_id",
                                        pid,
                                    )
                        except Exception:
                            _dream_log.warning(
                                "Failed to check/trigger dream for user %s, persona %s",
                                uid, pid, exc_info=True,
                            )
                except Exception:
                    _dream_log.warning("Dreaming auto-trigger cycle failed", exc_info=True)
        except asyncio.CancelledError:
            _lifecycle_log.info("cancelled dreaming_trigger_loop")
            raise
        finally:
            _lifecycle_log.info("stopped dreaming_trigger_loop")

    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    memory_auto_commit_task = asyncio.create_task(_memory_auto_commit_loop())
    dreaming_task = asyncio.create_task(_dreaming_trigger_loop())

    _extraction_log = logging.getLogger("chatsune.extraction")

    # Periodic fallback memory extraction (default every 15 minutes; override
    # via PERIODIC_EXTRACTION_INTERVAL_SECONDS in .env for local testing).
    from backend.config import settings as _cfg_settings
    _periodic_extraction_interval = _cfg_settings.periodic_extraction_interval_seconds

    async def _periodic_extraction_loop() -> None:
        _lifecycle_log.info(
            "starting periodic_extraction_loop interval=%ds",
            _periodic_extraction_interval,
        )
        try:
            while True:
                await asyncio.sleep(_periodic_extraction_interval)
                try:
                    from backend.modules.chat import (
                        find_sessions_for_extraction,
                        list_unextracted_messages_for_session,
                    )
                    from backend.modules.persona import get_persona as _ext_get_persona
                    from backend.jobs._submit import submit as _ext_submit
                    from backend.jobs._models import JobType as _ExtJobType
                    from backend.jobs._dedup import (
                        memory_extraction_slot_key as _ext_slot_key,
                        try_acquire_inflight_slot as _ext_try_acquire,
                    )

                    ext_redis = get_redis()

                    # Scan for all extraction tracking keys. redis-py returns
                    # the cursor as an int — 0 marks the end of the scan.
                    # Using a string "0" here previously caused the inner
                    # while loop to never terminate, which in turn flooded
                    # the queue with thousands of duplicate submissions.
                    #
                    # Any exception mid-scan must reset the cursor back to 0
                    # on the next cycle — otherwise a stale cursor would
                    # silently skip keys forever (Finding C-003).
                    cursor = 0
                    while True:
                        cursor, keys = await ext_redis.scan(
                            cursor=cursor, match="memory:extraction:*", count=100,
                        )
                        for key in keys:
                            try:
                                data = await ext_redis.hgetall(key)
                                msg_count_str = data.get("messages_since_extraction", "0")
                                msg_count = int(msg_count_str)
                                if msg_count <= 0:
                                    continue

                                # Parse user_id and persona_id from key
                                # Format: memory:extraction:{user_id}:{persona_id}
                                parts = key.split(":")
                                if len(parts) != 4:
                                    continue
                                uid = parts[2]
                                pid = parts[3]

                                # Find the most recent session for this user+persona
                                session = await find_sessions_for_extraction(uid, pid)
                                if not session:
                                    continue

                                session_id = session["_id"]

                                # Resolve model from persona, not session
                                _ext_persona = await _ext_get_persona(pid, uid)
                                if not _ext_persona:
                                    continue
                                model_unique_id = _ext_persona.get("model_unique_id", "")
                                if not model_unique_id:
                                    continue

                                # Fetch unextracted user messages only
                                unextracted = await list_unextracted_messages_for_session(
                                    session_id, limit=20,
                                )
                                if not unextracted:
                                    _extraction_log.debug(
                                        "No unextracted messages for periodic extraction: user=%s persona=%s session=%s",
                                        uid, pid, session_id,
                                    )
                                    continue

                                msg_ids = [m["_id"] for m in unextracted]
                                msg_contents = [m["content"] for m in unextracted]

                                # Dedup: skip if an extraction for this
                                # persona is already queued / running /
                                # retrying, or still inside the cooldown
                                # window from a recent failure. Without
                                # this the periodic loop floods the queue
                                # every 15 min for personas whose messages
                                # get filtered to empty in the handler.
                                # Per-user submit rate-limit (SG-004):
                                # at most one periodic extraction submit per
                                # user per 5 minutes, regardless of persona.
                                rl_key = f"safeguard:extraction_submit:{uid}"
                                if not await ext_redis.set(
                                    rl_key, "1", nx=True, ex=300,
                                ):
                                    _extraction_log.debug(
                                        "extraction_loop: rate-limited submit for user=%s",
                                        uid,
                                    )
                                    continue

                                _slot_key = _ext_slot_key(uid, pid)
                                if not await _ext_try_acquire(
                                    ext_redis, _slot_key, ttl_seconds=3600,
                                ):
                                    _extraction_log.info(
                                        "Skipping periodic extraction — already in flight: user=%s persona=%s",
                                        uid, pid,
                                    )
                                    continue

                                await _ext_submit(
                                    job_type=_ExtJobType.MEMORY_EXTRACTION,
                                    user_id=uid,
                                    model_unique_id=model_unique_id,
                                    payload={
                                        "persona_id": pid,
                                        "session_id": session_id,
                                        "messages": msg_contents,
                                        "message_ids": msg_ids,
                                    },
                                )
                                _extraction_log.info(
                                    "Submitted periodic fallback extraction: user=%s persona=%s session=%s msg_count=%d",
                                    uid, pid, session_id, len(msg_ids),
                                )
                            except Exception:
                                _extraction_log.warning(
                                    "Failed to process extraction key %s", key, exc_info=True,
                                )

                        if cursor == 0:
                            break
                except Exception:
                    # Cursor is a local var — it resets to 0 on next
                    # iteration automatically. Brief sleep to avoid a
                    # tight failure loop if Redis is temporarily down.
                    _extraction_log.warning(
                        "Periodic extraction cycle failed", exc_info=True,
                    )
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            _lifecycle_log.info("cancelled periodic_extraction_loop")
            raise
        finally:
            _lifecycle_log.info("stopped periodic_extraction_loop")

    extraction_task = asyncio.create_task(_periodic_extraction_loop())

    # H-003: drain any disconnect-extraction submits that were buffered in
    # Redis because ``submit()`` failed at WS-disconnect time.
    from backend.jobs._disconnect_retry import disconnect_retry_recovery_loop
    disconnect_retry_task = asyncio.create_task(
        disconnect_retry_recovery_loop(get_redis()),
    )

    # Community provisioning: periodic sidecar health ticker. Emits
    # degraded/offline transitions based on last_traffic_at (design spec §5.10).
    _sidecar_log = logging.getLogger("chatsune.sidecar_health")

    async def _sidecar_health_loop() -> None:
        _lifecycle_log.info("starting sidecar_health_loop")
        try:
            while True:
                await asyncio.sleep(15)
                try:
                    await sidecar_registry.tick_health()
                except Exception:
                    _sidecar_log.warning("sidecar health tick failed", exc_info=True)
        except asyncio.CancelledError:
            _lifecycle_log.info("cancelled sidecar_health_loop")
            raise
        finally:
            _lifecycle_log.info("stopped sidecar_health_loop")

    sidecar_health_task = asyncio.create_task(_sidecar_health_loop())

    _lifecycle_log.info("started background tasks: consumer, trim, session_cleanup, memory_auto_commit, dreaming, extraction, disconnect_retry, sidecar_health")

    yield

    # Cancel in-flight WebSocket tasks
    ws_tasks = get_background_tasks()
    for task in ws_tasks:
        task.cancel()
    if ws_tasks:
        await asyncio.gather(*ws_tasks, return_exceptions=True)
    ws_tasks.clear()

    # Shut down background tasks
    _lifecycle_log.info("cancelling background tasks")
    cleanup_task.cancel()
    memory_auto_commit_task.cancel()
    dreaming_task.cancel()
    consumer_task.cancel()
    trim_task.cancel()
    extraction_task.cancel()
    disconnect_retry_task.cancel()
    sidecar_health_task.cancel()
    for task in (
        cleanup_task,
        memory_auto_commit_task,
        dreaming_task,
        consumer_task,
        trim_task,
        extraction_task,
        disconnect_retry_task,
        sidecar_health_task,
    ):
        try:
            await task
        except asyncio.CancelledError:
            pass
    _lifecycle_log.info("all background tasks stopped")

    await embedding_shutdown()
    await close_voice_http_client()
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(user_router)
app.include_router(llm_router)
app.include_router(llm_homelab_router)
app.include_router(persona_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(bookmark_router)
app.include_router(storage_router)
app.include_router(memory_router)
app.include_router(embedding_router)
app.include_router(knowledge_router)
app.include_router(artefact_router)
app.include_router(artefact_global_router)
app.include_router(project_router)
app.include_router(integrations_router)
app.include_router(providers_router)
app.include_router(debug_router)
app.include_router(jobs_http_router)
app.include_router(ws_router)
app.include_router(sidecar_router)
app.include_router(metrics_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
