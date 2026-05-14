"""Tests for the Mistral HTTP adapter — curated model table, stream parser, routing."""

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
    _parse_sse_line,
    _SSE_DONE,
    _ToolCallAccumulator,
    _translate_delta_content,
    _translate_message,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolCallResult,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability

from backend.modules.llm._adapters._mistral_http import (
    _MISTRAL_MODELS,
    _MISTRAL_MODELS_BY_ID,
    _MistralModelEntry,
)


def test_mistral_models_table_has_exactly_three_entries():
    assert len(_MISTRAL_MODELS) == 3
    ids = {m.model_id for m in _MISTRAL_MODELS}
    assert ids == {"mistral-small-4", "mistral-medium-3-5", "mistral-large-3"}


def test_mistral_models_display_names_are_curated():
    by_id = {m.model_id: m.display_name for m in _MISTRAL_MODELS}
    assert by_id["mistral-small-4"] == "Mistral Small 4"
    assert by_id["mistral-medium-3-5"] == "Mistral Medium 3.5"
    assert by_id["mistral-large-3"] == "Mistral Large 3"


def test_mistral_models_upstream_slugs_match_api_reality():
    by_id = {m.model_id: m.upstream_slug for m in _MISTRAL_MODELS}
    assert by_id["mistral-small-4"] == "mistral-small-latest"
    assert by_id["mistral-medium-3-5"] == "mistral-medium-3-5"
    assert by_id["mistral-large-3"] == "mistral-large-latest"


def test_mistral_models_first_class_only_for_reasoning_models():
    by_id = {m.model_id: m.first_class_support for m in _MISTRAL_MODELS}
    assert by_id["mistral-small-4"] is True
    assert by_id["mistral-medium-3-5"] is True
    assert by_id["mistral-large-3"] is False


def test_mistral_models_large_3_has_no_reasoning():
    entry = _MISTRAL_MODELS_BY_ID["mistral-large-3"]
    assert entry.has_reasoning is False


def test_mistral_models_small_and_medium_have_reasoning():
    assert _MISTRAL_MODELS_BY_ID["mistral-small-4"].has_reasoning is True
    assert _MISTRAL_MODELS_BY_ID["mistral-medium-3-5"].has_reasoning is True


def test_mistral_models_context_window_is_262144_for_all():
    for entry in _MISTRAL_MODELS:
        assert entry.context_window == 262_144


def test_mistral_models_all_support_vision_and_tools():
    for entry in _MISTRAL_MODELS:
        assert entry.supports_vision is True
        assert entry.supports_tool_calls is True


def test_capability_hint_returns_optional_reasoning_for_small_4():
    adapter = MistralHttpAdapter()
    hint = adapter.capability_hint("mistral-small-4")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.default_on is True
    assert hint.reasoning.effort is None
    assert hint.tools.supported is True
    assert hint.first_class_support is True


def test_capability_hint_returns_no_reasoning_for_large_3():
    adapter = MistralHttpAdapter()
    hint = adapter.capability_hint("mistral-large-3")
    assert hint is not None
    assert hint.reasoning.kind == "no_reasoning"
    assert hint.reasoning.default_on is False
    assert hint.tools.supported is True
    assert hint.first_class_support is False


def test_capability_hint_returns_none_for_unknown_model_id():
    adapter = MistralHttpAdapter()
    assert adapter.capability_hint("magistral-medium-latest") is None
    assert adapter.capability_hint("totally-made-up") is None


def test_resolve_capabilities_small_4_has_no_effort_buckets():
    from backend.modules.llm._capabilities import resolve_capabilities
    adapter = MistralHttpAdapter()
    resolved = resolve_capabilities(
        adapter_type="mistral_http",
        model_id="mistral-small-4",
        adapter=adapter,
    )
    assert resolved.reasoning.kind == "optional"
    assert resolved.reasoning.effort is None
    assert resolved.reasoning.default_on is True
    assert resolved.first_class_support is True


def test_resolve_capabilities_medium_3_5_has_no_effort_buckets():
    from backend.modules.llm._capabilities import resolve_capabilities
    adapter = MistralHttpAdapter()
    resolved = resolve_capabilities(
        adapter_type="mistral_http",
        model_id="mistral-medium-3-5",
        adapter=adapter,
    )
    assert resolved.reasoning.kind == "optional"
    assert resolved.reasoning.effort is None
    assert resolved.first_class_support is True


