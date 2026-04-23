"""Tests for the Nano-GPT HTTP adapter — identity, templates,
config schema, the wired ``fetch_models`` pipeline, and the Phase-2
stub behaviour of ``stream_completion``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis

from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._types import ResolvedConnection

FIXTURES = Path(__file__).parent / "fixtures" / "nano_gpt"


def _resolved_conn(
    *, base_url: str = "https://api.nano-gpt.com/v1",
    api_key: str = "nano-test-key",
) -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-nano-1",
        user_id="u1",
        adapter_type="nano_gpt_http",
        display_name="Chris's Nano-GPT",
        slug="chris-nano",
        config={
            "base_url": base_url,
            "api_key": api_key,
            "max_parallel": 3,
        },
        created_at=now,
        updated_at=now,
    )


@pytest_asyncio.fixture
async def redis_client():
    client = fake_aioredis.FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()


def test_adapter_identity():
    assert NanoGptHttpAdapter.adapter_type == "nano_gpt_http"
    assert NanoGptHttpAdapter.display_name == "Nano-GPT"
    assert NanoGptHttpAdapter.view_id == "nano_gpt_http"
    assert NanoGptHttpAdapter.secret_fields == frozenset({"api_key"})


def test_templates_single_default():
    tpls = NanoGptHttpAdapter.templates()
    assert len(tpls) == 1
    tpl = tpls[0]
    assert tpl.id == "nano_gpt_default"
    assert tpl.display_name == "Nano-GPT"
    assert tpl.slug_prefix == "nano"
    assert tpl.config_defaults["base_url"] == "https://api.nano-gpt.com/v1"
    assert tpl.config_defaults["max_parallel"] == 3
    assert "api_key" in tpl.required_config_fields


def test_config_schema_has_expected_fields():
    schema = NanoGptHttpAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"base_url", "api_key", "max_parallel"}

    api_key_field = next(f for f in schema if f.name == "api_key")
    assert api_key_field.type == "secret"
    assert api_key_field.required is True

    base_url_field = next(f for f in schema if f.name == "base_url")
    assert base_url_field.type == "url"
    assert base_url_field.required is False

    max_parallel_field = next(f for f in schema if f.name == "max_parallel")
    assert max_parallel_field.type == "integer"
    assert max_parallel_field.min == 1
    assert max_parallel_field.max == 32


@pytest.mark.asyncio
async def test_fetch_models_without_redis_raises():
    adapter = NanoGptHttpAdapter()
    with pytest.raises(RuntimeError, match="Redis"):
        await adapter.fetch_models(_resolved_conn())


@pytest.mark.asyncio
async def test_fetch_models_returns_canonical_dtos_with_connection_fields(
    redis_client, monkeypatch,
):
    # ``mini_dump.json`` is stored in the upstream envelope shape
    # ``{"object": "list", "data": [...]}``; the real ``_http_get_models``
    # peels off ``data`` before returning. Mirror that here.
    envelope = json.loads((FIXTURES / "mini_dump.json").read_text())
    raw_data = envelope["data"]

    async def _fake_get(**kwargs):
        return raw_data

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http._http_get_models",
        _fake_get,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    conn = _resolved_conn()
    metas = await adapter.fetch_models(conn)

    assert metas, "mini_dump should yield at least one canonical model"
    for m in metas:
        assert m.connection_id == conn.id
        assert m.connection_slug == conn.slug
        assert m.connection_display_name == conn.display_name
        # billing_category is populated by the adapter from is_subscription
        assert m.billing_category in {"subscription", "pay_per_token"}


@pytest.mark.asyncio
async def test_fetch_models_persists_pair_map_in_redis(
    redis_client, monkeypatch,
):
    envelope = json.loads((FIXTURES / "mini_dump.json").read_text())
    raw_data = envelope["data"]

    async def _fake_get(**kwargs):
        return raw_data

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http._http_get_models",
        _fake_get,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    conn = _resolved_conn()
    await adapter.fetch_models(conn)

    # Load the pair map through the real helper to prove the key schema
    # and JSON encoding stay consistent with the persistence layer.
    from backend.modules.llm._adapters._nano_gpt_pair_map import load_pair_map
    pair_map = await load_pair_map(redis_client, connection_id=conn.id)

    assert pair_map, "mini_dump contains pairs; the pair_map must be non-empty"
    # Sanity-check the shape of one entry
    for model_id, pair in pair_map.items():
        assert "non_thinking_slug" in pair
        assert "thinking_slug" in pair
        # At least one model should have a thinking_slug set (mini_dump has pairs)
    assert any(p["thinking_slug"] is not None for p in pair_map.values()), \
        "mini_dump should produce at least one pair with a thinking_slug"


@pytest.mark.asyncio
async def test_stream_completion_raises_phase_2_not_implemented():
    adapter = NanoGptHttpAdapter()
    conn = _resolved_conn()
    # stream_completion yields events — to trigger the raise we must
    # start iterating. The NotImplementedError is raised on the first
    # __anext__() call.
    agen = adapter.stream_completion(conn, request=None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="Phase 2"):
        async for _ in agen:
            break


# ---------------------------------------------------------------------------
# SSE helper unit tests — ported from the xAI adapter, minus xAI-specific bits.
# ---------------------------------------------------------------------------

from shared.dtos.inference import CompletionMessage, ContentPart, ToolCallResult
from backend.modules.llm._adapters._nano_gpt_http import _translate_message


def test_translate_message_plain_text_becomes_string():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hi")],
    )
    out = _translate_message(msg)
    assert out == {"role": "user", "content": "hi"}


def test_translate_message_with_image_becomes_list_of_parts():
    msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="look at this"),
            ContentPart(type="image", data="BASE64DATA", media_type="image/png"),
        ],
    )
    out = _translate_message(msg)
    assert out["role"] == "user"
    assert out["content"] == [
        {"type": "text", "text": "look at this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BASE64DATA"}},
    ]


def test_translate_message_tool_call_round_trip():
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="")],
        tool_calls=[ToolCallResult(id="c1", name="f", arguments='{"x":1}')],
    )
    out = _translate_message(msg)
    assert out["tool_calls"] == [
        {"id": "c1", "type": "function",
         "function": {"name": "f", "arguments": '{"x":1}'}},
    ]


def test_translate_message_tool_response_carries_tool_call_id():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text="result")],
        tool_call_id="c1",
    )
    out = _translate_message(msg)
    assert out["tool_call_id"] == "c1"
    assert out["content"] == "result"


from backend.modules.llm._adapters._nano_gpt_http import _parse_sse_line, _SSE_DONE


def test_parse_sse_line_ignores_blank():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("   ") is None


def test_parse_sse_line_ignores_non_data_frames():
    assert _parse_sse_line("event: ping") is None
    assert _parse_sse_line(":keepalive") is None


def test_parse_sse_line_done_sentinel():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_valid_json():
    assert _parse_sse_line('data: {"x":1}') == {"x": 1}


def test_parse_sse_line_malformed_json_returns_none():
    assert _parse_sse_line("data: {bad json") is None


from backend.modules.llm._adapters._nano_gpt_http import (
    _ToolCallAccumulator, _chunk_to_events,
)
from backend.modules.llm._adapters._events import (
    ContentDelta, ThinkingDelta, StreamDone, StreamRefused, ToolCallEvent,
)


def test_tool_call_accumulator_merges_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "c_1", "function": {"name": "sum", "arguments": '{"a":1'}}])
    acc.ingest([{"index": 0, "function": {"arguments": ',"b":2}'}}])
    calls = acc.finalised()
    assert calls == [{"id": "c_1", "name": "sum", "arguments": '{"a":1,"b":2}'}]


def test_chunk_to_events_content_delta():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"content": "hello"}}]}, acc,
    )
    assert events == [ContentDelta(delta="hello")]


def test_chunk_to_events_thinking_delta_from_reasoning_content():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning_content": "thinking…"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking…")]


def test_chunk_to_events_usage_only_emits_stream_done_with_tokens():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 34}}, acc,
    )
    assert events == [StreamDone(input_tokens=12, output_tokens=34)]


def test_chunk_to_events_tool_call_finish():
    acc = _ToolCallAccumulator()
    # fragment chunk
    _chunk_to_events({"choices": [{"delta": {
        "tool_calls": [{"index": 0, "id": "c1",
                         "function": {"name": "f", "arguments": '{"x":1}'}}],
    }}]}, acc)
    # finish chunk
    events = _chunk_to_events({"choices": [{
        "delta": {}, "finish_reason": "tool_calls",
    }]}, acc)
    assert events == [ToolCallEvent(id="c1", name="f", arguments='{"x":1}')]


def test_chunk_to_events_refusal():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events({"choices": [{
        "delta": {"refusal": "blocked"},
        "finish_reason": "content_filter",
    }]}, acc)
    assert events == [StreamRefused(reason="content_filter", refusal_text="blocked")]
