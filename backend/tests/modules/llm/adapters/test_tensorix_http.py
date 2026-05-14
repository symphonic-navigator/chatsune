"""Tests for the Tensorix HTTP adapter."""
from __future__ import annotations

import json as _json
from datetime import UTC, datetime

import pytest

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamError,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._tensorix_http import (
    _TENSORIX_MODELS,
    _TENSORIX_MODELS_BY_ID,
    _TensorixModelEntry,
    _build_chat_payload,
    _chunk_to_events,
    _parse_sse_line,
    _SSE_DONE,
    _ToolCallAccumulator,
    TensorixHttpAdapter,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._capabilities import CapabilityHint
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


# ---------------------------------------------------------------------------
# Task 5: Curated table.
# ---------------------------------------------------------------------------


def test_tensorix_models_table_has_exactly_seven_entries():
    assert len(_TENSORIX_MODELS) == 7
    ids = {m.model_id for m in _TENSORIX_MODELS}
    assert ids == {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "kimi-k2-6",
        "glm-5-1",
        "glm-5",
        "deepseek-v3-2",
        "glm-4-6",
    }


def test_tensorix_models_upstream_slugs_match_api_reality():
    by_id = {m.model_id: m.upstream_slug for m in _TENSORIX_MODELS}
    assert by_id["deepseek-v4-flash"] == "deepseek/deepseek-v4-flash"
    assert by_id["deepseek-v4-pro"] == "deepseek/deepseek-v4-pro"
    assert by_id["kimi-k2-6"] == "moonshotai/Kimi-K2.6"
    assert by_id["glm-5-1"] == "z-ai/glm-5.1"
    assert by_id["glm-5"] == "z-ai/glm-5"
    assert by_id["deepseek-v3-2"] == "deepseek/deepseek-v3.2"
    assert by_id["glm-4-6"] == "z-ai/glm-4.6"


def test_tensorix_models_all_first_class():
    assert all(m.first_class_support for m in _TENSORIX_MODELS)


def test_tensorix_models_reasoning_mode_assignments():
    by_id = {m.model_id: m.reasoning_mode for m in _TENSORIX_MODELS}
    assert by_id["deepseek-v4-flash"] == "binary"
    assert by_id["deepseek-v4-pro"] == "stepped"
    assert by_id["kimi-k2-6"] == "binary"
    assert by_id["glm-5-1"] == "stepped"
    assert by_id["glm-5"] == "stepped"
    assert by_id["deepseek-v3-2"] == "binary"
    assert by_id["glm-4-6"] == "binary"


def test_tensorix_models_vision_only_for_kimi():
    by_id = {m.model_id: m.supports_vision for m in _TENSORIX_MODELS}
    assert by_id["kimi-k2-6"] is True
    for k, v in by_id.items():
        if k != "kimi-k2-6":
            assert v is False, f"{k} should not advertise vision"


def test_tensorix_models_all_support_tools():
    assert all(m.supports_tool_calls for m in _TENSORIX_MODELS)


def test_tensorix_models_by_id_lookup_consistent():
    for m in _TENSORIX_MODELS:
        assert _TENSORIX_MODELS_BY_ID[m.model_id] is m


# ---------------------------------------------------------------------------
# Task 6: Capability hint.
# ---------------------------------------------------------------------------


def test_capability_hint_binary_model_has_no_effort_buckets():
    hint = TensorixHttpAdapter().capability_hint("deepseek-v4-flash")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.effort is None  # binary -> no bucket selector
    assert hint.reasoning.default_on is False
    assert hint.tools.supported is True
    assert hint.first_class_support is True


def test_capability_hint_stepped_model_has_three_effort_buckets():
    hint = TensorixHttpAdapter().capability_hint("deepseek-v4-pro")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.effort is not None
    assert hint.reasoning.effort.buckets == ["low", "medium", "high"]
    assert hint.reasoning.effort.default_bucket == "medium"
    assert hint.reasoning.default_on is False


def test_capability_hint_unknown_model_returns_none():
    assert TensorixHttpAdapter().capability_hint("not-a-tensorix-model") is None


def test_capability_hint_kimi_advertises_vision_via_meta_not_hint():
    # The vision flag rides on ModelMetaDto.supports_vision, not on
    # CapabilityHint — confirm capability_hint still returns the
    # expected reasoning/tools shape for Kimi.
    hint = TensorixHttpAdapter().capability_hint("kimi-k2-6")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.effort is None  # Kimi is binary


# ---------------------------------------------------------------------------
# Task 7: fetch_models.
# ---------------------------------------------------------------------------


def _make_resolved_connection() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="premium:tensorix",
        user_id="user-1",
        adapter_type="tensorix_http",
        display_name="Tensorix",
        slug="tensorix",
        config={
            "url": "https://api.tensorix.ai/v1",
            "api_key": "sk-test",
        },
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_fetch_models_returns_seven_curated_entries():
    metas = await TensorixHttpAdapter().fetch_models(_make_resolved_connection())
    assert len(metas) == 7
    ids = {m.model_id for m in metas}
    assert "deepseek-v4-flash" in ids
    assert "glm-4-6" in ids


@pytest.mark.asyncio
async def test_fetch_models_propagates_connection_metadata():
    metas = await TensorixHttpAdapter().fetch_models(_make_resolved_connection())
    for m in metas:
        assert m.connection_id == "premium:tensorix"
        assert m.connection_slug == "tensorix"
        assert m.connection_display_name == "Tensorix"


@pytest.mark.asyncio
async def test_fetch_models_carries_first_class_and_billing():
    metas = await TensorixHttpAdapter().fetch_models(_make_resolved_connection())
    for m in metas:
        assert m.first_class_support is True
        assert m.billing_category == "pay_per_token"
        assert m.is_deprecated is False


# ---------------------------------------------------------------------------
# Task 8: _build_chat_payload.
# ---------------------------------------------------------------------------


def _make_request(
    *,
    model_id: str,
    reasoning_mode: str = "off",
    reasoning_effort: str | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        model=model_id,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hello")],
            ),
        ],
        temperature=0.7,
        tools=[],
        reasoning=ReasoningCapability(kind="optional", default_on=False),
        tools_capability=ToolCapability(supported=True, exclusive_with_reasoning=False),
        extras=ChatSessionExtras(
            tools_enabled=False,
            reasoning_mode=reasoning_mode,  # type: ignore[arg-type]
            reasoning_effort=reasoning_effort,
        ),
    )


