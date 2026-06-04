"""Tests for the Nano-GPT HTTP adapter — identity, templates,
config schema, the wired ``fetch_models`` pipeline, and the SSE
streaming loop of ``stream_completion``.
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
    *, base_url: str = "https://nano-gpt.com/api/v1",
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
    assert tpl.config_defaults["base_url"] == "https://nano-gpt.com/api/v1"
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

    # The pair map is exposed via ``cache_extras`` so it can be persisted
    # inside the connection model-cache envelope (one key, one 7-day TTL)
    # rather than a separate short-lived Redis key.
    pair_map = adapter.cache_extras()["nano_gpt_pair_map"]

    assert pair_map, "mini_dump contains pairs; the pair_map must be non-empty"
    # Sanity-check the shape of one entry
    for model_id, pair in pair_map.items():
        assert "non_thinking_slug" in pair
        assert "thinking_slug" in pair
        assert pair["switching_mode"] in {"slug", "flag", "none"}
    assert any(
        p["switching_mode"] == "slug" for p in pair_map.values()
    ), "mini_dump should produce at least one slug-switched pair"
    assert any(
        p["switching_mode"] == "flag" for p in pair_map.values()
    ), "mini_dump should produce at least one switchable singleton (gpt-5)"


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
    assert calls == [{"id": "c_1", "name": "sum", "arguments": '{"a":1,"b":2}', "index": 0}]


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


def test_chunk_to_events_thinking_delta_from_reasoning_field():
    """Default nano-gpt endpoint streams reasoning in delta.reasoning."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning": "thinking…"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking…")]


