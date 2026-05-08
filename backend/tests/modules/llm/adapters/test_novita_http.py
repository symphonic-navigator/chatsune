"""Tests for the Novita AI HTTP adapter.

Mirrors `test_openrouter_http.py`; coverage grows task by task.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
)
from backend.modules.llm._adapters._novita_http import (
    _SSE_DONE,
    MIN_CONTEXT_TOKENS,
    NovitaHttpAdapter,
    _build_chat_payload,
    _chunk_to_events,
    _entry_to_meta,
    _parse_sse_line,
    _ToolCallAccumulator,
    _translate_message,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    _PREMIUM_ONLY_ADAPTERS,
    get_adapter_class,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolCallResult,
    ToolDefinition,
)


def test_adapter_identity():
    a = NovitaHttpAdapter()
    assert a.adapter_type == "novita_http"
    assert a.display_name == "Novita AI"
    assert a.view_id == "novita_http"
    assert a.secret_fields == frozenset({"api_key"})


def test_adapter_is_premium_only_not_user_creatable():
    # User-facing registry must NOT contain novita — it is premium-only.
    assert "novita_http" not in ADAPTER_REGISTRY
    # But the resolver helper should find it.
    assert get_adapter_class("novita_http") is NovitaHttpAdapter


def test_adapter_registered_in_premium_only_map():
    assert "novita_http" in _PREMIUM_ONLY_ADAPTERS
    assert _PREMIUM_ONLY_ADAPTERS["novita_http"] is NovitaHttpAdapter


def test_parse_sse_line_returns_dict_for_data_line():
    out = _parse_sse_line('data: {"a":1}')
    assert out == {"a": 1}


def test_parse_sse_line_returns_done_sentinel_for_done_marker():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_returns_none_for_empty_or_malformed():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("data: not json") is None


def test_chunk_emits_content_delta():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"content": "hi"}}]}, acc,
    )
    assert events == [ContentDelta(delta="hi")]


def test_chunk_emits_thinking_delta_for_reasoning_content():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning_content": "hmm"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="hmm")]


def test_chunk_emits_thinking_delta_for_plain_reasoning_key():
    """Some upstream models stream their thinking under a bare
    ``reasoning`` field. Adapter must produce a ThinkingDelta for either
    field (defensive — providers in the wild use either)."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning": "thinking"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking")]


def test_chunk_emits_stream_done_on_usage_chunk():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }, acc,
    )
    assert events == [StreamDone(input_tokens=10, output_tokens=20)]


def test_chunk_emits_refusal_on_content_filter():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"finish_reason": "content_filter", "delta": {}}]},
        acc,
    )
    assert any(isinstance(e, StreamRefused) for e in events)


def test_accumulator_collects_tool_call_across_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1",
                 "function": {"name": "lookup", "arguments": '{"q":'}}])
    acc.ingest([{"index": 0,
                 "function": {"arguments": '"hello"}'}}])
    finalised = acc.finalised()
    assert finalised == [{
        "id": "call_1", "name": "lookup", "arguments": '{"q":"hello"}',
    }]


def test_accumulator_finalised_is_idempotent():
    """Some upstreams emit two finish_reason="tool_calls" chunks for the
    same call. _chunk_to_events re-invokes finalised(), so a non-
    idempotent finalised() surfaces the same call as two ToolCallStarted
    events downstream."""
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1",
                 "function": {"name": "lookup", "arguments": "{}"}}])
    first = acc.finalised()
    second = acc.finalised()
    assert len(first) == 1
    assert second == []


def test_translate_text_only_user_message():
    msg = CompletionMessage(role="user",
                            content=[ContentPart(type="text", text="hi")])
    assert _translate_message(msg) == {"role": "user", "content": "hi"}


def test_translate_image_message_uses_openai_image_url_format():
    msg = CompletionMessage(role="user", content=[
        ContentPart(type="text", text="describe"),
        ContentPart(type="image", data="aGVsbG8=", media_type="image/png"),
    ])
    out = _translate_message(msg)
    assert out["role"] == "user"
    assert isinstance(out["content"], list)
    assert out["content"][0] == {"type": "text", "text": "describe"}
    assert out["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
    }


def test_build_payload_passes_model_through():
    req = CompletionRequest(
        model="xiaomimimo/mimo-v2.5-pro",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["model"] == "xiaomimimo/mimo-v2.5-pro"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_includes_temperature_when_set():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        temperature=0.4,
    )
    assert _build_chat_payload(req)["temperature"] == 0.4


def test_build_payload_omits_temperature_when_none():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    assert "temperature" not in _build_chat_payload(req)


