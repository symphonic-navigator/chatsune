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
async def test_fetch_models_returns_one_grok_4_1_fast():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert len(metas) == 1
    m = metas[0]
    assert m.model_id == "grok-4.1-fast"
    assert m.display_name == "Grok 4.1 Fast"
    assert m.context_window == 200_000
    assert m.supports_reasoning is True
    assert m.supports_vision is True
    assert m.supports_tool_calls is True
    assert m.connection_id == "conn-xai-1"
    assert m.connection_slug == "chris-xai"


@pytest.mark.asyncio
async def test_fetch_models_labels_billing_category_as_pay_per_token():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert metas, "expected at least one model"
    for m in metas:
        assert m.billing_category == "pay_per_token"


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
