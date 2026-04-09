"""Redis-backed retry buffer for disconnect-triggered memory extractions.

When ``trigger_disconnect_extraction`` cannot enqueue a job via ``submit()``
after its in-line retries, it serialises the full submit kwargs into a
per-user sorted set. A periodic recovery loop then drains this buffer,
replaying entries until they succeed or exceed a maximum attempt count, at
which point they are moved to a dead-letter list.

See finding H-003.
"""

from __future__ import annotations

import asyncio
import json

import structlog

from backend.jobs._models import JobType
from backend.jobs._submit import submit

_log = structlog.get_logger("chatsune.jobs.disconnect_retry")

BUFFER_KEY_PREFIX = "jobs:disconnect_retry:"
DEAD_KEY_PREFIX = "jobs:disconnect_retry_dead:"
MAX_ATTEMPTS = 5
RECOVERY_INTERVAL_SECONDS = 60.0


def buffer_key(user_id: str) -> str:
    return f"{BUFFER_KEY_PREFIX}{user_id}"


def dead_key(user_id: str) -> str:
    return f"{DEAD_KEY_PREFIX}{user_id}"


async def buffer_submit_payload(redis, user_id: str, submit_kwargs: dict) -> None:
    """Persist failed submit kwargs to the per-user retry zset at score 0."""
    member = json.dumps(submit_kwargs, sort_keys=True, default=str)
    await redis.zadd(buffer_key(user_id), {member: 0.0})


async def _replay_submit(submit_kwargs: dict) -> None:
    """Call ``submit`` with the previously serialised kwargs.

    ``job_type`` is serialised as a string; convert it back to the enum.
    """
    kwargs = dict(submit_kwargs)
    job_type = kwargs.get("job_type")
    if isinstance(job_type, str):
        kwargs["job_type"] = JobType(job_type)
    await submit(**kwargs)


async def drain_disconnect_retry_buffer(redis) -> None:
    """Single pass: scan all buffer keys, replay members, manage attempts.

    Exposed as a standalone function so tests can drive it directly without
    waiting on the outer 60-second loop.
    """
    async for raw_key in redis.scan_iter(match=f"{BUFFER_KEY_PREFIX}*", count=100):
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        user_id = key[len(BUFFER_KEY_PREFIX):]

        entries = await redis.zrange(key, 0, -1, withscores=True)
        for raw_member, score in entries:
            member = raw_member.decode() if isinstance(raw_member, bytes) else raw_member
            try:
                submit_kwargs = json.loads(member)
            except Exception:
                _log.error(
                    "job.disconnect_retry.loop_error", redis_key=key,
                    detail="undecodable member, removing",
                )
                await redis.zrem(key, member)
                continue

            try:
                await _replay_submit(submit_kwargs)
                await redis.zrem(key, member)
                _log.info("job.disconnect_retry.requeued", user_id=user_id)
            except Exception:
                new_score = await redis.zincrby(key, 1, member)
                if new_score >= MAX_ATTEMPTS:
                    await redis.zrem(key, member)
                    await redis.rpush(dead_key(user_id), member)
                    _log.error(
                        "job.disconnect_retry.loop_error",
                        user_id=user_id, attempts=int(new_score),
                        detail="dead-lettered after max attempts",
                        exc_info=True,
                    )
                else:
                    _log.warning(
                        "job.disconnect_retry.loop_error",
                        user_id=user_id, attempt=int(new_score),
                        detail="replay failed, will retry",
                        exc_info=True,
                    )


async def disconnect_retry_recovery_loop(redis) -> None:
    """Forever loop that calls :func:`drain_disconnect_retry_buffer` every minute."""
    _log.info("job.disconnect_retry.loop_started")
    try:
        while True:
            try:
                await drain_disconnect_retry_buffer(redis)
            except Exception:
                _log.exception("job.disconnect_retry.loop_error")
            await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        _log.info("job.disconnect_retry.loop_stopped", reason="cancelled")
        raise
    finally:
        _log.info("job.disconnect_retry.loop_stopped", reason="finalised")