def test_chunk_to_events_reasoning_takes_precedence_over_reasoning_content():
    """If a single delta somehow carries both (never expected in practice),
    ``reasoning`` wins so the modern field name is authoritative."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {
            "reasoning": "modern",
            "reasoning_content": "legacy",
        }}]}, acc,
    )
    assert events == [ThinkingDelta(delta="modern")]


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
    assert events == [ToolCallEvent(id="c1", name="f", arguments='{"x":1}', index=0)]


def test_chunk_to_events_refusal():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events({"choices": [{
        "delta": {"refusal": "blocked"},
        "finish_reason": "content_filter",
    }]}, acc)
    assert events == [StreamRefused(reason="content_filter", refusal_text="blocked")]


# ---------------------------------------------------------------------------
# _resolve_call unit tests — three switching modes
# ---------------------------------------------------------------------------

from backend.modules.llm._adapters._nano_gpt_http import _resolve_call


def test_resolve_call_slug_mode_off_returns_non_thinking():
    pair = {
        "non_thinking_slug": "m1",
        "thinking_slug": "m1:thinking",
        "switching_mode": "slug",
    }
    out = _resolve_call(pair, "m1", reasoning_enabled=False)
    assert out == {"slug": "m1", "send_reasoning_flag": False}


def test_resolve_call_slug_mode_on_returns_thinking():
    pair = {
        "non_thinking_slug": "m1",
        "thinking_slug": "m1:thinking",
        "switching_mode": "slug",
    }
    out = _resolve_call(pair, "m1", reasoning_enabled=True)
    assert out == {"slug": "m1:thinking", "send_reasoning_flag": False}


def test_build_upstream_call_pair_switches_via_slug():
    """Slug-mode happy path, both directions."""
    pair = {
        "non_thinking_slug": "z-ai/glm-4.6",
        "thinking_slug": "z-ai/glm-4.6:thinking",
        "switching_mode": "slug",
    }
    non = _resolve_call(pair, "z-ai/glm-4.6", reasoning_enabled=False)
    yes = _resolve_call(pair, "z-ai/glm-4.6", reasoning_enabled=True)
    assert non == {"slug": "z-ai/glm-4.6", "send_reasoning_flag": False}
    assert yes == {"slug": "z-ai/glm-4.6:thinking", "send_reasoning_flag": False}


def test_build_upstream_call_switchable_singleton_uses_flag():
    """Flag-mode happy path: slug stays the same, the flag is always
    sent (the body carries ``reasoning_enabled`` in both directions —
    vendors disagree on the default direction)."""
    pair = {
        "non_thinking_slug": "openai/gpt-5",
        "thinking_slug": "openai/gpt-5",
        "switching_mode": "flag",
    }
    non = _resolve_call(pair, "openai/gpt-5", reasoning_enabled=False)
    yes = _resolve_call(pair, "openai/gpt-5", reasoning_enabled=True)
    assert non == {"slug": "openai/gpt-5", "send_reasoning_flag": True}
    assert yes == {"slug": "openai/gpt-5", "send_reasoning_flag": True}


def test_build_upstream_call_plain_singleton_never_sends_flag():
    """None-mode: send_reasoning_flag stays False regardless of the toggle."""
    pair = {
        "non_thinking_slug": "vendor/plain-chat-model",
        "thinking_slug": None,
        "switching_mode": "none",
    }
    non = _resolve_call(pair, "vendor/plain-chat-model", reasoning_enabled=False)
    yes = _resolve_call(pair, "vendor/plain-chat-model", reasoning_enabled=True)
    assert non == {"slug": "vendor/plain-chat-model", "send_reasoning_flag": False}
    assert yes == {"slug": "vendor/plain-chat-model", "send_reasoning_flag": False}


def test_resolve_call_unknown_model_returns_passthrough():
    out = _resolve_call(None, "vendor/unknown", reasoning_enabled=True)
    assert out == {"slug": "vendor/unknown", "send_reasoning_flag": False}


# ---------------------------------------------------------------------------
# stream_completion end-to-end SSE tests
# ---------------------------------------------------------------------------

from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _make_request(model_id: str, *, reasoning_enabled: bool = False) -> CompletionRequest:
    """Build a CompletionRequest under the new capability-based contract.

    The legacy ``reasoning_enabled`` boolean kwarg is preserved on this
    helper to keep existing test sites concise; it is translated into
    ``extras.reasoning_mode`` and ``reasoning.kind=optional`` so the
    adapter sees a model whose user toggled reasoning on/off.
    """
    return CompletionRequest(
        model=model_id,
        messages=[CompletionMessage(
            role="user",
            content=[ContentPart(type="text", text="hi")],
        )],
        reasoning=ReasoningCapability(kind="optional"),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=False,
            reasoning_mode="on" if reasoning_enabled else "off",
            reasoning_effort=None,
        ),
    )


class _FakeResponse:
    """Minimal httpx.Response lookalike for client.stream(...) context."""
    def __init__(self, status_code: int, lines: list[str], body: bytes = b""):
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
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.posted_url: str | None = None
        self.posted_payload: dict | None = None
        self.posted_headers: dict | None = None

    def stream(self, method, url, *, json=None, headers=None):
        self.posted_url = url
        self.posted_payload = json
        self.posted_headers = headers
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def _populate_pair_map(redis_client, conn_id: str):
    """Write the pair map into the connection model-cache envelope, the
    same way the refresher does. ``stream_completion`` reads it back from
    there via ``get_connection_adapter_extras``."""
    from backend.modules.llm._metadata import _cache_key, _encode_cache

    pair_map = {
        "anthropic/claude-opus-4.6": {
            "non_thinking_slug": "anthropic/claude-opus-4.6",
            "thinking_slug": "anthropic/claude-opus-4.6:thinking",
            "switching_mode": "slug",
        },
        "free/phi-small": {
            "non_thinking_slug": "free/phi-small",
            "thinking_slug": None,
            "switching_mode": "none",
        },
        "openai/gpt-5": {
            "non_thinking_slug": "openai/gpt-5",
            "thinking_slug": "openai/gpt-5",
            "switching_mode": "flag",
        },
    }
    await redis_client.set(
        _cache_key(conn_id),
        _encode_cache([], {"nano_gpt_pair_map": pair_map}),
    )


@pytest.mark.asyncio
async def test_stream_completion_happy_path_non_thinking(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"content":"hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        'data: [DONE]',
    ]
    fake = _FakeClient(_FakeResponse(200, sse_lines))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = []
    async for ev in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6"),
    ):
        events.append(ev)

    from backend.modules.llm._adapters._events import ContentDelta, StreamDone
    assert [type(e) for e in events] == [ContentDelta, ContentDelta, StreamDone]
    assert events[0].delta == "hel"
    assert events[1].delta == "lo"
    assert events[2].input_tokens == 3
    assert events[2].output_tokens == 2

    # Upstream slug used is the non-thinking variant; Authorization header set.
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6"
    assert "reasoning" not in fake.posted_payload
    assert "reasoning_effort" not in fake.posted_payload
    assert "thinking" not in fake.posted_payload
    assert fake.posted_headers["Authorization"] == "Bearer nano-test-key"
    assert fake.posted_url.endswith("/chat/completions")


@pytest.mark.asyncio
async def test_stream_completion_thinking_picks_thinking_slug(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"…"}}]}',
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
    events = []
    async for ev in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6", reasoning_enabled=True),
    ):
        events.append(ev)

    from backend.modules.llm._adapters._events import ThinkingDelta
    assert any(isinstance(e, ThinkingDelta) for e in events)
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6:thinking"


@pytest.mark.asyncio
async def test_stream_completion_unknown_model_emits_model_not_found(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            conn, _make_request("not/in/map"),
        )
    ]
    assert len(events) == 1
    from backend.modules.llm._adapters._events import StreamError
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "model_not_found"


@pytest.mark.asyncio
async def test_stream_completion_401_emits_invalid_api_key(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    fake = _FakeClient(_FakeResponse(401, [], body=b"unauthorized"))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            conn, _make_request("anthropic/claude-opus-4.6"),
        )
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert len(events) == 1
    assert events[0].error_code == "invalid_api_key"


@pytest.mark.asyncio
async def test_stream_completion_500_emits_provider_unavailable(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    fake = _FakeClient(_FakeResponse(500, [], body=b"boom"))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            conn, _make_request("anthropic/claude-opus-4.6"),
        )
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert len(events) == 1
    assert events[0].error_code == "provider_unavailable"
    assert "500" in events[0].message


@pytest.mark.asyncio
async def test_stream_completion_requires_redis():
    adapter = NanoGptHttpAdapter()  # no redis
    conn = _resolved_conn()
    agen = adapter.stream_completion(conn, _make_request("m1"))
    with pytest.raises(RuntimeError, match="Redis"):
        async for _ in agen:
            pass


# ---------------------------------------------------------------------------
# _build_chat_payload unit tests — reasoning-flag gate
# ---------------------------------------------------------------------------

from backend.modules.llm._adapters._nano_gpt_http import _build_chat_payload


def _basic_request(model: str = "m1") -> CompletionRequest:
    return CompletionRequest(
        model=model,
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


def test_build_chat_payload_flag_mode_on_writes_reasoning_enabled_true():
    req = _basic_request()
    payload = _build_chat_payload(
        req, upstream_slug="openai/gpt-5",
        send_reasoning_flag=True, reasoning_enabled=True,
    )
    assert payload["reasoning"] == {"enabled": True}
    assert payload["model"] == "openai/gpt-5"


def test_build_chat_payload_flag_mode_off_still_writes_reasoning_enabled_false():
    """Flag-mode invariant: even with reasoning_enabled=False, the field
    must be on the wire (vendors disagree on the default direction)."""
    req = _basic_request()
    payload = _build_chat_payload(
        req, upstream_slug="openai/gpt-5",
        send_reasoning_flag=True, reasoning_enabled=False,
    )
    assert payload["reasoning"] == {"enabled": False}


def test_build_chat_payload_slug_mode_omits_reasoning_field():
    """Slug-mode: send_reasoning_flag=False and the body must not carry
    any reasoning-related field. Empirically, sending one inverts the
    user's intent (mimo-v2-flash-thinking case)."""
    req = _basic_request()
    payload = _build_chat_payload(
        req, upstream_slug="m1",
        send_reasoning_flag=False, reasoning_enabled=False,
    )
    forbidden = {"reasoning", "reasoning_effort", "reasoning_content", "thinking"}
    assert not (forbidden & set(payload.keys())), (
        f"Slug-mode leaked reasoning keys: {forbidden & set(payload.keys())}"
    )
    assert payload["model"] == "m1"


