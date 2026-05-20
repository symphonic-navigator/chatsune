"""Read path is pure cache lookup — no synchronous fetch on miss."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _cache_key,
    _premium_cache_key,
    get_models_for_connection,
    get_premium_models,
)
from shared.dtos.llm import ModelMetaDto


def _make_conn() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-1",
        user_id="user-a",
        adapter_type="ollama_http",
        display_name="conn-1",
        slug="conn-1",
        config={"url": "http://x", "api_key": "k"},
        created_at=now,
        updated_at=now,
    )


def _fake_redis_with(cached_value: str | None) -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=cached_value)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_connection_cache_miss_returns_empty_without_fetching():
    conn = _make_conn()
    adapter_cls = MagicMock()
    redis = _fake_redis_with(None)

    result = await get_models_for_connection(conn, adapter_cls, redis)

    assert result == []
    adapter_cls.assert_not_called()  # adapter never instantiated
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_cache_hit_returns_parsed():
    conn = _make_conn()
    adapter_cls = MagicMock()
    model = ModelMetaDto(
        connection_id="conn-1",
        model_id="m",
        display_name="m",
        context_window=4096,
        supports_vision=False,
        supports_tool_calls=False,
    )
    cached = json.dumps([model.model_dump(mode="json")])
    redis = _fake_redis_with(cached)

    result = await get_models_for_connection(conn, adapter_cls, redis)

    assert len(result) == 1
    assert result[0].model_id == "m"


@pytest.mark.asyncio
async def test_connection_cache_validation_error_drops_key_and_returns_empty():
    conn = _make_conn()
    adapter_cls = MagicMock()
    # Garbage that no DTO can parse:
    redis = _fake_redis_with(json.dumps([{"unknown_field": True}]))

    result = await get_models_for_connection(conn, adapter_cls, redis)

    assert result == []
    redis.delete.assert_awaited_once_with(_cache_key("conn-1"))
    adapter_cls.assert_not_called()


@pytest.mark.asyncio
async def test_premium_cache_miss_returns_empty_without_fetching():
    conn = _make_conn()
    adapter_cls = MagicMock()
    redis = _fake_redis_with(None)

    result = await get_premium_models(conn, adapter_cls, redis, "user-a", "xai")

    assert result == []
    adapter_cls.assert_not_called()
    redis.set.assert_not_awaited()