def test_resolve_capabilities_large_3_has_no_reasoning():
    from backend.modules.llm._capabilities import resolve_capabilities
    adapter = MistralHttpAdapter()
    resolved = resolve_capabilities(
        adapter_type="mistral_http",
        model_id="mistral-large-3",
        adapter=adapter,
    )
    assert resolved.reasoning.kind == "no_reasoning"
    assert resolved.tools.supported is True
    assert resolved.first_class_support is False


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
    # BaseAdapter defaults (empty templates + schema).
    assert MistralHttpAdapter.templates() == []
    assert MistralHttpAdapter.config_schema() == []


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
    """Build a CompletionRequest under the new contract.

    Legacy ``reasoning_enabled=`` and ``supports_reasoning=`` kwargs are
    translated into the new ``extras.reasoning_mode`` / ``reasoning``
    capability shape so existing call sites remain ergonomic.
    """
    reasoning_enabled = bool(kwargs.pop("reasoning_enabled", False))
    kwargs.pop("supports_reasoning", None)
    base = {
        "model": "mistral-medium-3-5",
        "messages": [
            CompletionMessage(role="user",
                              content=[ContentPart(type="text", text="hi")]),
        ],
        "reasoning": ReasoningCapability(kind="optional"),
        "tools_capability": ToolCapability(supported=True),
        "extras": ChatSessionExtras(
            tools_enabled=False,
            reasoning_mode="on" if reasoning_enabled else "off",
            reasoning_effort=None,
        ),
    }
    base.update(kwargs)
    return CompletionRequest(**base)


# ---------------------------------------------------------------------------
# build_chat_payload — slug-mapping, reasoning toggle, legacy fallback
# ---------------------------------------------------------------------------


def test_build_payload_maps_small_4_to_mistral_small_latest():
    req = _simple_request(model="mistral-small-4")
    payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-small-latest"


def test_build_payload_maps_medium_3_5_to_dated_slug():
    req = _simple_request(model="mistral-medium-3-5")
    payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-medium-3-5"


def test_build_payload_maps_large_3_to_mistral_large_latest():
    req = _simple_request(model="mistral-large-3")
    payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-large-latest"


def test_build_payload_reasoning_on_sends_high():
    req = _simple_request(
        model="mistral-small-4",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort=None,
        ),
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning_effort"] == "high"


