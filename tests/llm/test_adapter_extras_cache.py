"""Regression + behaviour tests for folding adapter-internal extras into
the connection model-metadata cache.

Background: the nano-gpt pair map used to live in its own Redis key
(``nano_gpt:pair_map:v2:{connection_id}``) with a 30-minute TTL while the
model list lived under ``llm:models:{connection_id}`` with a 7-day TTL.
When a background refresh was slow/jittered, the pair map expired while
the model list survived, so a known model resolved to a
``model_not_found`` ``StreamError``.

The fix folds the pair map into the SAME Redis value as the cached model
list, under the existing connection cache key, so one write/one TTL makes
divergence structurally impossible.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import fakeredis.aioredis
import pytest

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _TTL_SECONDS,
    _cache_key,
    _decode_cache,
    _encode_cache,
    get_connection_adapter_extras,
    get_models_for_connection,
)
from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability


def _conn(conn_id: str = "conn-nano-1") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id=conn_id,
        user_id="u1",
        adapter_type="nano_gpt_http",
        display_name="Chris's Nano-GPT",
        slug="chris-nano",
        config={
            "base_url": "https://nano-gpt.com/api/v1",
            "api_key": "nano-test-key",
            "max_parallel": 3,
        },
        created_at=now,
        updated_at=now,
    )


def _meta(c: ResolvedConnection, model_id: str = "anthropic/claude-opus-4.6") -> ModelMetaDto:
    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=model_id,
        display_name=model_id,
        context_window=200000,
        reasoning=ReasoningCapability(kind="optional"),
        tools=ToolCapability(supported=True),
        supports_vision=False,
        supports_tool_calls=True,
    )


# --- envelope encode/decode --------------------------------------------------


def test_encode_decode_round_trip():
    c = _conn()
    extras = {"nano_gpt_pair_map": {"m": {"switching_mode": "none"}}}
    raw = _encode_cache([_meta(c)], extras)

    models, decoded_extras = _decode_cache(raw)
    assert len(models) == 1
    assert models[0]["model_id"] == "anthropic/claude-opus-4.6"
    assert decoded_extras == extras


def test_decode_tolerates_legacy_bare_list():
    """A pre-envelope cache value was a plain JSON list of model dicts.
    Decoding such a value must yield ``(list, {})`` so deploys are safe."""
    c = _conn()
    legacy = json.dumps([_meta(c).model_dump(mode="json")])

    models, extras = _decode_cache(legacy)
    assert len(models) == 1
    assert models[0]["model_id"] == "anthropic/claude-opus-4.6"
    assert extras == {}


def test_decode_legacy_accepts_bytes():
    c = _conn()
    legacy = json.dumps([_meta(c).model_dump(mode="json")]).encode("utf-8")
    models, extras = _decode_cache(legacy)
    assert len(models) == 1
    assert extras == {}


# --- get_connection_adapter_extras ------------------------------------------


@pytest.mark.asyncio
async def test_get_connection_adapter_extras_reads_from_model_cache():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _conn()
    pair_map = {
        "anthropic/claude-opus-4.6": {
            "non_thinking_slug": "anthropic/claude-opus-4.6",
            "thinking_slug": "anthropic/claude-opus-4.6:thinking",
            "switching_mode": "slug",
        },
    }
    await redis.set(
        _cache_key(c.id),
        _encode_cache([_meta(c)], {"nano_gpt_pair_map": pair_map}),
    )

    extras = await get_connection_adapter_extras(redis, c.id)
    assert extras["nano_gpt_pair_map"] == pair_map


@pytest.mark.asyncio
async def test_get_connection_adapter_extras_missing_returns_empty():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    assert await get_connection_adapter_extras(redis, "no-such-conn") == {}


@pytest.mark.asyncio
async def test_get_connection_adapter_extras_legacy_returns_empty():
    """A legacy bare-list value carries no extras."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _conn()
    await redis.set(
        _cache_key(c.id),
        json.dumps([_meta(c).model_dump(mode="json")]),
    )
    assert await get_connection_adapter_extras(redis, c.id) == {}


# --- backward-compat reads through the public read path ----------------------


@pytest.mark.asyncio
async def test_get_models_for_connection_reads_legacy_bare_list():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _conn()
    await redis.set(
        _cache_key(c.id),
        json.dumps([_meta(c).model_dump(mode="json")]),
    )
    # adapter_cls is unused by the read path now; pass a dummy.
    models = await get_models_for_connection(c, object, redis)
    assert len(models) == 1
    assert models[0].model_id == "anthropic/claude-opus-4.6"


@pytest.mark.asyncio
async def test_get_models_for_connection_reads_envelope():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    c = _conn()
    await redis.set(
        _cache_key(c.id),
        _encode_cache([_meta(c)], {"nano_gpt_pair_map": {}}),
    )
    models = await get_models_for_connection(c, object, redis)
    assert len(models) == 1
    assert models[0].model_id == "anthropic/claude-opus-4.6"
