"""Tests for the OpenRouter HTTP adapter.

Coverage grows task by task; this initial pass exercises adapter
identity and premium-only registration. Later tasks add model-list
mapping, defensive modality filter, auth/error handling, payload
shape (incl. reasoning logic), SSE parser extensions, and the /test
sub-router.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamError,
    StreamRefused,
    ThinkingDelta,
)
from backend.modules.llm._adapters._openrouter_http import (
    _SSE_DONE,
    OpenRouterHttpAdapter,
    _build_chat_payload,
    _chunk_to_events,
    _parse_sse_line,
    _ToolCallAccumulator,
    _translate_message,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    get_adapter_class,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)


def test_adapter_identity():
    a = OpenRouterHttpAdapter()
    assert a.adapter_type == "openrouter_http"
    assert a.display_name == "OpenRouter"
    assert a.view_id == "openrouter_http"
    assert a.secret_fields == frozenset({"api_key"})


def test_adapter_is_premium_only_not_user_creatable():
    # User-facing registry must NOT contain openrouter — it is premium-only.
    assert "openrouter_http" not in ADAPTER_REGISTRY
    # But the resolver helper should find it.
    assert get_adapter_class("openrouter_http") is OpenRouterHttpAdapter


def _resolved() -> ResolvedConnection:
    return ResolvedConnection(
        id="premium:openrouter",
        user_id="u1",
        adapter_type="openrouter_http",
        display_name="OpenRouter",
        slug="openrouter",
        config={
            "url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-v1-fake",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


_MODELS_USER_RESPONSE = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128_000,
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            "top_provider": {
                "context_length": 128_000,
                "max_completion_tokens": 16_384,
                "is_moderated": True,
            },
            "supported_parameters": [
                "max_tokens", "temperature", "tools", "tool_choice",
            ],
            "expiration_date": None,
        },
        {
            "id": "deepseek/deepseek-r1:free",
            "name": "DeepSeek: R1 (free)",
            "context_length": 131_072,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {
                "context_length": 131_072,
                "max_completion_tokens": 8_192,
                "is_moderated": False,
            },
            "supported_parameters": [
                "include_reasoning", "reasoning", "max_tokens", "temperature",
            ],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that returns a canned response."""

    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(_MODELS_USER_RESPONSE).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_maps_fields_correctly():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient,
    ):
        models = await a.fetch_models(_resolved())

    by_id = {m.model_id: m for m in models}

    gpt = by_id["openai/gpt-4o"]
    assert gpt.display_name == "OpenAI: GPT-4o"
    assert gpt.context_window == 128_000
    assert gpt.supports_vision is True       # input_modalities contains "image"
    assert gpt.supports_reasoning is False   # neither key in supported_parameters
    assert gpt.supports_tool_calls is True   # "tools" in supported_parameters
    assert gpt.is_moderated is True
    assert gpt.is_deprecated is False
    assert gpt.billing_category == "pay_per_token"
    assert gpt.connection_slug == "openrouter"

    r1 = by_id["deepseek/deepseek-r1:free"]
    assert r1.supports_vision is False
    assert r1.supports_reasoning is True     # both reasoning keys present
    assert r1.supports_tool_calls is False   # "tools" missing
    assert r1.is_moderated is False
    assert r1.billing_category == "free"     # both pricing fields == "0"


