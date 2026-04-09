"""Per-user job log stored in a Redis list.

Entries are JSON-encoded ``JobLogEntryDto`` instances. Each append
performs ``LPUSH`` + ``LTRIM`` so the list is capped at
``JOB_LOG_MAX`` (newest-first), then refreshes a rolling TTL so
inactive users' logs expire after ``JOB_LOG_TTL_SECONDS``.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from shared.dtos.jobs import JobLogEntryDto

JOB_LOG_MAX = 200
JOB_LOG_TTL_SECONDS = 7 * 24 * 3600  # 7 days

_log = logging.getLogger("chatsune.jobs.log")


def _key(user_id: str) -> str:
    return f"jobs:log:{user_id}"


async def append_job_log_entry(
    redis: Redis, *, user_id: str, entry: JobLogEntryDto
) -> None:
    """Append a single entry to the user's job log.

    Uses a pipeline so LPUSH/LTRIM/EXPIRE are issued back-to-back.
    Failures are logged but never raised — the job log is diagnostic
    and must not break the main job flow.
    """
    key = _key(user_id)
    payload = entry.model_dump_json()
    try:
        pipe = redis.pipeline(transaction=False)
        pipe.lpush(key, payload)
        pipe.ltrim(key, 0, JOB_LOG_MAX - 1)
        pipe.expire(key, JOB_LOG_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        _log.exception("job_log.append_failed user_id=%s", user_id)


async def read_job_log_entries(
    redis: Redis, *, user_id: str, limit: int = JOB_LOG_MAX
) -> list[JobLogEntryDto]:
    """Return up to ``limit`` most-recent entries (newest first)."""
    capped = max(0, min(limit, JOB_LOG_MAX))
    if capped == 0:
        return []
    raw = await redis.lrange(_key(user_id), 0, capped - 1)
    entries: list[JobLogEntryDto] = []
    for item in raw:
        try:
            entries.append(JobLogEntryDto.model_validate_json(item))
        except Exception:
            _log.warning("job_log.skip_invalid_entry user_id=%s", user_id)
    return entries
