"""``get_model_metadata`` must route premium-provider connections to the
user-scoped premium cache, not the connection-scoped cache.

Pre-fix the helper called ``get_models_for_connection`` for both flavours,
which only inspects the connection-scoped key ``llm:models:{connection_id}``.
Premium models are cached under ``llm:models:premium:{user_id}:{provider_id}``,
so reads always missed and — after the removal of the synchronous fetch on
miss — surfaced as ``None`` for every premium model. That in turn made the
PATCH ``/sessions/{id}/extras`` endpoint reject every cockpit toggle with
``400 "Model metadata unavailable"``.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis import aioredis as fake_aioredis

from backend.modules.llm import get_model_metadata
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import _cache_key, _premium_cache_key
from shared.dtos.llm import ModelMetaDto


def _model_dto(model_id: str) -> ModelMetaDto:
    return ModelMetaDto(
        connection_id="ignored-here",
        model_id=model_id,
        display_name=model_id,
        context_window=4096,
        supports_vision=False,
        supports_tool_calls=True,
    )


def _premium_resolved() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="premium:nano-gpt",
        user_id="user-a",
        adapter_type="nano_gpt_http",
        display_name="Nano-GPT",
        slug="nano-gpt",
        config={"url": "https://example", "api_key": "k"},
        created_at=now,
        updated_at=now,
    )


def _user_resolved() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-uuid-1",
        user_id="user-a",
        adapter_type="ollama_http",
        display_name="Homelab",
        slug="homelab",
        config={"url": "http://x", "api_key": "k"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_premium_metadata_reads_user_scoped_cache(monkeypatch):
    redis = fake_aioredis.FakeRedis()
    try:
        # Pre-populate ONLY the premium cache key. The buggy code path
        # reads from ``_cache_key(c.id)`` which would miss and surface
        # ``None``; the fixed path reads from ``_premium_cache_key``.
        model = _model_dto("deepseek-v4-flash")
        await redis.set(
            _premium_cache_key("user-a", "nano-gpt"),
            json.dumps([model.model_dump(mode="json")]),
        )

        monkeypatch.setattr(
            "backend.modules.llm.get_redis", lambda: redis,
        )

        async def _fake_resolve(*_a, **_k):
            return _premium_resolved()

        monkeypatch.setattr(
            "backend.modules.llm.resolve_for_model", _fake_resolve,
        )

        meta = await get_model_metadata(
            "user-a", "nano-gpt:deepseek-v4-flash",
        )
        assert meta is not None
        assert meta.model_id == "deepseek-v4-flash"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_premium_metadata_returns_none_when_premium_cache_empty(
    monkeypatch,
):
    """Cold-cache regression: with no entry under the premium key the read
    path now returns ``None`` cleanly (no upstream fetch). The background
    refresher owns cache population."""
    redis = fake_aioredis.FakeRedis()
    try:
        monkeypatch.setattr(
            "backend.modules.llm.get_redis", lambda: redis,
        )

        async def _fake_resolve(*_a, **_k):
            return _premium_resolved()

        monkeypatch.setattr(
            "backend.modules.llm.resolve_for_model", _fake_resolve,
        )

        meta = await get_model_metadata(
            "user-a", "nano-gpt:deepseek-v4-flash",
        )
        assert meta is None
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_user_connection_metadata_still_reads_connection_cache(
    monkeypatch,
):
    """Per-user Connection lookups must keep using the connection-scoped
    key — they should not regress when premium routing is added."""
    redis = fake_aioredis.FakeRedis()
    try:
        model = _model_dto("llama3.2")
        await redis.set(
            _cache_key("conn-uuid-1"),
            json.dumps([model.model_dump(mode="json")]),
        )

        monkeypatch.setattr(
            "backend.modules.llm.get_redis", lambda: redis,
        )

        async def _fake_resolve(*_a, **_k):
            return _user_resolved()

        monkeypatch.setattr(
            "backend.modules.llm.resolve_for_model", _fake_resolve,
        )

        meta = await get_model_metadata("user-a", "homelab:llama3.2")
        assert meta is not None
        assert meta.model_id == "llama3.2"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_premium_metadata_does_not_read_connection_cache_for_premium(
    monkeypatch,
):
    """Regression guard: even if the legacy connection-scoped key happens
    to be populated for a ``premium:*`` synthetic id (stale from before
    the routing fix), the premium path must not fall back to it."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()

    monkeypatch.setattr(
        "backend.modules.llm.get_redis", lambda: redis,
    )

    async def _fake_resolve(*_a, **_k):
        return _premium_resolved()

    monkeypatch.setattr(
        "backend.modules.llm.resolve_for_model", _fake_resolve,
    )

    meta = await get_model_metadata(
        "user-a", "nano-gpt:deepseek-v4-flash",
    )
    assert meta is None

    # Only the premium key should be read.
    called_keys = [c.args[0] for c in redis.get.await_args_list]
    assert _premium_cache_key("user-a", "nano-gpt") in called_keys
    assert _cache_key("premium:nano-gpt") not in called_keys
