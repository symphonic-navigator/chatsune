"""Per-user x provider rolling-window rate limiter, backed by Redis."""
from __future__ import annotations

from redis.asyncio import Redis

from ._config import SafeguardConfig


class RateLimitExceededError(Exception):
    """Raised when a user has exceeded the per-provider call rate.

    The associated job should be failed with an UnrecoverableJobError at the
    call site so the retry loop does not feed the problem."""

    def __init__(self, user_id: str, provider_id: str, limit: int, window: int) -> None:
        self.user_id = user_id
        self.provider_id = provider_id
        self.limit = limit
        self.window = window
        super().__init__(
            f"Rate limit exceeded: {limit} calls per {window}s "
            f"for user={user_id} provider={provider_id}"
        )


async def check_rate_limit(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    provider_id: str,
) -> None:
    """Raise RateLimitExceededError when the user has exhausted the
    configured per-provider call quota within the rolling window."""
    key = f"safeguard:ratelimit:{user_id}:{provider_id}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, config.rate_limit_window_seconds, nx=True)
        results = await pipe.execute()
    current = int(results[0])
    if current > config.rate_limit_max_calls:
        raise RateLimitExceededError(
            user_id=user_id,
            provider_id=provider_id,
            limit=config.rate_limit_max_calls,
            window=config.rate_limit_window_seconds,
        )
