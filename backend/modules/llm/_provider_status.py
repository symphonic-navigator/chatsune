"""Per-provider reachability state, persisted in Redis.

Reachability is derived from model-refresh outcomes (no separate health-poll).
A provider is "available" iff its most recent refresh produced >= 1 model.
"""

import json
from datetime import datetime, timezone

from redis.asyncio import Redis

_KEY_PREFIX = "llm:provider_status:"


def _key(provider_id: str) -> str:
    return f"{_KEY_PREFIX}{provider_id}"


async def set_status(
    redis: Redis,
    provider_id: str,
    *,
    available: bool,
    model_count: int,
) -> bool:
    """Persist status. Returns True iff ``available`` flipped from the previous
    value (or no previous value existed)."""
    raw = await redis.get(_key(provider_id))
    previous_available: bool | None = None
    if raw:
        try:
            previous_available = bool(json.loads(raw).get("available"))
        except (ValueError, TypeError):
            previous_available = None

    payload = {
        "available": available,
        "model_count": model_count,
        "last_refresh_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis.set(_key(provider_id), json.dumps(payload))

    return previous_available is None or previous_available != available


async def get_all_statuses(redis: Redis, provider_ids: list[str]) -> dict[str, bool]:
    """Return ``{provider_id: available}`` for the given provider IDs.
    Unknown providers default to ``False``."""
    result: dict[str, bool] = {}
    for pid in provider_ids:
        raw = await redis.get(_key(pid))
        if not raw:
            result[pid] = False
            continue
        try:
            result[pid] = bool(json.loads(raw).get("available"))
        except (ValueError, TypeError):
            result[pid] = False
    return result
