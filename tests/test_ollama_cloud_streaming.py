import json

import httpx
import pytest
import respx

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamError,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolCallResult,
    ToolDefinition,
)

BASE_URL = "https://test.ollama.com"
CHAT_URL = f"{BASE_URL}/api/chat"


@pytest.fixture
def adapter() -> OllamaCloudAdapter:
    return OllamaCloudAdapter(base_url=BASE_URL)


def _make_request(model: str = "qwen3:32b", text: str = "hi") -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[CompletionMessage(role="user", content=[ContentPart(type="text", text=text)])],
    )


def _ndjson(*chunks: dict) -> str:
    return "\n".join(json.dumps(c) for c in chunks)


async def _collect(adapter: OllamaCloudAdapter, request: CompletionRequest | None = None):
    events = []
    async for event in adapter.stream_completion("test-key", request or _make_request()):
        events.append(event)
    return events


@respx.mock
async def test_streams_content_deltas(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"message": {"role": "assistant", "content": " world"}, "done": False},
        {"done": True, "prompt_eval_count": 10, "eval_count": 5},
    )
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=body))

    events = await _collect(adapter)

    assert events[0] == ContentDelta(delta="Hello")
    assert events[1] == ContentDelta(delta=" world")
    assert events[2] == StreamDone(input_tokens=10, output_tokens=5)


@respx.mock
async def test_streams_thinking_deltas(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"role": "assistant", "content": "", "thinking": "Let me think"}, "done": False},
        {"message": {"role": "assistant", "content": "", "thinking": " about this"}, "done": False},
        {"message": {"role": "assistant", "content": "Answer"}, "done": False},
        {"done": True, "prompt_eval_count": 8, "eval_count": 12},
    )
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=body))

    events = await _collect(adapter)

    assert events[0] == ThinkingDelta(delta="Let me think")
    assert events[1] == ThinkingDelta(delta=" about this")
    assert events[2] == ContentDelta(delta="Answer")
    assert events[3] == StreamDone(input_tokens=8, output_tokens=12)


@respx.mock
async def test_streams_tool_calls(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "get_weather", "arguments": {"city": "London"}}},
                ],
            },
            "done": False,
        },
        {"done": True, "prompt_eval_count": 5, "eval_count": 3},
    )
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=body))

    events = await _collect(adapter)

    assert isinstance(events[0], ToolCallEvent)
    assert events[0].name == "get_weather"
    assert json.loads(events[0].arguments) == {"city": "London"}
    assert events[0].id.startswith("call_")
    assert len(events[0].id) == 17  # "call_" + 12 hex chars
    assert events[1] == StreamDone(input_tokens=5, output_tokens=3)


@respx.mock
async def test_content_and_tool_call_in_same_chunk(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {
            "message": {
                "role": "assistant",
                "content": "Using tool",
                "tool_calls": [
                    {"function": {"name": "search", "arguments": {"q": "test"}}},
                ],
            },
            "done": False,
        },
        {"done": True},
    )
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=body))

    events = await _collect(adapter)

    assert events[0] == ContentDelta(delta="Using tool")
    assert isinstance(events[1], ToolCallEvent)
    assert events[1].name == "search"
    assert events[2] == StreamDone()


@respx.mock
async def test_handles_eof_without_done(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"role": "assistant", "content": "partial"}, "done": False},
    )
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=body))

    events = await _collect(adapter)

    assert events[0] == ContentDelta(delta="partial")
    assert events[1] == StreamDone()


@respx.mock
async def test_returns_error_on_401(adapter: OllamaCloudAdapter):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(401))

    events = await _collect(adapter)

    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "invalid_api_key"


@respx.mock
async def test_returns_error_on_500(adapter: OllamaCloudAdapter):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(500))

    events = await _collect(adapter)

    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "provider_unavailable"


@respx.mock
async def test_sends_correct_request_payload(adapter: OllamaCloudAdapter):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=_ndjson({"done": True})))

    request = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="system", content=[ContentPart(type="text", text="You are helpful")]),
            CompletionMessage(
                role="user",
                content=[
                    ContentPart(type="text", text="Describe this"),
                    ContentPart(type="image", data="abc123base64", media_type="image/png"),
                ],
            ),
        ],
        temperature=0.7,
        reasoning_enabled=True,
    )

    await _collect(adapter, request)

    req = respx.calls.last.request
    payload = json.loads(req.content)

    assert payload["model"] == "qwen3:32b"
    assert payload["stream"] is True
    assert payload["think"] is True
    assert payload["options"]["temperature"] == 0.7

    # System message
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "You are helpful"

    # User message with image
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"] == "Describe this"
    assert payload["messages"][1]["images"] == ["abc123base64"]

    # Auth header
    assert req.headers["Authorization"] == "Bearer test-key"


@respx.mock
async def test_sends_tool_definitions(adapter: OllamaCloudAdapter):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=_ndjson({"done": True})))

    request = CompletionRequest(
        model="qwen3:32b",
        messages=[CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])],
        tools=[
            ToolDefinition(
                name="get_weather",
                description="Get weather for a city",
                parameters={"type": "object", "properties": {"city": {"type": "string"}}},
            ),
        ],
    )

    await _collect(adapter, request)

    payload = json.loads(respx.calls.last.request.content)
    assert len(payload["tools"]) == 1
    assert payload["tools"][0]["function"]["name"] == "get_weather"


@respx.mock
async def test_maps_tool_result_messages(adapter: OllamaCloudAdapter):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, text=_ndjson({"done": True})))

    request = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="user", content=[ContentPart(type="text", text="What is the weather?")]),
            CompletionMessage(
                role="assistant",
                content=[ContentPart(type="text", text="")],
                tool_calls=[
                    ToolCallResult(id="call_abc", name="get_weather", arguments='{"city": "London"}'),
                ],
            ),
            CompletionMessage(
                role="tool",
                content=[ContentPart(type="text", text='{"temp": 15}')],
                tool_call_id="call_abc",
            ),
        ],
    )

    await _collect(adapter, request)

    payload = json.loads(respx.calls.last.request.content)

    # Assistant message should have tool_calls
    assistant_msg = payload["messages"][1]
    assert assistant_msg["role"] == "assistant"
    assert len(assistant_msg["tool_calls"]) == 1
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "get_weather"
    assert assistant_msg["tool_calls"][0]["function"]["arguments"] == {"city": "London"}

    # Tool result message
    tool_msg = payload["messages"][2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == '{"temp": 15}'
