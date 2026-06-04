"""Regression test for the nano-gpt pair-map divergence bug.

After a connection fetch+cache cycle the pair-map data must be retrievable
from the SAME ``llm:models:{connection_id}`` key (via
``get_connection_adapter_extras``), the key's TTL must be the 7-day
``_TTL_SECONDS``, and NO ``nano_gpt:pair_map:*`` key may be written.

Also covers ``cache_extras()`` round-trips and that ``stream_completion``
resolves a known model from the metadata-cache extras rather than its old
dedicated key.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import fakeredis.aioredis
import pytest

from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _TTL_SECONDS,
    _cache_key,
    get_connection_adapter_extras,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = (
    _REPO_ROOT
    / "backend"
    / "tests"
    / "modules"
    / "llm"
    / "adapters"
    / "fixtures"
    / "nano_gpt"
)


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


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


def _patch_http_models(monkeypatch):
    envelope = json.loads((FIXTURES / "mini_dump.json").read_text())
    raw_data = envelope["data"]

    async def _fake_get(**kwargs):
        return raw_data

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http._http_get_models",
        _fake_get,
    )


@pytest.mark.asyncio
async def test_refresh_cycle_folds_pair_map_into_model_cache(
    redis_client, monkeypatch,
):
    from backend.modules.llm._metadata_refresher import (
        _refresh_connection_into_cache,
    )

    _patch_http_models(monkeypatch)
    c = _conn()

    await _refresh_connection_into_cache(c, NanoGptHttpAdapter, redis_client)

    # Pair map retrievable from the SAME llm:models:{id} key.
    extras = await get_connection_adapter_extras(redis_client, c.id)
    pair_map = extras.get("nano_gpt_pair_map")
    assert pair_map, "pair map must live inside the model-cache envelope"
    for pair in pair_map.values():
        assert pair["switching_mode"] in {"slug", "flag", "none"}

    # TTL on the model cache key is the 7-day value.
    ttl = await redis_client.ttl(_cache_key(c.id))
    assert 0 < ttl <= _TTL_SECONDS
    assert ttl > 24 * 60 * 60, "TTL must be far longer than the old 30-min pair map"

    # No separate nano_gpt:pair_map:* key exists anymore.
    keys = await redis_client.keys("nano_gpt:pair_map:*")
    assert keys == [], f"legacy pair-map key must not be written, found {keys!r}"


@pytest.mark.asyncio
async def test_cache_extras_round_trip_nano_gpt(redis_client, monkeypatch):
    _patch_http_models(monkeypatch)
    adapter = NanoGptHttpAdapter(redis=redis_client)

    # Before fetch: empty.
    assert adapter.cache_extras() == {"nano_gpt_pair_map": {}}

    await adapter.fetch_models(_conn())
    extras = adapter.cache_extras()
    assert "nano_gpt_pair_map" in extras
    assert extras["nano_gpt_pair_map"], "fetch must populate the pair map"


@pytest.mark.asyncio
async def test_cache_extras_default_empty_for_non_nano_adapter():
    adapter = OllamaHttpAdapter()
    assert adapter.cache_extras() == {}


@pytest.mark.asyncio
async def test_fetch_models_does_not_write_legacy_pair_map_key(
    redis_client, monkeypatch,
):
    _patch_http_models(monkeypatch)
    adapter = NanoGptHttpAdapter(redis=redis_client)
    await adapter.fetch_models(_conn())
    keys = await redis_client.keys("nano_gpt:pair_map:*")
    assert keys == []


# --- stream_completion resolving from the metadata cache ---------------------


from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _make_request(model_id: str) -> CompletionRequest:
    return CompletionRequest(
        model=model_id,
        messages=[CompletionMessage(
            role="user",
            content=[ContentPart(type="text", text="hi")],
        )],
        reasoning=ReasoningCapability(kind="optional"),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    )


class _FakeResponse:
    def __init__(self, status_code, lines, body=b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, response):
        self._response = response
        self.posted_payload = None

    def stream(self, method, url, *, json=None, headers=None):
        self.posted_payload = json
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_stream_completion_resolves_known_model_from_metadata_cache(
    redis_client, monkeypatch,
):
    _patch_http_models(monkeypatch)
    c = _conn()

    # Populate the metadata cache the way the refresher does.
    adapter_fill = NanoGptHttpAdapter(redis=redis_client)
    from backend.modules.llm._metadata import _encode_cache
    models = await adapter_fill.fetch_models(c)
    await redis_client.set(
        _cache_key(c.id),
        _encode_cache(models, adapter_fill.cache_extras()),
    )

    # Pick a model that actually exists in the freshly built pair map.
    extras = await get_connection_adapter_extras(redis_client, c.id)
    known_model = next(iter(extras["nano_gpt_pair_map"].keys()))

    sse_lines = [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        'data: [DONE]',
    ]
    fake = _FakeClient(_FakeResponse(200, sse_lines))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(c, _make_request(known_model))
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert not any(
        isinstance(e, StreamError) and e.error_code == "model_not_found"
        for e in events
    ), "known model must resolve from the metadata-cache pair map"


@pytest.mark.asyncio
async def test_stream_completion_empty_cache_still_model_not_found(
    redis_client, monkeypatch,
):
    c = _conn()
    # No cache written at all.
    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            c, _make_request("anything/at-all"),
        )
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "model_not_found"
