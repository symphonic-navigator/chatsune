"""Tests for the Redis-backed nano-gpt pair-map persistence layer.

Uses ``fakeredis.aioredis.FakeRedis`` so the suite stays hermetic — no
Docker or live Redis required. The fixture yields a client that quacks
like ``redis.asyncio.Redis`` for everything the persistence layer uses
(``set`` with ``ex=``, ``get``, ``ttl``).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis

from backend.modules.llm._adapters._nano_gpt_pair_map import (
    PAIR_MAP_TTL_SECONDS,
    load_pair_map,
    save_pair_map,
)


@pytest_asyncio.fixture
async def redis_client():
    client = fake_aioredis.FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_save_and_load_pair_map_round_trip(redis_client):
    pair_map = {
        "anthropic/claude-opus-4.6": {
            "non_thinking_slug": "anthropic/claude-opus-4.6",
            "thinking_slug": "anthropic/claude-opus-4.6:thinking",
        },
        "openai/gpt-5": {
            "non_thinking_slug": "openai/gpt-5",
            "thinking_slug": None,
        },
    }
    await save_pair_map(redis_client, connection_id="c1", pair_map=pair_map)
    loaded = await load_pair_map(redis_client, connection_id="c1")
    assert loaded == pair_map


@pytest.mark.asyncio
async def test_load_pair_map_missing_returns_empty_dict(redis_client):
    loaded = await load_pair_map(redis_client, connection_id="does-not-exist")
    assert loaded == {}


@pytest.mark.asyncio
async def test_save_pair_map_sets_ttl(redis_client):
    await save_pair_map(
        redis_client,
        connection_id="c2",
        pair_map={"m": {"non_thinking_slug": "m", "thinking_slug": None}},
    )
    ttl = await redis_client.ttl("nano_gpt:pair_map:c2")
    assert 0 < ttl <= PAIR_MAP_TTL_SECONDS


@pytest.mark.asyncio
async def test_save_pair_map_key_is_connection_scoped(redis_client):
    await save_pair_map(
        redis_client,
        connection_id="a",
        pair_map={"x": {"non_thinking_slug": "x", "thinking_slug": None}},
    )
    await save_pair_map(
        redis_client,
        connection_id="b",
        pair_map={"y": {"non_thinking_slug": "y", "thinking_slug": None}},
    )
    loaded_a = await load_pair_map(redis_client, connection_id="a")
    loaded_b = await load_pair_map(redis_client, connection_id="b")
    assert "x" in loaded_a
    assert "y" in loaded_b
    assert "x" not in loaded_b
    assert "y" not in loaded_a
