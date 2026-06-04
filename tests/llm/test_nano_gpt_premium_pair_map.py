"""Premium-path regression for the nano-gpt pair-map lookup.

nano-gpt is registered as a Premium Provider (``provider_id == "nano_gpt"``),
so its models are commonly resolved via the premium path. On that path the
model-cache envelope — and the pair map folded into it — is written under the
USER-SCOPED key ``llm:models:premium:{user_id}:{provider_id}`` by the
refresher, and a premium-resolved ``ResolvedConnection`` has
``id == "premium:{provider_id}"`` with a populated ``user_id``.

A connection-scoped read (``llm:models:{connection.id}`` =
``llm:models:premium:nano_gpt``, no user_id) does NOT match that key, so
reading the wrong key would leave the pair map empty and produce a spurious
``model_not_found`` on every premium message. These tests prove the premium
path round-trips: the cache the refresher writes is readable via
``get_premium_adapter_extras`` and drives ``stream_completion`` to resolve a
known model without emitting ``model_not_found``.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import fakeredis.aioredis
import pytest

from backend.modules.llm._adapters._events import StreamError
from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _premium_cache_key,
    get_premium_adapter_extras,
)
from backend.modules.llm._metadata_refresher import _refresh_premium_into_cache
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ReasoningCapability, ToolCapability

_PROVIDER_ID = "nano_gpt"
_USER_ID = "u-premium-1"

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


def _premium_conn() -> ResolvedConnection:
    """A premium-resolved connection, exactly as ``_resolver.py`` builds it:
    ``id == "premium:{provider_id}"`` with a populated ``user_id``."""
    now = datetime.now(UTC)
    return ResolvedConnection(
        id=f"premium:{_PROVIDER_ID}",
        user_id=_USER_ID,
        adapter_type="nano_gpt_http",
        display_name="Nano-GPT (Premium)",
        slug="nano-gpt-premium",
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
async def test_refresher_premium_cache_readable_via_premium_extras(
    redis_client, monkeypatch,
):
    """The pair map the refresher writes under the user-scoped premium key
    is readable back via ``get_premium_adapter_extras`` — and NOT under the
    connection-scoped key the premium ``id`` would point at."""
    from backend.modules.llm._metadata import get_connection_adapter_extras

    _patch_http_models(monkeypatch)
    c = _premium_conn()

    await _refresh_premium_into_cache(
        c, NanoGptHttpAdapter, redis_client, _USER_ID, _PROVIDER_ID,
    )

    extras = await get_premium_adapter_extras(
        redis_client, _USER_ID, _PROVIDER_ID,
    )
    pair_map = extras.get("nano_gpt_pair_map")
    assert pair_map, "pair map must live in the user-scoped premium envelope"
    for pair in pair_map.values():
        assert pair["switching_mode"] in {"slug", "flag", "none"}

    # The wrong (connection-scoped) read must be empty: that key was never
    # written on the premium path. This is exactly the bug this fix guards.
    wrong = await get_connection_adapter_extras(redis_client, c.id)
    assert wrong == {}, (
        "connection-scoped key must be empty for a premium-resolved nano-gpt "
        "connection — proving the premium branch is required"
    )


@pytest.mark.asyncio
async def test_get_premium_adapter_extras_missing_returns_empty(redis_client):
    assert await get_premium_adapter_extras(
        redis_client, "no-user", "no-provider",
    ) == {}


@pytest.mark.asyncio
async def test_get_premium_adapter_extras_legacy_returns_empty(redis_client):
    """A legacy bare-list value in the premium key carries no extras."""
    await redis_client.set(
        _premium_cache_key(_USER_ID, _PROVIDER_ID),
        json.dumps([]),
    )
    assert await get_premium_adapter_extras(
        redis_client, _USER_ID, _PROVIDER_ID,
    ) == {}


@pytest.mark.asyncio
async def test_premium_stream_completion_resolves_known_model(
    redis_client, monkeypatch,
):
    """A premium-resolved connection drives ``stream_completion`` to resolve
    a known model from the user-scoped premium cache — no model_not_found."""
    _patch_http_models(monkeypatch)
    c = _premium_conn()

    # Populate the premium cache the way the refresher does.
    await _refresh_premium_into_cache(
        c, NanoGptHttpAdapter, redis_client, _USER_ID, _PROVIDER_ID,
    )

    extras = await get_premium_adapter_extras(
        redis_client, _USER_ID, _PROVIDER_ID,
    )
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
    assert not any(
        isinstance(e, StreamError) and e.error_code == "model_not_found"
        for e in events
    ), "known model must resolve from the user-scoped premium pair map"


@pytest.mark.asyncio
async def test_premium_stream_completion_empty_cache_model_not_found(
    redis_client,
):
    """With no premium cache written, the premium path still yields a clean
    model_not_found (the empty-case guard is preserved)."""
    c = _premium_conn()
    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            c, _make_request("anything/at-all"),
        )
    ]
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "model_not_found"
