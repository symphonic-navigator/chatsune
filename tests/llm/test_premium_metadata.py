"""Unit tests for the Premium-Provider model-listing helpers in
:mod:`backend.modules.llm._metadata`.

The integration happy paths live in ``tests/modules/providers/test_handlers.py``
— this module covers the cache-key shape, the user-scoping invariant, and
the error-degradation behaviour of ``get_premium_models`` vs.
``refresh_premium_models`` without dragging the full HTTP stack in.
"""
from __future__ import annotations

from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _premium_cache_key,
    get_premium_models,
    refresh_premium_models,
)
from shared.dtos.llm import ModelMetaDto


def _synthetic_conn(user_id: str = "user-1") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="premium:xai",
        user_id=user_id,
        adapter_type="xai_http",
        display_name="xAI",
        slug="xai",
        config={"url": "https://api.x.ai/v1", "api_key": "key"},
        created_at=now,
        updated_at=now,
    )


def _meta(c: ResolvedConnection, model_id: str = "grok-4.1-fast") -> ModelMetaDto:
    return ModelMetaDto(
        connection_id=c.id,
        connection_display_name=c.display_name,
        connection_slug=c.slug,
        model_id=model_id,
        display_name=model_id,
        context_window=200_000,
        supports_reasoning=True,
        supports_vision=True,
        supports_tool_calls=True,
    )


class _StubAdapter:
    """Adapter stub with a programmable ``fetch_models`` behaviour."""

    def __init__(self) -> None:
        self.calls = 0
        self._raise: Exception | None = None
        self._return: list[ModelMetaDto] = []

    def will_raise(self, exc: Exception) -> None:
        self._raise = exc

    def will_return(self, models: list[ModelMetaDto]) -> None:
        self._return = models

    async def fetch_models(self, c):  # noqa: ANN001 — signature matches BaseAdapter
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        return list(self._return)


def _adapter_factory(stub: _StubAdapter):
    """Return a callable that ``_metadata.py`` can instantiate with ``()``."""

    class _Bound:
        def __init__(self) -> None:
            self._inner = stub

        async def fetch_models(self, c):
            return await self._inner.fetch_models(c)

    return _Bound


def test_premium_cache_key_is_user_scoped():
    # Different users must get different keys — future provider integrations
    # will list per-user models and must not leak one user's list to another.
    assert _premium_cache_key("alice", "xai") != _premium_cache_key("bob", "xai")
    assert _premium_cache_key("alice", "xai").startswith("llm:models:premium:")


@pytest.mark.asyncio
async def test_get_premium_models_caches_after_first_fetch():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _synthetic_conn()
    stub = _StubAdapter()
    stub.will_return([_meta(c)])

    first = await get_premium_models(c, _adapter_factory(stub), redis, "user-1", "xai")
    second = await get_premium_models(c, _adapter_factory(stub), redis, "user-1", "xai")

    assert len(first) == 1 and len(second) == 1
    assert first[0].model_id == "grok-4.1-fast"
    assert stub.calls == 1, "second call must come from Redis cache"


@pytest.mark.asyncio
async def test_get_premium_models_returns_empty_on_adapter_exception():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    stub = _StubAdapter()
    stub.will_raise(RuntimeError("boom"))

    result = await get_premium_models(
        _synthetic_conn(), _adapter_factory(stub), redis, "user-1", "xai",
    )
    assert result == []


@pytest.mark.asyncio
async def test_refresh_premium_models_raises_and_clears_cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _synthetic_conn()
    stub = _StubAdapter()
    stub.will_return([_meta(c)])

    # Warm the cache via the tolerant getter.
    await get_premium_models(c, _adapter_factory(stub), redis, "user-1", "xai")
    assert stub.calls == 1
    # Now make upstream fail and call refresh — must raise.
    stub.will_raise(RuntimeError("upstream 500"))
    with pytest.raises(RuntimeError):
        await refresh_premium_models(
            c, _adapter_factory(stub), redis, "user-1", "xai",
        )
    # The cache key must have been evicted so the next read doesn't
    # serve stale data (it will re-attempt fetch, get the error, and
    # degrade to []).
    key = _premium_cache_key("user-1", "xai")
    assert await redis.get(key) is None


@pytest.mark.asyncio
async def test_premium_cache_is_per_user():
    # Two users hitting the same provider must each warm their own cache.
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    alice_conn = _synthetic_conn("alice")
    bob_conn = _synthetic_conn("bob")
    stub = _StubAdapter()
    stub.will_return([_meta(alice_conn)])

    await get_premium_models(alice_conn, _adapter_factory(stub), redis, "alice", "xai")
    await get_premium_models(bob_conn, _adapter_factory(stub), redis, "bob", "xai")
    # Both must have triggered the adapter — no cross-user cache hit.
    assert stub.calls == 2