_MODELS_USER_RESPONSE_WITH_IMAGE_OUTPUT = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128_000,
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "stability/sdxl",
            "name": "SDXL",
            "context_length": 2048,
            "architecture": {
                "modality": "text->image",
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "multimodal/text-and-image-output",
            "name": "Mixed Output",
            "context_length": 32_000,
            "architecture": {
                "modality": "text->text+image",
                "input_modalities": ["text"],
                "output_modalities": ["text", "image"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "broken/missing-arch",
            "name": "No Architecture",
            "context_length": 1024,
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClientImageOutput(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(
                _MODELS_USER_RESPONSE_WITH_IMAGE_OUTPUT
            ).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_filters_non_text_output():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClientImageOutput,
    ):
        models = await a.fetch_models(_resolved())

    ids = {m.model_id for m in models}
    # Only the strict text-only output model survives.
    assert ids == {"openai/gpt-4o"}


class _FakeAsyncClient401(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=401,
            content=b'{"error":{"code":401,"message":"Bad key"}}',
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


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_401():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient401,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_5xx():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient500,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_transport_error():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClientTransport,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


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
    """OpenRouter normalises some upstream models' thinking output to
    `delta.reasoning` (plain key). Must produce a ThinkingDelta."""
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
    """Some upstream providers (DeepSeek via OpenRouter) emit two
    finish_reason="tool_calls" chunks for the same call. _chunk_to_events
    re-invokes finalised() each time, so a non-idempotent finalised()
    surfaces the same call as two ToolCallStarted events downstream."""
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
        model="openai/gpt-4o",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["model"] == "openai/gpt-4o"
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


class _FakeStreamResponse:
    """httpx response stand-in that yields prepared SSE lines."""

    def __init__(
        self, lines: list[str], status_code: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self._lines = lines
        self.status_code = status_code
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            await asyncio.sleep(0)
            yield line

    async def aread(self):
        return b""


class _FakeStreamingClient:
    """httpx.AsyncClient stand-in that returns a canned SSE stream."""

    def __init__(self, lines, status_code=200):
        self._lines = lines
        self._status = status_code
        self.captured_headers = None

    def __call__(self, *_, **__):  # used as ctor when patched
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def stream(self, method, url, json=None, headers=None):  # noqa: ARG002
        self.captured_headers = headers
        return _FakeStreamResponse(self._lines, self._status)


@pytest.mark.asyncio
async def test_stream_completion_emits_content_then_done():
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[{"finish_reason":"stop","delta":{}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClient(lines)

    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="openai/gpt-4o",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )

    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_args, **_kw: fake,
    ):
        events = []
        async for ev in a.stream_completion(_resolved(), req):
            events.append(ev)

    contents = [e for e in events if isinstance(e, ContentDelta)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert "".join(c.delta for c in contents) == "Hello"
    assert len(dones) == 1
    assert dones[0].input_tokens == 3
    assert dones[0].output_tokens == 2


@pytest.mark.asyncio
async def test_stream_completion_sends_attribution_headers():
    """OpenRouter app-attribution headers must be sent on every chat request."""
    lines = [
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClient(lines)

    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )

    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_args, **_kw: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass

    assert fake.captured_headers is not None
    assert fake.captured_headers["HTTP-Referer"] == (
        "https://github.com/symphonic-navigator/chatsune"
    )
    assert fake.captured_headers["X-OpenRouter-Title"] == "Chatsune"
    assert fake.captured_headers["X-OpenRouter-Categories"] == (
        "general-chat,roleplay"
    )
    assert fake.captured_headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_stream_completion_401_yields_invalid_api_key():
    fake = _FakeStreamingClient([], status_code=401)
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "invalid_api_key"


class _FakeStreamingClientWithStatusSeq(_FakeStreamingClient):
    """Returns one response per attempt. ``status_codes_seq`` controls
    the status code per call to ``stream()``; once the sequence is
    exhausted, the last value is reused."""

    def __init__(self, lines, status_codes_seq, response_headers=None):
        super().__init__(lines)
        self._status_seq = list(status_codes_seq)
        self._response_headers = response_headers or {}
        self.attempts = 0

    def stream(self, method, url, json=None, headers=None):  # noqa: ARG002
        self.captured_headers = headers
        idx = min(self.attempts, len(self._status_seq) - 1)
        status = self._status_seq[idx]
        self.attempts += 1
        return _FakeStreamResponse(
            self._lines, status, headers=self._response_headers,
        )


async def _async_noop(*_a, **_k):
    return None


@pytest.mark.asyncio
async def test_stream_completion_retries_on_429_then_succeeds(monkeypatch):
    """First attempt returns 429, second returns 200 with content.
    The adapter should retry transparently and emit the success stream."""
    lines = [
        'data: {"choices":[{"delta":{"content":"OK"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClientWithStatusSeq(lines, status_codes_seq=[429, 200])
    monkeypatch.setattr(
        "backend.modules.llm._adapters._openrouter_http.asyncio.sleep",
        _async_noop,
    )

    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]

    contents = [e for e in events if isinstance(e, ContentDelta)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert "".join(c.delta for c in contents) == "OK"
    assert len(dones) == 1
    assert errs == []
    assert fake.attempts == 2  # one retry happened


@pytest.mark.asyncio
async def test_stream_completion_429_yields_provider_unavailable(monkeypatch):
    """All retries return 429 — error is yielded only after exhaustion."""
    fake = _FakeStreamingClient([], status_code=429)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._openrouter_http.asyncio.sleep",
        _async_noop,
    )
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"
    assert "429" in errs[0].message
    assert "gave up" in errs[0].message.lower()


@pytest.mark.asyncio
async def test_stream_completion_5xx_yields_provider_unavailable():
    fake = _FakeStreamingClient([], status_code=500)
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"


@pytest.mark.asyncio
async def test_stream_completion_does_not_retry_on_5xx():
    """Retries are reserved for transient 429s. A 500 must surface
    immediately so the user sees a real error rather than a 15-second
    silent stall."""
    fake = _FakeStreamingClientWithStatusSeq([], status_codes_seq=[500])
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass
    assert fake.attempts == 1  # no retry on 5xx


@pytest.mark.asyncio
async def test_stream_completion_does_not_retry_on_401():
    """Auth failures are not transient — never retry."""
    fake = _FakeStreamingClientWithStatusSeq([], status_codes_seq=[401])
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass
    assert fake.attempts == 1


@pytest.mark.asyncio
async def test_stream_completion_429_honours_retry_after_header(monkeypatch):
    """When the upstream sends a numeric Retry-After header on a 429,
    we must use it as the delay rather than our exponential default."""
    captured: list[float] = []

    async def capture_sleep(delay: float) -> None:
        captured.append(delay)

    monkeypatch.setattr(
        "backend.modules.llm._adapters._openrouter_http.asyncio.sleep",
        capture_sleep,
    )

    fake = _FakeStreamingClientWithStatusSeq(
        ['data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
         "data: [DONE]"],
        status_codes_seq=[429, 200],
        response_headers={"Retry-After": "7"},
    )
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass

    # Filter out the zero-delay yield-control sleeps emitted by
    # _FakeStreamResponse.aiter_lines; we only care about real backoff
    # waits the adapter inserted between attempts.
    backoff_sleeps = [s for s in captured if s > 0]
    assert backoff_sleeps == [7.0]


def _make_app_with_test_route(monkeypatch):
    """Mount the adapter router under a stubbed dependency that
    returns a pre-baked ResolvedConnection — no real auth or DB."""
    app = FastAPI()
    router = OpenRouterHttpAdapter.router()
    assert router is not None

    from backend.modules.llm._resolver import resolve_connection_for_user

    async def fake_resolver():
        return _resolved()

    app.dependency_overrides[resolve_connection_for_user] = fake_resolver
    app.include_router(router, prefix="/api/llm/connections/{connection_id}/adapter")
    return app


@pytest.mark.asyncio
async def test_router_post_test_valid_when_models_returned(monkeypatch):
    app = _make_app_with_test_route(monkeypatch)

    async def fake_fetch(self, c):  # noqa: ARG001
        return [object()]  # any non-empty list

    monkeypatch.setattr(OpenRouterHttpAdapter, "fetch_models", fake_fetch)

    with TestClient(app) as client:
        r = client.post("/api/llm/connections/premium:openrouter/adapter/test")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["error"] is None


@pytest.mark.asyncio
async def test_router_post_test_invalid_when_no_models(monkeypatch):
    app = _make_app_with_test_route(monkeypatch)

    async def fake_fetch(self, c):  # noqa: ARG001
        return []

    monkeypatch.setattr(OpenRouterHttpAdapter, "fetch_models", fake_fetch)

    with TestClient(app) as client:
        r = client.post("/api/llm/connections/premium:openrouter/adapter/test")
    body = r.json()
    assert body["valid"] is False
    assert body["error"]  # non-empty string


_MODELS_USER_RESPONSE_LOW_CONTEXT = {
    "data": [
        {
            "id": "tiny/8k",
            "name": "Tiny 8k",
            "context_length": 8192,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "edge/just-below",
            "name": "Just Below 80k",
            "context_length": 79_999,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "edge/at-threshold",
            "name": "At 80k",
            "context_length": 80_000,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "okay/128k",
            "name": "Big 128k",
            "context_length": 128_000,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "broken/missing-context",
            "name": "No Context",
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClientLowContext(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(_MODELS_USER_RESPONSE_LOW_CONTEXT).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_drops_models_below_min_context_window():
    """Mirror nano-gpt's MIN_CONTEXT=80_000 — sub-80k models give us no
    breathing room in the context window once history accumulates."""
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClientLowContext,
    ):
        models = await a.fetch_models(_resolved())

    ids = {m.model_id for m in models}
    # Threshold is inclusive: exactly 80_000 survives. Anything below is dropped.
    assert ids == {"edge/at-threshold", "okay/128k"}