def test_build_payload_translates_tools():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        tools=[ToolDefinition(
            name="lookup", description="d", parameters={"type": "object"},
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "lookup", "description": "d",
            "parameters": {"type": "object"},
        },
    }]


def test_reasoning_field_omitted_when_enabled_and_supported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=True, reasoning_enabled=True,
    )
    assert "reasoning" not in _build_chat_payload(req)


def test_reasoning_field_set_to_exclude_when_disabled_and_supported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=True, reasoning_enabled=False,
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning"] == {"exclude": True}


def test_reasoning_field_omitted_when_unsupported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=False, reasoning_enabled=True,
    )
    assert "reasoning" not in _build_chat_payload(req)


def test_translate_assistant_with_tool_calls():
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="")],
        tool_calls=[ToolCallResult(id="c1", name="lookup", arguments='{"q":1}')],
    )
    out = _translate_message(msg)
    assert out["tool_calls"] == [{
        "id": "c1", "type": "function",
        "function": {"name": "lookup", "arguments": '{"q":1}'},
    }]


def test_translate_tool_message_carries_tool_call_id():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text="42")],
        tool_call_id="c1",
    )
    out = _translate_message(msg)
    assert out["tool_call_id"] == "c1"


def _resolved() -> ResolvedConnection:
    return ResolvedConnection(
        id="premium:novita",
        user_id="u1",
        adapter_type="novita_http",
        display_name="Novita AI",
        slug="novita",
        config={
            "url": "https://api.novita.ai/openai/v1",
            "api_key": "sk-novita-fake",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_entry(**overrides) -> dict:
    """Returns a Novita catalogue entry that PASSES every filter rule.
    Override fields to drive specific failure cases."""
    base = {
        "id": "xiaomimimo/mimo-v2.5-pro",
        "display_name": "XiaomiMiMo/MiMo-V2.5-Pro",
        "context_size": 1_048_576,
        "model_type": "chat",
        "status": 1,
        "endpoints": ["completions", "chat/completions", "anthropic"],
        "features": ["serverless", "function-calling",
                     "structured-outputs", "reasoning"],
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "input_token_price_per_m": 20000,
        "output_token_price_per_m": 60000,
    }
    base.update(overrides)
    return base


def test_entry_to_meta_maps_all_fields_for_a_full_pass():
    meta = _entry_to_meta(_make_entry(), _resolved())
    assert meta is not None
    assert meta.connection_id == "premium:novita"
    assert meta.connection_slug == "novita"
    assert meta.connection_display_name == "Novita AI"
    assert meta.model_id == "xiaomimimo/mimo-v2.5-pro"
    assert meta.display_name == "XiaomiMiMo/MiMo-V2.5-Pro"
    assert meta.context_window == 1_048_576
    assert meta.supports_reasoning is True
    assert meta.supports_vision is False
    assert meta.supports_tool_calls is True
    assert meta.is_deprecated is False
    assert meta.billing_category == "pay_per_token"
    assert meta.is_moderated is None


def test_entry_to_meta_falls_back_to_id_when_display_name_missing():
    meta = _entry_to_meta(_make_entry(display_name=None), _resolved())
    assert meta is not None
    assert meta.display_name == "xiaomimimo/mimo-v2.5-pro"


def test_entry_to_meta_filters_non_text_output():
    assert _entry_to_meta(
        _make_entry(output_modalities=["image"]), _resolved(),
    ) is None
    assert _entry_to_meta(
        _make_entry(output_modalities=["text", "image"]), _resolved(),
    ) is None


def test_entry_to_meta_filters_below_min_context():
    assert _entry_to_meta(
        _make_entry(context_size=MIN_CONTEXT_TOKENS - 1), _resolved(),
    ) is None


def test_entry_to_meta_passes_at_min_context_threshold():
    meta = _entry_to_meta(
        _make_entry(context_size=MIN_CONTEXT_TOKENS), _resolved(),
    )
    assert meta is not None


def test_entry_to_meta_filters_when_chat_endpoint_missing():
    assert _entry_to_meta(
        _make_entry(endpoints=["completions", "anthropic"]), _resolved(),
    ) is None


def test_entry_to_meta_filters_non_serverless():
    assert _entry_to_meta(
        _make_entry(features=["function-calling", "reasoning"]), _resolved(),
    ) is None


def test_entry_to_meta_filters_non_chat_model_type():
    assert _entry_to_meta(
        _make_entry(model_type="completion"), _resolved(),
    ) is None


def test_entry_to_meta_filters_inactive_status():
    assert _entry_to_meta(
        _make_entry(status=0), _resolved(),
    ) is None


def test_entry_to_meta_billing_free_when_both_prices_zero():
    meta = _entry_to_meta(
        _make_entry(input_token_price_per_m=0, output_token_price_per_m=0),
        _resolved(),
    )
    assert meta is not None
    assert meta.billing_category == "free"


def test_entry_to_meta_billing_paid_when_either_price_nonzero():
    only_in = _entry_to_meta(
        _make_entry(input_token_price_per_m=1, output_token_price_per_m=0),
        _resolved(),
    )
    only_out = _entry_to_meta(
        _make_entry(input_token_price_per_m=0, output_token_price_per_m=1),
        _resolved(),
    )
    assert only_in.billing_category == "pay_per_token"
    assert only_out.billing_category == "pay_per_token"


def test_entry_to_meta_supports_vision_when_image_in_input_modalities():
    meta = _entry_to_meta(
        _make_entry(input_modalities=["text", "image"]), _resolved(),
    )
    assert meta is not None
    assert meta.supports_vision is True


def test_entry_to_meta_supports_reasoning_only_when_feature_present():
    meta = _entry_to_meta(
        _make_entry(features=["serverless", "function-calling"]),
        _resolved(),
    )
    assert meta is not None
    assert meta.supports_reasoning is False


def test_entry_to_meta_supports_tool_calls_only_when_feature_present():
    meta = _entry_to_meta(
        _make_entry(features=["serverless", "reasoning"]),
        _resolved(),
    )
    assert meta is not None
    assert meta.supports_tool_calls is False


_MODELS_RESPONSE = {
    "data": [
        # Passing model — full pass.
        {
            "id": "xiaomimimo/mimo-v2.5-pro",
            "display_name": "XiaomiMiMo/MiMo-V2.5-Pro",
            "context_size": 1_048_576,
            "model_type": "chat",
            "status": 1,
            "endpoints": ["completions", "chat/completions", "anthropic"],
            "features": ["serverless", "function-calling",
                         "structured-outputs", "reasoning"],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "input_token_price_per_m": 20000,
            "output_token_price_per_m": 60000,
        },
        # Image-output model — must be filtered.
        {
            "id": "stability/sdxl",
            "display_name": "SDXL",
            "context_size": 2048,
            "model_type": "chat",
            "status": 1,
            "endpoints": ["chat/completions"],
            "features": ["serverless"],
            "input_modalities": ["text"],
            "output_modalities": ["image"],
            "input_token_price_per_m": 0,
            "output_token_price_per_m": 0,
        },
        # Sub-80k context — must be filtered.
        {
            "id": "tiny/8k",
            "display_name": "Tiny",
            "context_size": 8192,
            "model_type": "chat",
            "status": 1,
            "endpoints": ["chat/completions"],
            "features": ["serverless"],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "input_token_price_per_m": 0,
            "output_token_price_per_m": 0,
        },
        # Free-tier passing model.
        {
            "id": "free/big",
            "display_name": "Free Big",
            "context_size": 200_000,
            "model_type": "chat",
            "status": 1,
            "endpoints": ["chat/completions"],
            "features": ["serverless", "reasoning"],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "input_token_price_per_m": 0,
            "output_token_price_per_m": 0,
        },
        # Missing id — must be silently dropped.
        {
            "display_name": "No ID",
            "context_size": 200_000,
            "model_type": "chat",
            "status": 1,
            "endpoints": ["chat/completions"],
            "features": ["serverless"],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ],
}


class _FakeAsyncClient:
    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(_MODELS_RESPONSE).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_returns_only_passing_entries():
    a = NovitaHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        _FakeAsyncClient,
    ):
        models = await a.fetch_models(_resolved())

    by_id = {m.model_id: m for m in models}
    assert set(by_id) == {"xiaomimimo/mimo-v2.5-pro", "free/big"}

    pro = by_id["xiaomimimo/mimo-v2.5-pro"]
    assert pro.billing_category == "pay_per_token"
    assert pro.supports_reasoning is True
    assert pro.supports_tool_calls is True

    free = by_id["free/big"]
    assert free.billing_category == "free"
    assert free.supports_reasoning is True
    assert free.supports_tool_calls is False


class _FakeAsyncClient401(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=401,
            content=b'{"error":"Bad key"}',
            request=httpx.Request("GET", url),
        )


class _FakeAsyncClient500(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=500,
            content=b"upstream blew up",
            request=httpx.Request("GET", url),
        )


class _FakeAsyncClientTransport(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        raise httpx.ConnectError("network down")


class _FakeAsyncClientMalformed(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=b"this is not json",
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_401():
    a = NovitaHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        _FakeAsyncClient401,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_5xx():
    a = NovitaHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        _FakeAsyncClient500,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_transport_error():
    a = NovitaHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        _FakeAsyncClientTransport,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_malformed_json():
    a = NovitaHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        _FakeAsyncClientMalformed,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []
