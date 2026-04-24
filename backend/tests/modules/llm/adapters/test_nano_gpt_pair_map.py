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
    _key,
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
            "switching_mode": "slug",
        },
        "openai/gpt-5": {
            "non_thinking_slug": "openai/gpt-5",
            "thinking_slug": "openai/gpt-5",
            "switching_mode": "flag",
        },
        "vendor/plain": {
            "non_thinking_slug": "vendor/plain",
            "thinking_slug": None,
            "switching_mode": "none",
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
        pair_map={"m": {
            "non_thinking_slug": "m",
            "thinking_slug": None,
            "switching_mode": "none",
        }},
    )
    ttl = await redis_client.ttl(_key("c2"))
    assert 0 < ttl <= PAIR_MAP_TTL_SECONDS


@pytest.mark.asyncio
async def test_save_pair_map_key_is_connection_scoped(redis_client):
    await save_pair_map(
        redis_client,
        connection_id="a",
        pair_map={"x": {
            "non_thinking_slug": "x",
            "thinking_slug": None,
            "switching_mode": "none",
        }},
    )
    await save_pair_map(
        redis_client,
        connection_id="b",
        pair_map={"y": {
            "non_thinking_slug": "y",
            "thinking_slug": None,
            "switching_mode": "none",
        }},
    )
    loaded_a = await load_pair_map(redis_client, connection_id="a")
    loaded_b = await load_pair_map(redis_client, connection_id="b")
    assert "x" in loaded_a
    assert "y" in loaded_b
    assert "x" not in loaded_b
    assert "y" not in loaded_a


@pytest.mark.asyncio
async def test_pair_map_key_uses_v2_prefix(redis_client):
    """The cache key carries the ``v2`` revision so stale v1-shape values
    cannot be misread as the new shape."""
    assert _key("conn-x") == "nano_gpt:pair_map:v2:conn-x"


@pytest.mark.asyncio
async def test_load_pair_map_treats_legacy_shape_as_cache_miss(redis_client):
    """A v1-shape entry (missing ``switching_mode``) under the v2 key must
    be treated as a cache miss — the adapter will then re-fetch and write
    a fresh, well-shaped map."""
    import json

    legacy = {
        "anthropic/claude-opus-4.6": {
            "non_thinking_slug": "anthropic/claude-opus-4.6",
            "thinking_slug": "anthropic/claude-opus-4.6:thinking",
        },
    }
    await redis_client.set(_key("legacy-conn"), json.dumps(legacy))
    loaded = await load_pair_map(redis_client, connection_id="legacy-conn")
    assert loaded == {}