def test_payload_maps_model_id_to_upstream_slug():
    payload = _build_chat_payload(_make_request(model_id="deepseek-v4-flash"))
    assert payload["model"] == "deepseek/deepseek-v4-flash"


def test_payload_sets_stream_and_include_usage():
    payload = _build_chat_payload(_make_request(model_id="kimi-k2-6"))
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_payload_binary_reasoning_off_omits_effort():
    payload = _build_chat_payload(
        _make_request(model_id="deepseek-v4-flash", reasoning_mode="off"),
    )
    assert "reasoning_effort" not in payload


def test_payload_binary_reasoning_on_sets_effort_high():
    payload = _build_chat_payload(
        _make_request(model_id="deepseek-v4-flash", reasoning_mode="on"),
    )
    assert payload["reasoning_effort"] == "high"


def test_payload_stepped_reasoning_off_omits_effort():
    payload = _build_chat_payload(
        _make_request(model_id="deepseek-v4-pro", reasoning_mode="off"),
    )
    assert "reasoning_effort" not in payload


def test_payload_stepped_reasoning_passes_through_low():
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort="low",
    ))
    assert payload["reasoning_effort"] == "low"


def test_payload_stepped_reasoning_passes_through_medium():
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort="medium",
    ))
    assert payload["reasoning_effort"] == "medium"


def test_payload_stepped_reasoning_passes_through_high():
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort="high",
    ))
    assert payload["reasoning_effort"] == "high"


def test_payload_stepped_with_no_effort_falls_back_to_default_bucket():
    # ``reasoning_mode=on`` with no explicit bucket -> use the model's
    # default_bucket ("medium").
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort=None,
    ))
    assert payload["reasoning_effort"] == "medium"


def test_payload_unknown_model_falls_back_to_deepseek_v3_2():
    payload = _build_chat_payload(_make_request(model_id="not-a-real-model"))
    assert payload["model"] == "deepseek/deepseek-v3.2"


# ---------------------------------------------------------------------------
# Task 9: SSE chunk parser.
# ---------------------------------------------------------------------------


def test_parse_sse_line_data_json():
    parsed = _parse_sse_line('data: {"choices": []}')
    assert parsed == {"choices": []}


def test_parse_sse_line_done():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_blank_is_none():
    assert _parse_sse_line("") is None


def test_parse_sse_line_garbage_is_none():
    assert _parse_sse_line('data: {not json}') is None


