# Inference Phase 1: Minimal Streaming Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream LLM inference tokens from Ollama Cloud to the frontend over the existing WebSocket connection -- end-to-end, no tools, no context management yet.

**Architecture:** A `chat.send` WebSocket message triggers the chat module, which resolves the user's API key via the LLM module, streams from the Ollama Cloud adapter, emits delta events over WebSocket, and persists the resulting messages in MongoDB. Cancellation is supported via `chat.cancel`. One stream at a time per user (serialised via asyncio.Lock, released during `requires_action`).

**Tech Stack:** FastAPI, motor (MongoDB), httpx (streaming HTTP), redis (event bus), pydantic v2, pytest + respx (tests)

**Constraint:** `frontend/` must not be modified -- frontend work is happening in parallel.

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `shared/dtos/chat.py` | Chat DTOs: `ChatSessionDto`, `ChatMessageDto`, `ChatSendMessage`, `ChatToolResultMessage` |
| `shared/dtos/inference.py` | Inference models: `ContentPart`, `CompletionMessage`, `ToolDefinition`, `CompletionRequest` |
| `shared/events/chat.py` | Chat events: stream lifecycle, deltas, errors |
| `backend/modules/chat/__init__.py` | Public API: `ChatService`, `router`, `init_indexes` |
| `backend/modules/chat/_handlers.py` | REST endpoints for session CRUD |
| `backend/modules/chat/_repository.py` | MongoDB: `chat_sessions`, `chat_messages` collections |
| `backend/modules/chat/_models.py` | Internal document models: `ChatSessionDocument`, `ChatMessageDocument` |
| `backend/modules/chat/_inference.py` | `InferenceRunner`: streaming loop, cancellation, per-user lock |
| `backend/modules/llm/_adapters/_events.py` | Provider stream events: `ContentDelta`, `ThinkingDelta`, `ToolCallEvent`, `StreamDone`, `StreamError` |
| `tests/test_provider_stream_events.py` | Unit tests for provider event models |
| `tests/test_ollama_cloud_streaming.py` | Unit tests for Ollama adapter streaming (respx mocked) |
| `tests/test_inference_runner.py` | Unit tests for InferenceRunner (adapter mocked) |
| `tests/test_chat_sessions.py` | Integration tests for session CRUD endpoints |
| `tests/test_chat_repository.py` | Unit tests for ChatRepository |

### Modified Files

| File | Change |
|---|---|
| `shared/topics.py` | Add chat and inference topic constants |
| `backend/modules/llm/_adapters/_base.py` | Add abstract `stream_completion` method |
| `backend/modules/llm/_adapters/_ollama_cloud.py` | Implement `stream_completion` with NDJSON parsing |
| `backend/modules/llm/__init__.py` | Expose `stream_completion` public function + `LlmCredentialNotFoundError` |
| `backend/ws/event_bus.py` | Add fan-out rules for chat events (delta events skip Redis persistence) |
| `backend/ws/router.py` | Dispatch `chat.send`, `chat.tool_result`, `chat.cancel` messages |
| `backend/main.py` | Register chat module router + init_indexes |

---

## Task 1: Shared Inference Models

**Files:**
- Create: `shared/dtos/inference.py`
- Create: `tests/test_shared_inference_contracts.py`

- [ ] **Step 1: Write tests for inference DTOs**

```python
# tests/test_shared_inference_contracts.py
from shared.dtos.inference import ContentPart, CompletionMessage, ToolDefinition, CompletionRequest


def test_text_content_part():
    part = ContentPart(type="text", text="hello")
    assert part.type == "text"
    assert part.text == "hello"
    assert part.data is None


def test_image_content_part():
    part = ContentPart(type="image", data="base64data", media_type="image/png")
    assert part.type == "image"
    assert part.data == "base64data"


def test_completion_message_user():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hi")],
    )
    assert msg.role == "user"
    assert len(msg.content) == 1
    assert msg.tool_calls is None
    assert msg.tool_call_id is None


def test_completion_message_tool():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"result": 42}')],
        tool_call_id="call_abc",
    )
    assert msg.role == "tool"
    assert msg.tool_call_id == "call_abc"


def test_tool_definition():
    td = ToolDefinition(
        name="web_search",
        description="Search the web",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    assert td.type == "function"
    assert td.name == "web_search"


def test_completion_request_minimal():
    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])
        ],
    )
    assert req.model == "qwen3:32b"
    assert req.temperature is None
    assert req.tools is None
    assert req.reasoning_enabled is False


def test_completion_request_full():
    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="system", content=[ContentPart(type="text", text="You are helpful.")]),
            CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")]),
        ],
        temperature=0.7,
        tools=[
            ToolDefinition(name="search", description="Search", parameters={"type": "object", "properties": {}}),
        ],
        reasoning_enabled=True,
    )
    assert req.temperature == 0.7
    assert len(req.tools) == 1
    assert req.reasoning_enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_shared_inference_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.dtos.inference'`

- [ ] **Step 3: Implement inference DTOs**

```python
# shared/dtos/inference.py
from typing import Literal

from pydantic import BaseModel


class ContentPart(BaseModel):
    type: Literal["text", "image"]
    text: str | None = None
    data: str | None = None           # base64 for images
    media_type: str | None = None     # e.g. "image/png"


class ToolCallResult(BaseModel):
    id: str
    name: str
    arguments: str                    # JSON string


class CompletionMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]
    tool_calls: list[ToolCallResult] | None = None
    tool_call_id: str | None = None   # for role="tool" messages


class ToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    name: str
    description: str
    parameters: dict                  # JSON Schema object


class CompletionRequest(BaseModel):
    model: str                        # provider-specific slug
    messages: list[CompletionMessage]
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None
    reasoning_enabled: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest tests/test_shared_inference_contracts.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
git add shared/dtos/inference.py tests/test_shared_inference_contracts.py
git commit -m "Add shared inference DTOs (ContentPart, CompletionMessage, CompletionRequest)"
```

---

## Task 2: Provider Stream Events

**Files:**
- Create: `backend/modules/llm/_adapters/_events.py`
- Create: `tests/test_provider_stream_events.py`

- [ ] **Step 1: Write tests for provider stream events**

```python
# tests/test_provider_stream_events.py
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ThinkingDelta,
    ToolCallEvent,
    StreamDone,
    StreamError,
)


def test_content_delta():
    e = ContentDelta(delta="Hello")
    assert e.delta == "Hello"


def test_thinking_delta():
    e = ThinkingDelta(delta="Let me think...")
    assert e.delta == "Let me think..."


def test_tool_call_event():
    e = ToolCallEvent(id="call_abc", name="web_search", arguments='{"query": "test"}')
    assert e.id == "call_abc"
    assert e.name == "web_search"
    assert e.arguments == '{"query": "test"}'


def test_stream_done_with_usage():
    e = StreamDone(input_tokens=150, output_tokens=42)
    assert e.input_tokens == 150
    assert e.output_tokens == 42


def test_stream_done_without_usage():
    e = StreamDone()
    assert e.input_tokens is None
    assert e.output_tokens is None


def test_stream_error():
    e = StreamError(error_code="invalid_api_key", message="Bad key")
    assert e.error_code == "invalid_api_key"
    assert e.message == "Bad key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_provider_stream_events.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement provider stream events**

```python
# backend/modules/llm/_adapters/_events.py
from pydantic import BaseModel


class ContentDelta(BaseModel):
    delta: str


class ThinkingDelta(BaseModel):
    delta: str


