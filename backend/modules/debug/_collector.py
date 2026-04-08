"""Snapshot collector — assembles a full diagnostic snapshot from every
relevant subsystem (LLM inference tracker, jobs, locks, embedding queue).

This module is the cross-module aggregator. It is the *only* place that
talks to multiple module public APIs at once for the purpose of
producing a single read-only debug view.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.database import get_redis
from backend.jobs import (
    get_lock_snapshot,
    get_pending_jobs,
    get_stream_queue_snapshot,
)
from backend.modules.embedding import get_status as get_embedding_status
from backend.modules.llm import get_active_inferences
from backend.modules.user import get_usernames
from shared.dtos.debug import (
    DebugSnapshotDto,
    EmbeddingQueueDto,
    JobSnapshotDto,
    LockSnapshotDto,
    StreamQueueDto,
)

_log = logging.getLogger("chatsune.debug.collector")


# Job retry counts mirror backend.jobs._registry.JOB_REGISTRY but are kept
# decoupled — the debug collector only reports what the registry says,
# never modifies it.
def _max_retries_for(job_type: str) -> int | None:
    try:
        from backend.jobs._registry import JOB_REGISTRY
        from backend.jobs._models import JobType

        try:
            jt = JobType(job_type)
        except ValueError:
            return None
        config = JOB_REGISTRY.get(jt)
        return config.max_retries if config else None
    except Exception:
        return None


async def collect_snapshot() -> DebugSnapshotDto:
    """Assemble a full debug snapshot.

    Returns a fresh ``DebugSnapshotDto`` with current state from every
    subsystem. Any individual subsystem failure is logged and the
    corresponding section comes back empty — the snapshot itself is
    always returned so the admin can still see what *did* work.
    """
    redis = get_redis()
    now = datetime.now(timezone.utc)

    # 1. Pending jobs from Redis Stream
    try:
        pending = await get_pending_jobs(redis, limit=200)
    except Exception:
        _log.warning("get_pending_jobs failed", exc_info=True)
        pending = []

    # 2. Locks held in this process
    try:
        locks_raw = get_lock_snapshot()
    except Exception:
        _log.warning("get_lock_snapshot failed", exc_info=True)
        locks_raw = []

    # 3. In-flight LLM inferences (no usernames yet — batched below)
    try:
        active_raw = get_active_inferences()
    except Exception:
        _log.warning("get_active_inferences failed", exc_info=True)
        active_raw = []

    # 4. Stream queue depth + pending count
    try:
        queue_data = await get_stream_queue_snapshot(redis)
    except Exception:
        _log.warning("get_stream_queue_snapshot failed", exc_info=True)
        queue_data = {
            "name": "jobs:pending",
            "stream_length": 0,
            "pending_count": 0,
            "oldest_pending_age_seconds": None,
            "consumer_group": "workers",
        }

    # 5. Local embedding worker queue depths
    try:
        emb_status = get_embedding_status()
        embedding_dto = EmbeddingQueueDto(
            model_loaded=emb_status.model_loaded,
            model_name=emb_status.model_name,
            query_queue_size=emb_status.query_queue_size,
            embed_queue_size=emb_status.embed_queue_size,
        )
    except Exception:
        _log.warning("get_embedding_status failed", exc_info=True)
        embedding_dto = EmbeddingQueueDto(
            model_loaded=False,
            model_name="",
            query_queue_size=0,
            embed_queue_size=0,
        )

    # 6. Batch-resolve usernames so the UI can display human-readable
    # names instead of opaque user_ids. Single round-trip across the user
    # module's public API.
    user_ids: set[str] = set()
    for entry in pending:
        user_ids.add(entry["job"].user_id)
    for inf in active_raw:
        user_ids.add(inf.user_id)
    for lock in locks_raw:
        user_ids.add(lock["user_id"])

    try:
        usernames = await get_usernames(list(user_ids))
    except Exception:
        _log.warning("get_usernames failed", exc_info=True)
        usernames = {}

    # 7. Build job DTOs
    job_dtos: list[JobSnapshotDto] = []
    for entry in pending:
        job = entry["job"]
        retry = entry["retry"]
        next_retry_at = retry["next_retry_at"] if retry else None
        attempt = retry["attempt"] if retry else job.attempt
        job_dtos.append(
            JobSnapshotDto(
                job_id=job.id,
                job_type=str(job.job_type),
                user_id=job.user_id,
                username=usernames.get(job.user_id),
                model_unique_id=job.model_unique_id,
                correlation_id=job.correlation_id,
                created_at=job.created_at,
                age_seconds=(now - job.created_at).total_seconds(),
                attempt=attempt,
                status=entry["status"],
                next_retry_at=next_retry_at,
                max_retries=_max_retries_for(str(job.job_type)),
            )
        )

    # 8. Enrich active inferences with usernames (the LLM module accepts
    # the lookup map directly).
    try:
        active_inferences = get_active_inferences(usernames=usernames)
    except Exception:
        _log.warning("get_active_inferences (enriched) failed", exc_info=True)
        active_inferences = []

    # 9. Build lock DTOs
    lock_dtos = [
        LockSnapshotDto(
            kind=lock["kind"],
            user_id=lock["user_id"],
            username=usernames.get(lock["user_id"]),
        )
        for lock in locks_raw
    ]

    # 10. Build stream queue DTOs
    stream_queues = [
        StreamQueueDto(
            name=queue_data["name"],
            stream_length=queue_data["stream_length"],
            pending_count=queue_data["pending_count"],
            oldest_pending_age_seconds=queue_data["oldest_pending_age_seconds"],
            consumer_group=queue_data["consumer_group"],
        )
    ]

    return DebugSnapshotDto(
        generated_at=now,
        active_inferences=active_inferences,
        jobs=job_dtos,
        locks=lock_dtos,
        stream_queues=stream_queues,
        embedding_queue=embedding_dto,
    )