def test_chunk_emits_content_delta():
    chunk = {
        "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [ContentDelta(delta="Hello")]


def test_chunk_emits_thinking_delta_from_reasoning_content():
    chunk = {
        "choices": [{
            "delta": {"reasoning_content": "Let me think..."},
            "finish_reason": None,
        }],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [ThinkingDelta(delta="Let me think...")]


def test_chunk_emits_both_thinking_and_visible_in_order():
    chunk = {
        "choices": [{
            "delta": {
                "reasoning_content": "thinking",
                "content": "answer",
            },
            "finish_reason": None,
        }],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [
        ThinkingDelta(delta="thinking"),
        ContentDelta(delta="answer"),
    ]


def test_tool_call_accumulator_finalises_on_finish_reason():
    acc = _ToolCallAccumulator()
    # First chunk: id + name fragment.
    _chunk_to_events({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_abc",
                    "function": {"name": "get_weather", "arguments": '{"loc'},
                }],
            },
            "finish_reason": None,
        }],
    }, acc)
    # Second chunk: rest of arguments + finish.
    events = _chunk_to_events({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": '":"Tokyo"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }, acc)
    assert events == [ToolCallEvent(
        id="call_abc",
        name="get_weather",
        arguments='{"loc":"Tokyo"}',
    )]


def test_chunk_emits_stream_done_on_usage_chunk():
    chunk = {
        "choices": [],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 34,
            "completion_tokens_details": {"reasoning_tokens": 5},
        },
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [StreamDone(
        input_tokens=12,
        output_tokens=34,
        reasoning_tokens=5,
    )]


def test_chunk_emits_refused_on_content_filter():
    chunk = {
        "choices": [{
            "delta": {"refusal": "I cannot help with that."},
            "finish_reason": "content_filter",
        }],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert any(isinstance(e, StreamRefused) for e in events)


# ---------------------------------------------------------------------------
# Task 10: stream_completion.
# ---------------------------------------------------------------------------


class _MockAsyncStream:
    """Mimics httpx.Response under ``client.stream(...)``."""
    def __init__(self, lines: list[str], status_code: int = 200, headers: dict | None = None):
        self._lines = lines
        self.status_code = status_code
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def aiter_lines(self):
        async def _gen():
            for line in self._lines:
                yield line
        return _gen()

    async def aread(self):
        return b""


class _MockClient:
    def __init__(self, response: _MockAsyncStream):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def stream(self, method, url, json=None, headers=None):
        return self._response


@pytest.mark.asyncio
async def test_stream_completion_yields_content_then_done(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}',
        'data: [DONE]',
    ]
    mock_response = _MockAsyncStream(lines)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockClient(mock_response),
    )

    adapter = TensorixHttpAdapter()
    events = []
    async for ev in adapter.stream_completion(
        _make_resolved_connection(),
        _make_request(model_id="deepseek-v4-flash"),
    ):
        events.append(ev)

    assert any(isinstance(e, ContentDelta) and e.delta == "Hi" for e in events)
    assert any(isinstance(e, StreamDone) for e in events)


@pytest.mark.asyncio
async def test_stream_completion_401_emits_invalid_api_key(monkeypatch):
    mock_response = _MockAsyncStream(lines=[], status_code=401)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockClient(mock_response),
    )
    adapter = TensorixHttpAdapter()
    events = []
    async for ev in adapter.stream_completion(
        _make_resolved_connection(),
        _make_request(model_id="deepseek-v4-flash"),
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "invalid_api_key"


# ---------------------------------------------------------------------------
# Task 11: probe / test endpoint.
# ---------------------------------------------------------------------------


class _MockProbeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    async def aread(self):
        return _json.dumps(self._body).encode()

    def json(self):
        return self._body


class _MockProbeClient:
    def __init__(self, response: _MockProbeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None):
        return self._response


@pytest.mark.asyncio
async def test_adapter_test_endpoint_returns_valid_when_curated_slug_present(monkeypatch):
    body = {"data": [{"model_name": "deepseek/deepseek-v4-flash"}]}
    response = _MockProbeResponse(200, body)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockProbeClient(response),
    )

    from backend.modules.llm._adapters._tensorix_http import _probe_tensorix

    result = await _probe_tensorix(
        url="https://api.tensorix.ai/v1", api_key="sk-test",
    )
    assert result == {"valid": True, "error": None}


@pytest.mark.asyncio
async def test_adapter_test_endpoint_401_returns_rejected(monkeypatch):
    response = _MockProbeResponse(401, {})
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockProbeClient(response),
    )
    from backend.modules.llm._adapters._tensorix_http import _probe_tensorix

    result = await _probe_tensorix(
        url="https://api.tensorix.ai/v1", api_key="bad-key",
    )
    assert result["valid"] is False
    assert "rejected" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_adapter_test_endpoint_zero_curated_slugs_returns_drift_error(monkeypatch):
    # 200 response that lists models, but none of ours -> drift canary fires.
    body = {"data": [{"model_name": "totally/different-model"}]}
    response = _MockProbeResponse(200, body)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockProbeClient(response),
    )
    from backend.modules.llm._adapters._tensorix_http import _probe_tensorix

    result = await _probe_tensorix(
        url="https://api.tensorix.ai/v1", api_key="sk-test",
    )
    assert result["valid"] is False
    assert "curated" in (result["error"] or "").lower()
