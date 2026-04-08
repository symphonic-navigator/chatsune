"""Best-effort deduplication for job submissions.

Some job types (notably memory extraction) must not be queued twice for
the same scope. Two concurrent memory extractions for the same persona
race on the same journal state and also pointlessly multiply load; with
a slow upstream provider (e.g. a cold local Ollama) failed retry chains
can otherwise stack up faster than they drain, flooding the queue.

This helper provides a tiny Redis-backed slot: a caller tries to acquire
a slot before submitting, and releases it after the handler has finished
successfully. The slot is set with ``SET NX EX`` — the TTL is a safety
net so a crashed worker cannot block the scope forever. On a failed
retry chain we deliberately do **not** release the slot: the TTL then
acts as a cooldown before the next extraction is allowed, which is the
desired behaviour in the queue-flood scenario.
"""

from redis.asyncio import Redis


async def try_acquire_inflight_slot(
    redis: Redis, key: str, ttl_seconds: int,
) -> bool:
    """Claim the slot identified by ``key``.

    Returns True if the slot was free and is now held by the caller,
    False if another in-flight submission already holds it.
    """
    result = await redis.set(key, "1", nx=True, ex=ttl_seconds)
    return result is True


async def release_inflight_slot(redis: Redis, key: str) -> None:
    """Release a previously-acquired slot.

    Safe to call even if the key does not exist (TTL already expired or
    the slot was never acquired).
    """
    await redis.delete(key)


def memory_extraction_slot_key(user_id: str, persona_id: str) -> str:
    """Return the Redis key used to guard a memory-extraction scope."""
    return f"jobs:inflight:memory_extraction:{user_id}:{persona_id}"
