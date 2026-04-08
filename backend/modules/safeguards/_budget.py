"""Daily token budget for background jobs. Per user, UTC day.

This does NOT cap the user's own interactive LLM usage - testers bring
their own API keys and we stay out of that. This exists only to bound
what the *server* spends on their behalf via automated jobs (extraction,
consolidation, title generation). It protects users from bugs in our own
code, not from themselves."""
from __future__ import annotations

from datetime import datetime, timezone

from redis.asyncio import Redis

from ._config import SafeguardConfig


class BudgetExceededError(Exception):
    def __init__(self, user_id: str, spent: int, budget: int) -> None:
        self.user_id = user_id
        self.spent = spent
        self.budget = budget
        super().__init__(
            f"Daily job token budget exceeded: user={user_id} "
            f"spent={spent} budget={budget}"
        )


def _key(user_id: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"safeguard:budget:{user_id}:{today}"


async def check_budget(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    tokens_to_reserve: int = 0,
) -> None:
    """Raise BudgetExceededError when the user's pending + recorded spend
    would exceed the configured daily budget."""
    if not config.budget_enabled:
        return
    raw = await redis.get(_key(user_id))
    spent = int(raw) if raw else 0
    if spent + tokens_to_reserve > config.daily_token_budget:
        raise BudgetExceededError(user_id, spent, config.daily_token_budget)


async def record_tokens(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    tokens: int,
) -> None:
    """Add to the user's daily counter. No-op when the budget is disabled
    or the token count is non-positive."""
    if not config.budget_enabled or tokens <= 0:
        return
    key = _key(user_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incrby(key, tokens)
        pipe.expire(key, 36 * 3600, nx=True)
        await pipe.execute()
