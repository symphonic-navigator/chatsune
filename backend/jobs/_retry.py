from datetime import datetime

from redis.asyncio import Redis

_RETRY_TTL = 7200  # 2 hours


async def set_retry(
    redis: Redis,
    job_id: str,
    attempt: int,
    next_retry_at: datetime,
) -> None:
    """Store retry state for a job in Redis."""
    key = f"jobs:retry:{job_id}"
    await redis.hset(key, mapping={
        "attempt": str(attempt),
        "next_retry_at": next_retry_at.isoformat(),
    })
    await redis.expire(key, _RETRY_TTL)


async def get_retry(redis: Redis, job_id: str) -> dict | None:
    """Read retry state, or None if no retry is pending."""
    key = f"jobs:retry:{job_id}"
    data = await redis.hgetall(key)
    if not data:
        return None
    return {
        "attempt": int(data["attempt"]),
        "next_retry_at": datetime.fromisoformat(data["next_retry_at"]),
    }


async def clear_retry(redis: Redis, job_id: str) -> None:
    """Remove retry state after job completes or is discarded."""
    await redis.delete(f"jobs:retry:{job_id}")