class ToolCallEvent(BaseModel):
    id: str                           # synthetic ID generated by adapter
    name: str
    arguments: str                    # JSON string


class StreamDone(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class StreamError(BaseModel):
    error_code: str                   # "invalid_api_key", "provider_unavailable", "model_not_found"
    message: str


ProviderStreamEvent = ContentDelta | ThinkingDelta | ToolCallEvent | StreamDone | StreamError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest tests/test_provider_stream_events.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
git add backend/modules/llm/_adapters/_events.py tests/test_provider_stream_events.py
git commit -m "Add provider stream event models (ContentDelta, ThinkingDelta, StreamDone, StreamError)"
```

---

## Task 3: Extend BaseAdapter with stream_completion

**Files:**
- Modify: `backend/modules/llm/_adapters/_base.py`

- [ ] **Step 1: Add abstract stream_completion method**

Add to `BaseAdapter` class, after the existing `fetch_models` method:

```python
# Add these imports at the top of _base.py
from collections.abc import AsyncIterator

from shared.dtos.inference import CompletionRequest
from backend.modules.llm._adapters._events import ProviderStreamEvent
```

Add this method to the `BaseAdapter` class:

```python
    @abstractmethod
    def stream_completion(
        self,
        api_key: str,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream inference events from the upstream provider.

        Yields ProviderStreamEvent variants. The caller consumes the
        iterator and translates events to Chatsune's event envelope.
        """
        ...
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run --project backend pytest tests/test_ollama_cloud_adapter.py -v`
Expected: All PASS (OllamaCloudAdapter must implement stream_completion to remain instantiable -- this will FAIL)

- [ ] **Step 3: Add stub to OllamaCloudAdapter**

Add to `_ollama_cloud.py`, inside the `OllamaCloudAdapter` class, after `_map_to_dto`:

```python
    async def stream_completion(
        self,
        api_key: str,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError("Streaming not yet implemented")
        yield  # makes this an async generator
```

Also add the necessary imports at the top of `_ollama_cloud.py`:

```python
from collections.abc import AsyncIterator

from shared.dtos.inference import CompletionRequest
from backend.modules.llm._adapters._events import ProviderStreamEvent
```

- [ ] **Step 4: Verify existing tests pass again**

Run: `uv run --project backend pytest tests/test_ollama_cloud_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
git add backend/modules/llm/_adapters/_base.py backend/modules/llm/_adapters/_ollama_cloud.py
git commit -m "Add abstract stream_completion to BaseAdapter with OllamaCloud stub"
```

---

## Task 4: Ollama Cloud Streaming Implementation

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_cloud.py`
- Create: `tests/test_ollama_cloud_streaming.py`

- [ ] **Step 1: Write tests for Ollama streaming**

```python
# tests/test_ollama_cloud_streaming.py
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
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart


@pytest.fixture
def adapter() -> OllamaCloudAdapter:
    return OllamaCloudAdapter(base_url="https://test.ollama.com")


def _make_request(model: str = "qwen3:32b", text: str = "hi") -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[
            CompletionMessage(role="user", content=[ContentPart(type="text", text=text)]),
        ],
    )


def _ndjson(*chunks: dict) -> str:
    return "\n".join(json.dumps(c) for c in chunks)


@respx.mock
async def test_streams_content_deltas(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " world"}, "done": False},
        {"done": True, "prompt_eval_count": 10, "eval_count": 5},
    )
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    assert len(events) == 3
    assert isinstance(events[0], ContentDelta)
    assert events[0].delta == "Hello"
    assert isinstance(events[1], ContentDelta)
    assert events[1].delta == " world"
    assert isinstance(events[2], StreamDone)
    assert events[2].input_tokens == 10
    assert events[2].output_tokens == 5


@respx.mock
async def test_streams_thinking_deltas(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"thinking": "Let me think..."}, "done": False},
        {"message": {"content": "The answer is 42."}, "done": False},
        {"done": True, "prompt_eval_count": 20, "eval_count": 10},
    )
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    assert isinstance(events[0], ThinkingDelta)
    assert events[0].delta == "Let me think..."
    assert isinstance(events[1], ContentDelta)
    assert events[1].delta == "The answer is 42."
    assert isinstance(events[2], StreamDone)


@respx.mock
async def test_streams_tool_calls(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"tool_calls": [
            {"function": {"name": "web_search", "arguments": {"query": "test"}}}
        ]}, "done": False},
        {"done": True, "prompt_eval_count": 15, "eval_count": 8},
    )
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    assert isinstance(events[0], ToolCallEvent)
    assert events[0].name == "web_search"
    assert json.loads(events[0].arguments) == {"query": "test"}
    assert events[0].id.startswith("call_")
    assert isinstance(events[1], StreamDone)


@respx.mock
async def test_content_and_tool_call_in_same_chunk(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"content": "Let me search.", "tool_calls": [
            {"function": {"name": "search", "arguments": {"q": "x"}}}
        ]}, "done": False},
        {"done": True, "prompt_eval_count": 5, "eval_count": 3},
    )
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    types = [type(e).__name__ for e in events]
    assert "ContentDelta" in types
    assert "ToolCallEvent" in types
    assert "StreamDone" in types


@respx.mock
async def test_handles_eof_without_done(adapter: OllamaCloudAdapter):
    body = _ndjson(
        {"message": {"content": "partial"}, "done": False},
    )
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    assert isinstance(events[-1], StreamDone)
    assert events[-1].input_tokens is None


@respx.mock
async def test_returns_error_on_401(adapter: OllamaCloudAdapter):
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(401)
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "invalid_api_key"


@respx.mock
async def test_returns_error_on_500(adapter: OllamaCloudAdapter):
    respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    events = []
    async for event in adapter.stream_completion("key", _make_request()):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "provider_unavailable"


@respx.mock
async def test_sends_correct_request_payload(adapter: OllamaCloudAdapter):
    body = _ndjson({"done": True, "prompt_eval_count": 1, "eval_count": 1})
    route = respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="system", content=[ContentPart(type="text", text="Be helpful.")]),
            CompletionMessage(role="user", content=[
                ContentPart(type="text", text="Describe this."),
                ContentPart(type="image", data="abc123", media_type="image/png"),
            ]),
        ],
        temperature=0.5,
        reasoning_enabled=True,
    )

    events = []
    async for event in adapter.stream_completion("test-key", req):
        events.append(event)

    assert route.called
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "qwen3:32b"
    assert sent["stream"] is True
    assert sent["think"] is True
    assert sent["options"]["temperature"] == 0.5
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][0]["content"] == "Be helpful."
    assert sent["messages"][1]["role"] == "user"
    assert sent["messages"][1]["content"] == "Describe this."
    assert sent["messages"][1]["images"] == ["abc123"]
    # Auth header
    assert route.calls[0].request.headers["authorization"] == "Bearer test-key"


@respx.mock
async def test_sends_tool_definitions(adapter: OllamaCloudAdapter):
    from shared.dtos.inference import ToolDefinition

    body = _ndjson({"done": True, "prompt_eval_count": 1, "eval_count": 1})
    route = respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")]),
        ],
        tools=[
            ToolDefinition(
                name="search",
                description="Search the web",
                parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            ),
        ],
    )

    async for _ in adapter.stream_completion("key", req):
        pass

    sent = json.loads(route.calls[0].request.content)
    assert len(sent["tools"]) == 1
    assert sent["tools"][0]["type"] == "function"
    assert sent["tools"][0]["function"]["name"] == "search"


@respx.mock
async def test_maps_tool_result_messages(adapter: OllamaCloudAdapter):
    from shared.dtos.inference import ToolCallResult

    body = _ndjson({"done": True, "prompt_eval_count": 1, "eval_count": 1})
    route = respx.post("https://test.ollama.com/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")]),
            CompletionMessage(
                role="assistant",
                content=[ContentPart(type="text", text="")],
                tool_calls=[ToolCallResult(id="call_1", name="search", arguments='{"q":"x"}')],
            ),
            CompletionMessage(
                role="tool",
                content=[ContentPart(type="text", text='{"results": []}')],
                tool_call_id="call_1",
            ),
        ],
    )

    async for _ in adapter.stream_completion("key", req):
        pass

    sent = json.loads(route.calls[0].request.content)
    # Assistant message has tool_calls
    assert sent["messages"][1]["tool_calls"][0]["function"]["name"] == "search"
    # Tool result: role=tool, content=text, no tool_call_id (Ollama uses positional)
    assert sent["messages"][2]["role"] == "tool"
    assert sent["messages"][2]["content"] == '{"results": []}'
    assert "tool_call_id" not in sent["messages"][2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_ollama_cloud_streaming.py -v`
Expected: FAIL — `NotImplementedError: Streaming not yet implemented`

- [ ] **Step 3: Implement streaming in OllamaCloudAdapter**

Replace the `stream_completion` stub in `backend/modules/llm/_adapters/_ollama_cloud.py` with the full implementation. The complete file after changes:

```python
# backend/modules/llm/_adapters/_ollama_cloud.py
import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamError,
    ThinkingDelta,
    ToolCallEvent,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = 15.0


def _format_parameter_count(value: int | None) -> str | None:
    """Convert raw parameter count to human-readable form (e.g. 675B, 7.5B, 405M)."""
    if not value:
        return None
    if value >= 1_000_000_000_000:
        n = value / 1_000_000_000_000
        return f"{n:g}T"
    if value >= 1_000_000_000:
        n = value / 1_000_000_000
        return f"{n:g}B"
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{n:g}M"
    return None


def _build_display_name(model_name: str) -> str:
    """Convert 'mistral-large-3:675b' to 'Mistral Large 3 (675B)'."""
    colon_idx = model_name.find(":")
    if colon_idx >= 0:
        name_part = model_name[:colon_idx]
        tag = model_name[colon_idx + 1:]
    else:
        name_part = model_name
        tag = None

    title = " ".join(word.capitalize() for word in name_part.split("-"))

    if not tag or tag.lower() == "latest":
        return title
    return f"{title} ({tag.upper()})"


def _map_message(msg: CompletionMessage) -> dict:
    """Translate a CompletionMessage to Ollama's chat message format."""
    result: dict = {"role": msg.role}

    # Content: join text parts, extract images
    texts = []
    images = []
    for part in msg.content:
        if part.type == "text" and part.text:
            texts.append(part.text)
        elif part.type == "image" and part.data:
            images.append(part.data)

    result["content"] = "\n".join(texts)
    if images:
        result["images"] = images

    # Tool calls on assistant messages
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "function": {
                    "name": tc.name,
                    "arguments": json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments,
                }
            }
            for tc in msg.tool_calls
        ]

    # Tool results: no tool_call_id (Ollama uses positional matching)
    return result


