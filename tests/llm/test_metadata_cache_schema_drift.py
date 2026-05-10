"""Cache-schema-drift recovery tests for ``backend.modules.llm._metadata``.

Before the capabilities migration, cached entries could end up with shapes
that even the new defaults cannot rescue (e.g. ``reasoning`` stored as a
bare string). These tests inject such payloads into a fake Redis and assert
that ``get_models_for_connection`` and ``get_premium_models``:

* swallow the ``ValidationError`` (no 500 to the user);
* drop the poisoned cache key so the next call does not redeliver it;
* fall through to the adapter's ``fetch_models`` so the UI still gets data.

This protects the endpoint against any future field-without-default
landing on top of an existing cache — see CLAUDE.md §Data-Model Migrations.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _cache_key,
    _premium_cache_key,
    get_models_for_connection,
    get_premium_models,
)
from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability


def _synthetic_conn(user_id: str = "user-1") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-old-shape",
        user_id=user_id,
        adapter_type="ollama_http",
        display_name="Old Ollama",
        slug="old-ollama",
        config={"url": "http://localhost:11434", "api_key": ""},
        created_at=now,
        updated_at=now,
    )


def _meta(c: ResolvedConnection, model_id: str = "llama3.2") -> ModelMetaDto:
    return ModelMetaDto(
        connection_id=c.id,
        connection_display_name=c.display_name,
        connection_slug=c.slug,
        model_id=model_id,
        display_name=model_id,
        context_window=8192,
        reasoning=ReasoningCapability(kind="no_reasoning"),
        tools=ToolCapability(supported=False),
        supports_vision=False,
        supports_tool_calls=False,
    )


# A payload that even the new defaults cannot rescue: ``reasoning`` is a
# string instead of an object, so ``ModelMetaDto.model_validate`` raises.
_POISONED_PAYLOAD: list[dict] = [
    {
        "connection_id": "conn-old-shape",
        "connection_slug": "old-ollama",
        "connection_display_name": "Old Ollama",
        "model_id": "llama3.2",
        "display_name": "llama3.2",
        "context_window": 8192,
        "supports_vision": False,
        "supports_tool_calls": False,
        "reasoning": "yes",
    },
]


class _StubAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self._return: list[ModelMetaDto] = []

    def will_return(self, models: list[ModelMetaDto]) -> None:
        self._return = models

    async def fetch_models(self, c):  # noqa: ANN001 — matches BaseAdapter
        self.calls += 1
        return list(self._return)


def _adapter_factory(stub: _StubAdapter):
    """Return a callable ``_metadata`` can instantiate with ``()``."""

    class _Bound:
        def __init__(self) -> None:
            self._inner = stub

        async def fetch_models(self, c):
            return await self._inner.fetch_models(c)

    return _Bound


@pytest.mark.asyncio
async def test_get_models_for_connection_recovers_from_poisoned_cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _synthetic_conn()
    stub = _StubAdapter()
    stub.will_return([_meta(c)])

    key = _cache_key(c.id)
    await redis.set(key, json.dumps(_POISONED_PAYLOAD))

    result = await get_models_for_connection(c, _adapter_factory(stub), redis)

    assert stub.calls == 1, "must fall through to fetch when cache is poisoned"
    assert len(result) == 1
    assert result[0].model_id == "llama3.2"
    # The fresh fetch path writes the new shape back to Redis, so the key
    # must be present again — but it must NOT be the poisoned payload.
    new_cached = await redis.get(key)
    assert new_cached is not None
    assert json.loads(new_cached) != _POISONED_PAYLOAD


@pytest.mark.asyncio
async def test_get_premium_models_recovers_from_poisoned_cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _synthetic_conn()
    stub = _StubAdapter()
    stub.will_return([_meta(c)])

    key = _premium_cache_key("user-1", "xai")
    await redis.set(key, json.dumps(_POISONED_PAYLOAD))

    result = await get_premium_models(
        c, _adapter_factory(stub), redis, "user-1", "xai",
    )

    assert stub.calls == 1, "must fall through to fetch when cache is poisoned"
    assert len(result) == 1
    new_cached = await redis.get(key)
    assert new_cached is not None
    assert json.loads(new_cached) != _POISONED_PAYLOAD


@pytest.mark.asyncio
async def test_poisoned_cache_recovery_logs_and_does_not_raise(caplog):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _synthetic_conn()
    stub = _StubAdapter()
    stub.will_return([_meta(c)])
    await redis.set(_cache_key(c.id), json.dumps(_POISONED_PAYLOAD))

    with caplog.at_level("WARNING", logger="backend.modules.llm._metadata"):
        await get_models_for_connection(c, _adapter_factory(stub), redis)

    assert any(
        "cache" in rec.getMessage().lower() or "schema" in rec.getMessage().lower()
        for rec in caplog.records
    ), "expected a warning about the cache schema drift"
