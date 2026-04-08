"""Per user x provider x model circuit breaker.

Why per-model and not just per-provider: Ollama Cloud routes by model
and a flakey llama3.2 should not take down qwen for the same user."""
from __future__ import annotations

from redis.asyncio import Redis

from ._config import SafeguardConfig


class CircuitOpenError(Exception):
    def __init__(self, user_id: str, provider_id: str, model_slug: str) -> None:
        self.user_id = user_id
        self.provider_id = provider_id
        self.model_slug = model_slug
        super().__init__(
            f"Circuit open: user={user_id} provider={provider_id} "
            f"model={model_slug}"
        )


def _fail_key(u: str, p: str, m: str) -> str:
    return f"safeguard:cb:fail:{u}:{p}:{m}"


def _open_key(u: str, p: str, m: str) -> str:
    return f"safeguard:cb:open:{u}:{p}:{m}"


def _probe_key(u: str, p: str, m: str) -> str:
    return f"safeguard:cb:probe:{u}:{p}:{m}"


async def check_circuit(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    provider_id: str,
    model_slug: str,
) -> None:
    """Raise CircuitOpenError when the breaker is open and no probe is
    currently allowed. If the breaker is half-open, this call claims the
    probe slot and returns."""
    open_exists = await redis.exists(_open_key(user_id, provider_id, model_slug))
    if not open_exists:
        return
    claimed = await redis.set(
        _probe_key(user_id, provider_id, model_slug),
        "1",
        nx=True,
        ex=60,
    )
    if not claimed:
        raise CircuitOpenError(user_id, provider_id, model_slug)


async def record_failure(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    provider_id: str,
    model_slug: str,
) -> None:
    fkey = _fail_key(user_id, provider_id, model_slug)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(fkey)
        pipe.expire(fkey, config.circuit_window_seconds, nx=True)
        results = await pipe.execute()
    failures = int(results[0])
    if failures >= config.circuit_failure_threshold:
        await redis.set(
            _open_key(user_id, provider_id, model_slug),
            "1",
            ex=config.circuit_open_seconds,
        )
        # Drop the probe marker so the next check-after-open can claim it.
        await redis.delete(_probe_key(user_id, provider_id, model_slug))


async def record_success(
    redis: Redis,
    config: SafeguardConfig,
    user_id: str,
    provider_id: str,
    model_slug: str,
) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(_fail_key(user_id, provider_id, model_slug))
        pipe.delete(_open_key(user_id, provider_id, model_slug))
        pipe.delete(_probe_key(user_id, provider_id, model_slug))
        await pipe.execute()
