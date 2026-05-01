"""Tests for the xAI HTTP adapter — identity, template, and config schema."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter


def _resolved_conn(api_key: str = "xai-test-key") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-xai-1",
        user_id="u1",
        adapter_type="xai_http",
        display_name="Chris's xAI",
        slug="chris-xai",
        config={
            "url": "https://api.x.ai/v1",
            "api_key": api_key,
            "max_parallel": 4,
        },
        created_at=now,
        updated_at=now,
    )


def test_adapter_identity():
    assert XaiHttpAdapter.adapter_type == "xai_http"
    assert XaiHttpAdapter.display_name == "xAI / Grok"
    assert XaiHttpAdapter.view_id == "xai_http"
    assert "api_key" in XaiHttpAdapter.secret_fields


def test_single_template_for_xai_cloud():
    tmpls = XaiHttpAdapter.templates()
    assert len(tmpls) == 1
    t = tmpls[0]
    assert t.id == "xai_cloud"
    assert t.config_defaults["url"] == "https://api.x.ai/v1"
    assert t.config_defaults["max_parallel"] == 4
    assert t.required_config_fields == ("api_key",)


def test_config_schema_lists_url_api_key_max_parallel():
    schema = XaiHttpAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"url", "api_key", "max_parallel"}


import pytest


@pytest.mark.asyncio
async def test_fetch_models_returns_three_grok_entries():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m for m in metas}
    assert set(by_id) == {"grok-4.1-fast", "grok-4.20", "grok-4.3"}

    fast = by_id["grok-4.1-fast"]
    assert fast.display_name == "Grok 4.1 Fast"
    assert fast.context_window == 128_000
    assert fast.remarks is None

    g420 = by_id["grok-4.20"]
    assert g420.display_name == "Grok 4.20"
    assert g420.context_window == 200_000
    assert g420.remarks is None

    g43 = by_id["grok-4.3"]
    assert g43.display_name == "Grok 4.3"
    assert g43.context_window == 200_000
    assert g43.remarks == (
        "Falls back to Grok 4.20 (non-reasoning) when thinking is off."
    )

    for m in metas:
        assert m.supports_reasoning is True
        assert m.supports_vision is True
        assert m.supports_tool_calls is True
        assert m.connection_id == "conn-xai-1"
        assert m.connection_slug == "chris-xai"


@pytest.mark.asyncio
async def test_fetch_models_billing_category_is_pay_per_token_for_all_entries():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert {m.billing_category for m in metas} == {"pay_per_token"}


from shared.dtos.inference import CompletionMessage, ContentPart, ToolCallResult
from backend.modules.llm._adapters._xai_http import _translate_message


def test_translate_text_only_user_message():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hello")],
    )
    result = _translate_message(msg)
    assert result == {"role": "user", "content": "hello"}


def test_translate_image_message_uses_openai_image_url_format():
    msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="what is this?"),
            ContentPart(type="image", data="AAA=", media_type="image/png"),
        ],
    )
    result = _translate_message(msg)
    assert result["role"] == "user"
    assert isinstance(result["content"], list)
    assert result["content"][0] == {"type": "text", "text": "what is this?"}
    img = result["content"][1]
    assert img["type"] == "image_url"
    assert img["image_url"]["url"] == "data:image/png;base64,AAA="


def test_translate_assistant_with_tool_calls():
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="looking that up")],
        tool_calls=[
            ToolCallResult(id="call_a", name="web_search",
                           arguments='{"query":"grok"}'),
        ],
    )
    result = _translate_message(msg)
    assert result["role"] == "assistant"
    assert result["content"] == "looking that up"
    assert result["tool_calls"] == [
        {
            "id": "call_a",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query":"grok"}'},
        },
    ]


def test_translate_tool_role_message():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"results":[]}')],
        tool_call_id="call_a",
    )
    result = _translate_message(msg)
    assert result == {
        "role": "tool",
        "content": '{"results":[]}',
        "tool_call_id": "call_a",
    }


from shared.dtos.inference import CompletionRequest, ToolDefinition
from backend.modules.llm._adapters._xai_http import _build_chat_payload


def _simple_request(**kwargs) -> CompletionRequest:
    base = {
        "model": "grok-4.1-fast",
        "messages": [
            CompletionMessage(role="user",
                              content=[ContentPart(type="text", text="hi")]),
        ],
        "supports_reasoning": True,
    }
    base.update(kwargs)
    return CompletionRequest(**base)


def test_build_payload_picks_non_reasoning_model_by_default():
    payload = _build_chat_payload(_simple_request(reasoning_enabled=False))
    assert payload["model"] == "grok-4-1-fast-non-reasoning"
    assert payload["stream"] is True


def test_build_payload_picks_reasoning_model_when_toggle_on():
    payload = _build_chat_payload(_simple_request(reasoning_enabled=True))
    assert payload["model"] == "grok-4-1-fast-reasoning"


def test_build_payload_grok_4_20_reasoning_uses_reasoning_slug():
    payload = _build_chat_payload(
        _simple_request(model="grok-4.20", reasoning_enabled=True)
    )
    assert payload["model"] == "grok-4.20-0309-reasoning"


def test_build_payload_grok_4_20_non_reasoning_uses_non_reasoning_slug():
    payload = _build_chat_payload(
        _simple_request(model="grok-4.20", reasoning_enabled=False)
    )
    assert payload["model"] == "grok-4.20-0309-non-reasoning"


def test_build_payload_grok_4_3_reasoning_uses_4_3_slug():
    payload = _build_chat_payload(
        _simple_request(model="grok-4.3", reasoning_enabled=True)
    )
    assert payload["model"] == "grok-4.3"


def test_build_payload_grok_4_3_non_reasoning_falls_back_to_4_20():
    payload = _build_chat_payload(
        _simple_request(model="grok-4.3", reasoning_enabled=False)
    )
    assert payload["model"] == "grok-4.20-0309-non-reasoning"


def test_build_payload_unknown_model_falls_back_to_4_1_fast(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        payload = _build_chat_payload(
            _simple_request(model="grok-stale-legacy", reasoning_enabled=True)
        )
    assert payload["model"] == "grok-4-1-fast-reasoning"
    assert any(
        "grok-stale-legacy" in rec.message for rec in caplog.records
    ), "expected a warning log mentioning the unknown model_id"


def test_build_payload_unknown_model_non_reasoning_also_falls_back():
    payload = _build_chat_payload(
        _simple_request(model="grok-stale-legacy", reasoning_enabled=False)
    )
    assert payload["model"] == "grok-4-1-fast-non-reasoning"


def test_build_payload_omits_temperature_when_none():
    payload = _build_chat_payload(_simple_request(temperature=None))
    assert "temperature" not in payload


def test_build_payload_includes_temperature_when_set():
    payload = _build_chat_payload(_simple_request(temperature=0.7))
    assert payload["temperature"] == 0.7


def test_build_payload_includes_stream_options_for_usage():
    # xAI only emits the terminal usage chunk when stream_options.include_usage
    # is set on the request. Without this the StreamDone event is tokenless.
    payload = _build_chat_payload(_simple_request())
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_translates_tools_to_openai_schema():
    tool = ToolDefinition(
        name="web_search",
        description="Search the web",
        parameters={"type": "object",
                    "properties": {"query": {"type": "string"}}},
    )
    payload = _build_chat_payload(_simple_request(tools=[tool]))
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        },
    ]


from backend.modules.llm._adapters._xai_http import _parse_sse_line, _SSE_DONE


def test_parse_sse_line_returns_dict_for_data_line():
    parsed = _parse_sse_line('data: {"choices":[{"delta":{"content":"hi"}}]}')
    assert parsed == {"choices": [{"delta": {"content": "hi"}}]}


def test_parse_sse_line_returns_done_sentinel_for_done_marker():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_returns_none_for_empty_line():
    assert _parse_sse_line("") is None


def test_parse_sse_line_returns_none_for_non_data_line():
    # Some SSE producers prefix with event: / id: — xAI does not, but we
    # should ignore anything that isn't a data line rather than crash.
    assert _parse_sse_line("event: foo") is None


def test_parse_sse_line_returns_none_for_malformed_json():
    # We log and skip — adapter keeps streaming.
    assert _parse_sse_line("data: {not json}") is None


from backend.modules.llm._adapters._xai_http import _ToolCallAccumulator


def test_accumulator_collects_single_call_across_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "web_search"}}])
    acc.ingest([{"index": 0, "function": {"arguments": '{"q":'}}])
    acc.ingest([{"index": 0, "function": {"arguments": '"grok"}'}}])
    calls = acc.finalised()
    assert len(calls) == 1
    assert calls[0]["id"] == "call_1"
    assert calls[0]["name"] == "web_search"
    assert calls[0]["arguments"] == '{"q":"grok"}'


def test_accumulator_handles_multiple_parallel_calls():
    acc = _ToolCallAccumulator()
    acc.ingest([
        {"index": 0, "id": "call_a", "type": "function",
         "function": {"name": "search", "arguments": "{}"}},
        {"index": 1, "id": "call_b", "type": "function",
         "function": {"name": "fetch", "arguments": "{}"}},
    ])
    calls = acc.finalised()
    assert {c["id"] for c in calls} == {"call_a", "call_b"}


def test_accumulator_synthesises_id_when_upstream_omits_it():
    # Some providers stream only the name on the first fragment. We fall
    # back to a synthetic ID so downstream tool dispatch never sees "".
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "function": {"name": "calc"}}])
    acc.ingest([{"index": 0, "function": {"arguments": "{}"}}])
    calls = acc.finalised()
    assert len(calls) == 1
    assert calls[0]["id"]
    assert calls[0]["name"] == "calc"
    assert calls[0]["arguments"] == "{}"


import httpx

from backend.modules.llm._adapters._events import (
    ContentDelta, StreamDone, StreamError, ThinkingDelta, ToolCallEvent,
)


def _sse_response(lines: list[str], status: int = 200) -> httpx.Response:
    body = "\n".join(lines) + "\n"
    return httpx.Response(
        status,
        headers={"content-type": "text/event-stream"},
        content=body.encode(),
    )


def _install_mock_transport(monkeypatch, handler):
    """Patch httpx.AsyncClient to use a MockTransport with `handler`."""
    from backend.modules.llm._adapters import _xai_http

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_xai_http.httpx, "AsyncClient", _PatchedClient)


async def _collect(agen):
    return [e async for e in agen]


@pytest.mark.asyncio
async def test_stream_completion_yields_content_and_done(monkeypatch):
    def handler(request):
        assert request.headers["authorization"] == "Bearer xai-test-key"
        assert "x-grok-conv-id" not in request.headers  # no cache_hint
        return _sse_response([
            'data: {"choices":[{"delta":{"content":"he"}}]}',
            'data: {"choices":[{"delta":{"content":"llo"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
        supports_reasoning=True,
        reasoning_enabled=False,
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    deltas = [e for e in events if isinstance(e, ContentDelta)]
    assert [d.delta for d in deltas] == ["he", "llo"]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(dones) == 1
    assert dones[0].input_tokens == 5
    assert dones[0].output_tokens == 2


@pytest.mark.asyncio
async def test_stream_completion_forwards_cache_hint_header(monkeypatch):
    import json as _json
    seen_headers = {}
    seen_body: dict = {}

    def handler(request):
        seen_headers.update(dict(request.headers))
        seen_body.update(_json.loads(request.content))
        return _sse_response([
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
        cache_hint="session-abc-123",
    )
    await _collect(adapter.stream_completion(_resolved_conn(), req))
    assert seen_headers.get("x-grok-conv-id") == "session-abc-123"
    assert seen_body["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_completion_emits_thinking_delta_for_reasoning_content(monkeypatch):
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"reasoning_content":"hmm"}}]}',
            'data: {"choices":[{"delta":{"content":"42"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
        supports_reasoning=True,
        reasoning_enabled=True,
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
    content = [e for e in events if isinstance(e, ContentDelta)]
    assert [t.delta for t in thinking] == ["hmm"]
    assert [c.delta for c in content] == ["42"]


@pytest.mark.asyncio
async def test_stream_completion_accumulates_tool_call_fragments(monkeypatch):
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"tool_calls":'
            '[{"index":0,"id":"call_1","type":"function",'
            '"function":{"name":"web_search"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":'
            '[{"index":0,"function":{"arguments":"{\\"q\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":'
            '[{"index":0,"function":{"arguments":"\\"grok\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "web_search"
    assert tool_calls[0].arguments == '{"q":"grok"}'
    assert tool_calls[0].id == "call_1"
    # Terminal event after tool calls
    assert any(isinstance(e, StreamDone) for e in events)


@pytest.mark.asyncio
async def test_stream_completion_emits_safety_net_done_without_usage(monkeypatch):
    # If the upstream ends on [DONE] without a usage chunk, the outer
    # safety net in stream_completion emits a tokenless StreamDone so
    # downstream consumers always see a terminal event.
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(dones) == 1
    assert dones[0].input_tokens is None
    assert dones[0].output_tokens is None


@pytest.mark.asyncio
async def test_stream_completion_returns_invalid_api_key_on_401(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorised"})

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "invalid_api_key"


@pytest.mark.asyncio
async def test_stream_completion_returns_provider_unavailable_on_500(monkeypatch):
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "provider_unavailable"


@pytest.mark.asyncio
async def test_stream_completion_emits_refusal_on_content_filter(monkeypatch):
    # xAI signals a content-policy block via finish_reason="content_filter".
    # We must emit StreamRefused (not StreamDone) and stop the stream cleanly.
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"content":"I cannot"}}]}',
            'data: {"choices":[{"delta":{"refusal":"policy"},'
            '"finish_reason":"content_filter"}]}',
            'data: [DONE]',
        ])

    from backend.modules.llm._adapters._events import StreamRefused

    _install_mock_transport(monkeypatch, handler)
    adapter = XaiHttpAdapter()
    req = CompletionRequest(
        model="grok-4.1-fast",
        messages=[CompletionMessage(role="user",
                                     content=[ContentPart(type="text", text="hi")])],
    )
    events = await _collect(adapter.stream_completion(_resolved_conn(), req))
    refusals = [e for e in events if isinstance(e, StreamRefused)]
    assert len(refusals) == 1
    assert refusals[0].reason == "content_filter"
    assert refusals[0].refusal_text == "policy"
    # No StreamDone should follow the refusal — the stream terminates on it.
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert dones == []


# ---------------------------------------------------------------------------
# Sub-router POST /test
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_xai_router(monkeypatch, handler) -> TestClient:
    from backend.modules.llm._adapters import _xai_http
    from backend.modules.llm._resolver import resolve_connection_for_user

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_xai_http.httpx, "AsyncClient", _PatchedClient)

    router = XaiHttpAdapter.router()
    app = FastAPI()
    app.include_router(router, prefix="/adapter")
    app.dependency_overrides[resolve_connection_for_user] = lambda: _resolved_conn()

    from backend.modules.llm._connections import ConnectionRepository
    from backend.ws.event_bus import get_event_bus

    class _FakeRepo:
        async def update_test_status(self, *a, **kw):
            return None

    class _FakeBus:
        async def publish(self, *a, **kw):
            return None

    monkeypatch.setattr(_xai_http, "_xai_repo_factory", lambda: _FakeRepo(),
                        raising=False)
    app.dependency_overrides[get_event_bus] = lambda: _FakeBus()
    return TestClient(app)


def test_post_test_valid_key_returns_true(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer xai-test-key"
        return httpx.Response(200, json={"data": [{"id": "grok-4.1-fast"}]})

    client = _app_with_xai_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["error"] is None


def test_post_test_invalid_key_returns_false(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorised"})

    client = _app_with_xai_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "key" in body["error"].lower() or "401" in body["error"]


# ---------------------------------------------------------------------------
# Image generation — capability flag, group listing, and generate_images
# ---------------------------------------------------------------------------

from shared.dtos.images import (
    GeneratedImageResult,
    ModeratedRejection,
    XaiImagineConfig,
)


def test_xai_supports_image_generation_flag():
    assert XaiHttpAdapter.supports_image_generation is True


@pytest.mark.asyncio
async def test_xai_image_groups_returns_xai_imagine():
    adapter = XaiHttpAdapter()
    groups = await adapter.image_groups(_resolved_conn())
    assert groups == ["xai_imagine"]


@pytest.mark.asyncio
async def test_xai_generate_images_unknown_group_raises():
    adapter = XaiHttpAdapter()
    with pytest.raises(ValueError, match="unknown image group"):
        await adapter.generate_images(
            connection=_resolved_conn(),
            group_id="not_a_group",
            config=XaiImagineConfig(),
            prompt="x",
        )


@pytest.mark.asyncio
async def test_xai_generate_images_wrong_config_type_raises():
    """generate_images must reject configs from other groups (defence
    against the discriminated union being bypassed somewhere upstream).
    """
    adapter = XaiHttpAdapter()
    with pytest.raises(ValueError, match="expected XaiImagineConfig"):
        await adapter.generate_images(
            connection=_resolved_conn(),
            group_id="xai_imagine",
            config={"group_id": "xai_imagine"},  # raw dict, not parsed
            prompt="x",
        )


@pytest.mark.asyncio
async def test_xai_generate_images_success_and_moderation_mix(monkeypatch):
    """Mock the HTTP layer to return one success + one moderated item."""
    # Build a tiny real PNG so probe_dimensions returns something.
    import io as _io
    from PIL import Image as _Image
    _png = _io.BytesIO()
    _Image.new("RGB", (64, 32), (1, 2, 3)).save(_png, format="PNG")
    fake_image_bytes = _png.getvalue()

    fake_response = {
        "data": [
            {"url": "https://example/img1.png", "mime_type": "image/png"},
            {"respect_moderation": False, "reason": "filter_a"},
        ],
        "usage": {"cost_in_usd_ticks": 100000000},
    }

    class _FakeResp:
        def __init__(self, status_code=200, json_data=None, content=None, headers=None):
            self.status_code = status_code
            self._json = json_data
            self.content = content
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

        async def post(self, *a, **kw):
            return _FakeResp(json_data=fake_response)

        async def get(self, *a, **kw):
            return _FakeResp(
                content=fake_image_bytes,
                headers={"content-type": "image/png"},
            )

    monkeypatch.setattr(
        "backend.modules.llm._adapters._xai_http.httpx.AsyncClient",
        _FakeClient,
    )

    adapter = XaiHttpAdapter()
    items = await adapter.generate_images(
        connection=_resolved_conn(),
        group_id="xai_imagine",
        config=XaiImagineConfig(n=2),
        prompt="a tiny image",
    )

    assert len(items) == 2
    assert isinstance(items[0], GeneratedImageResult)
    assert items[0].width == 64
    assert items[0].height == 32
    assert items[0].model_id == "grok-imagine-image"
    assert isinstance(items[1], ModeratedRejection)
    assert items[1].reason == "filter_a"

    # Buffer should have been populated for the success item.
    from backend.modules.llm._adapters._xai_http import drain_image_buffer
    bufs = drain_image_buffer(items[0].id)
    assert bufs is not None
    bytes_, ct = bufs
    assert bytes_ == fake_image_bytes
    assert ct == "image/png"
    # Second drain returns None (buffer entry has been consumed).
    assert drain_image_buffer(items[0].id) is None


# ---------------------------------------------------------------------------
# Sub-router POST /imagine/test
# ---------------------------------------------------------------------------

def _app_with_imagine_test_router(monkeypatch, fake_client_cls) -> TestClient:
    """Build a minimal FastAPI app mounting the xAI sub-router with the
    httpx.AsyncClient replaced by *fake_client_cls* and dependency overrides
    so no real DB or event bus is needed.
    """
    from backend.modules.llm._adapters import _xai_http
    from backend.modules.llm._resolver import resolve_connection_for_user
    from backend.ws.event_bus import get_event_bus

    monkeypatch.setattr(
        "backend.modules.llm._adapters._xai_http.httpx.AsyncClient",
        fake_client_cls,
    )

    router = XaiHttpAdapter.router()
    app = FastAPI()
    app.include_router(router, prefix="/adapter")
    app.dependency_overrides[resolve_connection_for_user] = lambda: _resolved_conn()

    class _FakeBus:
        async def publish(self, *a, **kw):
            return None

    app.dependency_overrides[get_event_bus] = lambda: _FakeBus()
    monkeypatch.setattr(_xai_http, "_xai_repo_factory",
                        lambda: object(), raising=False)
    return TestClient(app)


def test_imagine_test_endpoint_invalid_config_returns_422(monkeypatch):
    """Submitting a config that fails Pydantic validation should return 422."""
    # n=99 exceeds XaiImagineConfig's Field(ge=1, le=10) constraint.
    class _UnusedClient:
        pass

    client = _app_with_imagine_test_router(monkeypatch, _UnusedClient)
    resp = client.post(
        "/adapter/imagine/test",
        json={"group_id": "xai_imagine", "config": {"n": 99}},
    )
    assert resp.status_code == 422
    assert "invalid config" in resp.json()["detail"].lower()


def test_imagine_test_endpoint_returns_items_and_drains_buffers(monkeypatch):
    """Successful generation returns items; buffers are drained (no bytes
    remain in _LAST_BATCH_BUFFERS after the endpoint response)."""
    import io as _io
    from PIL import Image as _Image

    _png = _io.BytesIO()
    _Image.new("RGB", (32, 32), (10, 20, 30)).save(_png, format="PNG")
    fake_image_bytes = _png.getvalue()

    fake_gen_response = {
        "data": [{"url": "https://example.test/img.png", "mime_type": "image/png"}],
        "usage": {"cost_in_usd_ticks": 0},
    }

    class _FakeResp:
        def __init__(self, status_code=200, json_data=None, content=None, headers=None):
            self.status_code = status_code
            self._json = json_data
            self.content = content or b""
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

        async def post(self, *a, **kw):
            return _FakeResp(json_data=fake_gen_response)

        async def get(self, *a, **kw):
            return _FakeResp(
                content=fake_image_bytes,
                headers={"content-type": "image/png"},
            )

    client = _app_with_imagine_test_router(monkeypatch, _FakeClient)
    resp = client.post(
        "/adapter/imagine/test",
        json={
            "group_id": "xai_imagine",
            "config": {"tier": "normal", "n": 1},
            "prompt": "a test mountain",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["kind"] == "image"
    assert item["width"] == 32
    assert item["height"] == 32

    # Buffer must have been drained — no bytes left behind.
    from backend.modules.llm._adapters._xai_http import drain_image_buffer
    assert drain_image_buffer(item["id"]) is None


@pytest.mark.asyncio
async def test_xai_generate_images_pro_tier_uses_pro_model(monkeypatch):
    captured_body: dict = {}

    class _FakeResp:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [], "usage": {}}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers, json):
            captured_body.update(json)
            return _FakeResp()

    monkeypatch.setattr(
        "backend.modules.llm._adapters._xai_http.httpx.AsyncClient",
        _FakeClient,
    )

    adapter = XaiHttpAdapter()
    await adapter.generate_images(
        connection=_resolved_conn(),
        group_id="xai_imagine",
        config=XaiImagineConfig(tier="pro", resolution="2k", aspect="16:9", n=1),
        prompt="x",
    )

    assert captured_body["model"] == "grok-imagine-image-pro"
    assert captured_body["resolution"] == "2k"
    assert captured_body["aspect_ratio"] == "16:9"
    assert captured_body["n"] == 1
