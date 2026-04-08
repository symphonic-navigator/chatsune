"""Per-user cap on pending background jobs. Enforced at submit time.

When a user exceeds the cap, the oldest queued job is evicted from the
Redis Stream (XDEL). This protects downstream handlers from queue-flood
bugs without rejecting new work - the most recent user intent wins."""
from __future__ import annotations

from redis.asyncio import Redis

from ._config import SafeguardConfig


def _queue_key(user_id: str) -> str:
    return f"safeguard:queue:{user_id}"


async def enforce_queue_cap(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    stream_key: str,
    new_message_id: str,
    now_ms: int,
) -> list[str]:
    """Register the new job in the per-user queue set, then evict any
    overflow. Returns the list of stream IDs that were evicted (possibly
    empty). Caller is responsible for logging the eviction."""
    if not config.queue_cap_enabled:
        return []

    key = _queue_key(user_id)
    await redis.zadd(key, {new_message_id: now_ms})
    # Keep the sorted set from growing forever even if XDEL fails.
    await redis.expire(key, 86400)

    overflow = await redis.zcard(key) - config.queue_cap_per_user
    if overflow <= 0:
        return []

    evicted: list[str] = []
    for _ in range(overflow):
        popped = await redis.zpopmin(key, count=1)
        if not popped:
            break
        msg_id_raw, _score = popped[0]
        msg_id = msg_id_raw.decode() if isinstance(msg_id_raw, bytes) else msg_id_raw
        evicted.append(msg_id)
        try:
            await redis.xdel(stream_key, msg_id)
        except Exception:
            # Best-effort: the message may already have been consumed.
            # Leave the book-keeping consistent with the sorted set.
            pass
    return evicted


async def acknowledge_job_done(
    redis: Redis,
    user_id: str,
    message_id: str,
) -> None:
    """Remove a completed job from the per-user queue set."""
    await redis.zrem(_queue_key(user_id), message_id)