def _map_tools(request: CompletionRequest) -> list[dict] | None:
    """Translate tool definitions to Ollama's format."""
    if not request.tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in request.tools
    ]


class OllamaCloudAdapter(BaseAdapter):
    """Ollama Cloud inference adapter."""

    async def validate_key(self, api_key: str) -> bool:
        """Validate key via GET /api/me. Returns True on 200, False on 401/403, raises otherwise."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{self.base_url}/api/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        resp.raise_for_status()

    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch model list from /api/tags, then details from /api/show per model."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tags_resp = await client.get(f"{self.base_url}/api/tags")
            tags_resp.raise_for_status()
            tag_entries = tags_resp.json().get("models", [])

            models: list[ModelMetaDto] = []
            for entry in tag_entries:
                name = entry["name"]
                try:
                    show_resp = await client.post(
                        f"{self.base_url}/api/show",
                        json={"model": name},
                    )
                    show_resp.raise_for_status()
                    detail = show_resp.json()
                except Exception:
                    _log.warning("Failed to fetch details for model '%s'; skipping.", name)
                    continue

                models.append(self._map_to_dto(name, detail))

        return models

    async def stream_completion(
        self,
        api_key: str,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream chat completion from Ollama's /api/chat NDJSON endpoint."""
        payload: dict = {
            "model": request.model,
            "messages": [_map_message(m) for m in request.messages],
            "stream": True,
        }

        options: dict = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if options:
            payload["options"] = options

        if request.reasoning_enabled:
            payload["think"] = True

        tools = _map_tools(request)
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=None,  # streaming: no timeout on response body
                )
            except httpx.ConnectError as e:
                yield StreamError(error_code="provider_unavailable", message=str(e))
                return

            if resp.status_code in (401, 403):
                yield StreamError(error_code="invalid_api_key", message="Invalid API key")
                return

            if resp.status_code != 200:
                yield StreamError(
                    error_code="provider_unavailable",
                    message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
                return

            got_done = False
            for line in resp.text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if chunk.get("done"):
                    got_done = True
                    yield StreamDone(
                        input_tokens=chunk.get("prompt_eval_count"),
                        output_tokens=chunk.get("eval_count"),
                    )
                    break

                message = chunk.get("message", {})

                thinking = message.get("thinking", "")
                if thinking:
                    yield ThinkingDelta(delta=thinking)

                content = message.get("content", "")
                if content:
                    yield ContentDelta(delta=content)

                for tc in message.get("tool_calls", []):
                    func = tc.get("function", {})
                    yield ToolCallEvent(
                        id=f"call_{uuid4().hex[:12]}",
                        name=func.get("name", ""),
                        arguments=json.dumps(func.get("arguments", {})),
                    )

            if not got_done:
                yield StreamDone()

    def _map_to_dto(self, model_name: str, detail: dict) -> ModelMetaDto:
        capabilities = detail.get("capabilities", [])
        model_info = detail.get("model_info", {})
        details = detail.get("details", {})

        # Extract context window from model_info (key ends with .context_length)
        context_window = 0
        for key, value in model_info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                context_window = value
                break

        # Extract parameter count — prefer details.parameter_size, fall back to model_info
        raw_params = None
        param_str = details.get("parameter_size")
        if param_str is not None:
            try:
                raw_params = int(param_str)
            except (ValueError, TypeError):
                pass
        if raw_params is None:
            raw_params = model_info.get("general.parameter_count")

        return ModelMetaDto(
            provider_id="ollama_cloud",
            model_id=model_name,
            display_name=_build_display_name(model_name),
            context_window=context_window,
            supports_reasoning="thinking" in capabilities,
            supports_vision="vision" in capabilities,
            supports_tool_calls="tools" in capabilities,
            parameter_count=_format_parameter_count(raw_params),
            quantisation_level=details.get("quantization_level"),
        )
```

- [ ] **Step 4: Run all adapter tests**

Run: `uv run --project backend pytest tests/test_ollama_cloud_adapter.py tests/test_ollama_cloud_streaming.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
git add backend/modules/llm/_adapters/_ollama_cloud.py tests/test_ollama_cloud_streaming.py
git commit -m "Implement Ollama Cloud streaming with NDJSON parsing and request translation"
```

---

## Task 5: LLM Module Public Streaming API

**Files:**
- Modify: `backend/modules/llm/__init__.py`
- Modify: `backend/modules/llm/_credentials.py` (no change needed -- `get_raw_key` already exists)

- [ ] **Step 1: Expose stream_completion in LLM module public API**

Add to `backend/modules/llm/__init__.py`:

```python
"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

from collections.abc import AsyncIterator

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_BASE_URLS
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.database import get_db
from shared.dtos.inference import CompletionRequest


class LlmCredentialNotFoundError(Exception):
    """User has no API key configured for the requested provider."""


class LlmProviderNotFoundError(Exception):
    """Provider ID is not registered in the adapter registry."""


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await CredentialRepository(db).create_indexes()
    await CurationRepository(db).create_indexes()
    await UserModelConfigRepository(db).create_indexes()


def is_valid_provider(provider_id: str) -> bool:
    """Return True if provider_id is registered in the adapter registry."""
    return provider_id in ADAPTER_REGISTRY


async def stream_completion(
    user_id: str,
    provider_id: str,
    request: CompletionRequest,
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve user's API key, instantiate adapter, stream completion.

    Raises:
        LlmProviderNotFoundError: provider_id not in registry.
        LlmCredentialNotFoundError: user has no key for this provider.
    """
    if provider_id not in ADAPTER_REGISTRY:
        raise LlmProviderNotFoundError(f"Unknown provider: {provider_id}")

    repo = CredentialRepository(get_db())
    cred = await repo.find(user_id, provider_id)
    if not cred:
        raise LlmCredentialNotFoundError(
            f"No API key configured for provider '{provider_id}'"
        )

    api_key = repo.get_raw_key(cred)
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])

    async for event in adapter.stream_completion(api_key, request):
        yield event


__all__ = [
    "router",
    "init_indexes",
    "is_valid_provider",
    "stream_completion",
    "LlmCredentialNotFoundError",
    "LlmProviderNotFoundError",
    "UserModelConfigRepository",
]
```

- [ ] **Step 2: Verify all existing tests still pass**

Run: `uv run --project backend pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```
git add backend/modules/llm/__init__.py
git commit -m "Expose stream_completion in LLM module public API with credential resolution"
```

---

## Task 6: Chat Shared Contracts (Events + Topics)

**Files:**
- Create: `shared/dtos/chat.py`
- Create: `shared/events/chat.py`
- Modify: `shared/topics.py`
- Create: `tests/test_shared_chat_contracts.py`

- [ ] **Step 1: Write tests for chat contracts**

```python
# tests/test_shared_chat_contracts.py
from datetime import datetime, timezone

from shared.dtos.chat import ChatSessionDto, ChatMessageDto
from shared.events.chat import (
    ChatStreamStartedEvent,
    ChatContentDeltaEvent,
    ChatThinkingDeltaEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
)
from shared.topics import Topics


def test_chat_session_dto():
    dto = ChatSessionDto(
        id="sess-1",
        user_id="user-1",
        persona_id="persona-1",
        model_unique_id="ollama_cloud:qwen3:32b",
        state="idle",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert dto.state == "idle"


def test_chat_message_dto():
    dto = ChatMessageDto(
        id="msg-1",
        session_id="sess-1",
        role="assistant",
        content="Hello!",
        thinking=None,
        token_count=5,
        created_at=datetime.now(timezone.utc),
    )
    assert dto.role == "assistant"
    assert dto.thinking is None


def test_stream_started_event():
    e = ChatStreamStartedEvent(
        session_id="sess-1",
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert e.type == "chat.stream.started"


def test_content_delta_event():
    e = ChatContentDeltaEvent(correlation_id="corr-1", delta="Hello")
    assert e.type == "chat.content.delta"
    assert e.delta == "Hello"


def test_thinking_delta_event():
    e = ChatThinkingDeltaEvent(correlation_id="corr-1", delta="Hmm...")
    assert e.type == "chat.thinking.delta"


def test_stream_ended_event():
    e = ChatStreamEndedEvent(
        correlation_id="corr-1",
        session_id="sess-1",
        status="completed",
        usage={"input_tokens": 10, "output_tokens": 5},
        context_status="green",
        timestamp=datetime.now(timezone.utc),
    )
    assert e.status == "completed"
    assert e.context_status == "green"


def test_stream_error_event():
    e = ChatStreamErrorEvent(
        correlation_id="corr-1",
        error_code="invalid_api_key",
        recoverable=False,
        user_message="Bad key",
        timestamp=datetime.now(timezone.utc),
    )
    assert e.type == "chat.stream.error"
    assert e.recoverable is False


def test_chat_topics_exist():
    assert Topics.CHAT_STREAM_STARTED == "chat.stream.started"
    assert Topics.CHAT_CONTENT_DELTA == "chat.content.delta"
    assert Topics.CHAT_THINKING_DELTA == "chat.thinking.delta"
    assert Topics.CHAT_STREAM_ENDED == "chat.stream.ended"
    assert Topics.CHAT_STREAM_ERROR == "chat.stream.error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_shared_chat_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement chat DTOs**

```python
# shared/dtos/chat.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatSessionDto(BaseModel):
    id: str
    user_id: str
    persona_id: str
    model_unique_id: str
    state: Literal["idle", "streaming", "requires_action"]
    created_at: datetime
    updated_at: datetime


class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    created_at: datetime
```

- [ ] **Step 4: Implement chat events**

```python
# shared/events/chat.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatStreamStartedEvent(BaseModel):
    type: str = "chat.stream.started"
    session_id: str
    correlation_id: str
    timestamp: datetime


class ChatContentDeltaEvent(BaseModel):
    type: str = "chat.content.delta"
    correlation_id: str
    delta: str


class ChatThinkingDeltaEvent(BaseModel):
    type: str = "chat.thinking.delta"
    correlation_id: str
    delta: str


class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    status: Literal["completed", "cancelled", "error"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    timestamp: datetime


class ChatStreamErrorEvent(BaseModel):
    type: str = "chat.stream.error"
    correlation_id: str
    error_code: str
    recoverable: bool
    user_message: str
    timestamp: datetime
```

- [ ] **Step 5: Add chat topics**

Add to the `Topics` class in `shared/topics.py`, after the existing entries:

```python
    # Chat inference
    CHAT_STREAM_STARTED = "chat.stream.started"
    CHAT_CONTENT_DELTA = "chat.content.delta"
    CHAT_THINKING_DELTA = "chat.thinking.delta"
    CHAT_STREAM_ENDED = "chat.stream.ended"
    CHAT_STREAM_ERROR = "chat.stream.error"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project backend pytest tests/test_shared_chat_contracts.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```
git add shared/dtos/chat.py shared/events/chat.py shared/topics.py tests/test_shared_chat_contracts.py
git commit -m "Add chat shared contracts (DTOs, events, topics) for inference streaming"
```

---

## Task 7: Chat Module — Repository + Models

**Files:**
- Create: `backend/modules/chat/_models.py`
- Create: `backend/modules/chat/_repository.py`
- Create: `backend/modules/chat/__init__.py`
- Create: `tests/test_chat_repository.py`

- [ ] **Step 1: Write tests for the chat repository**

```python
# tests/test_chat_repository.py
import pytest

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_create_session(repo: ChatRepository):
    doc = await repo.create_session(
        user_id="user-1",
        persona_id="persona-1",
        model_unique_id="ollama_cloud:qwen3:32b",
    )
    assert doc["user_id"] == "user-1"
    assert doc["state"] == "idle"
    assert doc["persona_id"] == "persona-1"
    assert doc["model_unique_id"] == "ollama_cloud:qwen3:32b"


async def test_get_session(repo: ChatRepository):
    created = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    found = await repo.get_session(created["_id"], "user-1")
    assert found is not None
    assert found["_id"] == created["_id"]


async def test_get_session_wrong_user(repo: ChatRepository):
    created = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    found = await repo.get_session(created["_id"], "other-user")
    assert found is None


async def test_list_sessions_for_user(repo: ChatRepository):
    await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    await repo.create_session("user-1", "p-2", "ollama_cloud:m")
    await repo.create_session("user-2", "p-3", "ollama_cloud:m")

    sessions = await repo.list_sessions("user-1")
    assert len(sessions) == 2


async def test_update_session_state(repo: ChatRepository):
    doc = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    updated = await repo.update_session_state(doc["_id"], "streaming")
    assert updated["state"] == "streaming"


async def test_save_and_list_messages(repo: ChatRepository):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]

    await repo.save_message(
        session_id=sid,
        role="user",
        content="Hello!",
        token_count=3,
    )
    await repo.save_message(
        session_id=sid,
        role="assistant",
        content="Hi there!",
        thinking="Let me respond naturally.",
        token_count=5,
    )

    messages = await repo.list_messages(sid)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["thinking"] is None
    assert messages[1]["role"] == "assistant"
    assert messages[1]["thinking"] == "Let me respond naturally."


async def test_delete_session_cascades_messages(repo: ChatRepository):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    await repo.save_message(session_id=sid, role="user", content="hi", token_count=1)

    deleted = await repo.delete_session(sid, "user-1")
    assert deleted is True

    messages = await repo.list_messages(sid)
    assert len(messages) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_chat_repository.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement internal models**

```python
# backend/modules/chat/_models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatSessionDocument(BaseModel):
    """Internal MongoDB document model for chat sessions. Never expose outside chat module."""

    id: str = Field(alias="_id")
    user_id: str
    persona_id: str
    model_unique_id: str
    state: Literal["idle", "streaming", "requires_action"] = "idle"
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class ChatMessageDocument(BaseModel):
    """Internal MongoDB document model for chat messages. Never expose outside chat module."""

    id: str = Field(alias="_id")
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    created_at: datetime

    model_config = {"populate_by_name": True}
```

- [ ] **Step 4: Implement repository**

```python
# backend/modules/chat/_repository.py
from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.chat import ChatMessageDto, ChatSessionDto


class ChatRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._sessions = db["chat_sessions"]
        self._messages = db["chat_messages"]

    async def create_indexes(self) -> None:
        await self._sessions.create_index("user_id")
        await self._sessions.create_index([("user_id", 1), ("updated_at", -1)])
        await self._messages.create_index("session_id")
        await self._messages.create_index([("session_id", 1), ("created_at", 1)])

    # --- Sessions ---

    async def create_session(
        self,
        user_id: str,
        persona_id: str,
        model_unique_id: str,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "persona_id": persona_id,
            "model_unique_id": model_unique_id,
            "state": "idle",
            "created_at": now,
            "updated_at": now,
        }
        await self._sessions.insert_one(doc)
        return doc

    async def get_session(self, session_id: str, user_id: str) -> dict | None:
        return await self._sessions.find_one(
            {"_id": session_id, "user_id": user_id}
        )

    async def list_sessions(self, user_id: str) -> list[dict]:
        cursor = self._sessions.find(
            {"user_id": user_id}
        ).sort("updated_at", -1)
        return await cursor.to_list(length=200)

    async def update_session_state(
        self, session_id: str, state: str
    ) -> dict | None:
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"state": state, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        result = await self._sessions.delete_one(
            {"_id": session_id, "user_id": user_id}
        )
        if result.deleted_count > 0:
            await self._messages.delete_many({"session_id": session_id})
            return True
        return False

    # --- Messages ---

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int,
        thinking: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking": thinking,
            "token_count": token_count,
            "created_at": now,
        }
        await self._messages.insert_one(doc)
        return doc

    async def list_messages(self, session_id: str) -> list[dict]:
        cursor = self._messages.find(
            {"session_id": session_id}
        ).sort("created_at", 1)
        return await cursor.to_list(length=5000)

    # --- DTO mapping ---

    @staticmethod
    def session_to_dto(doc: dict) -> ChatSessionDto:
        return ChatSessionDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            persona_id=doc["persona_id"],
            model_unique_id=doc["model_unique_id"],
            state=doc["state"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def message_to_dto(doc: dict) -> ChatMessageDto:
        return ChatMessageDto(
            id=doc["_id"],
            session_id=doc["session_id"],
            role=doc["role"],
            content=doc["content"],
            thinking=doc.get("thinking"),
            token_count=doc["token_count"],
            created_at=doc["created_at"],
        )
```

- [ ] **Step 5: Create module __init__.py (minimal)**

```python
# backend/modules/chat/__init__.py
"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

from backend.modules.chat._repository import ChatRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


__all__ = ["init_indexes"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project backend pytest tests/test_chat_repository.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```
git add backend/modules/chat/__init__.py backend/modules/chat/_models.py backend/modules/chat/_repository.py tests/test_chat_repository.py
git commit -m "Add chat module with session/message repository and MongoDB indexes"
```

---

## Task 8: Chat REST Handlers (Session CRUD)

**Files:**
- Create: `backend/modules/chat/_handlers.py`
- Modify: `backend/modules/chat/__init__.py`
- Modify: `backend/main.py`
- Create: `tests/test_chat_sessions.py`

- [ ] **Step 1: Write integration tests for session CRUD**

```python
# tests/test_chat_sessions.py
import pytest


@pytest.fixture
async def auth_headers(client):
    """Create a user and return auth headers."""
    # Setup: create master admin
    await client.post("/api/auth/setup", json={
        "username": "admin",
        "display_name": "Admin",
        "password": "testpass123",
        "pin": "test-pin",
    })
    # Login
    resp = await client.post("/api/auth/login", json={
        "username": "admin",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def persona_id(client, auth_headers) -> str:
    """Create a persona and return its ID."""
    resp = await client.post("/api/personas", json={
        "name": "Test Persona",
        "tagline": "A test persona",
        "model_unique_id": "ollama_cloud:qwen3:32b",
        "system_prompt": "You are helpful.",
    }, headers=auth_headers)
    return resp.json()["id"]


async def test_create_session(client, auth_headers, persona_id):
    resp = await client.post("/api/chat/sessions", json={
        "persona_id": persona_id,
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["persona_id"] == persona_id
    assert data["state"] == "idle"
    assert data["model_unique_id"] == "ollama_cloud:qwen3:32b"


async def test_create_session_invalid_persona(client, auth_headers):
    resp = await client.post("/api/chat/sessions", json={
        "persona_id": "nonexistent",
    }, headers=auth_headers)
    assert resp.status_code == 404


async def test_list_sessions(client, auth_headers, persona_id):
    await client.post("/api/chat/sessions", json={
        "persona_id": persona_id,
    }, headers=auth_headers)
    await client.post("/api/chat/sessions", json={
        "persona_id": persona_id,
    }, headers=auth_headers)

    resp = await client.get("/api/chat/sessions", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_session(client, auth_headers, persona_id):
    create_resp = await client.post("/api/chat/sessions", json={
        "persona_id": persona_id,
    }, headers=auth_headers)
    session_id = create_resp.json()["id"]

    resp = await client.get(f"/api/chat/sessions/{session_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == session_id


async def test_get_session_not_found(client, auth_headers):
    resp = await client.get("/api/chat/sessions/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_session_messages(client, auth_headers, persona_id):
    create_resp = await client.post("/api/chat/sessions", json={
        "persona_id": persona_id,
    }, headers=auth_headers)
    session_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/chat/sessions/{session_id}/messages", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_delete_session(client, auth_headers, persona_id):
    create_resp = await client.post("/api/chat/sessions", json={
        "persona_id": persona_id,
    }, headers=auth_headers)
    session_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/chat/sessions/{session_id}", headers=auth_headers
    )
    assert resp.status_code == 200

    get_resp = await client.get(
        f"/api/chat/sessions/{session_id}", headers=auth_headers
    )
    assert get_resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_chat_sessions.py -v`
Expected: FAIL — 404 on all routes (not yet registered)

- [ ] **Step 3: Implement chat handlers**

```python
# backend/modules/chat/_handlers.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.chat._repository import ChatRepository
from backend.modules.persona._repository import PersonaRepository


router = APIRouter(prefix="/api/chat")


def _chat_repo() -> ChatRepository:
    return ChatRepository(get_db())


def _persona_repo() -> PersonaRepository:
    return PersonaRepository(get_db())


class CreateSessionDto(BaseModel):
    persona_id: str


@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionDto,
    user: dict = Depends(require_active_session),
):
    persona_repo = _persona_repo()
    persona = await persona_repo.find_by_id(body.persona_id, user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    repo = _chat_repo()
    doc = await repo.create_session(
        user_id=user["sub"],
        persona_id=persona["_id"],
        model_unique_id=persona["model_unique_id"],
    )
    return ChatRepository.session_to_dto(doc)


@router.get("/sessions")
async def list_sessions(user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    docs = await repo.list_sessions(user["sub"])
    return [ChatRepository.session_to_dto(d) for d in docs]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    doc = await repo.get_session(session_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found")
    return ChatRepository.session_to_dto(doc)


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await repo.list_messages(session_id)
    return [ChatRepository.message_to_dto(m) for m in messages]


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    deleted = await repo.delete_session(session_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok"}
```

- [ ] **Step 4: Update chat __init__.py to export router**

```python
# backend/modules/chat/__init__.py
"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

from backend.modules.chat._handlers import router
from backend.modules.chat._repository import ChatRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]
```

- [ ] **Step 5: Register chat module in main.py**

Add to `backend/main.py` — import and register the chat router:

Add this import line alongside the other module imports:

```python
from backend.modules.chat import router as chat_router, init_indexes as chat_init_indexes
```

Add this to the lifespan, after `await settings_init_indexes(db)`:

```python
    await chat_init_indexes(db)
```

Add this after the other `app.include_router` calls:

```python
app.include_router(chat_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --project backend pytest tests/test_chat_sessions.py -v`
Expected: All PASS

- [ ] **Step 7: Run the full test suite**

Run: `uv run --project backend pytest tests/ -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```
git add backend/modules/chat/_handlers.py backend/modules/chat/__init__.py backend/main.py tests/test_chat_sessions.py
git commit -m "Add chat session CRUD endpoints with persona validation"
```

---

## Task 9: Inference Runner

**Files:**
- Create: `backend/modules/chat/_inference.py`
- Create: `tests/test_inference_runner.py`

This is the core streaming loop. For Phase 1, it handles only basic streaming (no tools, no context management). Tools and context management come in Phase 2+.

- [ ] **Step 1: Write tests for the inference runner**

```python
# tests/test_inference_runner.py
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamError,
    ThinkingDelta,
)
from shared.events.chat import (
    ChatContentDeltaEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatStreamStartedEvent,
    ChatThinkingDeltaEvent,
)


async def _mock_stream(*events):
    """Create an async generator yielding the given events."""
    for e in events:
        yield e


@pytest.fixture
def runner():
    return InferenceRunner()


@pytest.fixture
def mock_emit():
    return AsyncMock()


@pytest.fixture
def mock_stream_fn():
    return AsyncMock()


@pytest.fixture
def mock_save_fn():
    return AsyncMock()


async def test_basic_content_stream(runner, mock_emit, mock_stream_fn, mock_save_fn):
    mock_stream_fn.return_value = _mock_stream(
        ContentDelta(delta="Hello"),
        ContentDelta(delta=" world"),
        StreamDone(input_tokens=10, output_tokens=5),
    )

    await runner.run(
        user_id="user-1",
        session_id="sess-1",
        correlation_id="corr-1",
        stream_fn=mock_stream_fn,
        emit_fn=mock_emit,
        save_fn=mock_save_fn,
    )

    # Check emitted events
    emitted_types = [call.args[0].type for call in mock_emit.call_args_list]
    assert emitted_types[0] == "chat.stream.started"
    assert "chat.content.delta" in emitted_types
    assert emitted_types[-1] == "chat.stream.ended"

    # Check content deltas
    deltas = [
        call.args[0] for call in mock_emit.call_args_list
        if isinstance(call.args[0], ChatContentDeltaEvent)
    ]
    assert len(deltas) == 2
    assert deltas[0].delta == "Hello"
    assert deltas[1].delta == " world"

    # Check stream ended
    ended = mock_emit.call_args_list[-1].args[0]
    assert isinstance(ended, ChatStreamEndedEvent)
    assert ended.status == "completed"
    assert ended.usage == {"input_tokens": 10, "output_tokens": 5}

    # Check save was called with accumulated content
    mock_save_fn.assert_awaited_once()
    save_args = mock_save_fn.call_args
    assert save_args.kwargs["content"] == "Hello world"
    assert save_args.kwargs["thinking"] is None


async def test_thinking_and_content(runner, mock_emit, mock_stream_fn, mock_save_fn):
    mock_stream_fn.return_value = _mock_stream(
        ThinkingDelta(delta="Let me think..."),
        ContentDelta(delta="42"),
        StreamDone(input_tokens=20, output_tokens=10),
    )

    await runner.run(
        user_id="user-1",
        session_id="sess-1",
        correlation_id="corr-1",
        stream_fn=mock_stream_fn,
        emit_fn=mock_emit,
        save_fn=mock_save_fn,
    )

    thinking_deltas = [
        call.args[0] for call in mock_emit.call_args_list
        if isinstance(call.args[0], ChatThinkingDeltaEvent)
    ]
    assert len(thinking_deltas) == 1
    assert thinking_deltas[0].delta == "Let me think..."

    # Save includes thinking
    save_args = mock_save_fn.call_args
    assert save_args.kwargs["content"] == "42"
    assert save_args.kwargs["thinking"] == "Let me think..."


async def test_stream_error(runner, mock_emit, mock_stream_fn, mock_save_fn):
    mock_stream_fn.return_value = _mock_stream(
        StreamError(error_code="invalid_api_key", message="Bad key"),
    )

    await runner.run(
        user_id="user-1",
        session_id="sess-1",
        correlation_id="corr-1",
        stream_fn=mock_stream_fn,
        emit_fn=mock_emit,
        save_fn=mock_save_fn,
    )

    emitted_types = [call.args[0].type for call in mock_emit.call_args_list]
    assert "chat.stream.started" in emitted_types
    assert "chat.stream.error" in emitted_types
    assert "chat.stream.ended" in emitted_types

    error_event = [
        call.args[0] for call in mock_emit.call_args_list
        if isinstance(call.args[0], ChatStreamErrorEvent)
    ][0]
    assert error_event.error_code == "invalid_api_key"

    ended = [
        call.args[0] for call in mock_emit.call_args_list
        if isinstance(call.args[0], ChatStreamEndedEvent)
    ][0]
    assert ended.status == "error"

    # Save not called on error
    mock_save_fn.assert_not_awaited()


async def test_cancellation(runner, mock_emit, mock_stream_fn, mock_save_fn):
    """Test that cancelling stops the stream."""
    cancel_event = asyncio.Event()

    async def _slow_stream():
        yield ContentDelta(delta="Start")
        cancel_event.set()  # signal cancel after first delta
        await asyncio.sleep(10)  # this should be interrupted
        yield ContentDelta(delta="Should not appear")
        yield StreamDone()

    mock_stream_fn.return_value = _slow_stream()

    # Run inference in background
    task = asyncio.create_task(runner.run(
        user_id="user-1",
        session_id="sess-1",
        correlation_id="corr-1",
        stream_fn=mock_stream_fn,
        emit_fn=mock_emit,
        save_fn=mock_save_fn,
        cancel_event=cancel_event,
    ))

    await asyncio.sleep(0.05)  # let it start
    await task

    ended_events = [
        call.args[0] for call in mock_emit.call_args_list
        if isinstance(call.args[0], ChatStreamEndedEvent)
    ]
    assert len(ended_events) == 1
    assert ended_events[0].status == "cancelled"


async def test_per_user_serialisation(runner, mock_emit, mock_save_fn):
    """Two concurrent runs for the same user are serialised."""
    call_order = []

    async def _stream_a():
        call_order.append("a_start")
        yield ContentDelta(delta="A")
        await asyncio.sleep(0.05)
        yield StreamDone()
        call_order.append("a_end")

    async def _stream_b():
        call_order.append("b_start")
        yield ContentDelta(delta="B")
        yield StreamDone()
        call_order.append("b_end")

    fn_a = AsyncMock(return_value=_stream_a())
    fn_b = AsyncMock(return_value=_stream_b())

    task_a = asyncio.create_task(runner.run(
        user_id="user-1", session_id="sess-a", correlation_id="corr-a",
        stream_fn=fn_a, emit_fn=mock_emit, save_fn=mock_save_fn,
    ))
    # Small delay so task_a grabs the lock first
    await asyncio.sleep(0.01)
    task_b = asyncio.create_task(runner.run(
        user_id="user-1", session_id="sess-b", correlation_id="corr-b",
        stream_fn=fn_b, emit_fn=mock_emit, save_fn=mock_save_fn,
    ))

    await asyncio.gather(task_a, task_b)

    # B must start after A ends (serialised)
    assert call_order.index("a_end") < call_order.index("b_start")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest tests/test_inference_runner.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement InferenceRunner**

```python
# backend/modules/chat/_inference.py
import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Awaitable
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamError,
    ThinkingDelta,
    ToolCallEvent,
)
from shared.events.chat import (
    ChatContentDeltaEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatStreamStartedEvent,
    ChatThinkingDeltaEvent,
)

_log = logging.getLogger(__name__)


class InferenceRunner:
    """Orchestrates a single inference stream with per-user serialisation."""

    def __init__(self) -> None:
        self._user_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    async def run(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable[[], Awaitable[AsyncIterator[ProviderStreamEvent]]],
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        """Run inference loop: stream from provider, emit events, persist result.

        Args:
            user_id: owning user (used for per-user lock).
            session_id: chat session ID.
            correlation_id: ties all events from this invocation.
            stream_fn: async callable that returns an async iterator of ProviderStreamEvents.
            emit_fn: async callable(event) to send an event to the user.
            save_fn: async callable(content=, thinking=, usage=) to persist the assistant message.
            cancel_event: if set, the stream is cancelled.
        """
        lock = self._get_lock(user_id)
        async with lock:
            await self._run_locked(
                session_id, correlation_id,
                stream_fn, emit_fn, save_fn, cancel_event,
            )

    async def _run_locked(
        self,
        session_id: str,
        correlation_id: str,
        stream_fn,
        emit_fn,
        save_fn,
        cancel_event: asyncio.Event | None,
    ) -> None:
        now = datetime.now(timezone.utc)

        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=now,
        ))

        full_content = ""
        full_thinking = ""
        usage = None
        status = "completed"

        try:
            stream = await stream_fn() if asyncio.iscoroutinefunction(stream_fn) else stream_fn()

            async for event in stream:
                # Check cancellation
                if cancel_event and cancel_event.is_set():
                    status = "cancelled"
                    break

                match event:
                    case ContentDelta(delta=delta):
                        full_content += delta
                        await emit_fn(ChatContentDeltaEvent(
                            correlation_id=correlation_id,
                            delta=delta,
                        ))

                    case ThinkingDelta(delta=delta):
                        full_thinking += delta
                        await emit_fn(ChatThinkingDeltaEvent(
                            correlation_id=correlation_id,
                            delta=delta,
                        ))

                    case StreamDone() as done:
                        usage = {}
                        if done.input_tokens is not None:
                            usage["input_tokens"] = done.input_tokens
                        if done.output_tokens is not None:
                            usage["output_tokens"] = done.output_tokens

                    case StreamError() as err:
                        status = "error"
                        await emit_fn(ChatStreamErrorEvent(
                            correlation_id=correlation_id,
                            error_code=err.error_code,
                            recoverable=err.error_code == "provider_unavailable",
                            user_message=err.message,
                            timestamp=datetime.now(timezone.utc),
                        ))

        except Exception as e:
            _log.error("Inference error for session %s: %s", session_id, e)
            status = "error"
            await emit_fn(ChatStreamErrorEvent(
                correlation_id=correlation_id,
                error_code="internal_error",
                recoverable=False,
                user_message="An unexpected error occurred during inference.",
                timestamp=datetime.now(timezone.utc),
            ))

        # Persist assistant message (only if we got content)
        if status == "completed" and full_content:
            await save_fn(
                content=full_content,
                thinking=full_thinking or None,
                usage=usage,
            )

        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            status=status,
            usage=usage,
            context_status="green",  # Phase 1: always green (no context management yet)
            timestamp=datetime.now(timezone.utc),
        ))

    def cancel(self, correlation_id: str) -> None:
        """Cancel is handled via the cancel_event passed to run()."""
        pass  # caller manages the event externally
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project backend pytest tests/test_inference_runner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
git add backend/modules/chat/_inference.py tests/test_inference_runner.py
git commit -m "Add InferenceRunner with streaming, cancellation, and per-user serialisation"
```

---

## Task 10: EventBus Fan-Out Rules for Chat Events

**Files:**
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Add chat event fan-out rules**

Chat delta events (`chat.content.delta`, `chat.thinking.delta`) should **not** be persisted to Redis Streams -- they are high-frequency and ephemeral. All other chat events should be persisted and delivered to the target user.

Add a new set for events that skip Redis persistence, and update the fan-out logic. In `backend/ws/event_bus.py`:

Add this set after `_BROADCAST_ALL`:

```python
# Chat events that skip Redis Streams persistence (high-frequency, ephemeral).
# They are delivered directly to the target user's WebSocket but not stored.
_SKIP_PERSISTENCE: set[str] = {
    Topics.CHAT_CONTENT_DELTA,
    Topics.CHAT_THINKING_DELTA,
}
```

Add chat event entries to the `_FANOUT` dict:

```python
    Topics.CHAT_STREAM_STARTED: ([], True),
    Topics.CHAT_STREAM_ENDED: ([], True),
    Topics.CHAT_STREAM_ERROR: ([], True),
    Topics.CHAT_CONTENT_DELTA: ([], True),
    Topics.CHAT_THINKING_DELTA: ([], True),
```

Modify the `publish` method to skip Redis persistence for delta events. Replace the `stream_key` / `xadd` / `xtrim` block with:

```python
        if topic not in _SKIP_PERSISTENCE:
            stream_key = f"events:{scope}"
            stream_id = await self._redis.xadd(
                stream_key, {"envelope": envelope.model_dump_json()}
            )
            envelope.sequence = stream_id

            now_ms = int(now.timestamp() * 1000)
            try:
                await self._redis.xtrim(
                    stream_key, minid=str(now_ms - _TWENTY_FOUR_HOURS_MS)
                )
            except Exception:
                pass  # trim failure must not abort delivery
```

Also add the Topics imports at the top for the new constants. The existing `from shared.topics import Topics` already covers this since we added the constants in Task 6.

- [ ] **Step 2: Verify all existing tests still pass**

Run: `uv run --project backend pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```
git add backend/ws/event_bus.py
git commit -m "Add chat event fan-out rules with Redis persistence skip for delta events"
```

---

## Task 11: WebSocket Router — Chat Message Dispatch

**Files:**
- Modify: `backend/ws/router.py`
- Modify: `backend/modules/chat/__init__.py`

This wires `chat.send` and `chat.cancel` WebSocket messages to the ChatService. The `chat.tool_result` message type is registered but not yet implemented (Phase 2+).

- [ ] **Step 1: Create ChatService class in the chat module**

Update `backend/modules/chat/__init__.py` to expose a `ChatService` that ties together the repository, the LLM module, and the inference runner:

```python
# backend/modules/chat/__init__.py
"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._handlers import router
from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._repository import ChatRepository
from backend.database import get_db
from backend.modules.llm import stream_completion as llm_stream_completion, LlmCredentialNotFoundError
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


_runner: InferenceRunner | None = None
_cancel_events: dict[str, asyncio.Event] = {}


def get_runner() -> InferenceRunner:
    global _runner
    if _runner is None:
        _runner = InferenceRunner()
    return _runner


async def handle_chat_send(user_id: str, data: dict) -> None:
    """Handle a chat.send WebSocket message."""
    session_id = data.get("session_id")
    content_parts = data.get("content", [])
    if not session_id or not content_parts:
        return

    db = get_db()
    repo = ChatRepository(db)
    session = await repo.get_session(session_id, user_id)
    if not session:
        return

    # Extract text content for persistence
    text = " ".join(
        p.get("text", "") for p in content_parts if p.get("type") == "text"
    ).strip()
    if not text:
        return

    # Save user message
    user_msg = await repo.save_message(
        session_id=session_id,
        role="user",
        content=text,
        token_count=len(text) // 4,  # rough estimate; Phase 2 uses tiktoken
    )

    # Update session state
    await repo.update_session_state(session_id, "streaming")

    # Build CompletionRequest (Phase 1: minimal — just user message, no context management)
    messages = []

    # Load persona system prompt
    from backend.modules.persona._repository import PersonaRepository
    persona_repo = PersonaRepository(db)
    persona = await persona_repo.find_by_id(session["persona_id"], user_id)
    if persona and persona.get("system_prompt"):
        messages.append(CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=persona["system_prompt"])],
        ))

    # Load recent message history (Phase 1: load all, no context window management)
    history = await repo.list_messages(session_id)
    for msg in history:
        msg_content = [ContentPart(type="text", text=msg["content"])]
        messages.append(CompletionMessage(role=msg["role"], content=msg_content))

    # Parse provider_id from model_unique_id
    model_unique_id = session["model_unique_id"]
    provider_id, _, model_slug = model_unique_id.partition(":")
    if not model_slug:
        return

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=persona.get("reasoning_enabled", False) if persona else False,
    )

    correlation_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[correlation_id] = cancel_event

    event_bus = get_event_bus()
    manager = get_manager()

    async def emit_fn(event):
        event_dict = event.model_dump(mode="json")
        event_dict["scope"] = f"session:{session_id}"
        await manager.send_to_user(user_id, event_dict)

        # Also persist non-delta events to Redis
        topic = event_dict.get("type", "")
        if topic in (Topics.CHAT_STREAM_STARTED, Topics.CHAT_STREAM_ENDED, Topics.CHAT_STREAM_ERROR):
            await event_bus.publish(
                topic, event,
                scope=f"session:{session_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    async def stream_fn():
        return llm_stream_completion(user_id, provider_id, request)

    async def save_fn(content: str, thinking: str | None, usage: dict | None):
        await repo.save_message(
            session_id=session_id,
            role="assistant",
            content=content,
            thinking=thinking,
            token_count=len(content) // 4,  # rough estimate; Phase 2 uses tiktoken
        )
        await repo.update_session_state(session_id, "idle")

    runner = get_runner()
    try:
        await runner.run(
            user_id=user_id,
            session_id=session_id,
            correlation_id=correlation_id,
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=cancel_event,
        )
    except LlmCredentialNotFoundError:
        from shared.events.chat import ChatStreamErrorEvent, ChatStreamStartedEvent, ChatStreamEndedEvent
        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ))
        await emit_fn(ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="no_api_key",
            recoverable=False,
            user_message=f"No API key configured for provider '{provider_id}'. Please add one in settings.",
            timestamp=datetime.now(timezone.utc),
        ))
        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            status="error",
            usage=None,
            context_status="green",
            timestamp=datetime.now(timezone.utc),
        ))
        await repo.update_session_state(session_id, "idle")
    finally:
        _cancel_events.pop(correlation_id, None)


def handle_chat_cancel(user_id: str, data: dict) -> None:
    """Handle a chat.cancel WebSocket message."""
    correlation_id = data.get("correlation_id")
    if correlation_id and correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()


__all__ = ["router", "init_indexes", "handle_chat_send", "handle_chat_cancel"]
```

- [ ] **Step 2: Update WebSocket router**

In `backend/ws/router.py`, add the chat dispatch to the message loop. Add the import at the top:

```python
from backend.modules.chat import handle_chat_send, handle_chat_cancel
```

Inside the `while True:` loop, after the `if msg_type == "ping":` block, add:

```python
            elif msg_type == "chat.send":
                asyncio.create_task(handle_chat_send(user_id, data))

            elif msg_type == "chat.cancel":
                handle_chat_cancel(user_id, data)
```

- [ ] **Step 3: Verify all existing tests still pass**

Run: `uv run --project backend pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```
git add backend/modules/chat/__init__.py backend/ws/router.py
git commit -m "Wire chat.send and chat.cancel WebSocket messages to ChatService"
```

---

## Task 12: Final Integration Verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run --project backend pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Verify the server starts cleanly**

Run: `cd /home/chris/workspace/chatsune && docker compose up -d mongodb redis && uv run --project backend python -c "from backend.main import app; print('App loaded OK')"`
Expected: `App loaded OK` (no import errors)

- [ ] **Step 3: Commit any remaining changes**

If all good, no commit needed. If there were adjustments, commit them.

- [ ] **Step 4: Final commit message**

```
git log --oneline -12
```

Verify the commit history looks clean and tells the story of Phase 1.