def test_build_chat_payload_none_mode_omits_reasoning_even_if_user_toggled_on():
    """None-mode (capability-gated fallback): user toggled reasoning ON
    in the UI but the model is a plain singleton. send_reasoning_flag is
    False so we still must not send the field."""
    req = _basic_request()
    payload = _build_chat_payload(
        req, upstream_slug="vendor/plain",
        send_reasoning_flag=False, reasoning_enabled=True,
    )
    forbidden = {"reasoning", "reasoning_effort", "reasoning_content", "thinking"}
    assert not (forbidden & set(payload.keys()))


# ---------------------------------------------------------------------------
# stream_completion — reasoning-flag gate end-to-end tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_completion_slug_mode_off_omits_reasoning(
    redis_client, monkeypatch,
):
    """Slug-mode dispatch (reasoning off): body must not carry the flag."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

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
    async for _ in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6", reasoning_enabled=False),
    ):
        pass

    assert "reasoning" not in fake.posted_payload
    assert "reasoning_effort" not in fake.posted_payload
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6"


@pytest.mark.asyncio
async def test_stream_completion_slug_mode_on_picks_thinking_slug_no_flag(
    redis_client, monkeypatch,
):
    """Slug-mode dispatch (reasoning on): thinking_slug is used and the
    body must NOT carry the reasoning flag — the slug already selects."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"reasoning":"…"}}]}',
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
    async for _ in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6", reasoning_enabled=True),
    ):
        pass

    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6:thinking"
    assert "reasoning" not in fake.posted_payload
    assert "reasoning_effort" not in fake.posted_payload


