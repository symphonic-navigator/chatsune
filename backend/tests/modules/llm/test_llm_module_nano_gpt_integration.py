"""Integration test for the top-level ``llm.stream_completion`` facade
against the Nano-GPT adapter.

Guards the Redis-plumbing contract: the facade must construct the
Nano-GPT adapter with a live Redis client so pair-map lookup works at
request time. Without this plumbing, dispatch fails with a
``RuntimeError`` from the adapter's own defensive check.

We monkeypatch ``get_redis`` and ``resolve_for_model`` so the test is
hermetic — no live MongoDB, no live Redis, no outbound HTTP.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis

from backend.modules.llm import stream_completion
from backend.modules.llm._adapters._events import StreamError
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart


@pytest_asyncio.fixture
async def redis_client():
    client = fake_aioredis.FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stream_completion_passes_redis_to_nano_gpt_adapter(
    monkeypatch, redis_client,
):
    """The top-level ``llm.stream_completion`` must construct the nano-gpt
    adapter with the live Redis client, otherwise pair-map lookup fails
    at request time."""
    monkeypatch.setattr(
        "backend.modules.llm.get_redis", lambda: redis_client,
    )

    now = datetime.now(UTC)
    fake_conn = ResolvedConnection(
        id="c1", user_id="u1", adapter_type="nano_gpt_http",
        display_name="d", slug="s",
        config={"base_url": "https://example", "api_key": "k"},
        created_at=now, updated_at=now,
    )

    async def _fake_resolve(*a, **k):
        return fake_conn

    monkeypatch.setattr(
        "backend.modules.llm.resolve_for_model", _fake_resolve,
    )

    # Stub out the inference tracker + event publishing to avoid needing a
    # live event bus in the unit-test environment.
    monkeypatch.setattr(
        "backend.modules.llm._tracker.register", lambda **_kw: "inf-1",
    )
    monkeypatch.setattr(
        "backend.modules.llm._tracker.unregister", lambda _id: None,
    )

    async def _noop(**_kw):
        return None

    monkeypatch.setattr(
        "backend.modules.llm._publish_inference_started", _noop,
    )
    monkeypatch.setattr(
        "backend.modules.llm._publish_inference_finished", _noop,
    )

    # Empty pair map → adapter emits model_not_found cleanly, proving Redis
    # was plumbed through without us needing to mock httpx.
    request = CompletionRequest(
        model="does/not/exist",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
    )
    events = [
        ev async for ev in stream_completion("u1", "s:does/not/exist", request)
    ]
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "model_not_found"
