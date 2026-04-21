"""Tests for the Mistral HTTP adapter — identity, dedup pipeline, streaming."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamError,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._mistral_http import (
    MistralHttpAdapter,
    _build_chat_payload,
    _dedup_models,
    _parse_sse_line,
    _SSE_DONE,
    _ToolCallAccumulator,
    _translate_message,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolCallResult,
    ToolDefinition,
)


def _resolved_conn(api_key: str = "mistral-test-key") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="premium:mistral",
        user_id="u1",
        adapter_type="mistral_http",
        display_name="Mistral",
        slug="mistral",
        config={
            "url": "https://api.mistral.ai/v1",
            "api_key": api_key,
        },
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_adapter_identity():
    assert MistralHttpAdapter.adapter_type == "mistral_http"
    assert MistralHttpAdapter.display_name == "Mistral"
    assert MistralHttpAdapter.view_id == "mistral_http"
    assert "api_key" in MistralHttpAdapter.secret_fields


def test_premium_adapter_has_no_templates_or_config_schema():
    # Premium-only adapter: not user-createable, so it exposes the
    # BaseAdapter defaults (empty templates + schema + None router).
    assert MistralHttpAdapter.templates() == []
    assert MistralHttpAdapter.config_schema() == []
    assert MistralHttpAdapter.router() is None


# ---------------------------------------------------------------------------
# Dedup / filter pipeline
# ---------------------------------------------------------------------------


def _cap(**kw) -> dict:
    base = {
        "completion_chat": True,
        "completion_fim": False,
        "function_calling": False,
        "fine_tuning": False,
        "vision": False,
        "reasoning": False,
    }
    base.update(kw)
    return base


def test_dedup_collapses_latest_and_dated_aliases_onto_preferred_id():
    # Mirror of the user-provided sample: three entries for mistral-medium
    # (dated, -latest, bare) all sharing name="mistral-medium-2508" collapse
    # to a single row keyed on the -latest alias.
    entries = [
        {
            "id": "mistral-medium-2508",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": None,
        },
        {
            "id": "mistral-medium-latest",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": None,
        },
        {
            "id": "mistral-medium",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": None,
        },
    ]
    metas = _dedup_models(entries, _resolved_conn())
    assert len(metas) == 1
    m = metas[0]
    assert m.model_id == "mistral-medium-latest"
    assert m.display_name == "mistral-medium-latest"
    assert m.context_window == 131_072
    assert m.supports_tool_calls is True
    assert m.supports_vision is True
    assert m.supports_reasoning is False
    assert m.is_deprecated is False


def test_dedup_marks_group_deprecated_when_entries_carry_deprecation():
    entries = [
        {
            "id": "pixtral-large-2411",
            "name": "pixtral-large-2411",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": "2026-05-31T12:00:00Z",
        },
        {
            "id": "pixtral-large-latest",
            "name": "pixtral-large-2411",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": "2026-05-31T12:00:00Z",
        },
        {
            "id": "mistral-large-pixtral-2411",
            "name": "pixtral-large-2411",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": "2026-05-31T12:00:00Z",
        },
    ]
    metas = _dedup_models(entries, _resolved_conn())
    assert len(metas) == 1
    m = metas[0]
    assert m.model_id == "pixtral-large-latest"
    assert m.is_deprecated is True


def test_dedup_keeps_standalone_entry_without_latest_alias():
    entries = [
        {
            "id": "labs-mistral-small-creative",
            "name": "labs-mistral-small-creative",
            "max_context_length": 32_768,
            "capabilities": _cap(),
            "deprecation": "2026-09-01T00:00:00Z",
        },
    ]
    metas = _dedup_models(entries, _resolved_conn())
    assert len(metas) == 1
    m = metas[0]
    assert m.model_id == "labs-mistral-small-creative"
    assert m.is_deprecated is True


def test_dedup_filters_non_chat_models():
    entries = [
        {
            "id": "mistral-embed-2312",
            "name": "mistral-embed-2312",
            "max_context_length": 8_192,
            "capabilities": _cap(completion_chat=False),
            "deprecation": None,
        },
        {
            "id": "mistral-embed",
            "name": "mistral-embed-2312",
            "max_context_length": 8_192,
            "capabilities": _cap(completion_chat=False),
            "deprecation": None,
        },
    ]
    assert _dedup_models(entries, _resolved_conn()) == []


def test_dedup_full_sample_yields_exactly_three_rows():
    # The composite user-provided sample: medium group (3), pixtral group
    # (3), labs-creative (1), embed (2 — filtered). Expected output: 3.
    entries = [
        # medium group
        {
            "id": "mistral-medium-2508",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": None,
        },
        {
            "id": "mistral-medium-latest",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": None,
        },
        {
            "id": "mistral-medium",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": None,
        },
        # pixtral group (deprecated)
        {
            "id": "pixtral-large-2411",
            "name": "pixtral-large-2411",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": "2026-05-31T12:00:00Z",
        },
        {
            "id": "pixtral-large-latest",
            "name": "pixtral-large-2411",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": "2026-05-31T12:00:00Z",
        },
        {
            "id": "mistral-large-pixtral-2411",
            "name": "pixtral-large-2411",
            "max_context_length": 131_072,
            "capabilities": _cap(function_calling=True, vision=True),
            "deprecation": "2026-05-31T12:00:00Z",
        },
        # standalone deprecated
        {
            "id": "labs-mistral-small-creative",
            "name": "labs-mistral-small-creative",
            "max_context_length": 32_768,
            "capabilities": _cap(),
            "deprecation": "2026-09-01T00:00:00Z",
        },
        # embeddings (filtered)
        {
            "id": "mistral-embed-2312",
            "name": "mistral-embed-2312",
            "max_context_length": 8_192,
            "capabilities": _cap(completion_chat=False),
            "deprecation": None,
        },
        {
            "id": "mistral-embed",
            "name": "mistral-embed-2312",
            "max_context_length": 8_192,
            "capabilities": _cap(completion_chat=False),
            "deprecation": None,
        },
    ]
    metas = _dedup_models(entries, _resolved_conn())
    by_id = {m.model_id: m for m in metas}
    assert set(by_id.keys()) == {
        "mistral-medium-latest",
        "pixtral-large-latest",
        "labs-mistral-small-creative",
    }
    assert by_id["mistral-medium-latest"].is_deprecated is False
    assert by_id["pixtral-large-latest"].is_deprecated is True
    assert by_id["labs-mistral-small-creative"].is_deprecated is True


# ---------------------------------------------------------------------------
# Message translation
# ---------------------------------------------------------------------------


def test_translate_text_only_user_message():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hello")],
    )
    assert _translate_message(msg) == {"role": "user", "content": "hello"}


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
    img = result["content"][1]
    assert img["type"] == "image_url"
    assert img["image_url"]["url"] == "data:image/png;base64,AAA="


def test_translate_assistant_with_tool_calls():
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="looking")],
        tool_calls=[
            ToolCallResult(id="call_a", name="web_search",
                           arguments='{"query":"mistral"}'),
        ],
    )
    result = _translate_message(msg)
    assert result["tool_calls"][0]["function"]["name"] == "web_search"


def test_translate_tool_role_message():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"results":[]}')],
        tool_call_id="call_a",
    )
    assert _translate_message(msg)["tool_call_id"] == "call_a"


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


def _simple_request(**kwargs) -> CompletionRequest:
    base = {
        "model": "mistral-medium-latest",
        "messages": [
            CompletionMessage(role="user",
                              content=[ContentPart(type="text", text="hi")]),
        ],
    }
    base.update(kwargs)
    return CompletionRequest(**base)


def test_build_payload_passes_model_slug_through_unchanged():
    # Mistral does NOT route on reasoning_enabled the way xAI does — the
    # model slug from the caller must reach the upstream verbatim.
    payload = _build_chat_payload(_simple_request(
        model="magistral-medium-latest",
        reasoning_enabled=True,
    ))
    assert payload["model"] == "magistral-medium-latest"


def test_build_payload_includes_stream_options_for_usage():
    payload = _build_chat_payload(_simple_request())
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_omits_temperature_when_none():
    payload = _build_chat_payload(_simple_request(temperature=None))
    assert "temperature" not in payload


def test_build_payload_includes_temperature_when_set():
    payload = _build_chat_payload(_simple_request(temperature=0.7))
    assert payload["temperature"] == 0.7


def test_build_payload_translates_tools_to_openai_schema():
    tool = ToolDefinition(
        name="web_search",
        description="Search the web",
        parameters={"type": "object",
                    "properties": {"query": {"type": "string"}}},
    )
    payload = _build_chat_payload(_simple_request(tools=[tool]))
    assert payload["tools"][0]["function"]["name"] == "web_search"


# ---------------------------------------------------------------------------
# SSE parser
# ---------------------------------------------------------------------------


def test_parse_sse_line_returns_dict_for_data_line():
    parsed = _parse_sse_line('data: {"choices":[{"delta":{"content":"hi"}}]}')
    assert parsed == {"choices": [{"delta": {"content": "hi"}}]}


def test_parse_sse_line_returns_done_sentinel_for_done_marker():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_returns_none_for_empty_or_malformed():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("event: foo") is None
    assert _parse_sse_line("data: {not json}") is None


# ---------------------------------------------------------------------------
# Tool-call accumulator
# ---------------------------------------------------------------------------


def test_accumulator_collects_single_call_across_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "web_search"}}])
    acc.ingest([{"index": 0, "function": {"arguments": '{"q":'}}])
    acc.ingest([{"index": 0, "function": {"arguments": '"mistral"}'}}])
    calls = acc.finalised()
    assert len(calls) == 1
    assert calls[0]["id"] == "call_1"
    assert calls[0]["arguments"] == '{"q":"mistral"}'


# ---------------------------------------------------------------------------
# Streaming — mocked HTTP
# ---------------------------------------------------------------------------


def _sse_response(lines: list[str], status: int = 200) -> httpx.Response:
    body = "\n".join(lines) + "\n"
    return httpx.Response(
        status,
        headers={"content-type": "text/event-stream"},
        content=body.encode(),
    )


def _install_mock_transport(monkeypatch, handler):
    from backend.modules.llm._adapters import _mistral_http

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_mistral_http.httpx, "AsyncClient", _PatchedClient)


async def _collect(agen):
    return [e async for e in agen]


@pytest.mark.asyncio
async def test_stream_completion_yields_content_and_done(monkeypatch):
    def handler(request):
        assert request.headers["authorization"] == "Bearer mistral-test-key"
        assert request.url.path.endswith("/chat/completions")
        return _sse_response([
            'data: {"choices":[{"delta":{"content":"he"}}]}',
            'data: {"choices":[{"delta":{"content":"llo"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    deltas = [e for e in events if isinstance(e, ContentDelta)]
    assert [d.delta for d in deltas] == ["he", "llo"]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(dones) == 1
    assert dones[0].input_tokens == 5
    assert dones[0].output_tokens == 2


@pytest.mark.asyncio
async def test_stream_completion_does_not_send_grok_cache_header(monkeypatch):
    # Regression guard: the Mistral adapter must NOT leak the xAI-specific
    # x-grok-conv-id header even when the caller supplied cache_hint.
    seen_headers: dict = {}

    def handler(request):
        seen_headers.update(dict(request.headers))
        return _sse_response([
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    req = _simple_request(cache_hint="session-abc-123")
    await _collect(adapter.stream_completion(_resolved_conn(), req))
    assert "x-grok-conv-id" not in seen_headers


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
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
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
            '[{"index":0,"function":{"arguments":"\\"mistral\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "web_search"
    assert tool_calls[0].arguments == '{"q":"mistral"}'


@pytest.mark.asyncio
async def test_stream_completion_returns_invalid_api_key_on_401(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorised"})

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "invalid_api_key"
    assert "Mistral" in events[0].message


@pytest.mark.asyncio
async def test_stream_completion_returns_provider_unavailable_on_429(monkeypatch):
    def handler(request):
        return httpx.Response(429, json={"error": "slow down"})

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "provider_unavailable"
    assert "rate limit" in events[0].message.lower()


@pytest.mark.asyncio
async def test_stream_completion_returns_provider_unavailable_on_500(monkeypatch):
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "provider_unavailable"


@pytest.mark.asyncio
async def test_stream_completion_emits_refusal_on_content_filter(monkeypatch):
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"content":"I cannot"}}]}',
            'data: {"choices":[{"delta":{"refusal":"policy"},'
            '"finish_reason":"content_filter"}]}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    refusals = [e for e in events if isinstance(e, StreamRefused)]
    assert len(refusals) == 1
    assert refusals[0].reason == "content_filter"
    assert refusals[0].refusal_text == "policy"
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert dones == []


# ---------------------------------------------------------------------------
# fetch_models — mocked HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_models_calls_models_endpoint_with_auth(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer mistral-test-key"
        return httpx.Response(200, json={
            "object": "list",
            "data": [
                {
                    "id": "mistral-medium-latest",
                    "name": "mistral-medium-2508",
                    "max_context_length": 131_072,
                    "capabilities": _cap(function_calling=True, vision=True),
                    "deprecation": None,
                },
            ],
        })

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert len(metas) == 1
    assert metas[0].model_id == "mistral-medium-latest"
    assert metas[0].connection_slug == "mistral"


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorised"})

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert metas == []