@pytest.mark.asyncio
async def test_stream_completion_flag_mode_on_sends_enabled_true(
    redis_client, monkeypatch,
):
    """Flag-mode dispatch: same slug, body carries
    ``{"reasoning": {"enabled": true}}``."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"reasoning":"…"}}]}',
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
    async for _ in adapter.stream_completion(
        conn, _make_request("openai/gpt-5", reasoning_enabled=True),
    ):
        pass

    assert fake.posted_payload["model"] == "openai/gpt-5"
    assert fake.posted_payload["reasoning"] == {"enabled": True}


@pytest.mark.asyncio
async def test_stream_completion_flag_mode_off_still_sends_enabled_false(
    redis_client, monkeypatch,
):
    """Flag-mode invariant: reasoning_enabled=False MUST still send the
    flag with ``enabled: false`` (vendors disagree on default direction)."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

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
    async for _ in adapter.stream_completion(
        conn, _make_request("openai/gpt-5", reasoning_enabled=False),
    ):
        pass

    assert fake.posted_payload["model"] == "openai/gpt-5"
    assert fake.posted_payload["reasoning"] == {"enabled": False}


@pytest.mark.asyncio
async def test_stream_completion_none_mode_with_reasoning_on_omits_flag(
    redis_client, monkeypatch,
):
    """Plain singleton with no thinking option: even if the UI toggles
    reasoning ON, the body must NOT carry the flag (capability-gated
    fallback). Slug stays the same."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)  # has free/phi-small (none-mode)

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
    async for _ in adapter.stream_completion(
        conn, _make_request("free/phi-small", reasoning_enabled=True),
    ):
        pass

    assert "reasoning" not in fake.posted_payload
    assert "reasoning_effort" not in fake.posted_payload
    assert fake.posted_payload["model"] == "free/phi-small"


def test_streaming_tool_call_emits_args_deltas_nano_gpt():
    """Streaming a tool call should emit one ToolCallArgsDelta per
    fragment, followed by exactly one finalised ToolCallEvent."""
    from backend.modules.llm._adapters._nano_gpt_http import (
        _ToolCallAccumulator, _chunk_to_events,
    )
    from backend.modules.llm._adapters._events import (
        ToolCallArgsDelta, ToolCallEvent,
    )
    acc = _ToolCallAccumulator()
    chunk1 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_x",
         "function": {"name": "search", "arguments": '{"q'}},
    ]}, "finish_reason": None}]}
    chunk2 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]}, "finish_reason": None}]}
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    events: list = []
    events.extend(_chunk_to_events(chunk1, acc))
    events.extend(_chunk_to_events(chunk2, acc))
    events.extend(_chunk_to_events(chunk3, acc))
    deltas = [e for e in events if isinstance(e, ToolCallArgsDelta)]
    finals = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(deltas) == 2
    assert deltas[0].arguments_delta == '{"q'
    assert deltas[1].arguments_delta == '":"x"}'
    assert len(finals) == 1
    assert finals[0].arguments == '{"q":"x"}'
    assert finals[0].index == 0


# ---------------------------------------------------------------------------
# Image generation tests
# ---------------------------------------------------------------------------

import io

from PIL import Image as _PILImage

from backend.modules.llm._adapters._nano_gpt_image_groups import (
    SEEDREAM_GROUP_ID,
    ZIMAGE_GROUP_ID,
)
from shared.dtos.images import (
    GeneratedImageResult,
    SeedreamConfig,
    ZImageConfig,
)


def _resolved_nano_conn() -> ResolvedConnection:
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn_nano",
        user_id="u1",
        slug="nano",
        display_name="nano-gpt",
        adapter_type="nano_gpt_http",
        config={"base_url": "https://nano-gpt.com/api/v1", "api_key": "sk-test"},
        created_at=now,
        updated_at=now,
    )


def _fake_image_bytes() -> bytes:
    buf = io.BytesIO()
    _PILImage.new("RGB", (64, 32), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_nano_gpt_supports_image_generation_flag():
    assert NanoGptHttpAdapter.supports_image_generation is True


@pytest.mark.asyncio
async def test_nano_gpt_image_groups_returns_both_groups():
    adapter = NanoGptHttpAdapter()
    groups = await adapter.image_groups(_resolved_nano_conn())
    assert set(groups) == {ZIMAGE_GROUP_ID, SEEDREAM_GROUP_ID}


@pytest.mark.asyncio
async def test_nano_gpt_generate_images_zimage_attaches_bytes(monkeypatch):
    fake_bytes = _fake_image_bytes()
    fake_resp_json = {
        "created": 1,
        "requestId": "req_abc",
        "data": [{"storageKey": "k", "url": "https://r2.example/img.jpg"}],
        "cost": 0.017,
    }

    class _Resp:
        def __init__(self, status=200, content=b"", json_data=None, headers=None):
            self.status_code = status
            self.content = content
            self._json = json_data
            self.headers = headers or {}
            self.text = ""

        def json(self):
            return self._json

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, *a, **kw):
            assert url.endswith("/images/generations")
            return _Resp(json_data=fake_resp_json)

        async def get(self, url, *a, **kw):
            # Must NOT carry the Authorization header.
            headers = kw.get("headers") or {}
            assert "Authorization" not in headers, (
                "Cloudflare R2 signed URL must be fetched without bearer auth"
            )
            return _Resp(
                content=fake_bytes,
                headers={"content-type": "image/jpeg"},
            )

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        _FakeClient,
    )

    adapter = NanoGptHttpAdapter()
    items = await adapter.generate_images(
        connection=_resolved_nano_conn(),
        group_id=ZIMAGE_GROUP_ID,
        config=ZImageConfig(model="turbo", size="1024x1024", n=1),
        prompt="a serene landscape",
    )

    assert len(items) == 1
    assert isinstance(items[0], GeneratedImageResult)
    assert items[0].data == fake_bytes
    assert items[0].content_type == "image/jpeg"
    assert items[0].model_id == "z-image-turbo"
    assert items[0].width == 64
    assert items[0].height == 32


@pytest.mark.asyncio
async def test_nano_gpt_generate_images_seedream_attaches_bytes(monkeypatch):
    fake_bytes = _fake_image_bytes()
    fake_resp_json = {
        "created": 1,
        "requestId": "req_xyz",
        "data": [{"storageKey": "k", "url": "https://r2.example/img.jpg"}],
        "cost": 0.04,
    }

    captured_body = {}

    class _Resp:
        def __init__(self, status=200, content=b"", json_data=None, headers=None):
            self.status_code = status
            self.content = content
            self._json = json_data
            self.headers = headers or {}
            self.text = ""

        def json(self):
            return self._json

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, *a, **kw):
            captured_body.update(kw.get("json") or {})
            return _Resp(json_data=fake_resp_json)

        async def get(self, url, *a, **kw):
            return _Resp(
                content=fake_bytes,
                headers={"content-type": "image/jpeg"},
            )

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        _FakeClient,
    )

    adapter = NanoGptHttpAdapter()
    items = await adapter.generate_images(
        connection=_resolved_nano_conn(),
        group_id=SEEDREAM_GROUP_ID,
        config=SeedreamConfig(aspect="16:9", quality="standard", n=1),
        prompt="a city skyline at night",
    )

    assert len(items) == 1
    assert items[0].model_id == "seedream-v4.5"
    # Seedream sends "size: WxH" derived from the resolution table.
    assert captured_body.get("size") == "2560x1440"


@pytest.mark.asyncio
async def test_nano_gpt_generate_images_unknown_group_raises():
    adapter = NanoGptHttpAdapter()
    with pytest.raises(ValueError, match="unknown image group"):
        await adapter.generate_images(
            connection=_resolved_nano_conn(),
            group_id="bogus_group",
            config=ZImageConfig(),
            prompt="x",
        )
