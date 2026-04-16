"""Best-effort deduplication for job submissions.

Some job types (notably memory extraction) must not be queued twice for
the same scope. Two concurrent memory extractions for the same persona
race on the same journal state and also pointlessly multiply load; with
a slow upstream provider (e.g. a cold local Ollama) failed retry chains
can otherwise stack up faster than they drain, flooding the queue.

This helper provides a tiny Redis-backed slot: a caller tries to acquire
a slot before submitting, and the handler releases it once the job
reaches a terminal state. The slot is set with ``SET NX EX`` — the TTL
is a safety net so a crashed worker cannot block the scope forever, and
it must comfortably cover the full retry chain of the guarded job type.

The slot also doubles as a short cooldown window: when the handler hits
a ``ProviderUnavailableError``, it refreshes the TTL to the cooldown
duration and leaves the slot held, so a dead upstream provider cannot
flood the queue with fresh submissions while it recovers. On any other
terminal failure the handler is expected to release the slot and mark
the affected work items so they do not loop back into the queue.
"""

import structlog
from redis.asyncio import Redis

# Default lifetime for the in-flight slot. Must be long enough to cover
# the full retry chain of the guarded handler (memory extraction:
# max_retries * (execution_timeout + retry_delay) plus headroom). At the
# same time it should not be so long that a truly abandoned slot blocks
# the scope for hours — callers applying a provider cooldown shorten
# the TTL via ``redis.expire`` at that point.
MEMORY_EXTRACTION_SLOT_TTL_SECONDS = 1800  # 30 minutes

# Shorter cooldown applied to the in-flight slot on failure paths (generic
# exceptions, cancellations, retryable errors that are not yet terminal).
# The full 30-minute safety-net TTL exists purely to unblock the scope
# after a crashed worker; when we *know* the attempt just failed we should
# not make the user wait that long before a retry or a fresh submission
# can take over. Ten minutes gives the retry chain room to run and still
# frees the slot promptly if the job is abandoned.
MEMORY_EXTRACTION_FAILURE_TTL_SECONDS = 600  # 10 minutes

_log = structlog.get_logger("chatsune.jobs.dedup")


async def try_acquire_inflight_slot(
    redis: Redis, key: str, ttl_seconds: int,
) -> bool:
    """Claim the slot identified by ``key``.

    Returns True if the slot was free and is now held by the caller,
    False if another in-flight submission already holds it.
    """
    result = await redis.set(key, "1", nx=True, ex=ttl_seconds)
    if result is True:
        _log.debug("job.dedup.key_written", redis_key=key, ttl_seconds=ttl_seconds)
        _log.debug("job.dedup.miss", dedup_key=key)
        return True
    _log.info("job.dedup.hit", dedup_key=key)
    return False


async def release_inflight_slot(redis: Redis, key: str) -> None:
    """Release a previously-acquired slot.

    Safe to call even if the key does not exist (TTL already expired or
    the slot was never acquired).
    """
    await redis.delete(key)
    _log.debug("job.dedup.key_deleted", redis_key=key)


def memory_extraction_slot_key(user_id: str, persona_id: str) -> str:
    """Return the Redis key used to guard a memory-extraction scope."""
    return f"jobs:inflight:memory_extraction:{user_id}:{persona_id}"