def test_build_payload_reasoning_off_sends_none():
    req = _simple_request(
        model="mistral-small-4",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning_effort"] == "none"


def test_build_payload_ignores_persisted_effort_bucket():
    # Stale persona may carry e.g. reasoning_effort="medium" from a different
    # adapter — Mistral rejects medium with HTTP 400. We must drop it entirely
    # and always send the high/none binary derived from reasoning_mode.
    req = _simple_request(
        model="mistral-medium-3-5",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning_effort"] == "high"


def test_build_payload_large_3_omits_reasoning_effort():
    req = _simple_request(
        model="mistral-large-3",
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort=None,
        ),
    )
    payload = _build_chat_payload(req)
    assert "reasoning_effort" not in payload


def test_build_payload_unknown_model_falls_back_to_medium_3_5(caplog):
    import logging
    req = _simple_request(model="magistral-medium-latest")
    with caplog.at_level(logging.WARNING):
        payload = _build_chat_payload(req)
    assert payload["model"] == "mistral-medium-3-5"
    assert any(
        "unknown model_id" in r.message and "magistral-medium-latest" in r.message
        for r in caplog.records
    )


def test_build_payload_stream_options_included():
    req = _simple_request(model="mistral-small-4")
    payload = _build_chat_payload(req)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_tools_translated_to_openai_schema():
    req = _simple_request(
        model="mistral-large-3",
        tools=[ToolDefinition(
            name="get_weather",
            description="Get weather",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }]


def test_build_payload_omits_temperature_when_none():
    payload = _build_chat_payload(_simple_request(temperature=None))
    assert "temperature" not in payload


def test_build_payload_includes_temperature_when_set():
    payload = _build_chat_payload(_simple_request(temperature=0.7))
    assert payload["temperature"] == 0.7


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
# translate_delta_content (thinking-blocks)
# ---------------------------------------------------------------------------


def test_translate_delta_content_string_input_passes_through():
    visible, thinking = _translate_delta_content("hello")
    assert visible == "hello"
    assert thinking == ""


def test_translate_delta_content_empty_string():
    visible, thinking = _translate_delta_content("")
    assert visible == ""
    assert thinking == ""


def test_translate_delta_content_none_returns_empty_pair():
    visible, thinking = _translate_delta_content(None)
    assert visible == ""
    assert thinking == ""


def test_translate_delta_content_array_with_only_thinking():
    arr = [{
        "type": "thinking",
        "thinking": [{"type": "text", "text": "Okay, let me think"}],
        "closed": True,
    }]
    visible, thinking = _translate_delta_content(arr)
    assert visible == ""
    assert thinking == "Okay, let me think"


def test_translate_delta_content_array_with_only_text():
    arr = [{"type": "text", "text": "Result is 4"}]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "Result is 4"
    assert thinking == ""


def test_translate_delta_content_array_with_mixed_items():
    arr = [
        {"type": "thinking",
         "thinking": [{"type": "text", "text": "Hmm "}, {"type": "text", "text": "let me see."}]},
        {"type": "text", "text": "The answer "},
        {"type": "text", "text": "is 4."},
    ]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "The answer is 4."
    assert thinking == "Hmm let me see."


def test_translate_delta_content_ignores_unknown_item_types():
    arr = [
        {"type": "future_unknown_type", "data": "..."},
        {"type": "text", "text": "Hello"},
    ]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "Hello"
    assert thinking == ""


def test_translate_delta_content_robust_against_malformed_items():
    arr = [
        "not a dict",  # malformed item
        {"type": "thinking"},  # missing thinking-field
        {"type": "text"},  # missing text-field
        {"type": "text", "text": "ok"},
    ]
    visible, thinking = _translate_delta_content(arr)
    assert visible == "ok"
    assert thinking == ""


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
async def test_stream_completion_emits_thinking_delta_for_mistral_thinking_blocks(monkeypatch):
    """Mistral's proprietary format: delta.content as array with
    thinking-typed items.
    """
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{"content":'
            '[{"type":"thinking","thinking":[{"type":"text","text":"hmm"}]}]}}]}',
            'data: {"choices":[{"delta":{"content":'
            '[{"type":"text","text":"42"}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3}}',
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
async def test_stream_completion_does_not_double_emit_thinking_when_both_paths_present(monkeypatch):
    """If Mistral ever sends BOTH content-array thinking AND reasoning_content
    in the same chunk, we must emit exactly one ThinkingDelta (the
    Mistral-native one), not two.
    """
    def handler(request):
        return _sse_response([
            'data: {"choices":[{"delta":{'
            '"content":[{"type":"thinking","thinking":[{"type":"text","text":"native"}]}],'
            '"reasoning_content":"fallback"'
            '}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}',
            'data: [DONE]',
        ])

    _install_mock_transport(monkeypatch, handler)
    adapter = MistralHttpAdapter()
    events = await _collect(adapter.stream_completion(_resolved_conn(), _simple_request()))
    thinking = [e for e in events if isinstance(e, ThinkingDelta)]
    assert [t.delta for t in thinking] == ["native"]


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
    assert "429" in events[0].message
    assert "gave up" in events[0].message.lower()


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
# fetch_models — curated table (no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_models_returns_exactly_three_curated_entries():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    ids = {m.model_id for m in metas}
    assert ids == {"mistral-small-4", "mistral-medium-3-5", "mistral-large-3"}
    assert len(metas) == 3


@pytest.mark.asyncio
async def test_fetch_models_carries_curated_display_names():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m.display_name for m in metas}
    assert by_id["mistral-small-4"] == "Mistral Small 4"
    assert by_id["mistral-medium-3-5"] == "Mistral Medium 3.5"
    assert by_id["mistral-large-3"] == "Mistral Large 3"


@pytest.mark.asyncio
async def test_fetch_models_billing_category_is_pay_per_token_for_all_entries():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    for m in metas:
        assert m.billing_category == "pay_per_token"


@pytest.mark.asyncio
async def test_fetch_models_first_class_only_for_small_and_medium():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    by_id = {m.model_id: m.first_class_support for m in metas}
    assert by_id["mistral-small-4"] is True
    assert by_id["mistral-medium-3-5"] is True
    assert by_id["mistral-large-3"] is False


@pytest.mark.asyncio
async def test_fetch_models_makes_no_http_call(monkeypatch):
    """Curated fetch_models must not hit /v1/models — it's a static table."""
    called = False

    async def _boom(*a, **kw):
        nonlocal called
        called = True
        raise AssertionError("fetch_models should not perform HTTP")

    # Patch httpx so any accidental network call would crash loudly.
    monkeypatch.setattr(httpx.AsyncClient, "get", _boom)
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert called is False
    assert len(metas) == 3


@pytest.mark.asyncio
async def test_fetch_models_carries_context_window():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    for m in metas:
        assert m.context_window == 262_144


@pytest.mark.asyncio
async def test_fetch_models_carries_vision_and_tool_flags():
    adapter = MistralHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    for m in metas:
        assert m.supports_vision is True
        assert m.supports_tool_calls is True


# ---------------------------------------------------------------------------
# Sub-router POST /test
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app_with_mistral_router(monkeypatch, handler) -> TestClient:
    from backend.modules.llm._adapters import _mistral_http
    from backend.modules.llm._resolver import resolve_connection_for_user

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_mistral_http.httpx, "AsyncClient", _PatchedClient)

    router = MistralHttpAdapter.router()
    app = FastAPI()
    app.include_router(router, prefix="/adapter")
    app.dependency_overrides[resolve_connection_for_user] = lambda: _resolved_conn()

    from backend.ws.event_bus import get_event_bus

    class _FakeRepo:
        async def update_test_status(self, *a, **kw):
            return None

    class _FakeBus:
        async def publish(self, *a, **kw):
            return None

    monkeypatch.setattr(_mistral_http, "_mistral_repo_factory",
                        lambda: _FakeRepo(), raising=False)
    app.dependency_overrides[get_event_bus] = lambda: _FakeBus()
    return TestClient(app)


def test_post_test_valid_key_returns_true(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer mistral-test-key"
        return httpx.Response(200, json={"data": [{"id": "mistral-small-latest"}]})

    client = _app_with_mistral_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["error"] is None


def test_post_test_invalid_key_returns_false_with_clear_error(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorised"})

    client = _app_with_mistral_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "key" in body["error"].lower() and "mistral" in body["error"].lower()


def test_post_test_upstream_error_returns_false(monkeypatch):
    def handler(request):
        return httpx.Response(503, json={"error": "down"})

    client = _app_with_mistral_router(monkeypatch, handler)
    resp = client.post("/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "503" in body["error"]
