import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

from shared.dtos.inference import (
    CompletionMessage,
    ContentPart,
    CompletionRequest,
)
from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter


class _Probe(OllamaBaseAdapter):
    provider_id = "probe"
    provider_display_name = "Probe"
    requires_key_for_listing = False

    def _auth_headers(self, api_key):  # noqa: D401
        return {}

    async def validate_key(self, api_key):
        return True


def _make_request(**overrides):
    base = dict(
        model="llama3.2",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
        temperature=None,
        tools=None,
        supports_reasoning=False,
        reasoning_enabled=False,
    )
    base.update(overrides)
    return CompletionRequest(**base)


def test_build_chat_payload_minimal():
    payload = _Probe._build_chat_payload(_make_request())
    assert payload["model"] == "llama3.2"
    assert payload["stream"] is True
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert "think" not in payload
    assert "options" not in payload
    assert "tools" not in payload


def test_build_chat_payload_with_thinking_and_temperature():
    payload = _Probe._build_chat_payload(
        _make_request(supports_reasoning=True, reasoning_enabled=True, temperature=0.7),
    )
    assert payload["think"] is True
    assert payload["options"] == {"temperature": 0.7}


# ---------------------------------------------------------------------------
# _is_refusal_reason unit tests
# ---------------------------------------------------------------------------

def test_is_refusal_reason_known_values():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason("content_filter") is True
    assert _is_refusal_reason("refusal") is True


def test_is_refusal_reason_is_case_insensitive():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason("Content_Filter") is True
    assert _is_refusal_reason("REFUSAL") is True


def test_is_refusal_reason_normal_termination():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason("stop") is False
    assert _is_refusal_reason("length") is False


def test_is_refusal_reason_empty_or_none():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason(None) is False
    assert _is_refusal_reason("") is False


# ---------------------------------------------------------------------------
# Stream-parsing tests via mocked httpx
#
# There was no existing NDJSON-feeding helper in this file. The mechanism
# built here mocks httpx.AsyncClient.stream as an async context manager
# whose response object provides aiter_lines() as an async generator over
# the supplied list of NDJSON strings. This exactly mirrors the path taken
# inside OllamaBaseAdapter.stream_completion.
# ---------------------------------------------------------------------------

def _chunks_to_ndjson(chunks: list[dict]) -> list[str]:
    return [json.dumps(c) for c in chunks]


async def _collect_events_from_ndjson(ndjson: list[str]):
    """Feed synthetic NDJSON lines through the adapter and collect all events."""

    async def _aiter_lines():
        for line in ndjson:
            yield line

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = _aiter_lines

    @asynccontextmanager
    async def _mock_stream(*args, **kwargs):
        yield mock_resp

    adapter = _Probe("http://localhost:11434")
    with patch.object(adapter._client, "stream", _mock_stream):
        events = []
        async for event in adapter.stream_completion(api_key=None, request=_make_request()):
            events.append(event)
    return events


@pytest.mark.asyncio
async def test_ollama_normal_completion_emits_stream_done():
    """done_reason='stop' should yield StreamDone and no log line."""
    from backend.modules.llm._adapters._events import StreamDone, StreamRefused
    ndjson = _chunks_to_ndjson([
        {"message": {"content": "hello"}, "done": False},
        {"done": True, "done_reason": "stop",
         "prompt_eval_count": 5, "eval_count": 2},
    ])
    events = await _collect_events_from_ndjson(ndjson)
    assert any(isinstance(e, StreamDone) for e in events)
    assert not any(isinstance(e, StreamRefused) for e in events)


@pytest.mark.asyncio
async def test_ollama_content_filter_yields_stream_refused():
    from backend.modules.llm._adapters._events import StreamDone, StreamRefused
    ndjson = _chunks_to_ndjson([
        {"message": {"content": "I decline"}, "done": False},
        {"done": True, "done_reason": "content_filter", "message": {}},
    ])
    events = await _collect_events_from_ndjson(ndjson)
    refused = [e for e in events if isinstance(e, StreamRefused)]
    assert len(refused) == 1
    assert refused[0].reason == "content_filter"
    assert refused[0].refusal_text is None
    # Must not also emit StreamDone
    assert not any(isinstance(e, StreamDone) for e in events)


@pytest.mark.asyncio
async def test_ollama_refusal_with_body():
    from backend.modules.llm._adapters._events import StreamRefused
    ndjson = _chunks_to_ndjson([
        {"done": True, "done_reason": "refusal",
         "message": {"refusal": "I can't help with that"}},
    ])
    events = await _collect_events_from_ndjson(ndjson)
    refused = [e for e in events if isinstance(e, StreamRefused)]
    assert len(refused) == 1
    assert refused[0].refusal_text == "I can't help with that"


@pytest.mark.asyncio
async def test_ollama_unknown_done_reason_emits_done_and_logs(caplog):
    from backend.modules.llm._adapters._events import StreamDone, StreamRefused
    ndjson = _chunks_to_ndjson([
        {"done": True, "done_reason": "something_new"},
    ])
    with caplog.at_level("INFO"):
        events = await _collect_events_from_ndjson(ndjson)
    assert any(isinstance(e, StreamDone) for e in events)
    assert not any(isinstance(e, StreamRefused) for e in events)
    assert any("ollama_base.done_reason" in m and "something_new" in m
               for m in caplog.messages)


@pytest.mark.asyncio
async def test_ollama_vanilla_done_reasons_do_not_log(caplog):
    ndjson = _chunks_to_ndjson([
        {"done": True, "done_reason": "stop"},
    ])
    with caplog.at_level("INFO"):
        await _collect_events_from_ndjson(ndjson)
    assert not any("ollama_base.done_reason" in m for m in caplog.messages)
