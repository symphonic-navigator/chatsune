# xAI / Grok Adapter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new LLM adapter `xai_http` that exposes Grok 4.1 Fast (reasoning + non-reasoning folded into one logical model) via xAI's OpenAI-compatible Chat Completions API.

**Architecture:** New adapter class `XaiHttpAdapter(BaseAdapter)` in `backend/modules/llm/_adapters/_xai_http.py`. Internal model selection (reasoning → `grok-4-1-fast-reasoning`, non-reasoning → `grok-4-1-fast-non-reasoning`) is hidden from the chat flow. Cache-locality hint travels through a new `CompletionRequest.cache_hint` field and gets mapped onto xAI's `x-grok-conv-id` header. Tool calls are accumulated across SSE fragments. No frontend, migration, or event-contract changes.

**Tech Stack:** Python 3 / FastAPI, `httpx` async client, SSE parsing, Pydantic DTOs, `pytest-asyncio`, `httpx.MockTransport` for HTTP mocks.

**Spec:** [`devdocs/superpowers/specs/2026-04-20-xai-grok-adapter-design.md`](../specs/2026-04-20-xai-grok-adapter-design.md)

---

## Task 1: Add `cache_hint` to `CompletionRequest`

**Files:**
- Modify: `shared/dtos/inference.py:33-39`
- Test: `backend/tests/shared/test_completion_request.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/shared/test_completion_request.py
from shared.dtos.inference import CompletionRequest, CompletionMessage, ContentPart


def _msg() -> CompletionMessage:
    return CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])


def test_cache_hint_defaults_to_none():
    req = CompletionRequest(model="m", messages=[_msg()])
    assert req.cache_hint is None


def test_cache_hint_accepts_string():
    req = CompletionRequest(model="m", messages=[_msg()], cache_hint="sess-abc")
    assert req.cache_hint == "sess-abc"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/shared/test_completion_request.py -v
```
Expected: FAIL — `CompletionRequest` has no `cache_hint` field / `ValidationError: Extra inputs are not permitted`.

- [ ] **Step 3: Add the field**

In `shared/dtos/inference.py`, append one field to `CompletionRequest`:

```python
class CompletionRequest(BaseModel):
    model: str
    messages: list[CompletionMessage]
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None
    reasoning_enabled: bool = False
    supports_reasoning: bool = False
    cache_hint: str | None = None
```

- [ ] **Step 4: Re-run tests**

```bash
uv run pytest backend/tests/shared/test_completion_request.py -v
```
Expected: both tests PASS.

- [ ] **Step 5: Verify no regressions in chat/llm tests**

```bash
uv run pytest backend/tests/modules/llm backend/tests/modules/chat -q
```
Expected: existing tests still pass (new field is optional).

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/inference.py backend/tests/shared/test_completion_request.py
git commit -m "Add cache_hint field to CompletionRequest

Optional, provider-specific cache locality hint. Adapters that support
upstream cache locality translate this into a provider header; others
ignore it. Prepares the contract for the xAI adapter's x-grok-conv-id."
```

---

## Task 2: Propagate `cache_hint` through the chat flow

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py:428-435`
- Modify: `backend/modules/chat/_orchestrator.py:528-535`

No new tests — this is a one-line hook in each site and existing chat integration tests will exercise the path. The Pydantic default of `None` keeps all other `CompletionRequest(...)` call sites (jobs, vision fallback) backwards-compatible without touching them.

- [ ] **Step 1: Update WebSocket handler**

In `backend/modules/chat/_handlers_ws.py`, find the `CompletionRequest` construction at roughly line 428 and add one line. The surrounding block has `session_id` in scope from the earlier `await repo.get_session(session_id, user_id)` call (around line 424).

```python
request = CompletionRequest(
    model=model_slug,
    messages=messages,
    temperature=persona.get("temperature"),
    reasoning_enabled=persona.get("reasoning_enabled", False),
    supports_reasoning=supports_reasoning,
    tools=active_tools,
    cache_hint=session_id,
)
```

- [ ] **Step 2: Update orchestrator**

In `backend/modules/chat/_orchestrator.py`, find the `CompletionRequest` construction at roughly line 528 (the block that then calls `repo.update_session_state(session_id, "streaming")` a few lines below). Add the same field:

```python
request = CompletionRequest(
    model=model_slug,
    messages=messages,
    temperature=persona.get("temperature") if persona else None,
    reasoning_enabled=reasoning_enabled,
    supports_reasoning=supports_reasoning,
    tools=active_tools,
    cache_hint=session_id,
)
```

- [ ] **Step 3: Type-check and run full chat test suite**

```bash
uv run python -m py_compile backend/modules/chat/_handlers_ws.py backend/modules/chat/_orchestrator.py
uv run pytest backend/tests/modules/chat -q
```
Expected: compilation clean, chat tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py backend/modules/chat/_orchestrator.py
git commit -m "Pass chat session id as cache_hint into inference request

WebSocket handler and orchestrator now feed the session UUID through the
new CompletionRequest.cache_hint field. Non-chat callers (jobs, vision
fallback) keep the default None and remain unchanged."
```

---

## Task 3: `XaiHttpAdapter` skeleton — identity, templates, config schema

**Files:**
- Create: `backend/modules/llm/_adapters/_xai_http.py`
- Create: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/modules/llm/adapters/test_xai_http.py
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: FAIL — `ModuleNotFoundError: backend.modules.llm._adapters._xai_http`.

- [ ] **Step 3: Create the skeleton module**

```python
# backend/modules/llm/_adapters/_xai_http.py
"""xAI HTTP adapter — Chat Completions (legacy) for Grok 4.1 Fast."""

from __future__ import annotations

import logging

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
)

_log = logging.getLogger(__name__)


class XaiHttpAdapter(BaseAdapter):
    adapter_type = "xai_http"
    display_name = "xAI / Grok"
    view_id = "xai_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="xai_cloud",
                display_name="xAI Cloud",
                slug_prefix="xai",
                config_defaults={
                    "url": "https://api.x.ai/v1",
                    "api_key": "",
                    "max_parallel": 4,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="url", type="url", label="URL",
                placeholder="https://api.x.ai/v1",
            ),
            ConfigFieldHint(
                name="api_key", type="secret", label="API Key",
            ),
            ConfigFieldHint(
                name="max_parallel", type="integer",
                label="Max parallel inferences",
                min=1, max=32,
            ),
        ]

    # fetch_models + stream_completion added in later tasks.
```

The class is still abstract (`BaseAdapter` declares `fetch_models` and `stream_completion` abstract) — that is intentional; instantiation comes online only once Task 4 and later are in.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: three tests PASS. The class attribute / classmethod tests do not instantiate the adapter, so the still-missing abstract methods do not matter.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "Add XaiHttpAdapter skeleton with single xAI Cloud template

Identity attributes, xai_cloud template, and config schema. fetch_models
and stream_completion follow in the next tasks."
```

---

## Task 4: `fetch_models()` — hard-coded single model

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/modules/llm/adapters/test_xai_http.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py::test_fetch_models_returns_one_grok_4_1_fast -v
```
Expected: FAIL — `TypeError: Can't instantiate abstract class XaiHttpAdapter with abstract methods fetch_models, stream_completion`.

- [ ] **Step 3: Implement `fetch_models` and a no-op `stream_completion` stub**

Add imports and methods to `backend/modules/llm/_adapters/_xai_http.py`:

```python
from collections.abc import AsyncIterator

from backend.modules.llm._adapters._events import ProviderStreamEvent, StreamError
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto
```

Add these methods to the class (below `config_schema`):

```python
    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        return [
            ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id="grok-4.1-fast",
                display_name="Grok 4.1 Fast",
                context_window=200_000,
                supports_reasoning=True,
                supports_vision=True,
                supports_tool_calls=True,
            ),
        ]

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        # Stub — real implementation lands in Task 10.
        yield StreamError(
            error_code="provider_unavailable",
            message="xai_http stream_completion not implemented yet",
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "XaiHttpAdapter: hard-coded fetch_models for Grok 4.1 Fast

Single ModelMetaDto with 200K context cap and full capability matrix.
stream_completion is stubbed — real implementation follows."
```

---

## Task 5: `_translate_message` — OpenAI-style content mapping

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing tests**

Append to the test file:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k translate
```
Expected: FAIL — `ImportError: cannot import name '_translate_message'`.

- [ ] **Step 3: Implement `_translate_message`**

Add to `_xai_http.py` (module-level, before the class):

```python
from shared.dtos.inference import CompletionMessage


def _translate_message(msg: CompletionMessage) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat message."""
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    # When there is no image, a simple string content is more cache-friendly.
    if not image_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.media_type};base64,{p.data}",
                },
            })

    result: dict = {"role": msg.role, "content": content}

    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in msg.tool_calls
        ]

    if msg.tool_call_id is not None:
        result["tool_call_id"] = msg.tool_call_id

    return result
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k translate
```
Expected: four translate tests PASS; prior tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xai_http: translate CompletionMessage to OpenAI content format

Handles text-only, mixed text+image (data:URL encoding), assistant
tool_calls, and tool-role messages with tool_call_id."
```

---

## Task 6: `_build_chat_payload` — reasoning model switch + tools

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k build_payload
```
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement `_build_chat_payload`**

Add to `_xai_http.py` (module-level):

```python
_XAI_MODEL_REASONING = "grok-4-1-fast-reasoning"
_XAI_MODEL_NON_REASONING = "grok-4-1-fast-non-reasoning"


def _build_chat_payload(request: CompletionRequest) -> dict:
    model_slug = (
        _XAI_MODEL_REASONING if request.reasoning_enabled
        else _XAI_MODEL_NON_REASONING
    )
    payload: dict = {
        "model": model_slug,
        "stream": True,
        "messages": [_translate_message(m) for m in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
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
    return payload
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: all existing tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xai_http: build chat payload with reasoning model switch

Maps request.reasoning_enabled to one of two upstream model slugs; emits
OpenAI-compatible stream=True payload with tools in the function schema
form. Temperature omitted when None."
```

---

## Task 7: SSE line parser

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k sse_line
```
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement the parser**

Add to `_xai_http.py`:

```python
import json

_SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value


def _parse_sse_line(line: str) -> dict | object | None:
    """Parse a single SSE line.

    Returns:
        - a ``dict`` when the line is a valid ``data: {json}`` frame,
        - ``_SSE_DONE`` for ``data: [DONE]`` (stream terminator),
        - ``None`` for empty lines, non-data lines, or malformed JSON.
    """
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return _SSE_DONE
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        _log.warning("Skipping malformed SSE JSON: %s", payload[:200])
        return None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xai_http: SSE line parser with [DONE] sentinel

Pure function taking a single stream line and returning dict, done
sentinel, or None. Malformed JSON is logged and skipped so a single bad
frame does not kill the stream."
```

---

## Task 8: Tool-call fragment accumulator

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k accumulator
```
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement the accumulator**

Add to `_xai_http.py`:

```python
from uuid import uuid4


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    Upstream providers stream tool calls in pieces, indexed by
    ``tool_calls[].index``. Each fragment may carry id, name, or an
    arguments string fragment. We accumulate by index and finalise once
    the upstream signals ``finish_reason="tool_calls"``.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}

    def ingest(self, fragments: list[dict]) -> None:
        for frag in fragments:
            idx = frag.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(idx, {
                "id": None, "name": "", "args": "",
            })
            if frag.get("id"):
                slot["id"] = frag["id"]
            fn = frag.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    def finalised(self) -> list[dict]:
        """Return accumulated calls as [{id, name, arguments}, ...]."""
        calls: list[dict] = []
        for _, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
            })
        return calls
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xai_http: accumulate OpenAI-style tool_call fragments

_ToolCallAccumulator merges fragments across chunks keyed by
tool_calls[].index. Falls back to a synthetic call_ id when the
upstream omits one, so downstream dispatch never sees an empty id."
```

---

## Task 9: `stream_completion` — full streaming pipeline

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

This is the big one. The adapter talks to xAI via `httpx.AsyncClient`, streams SSE, maps chunks into `ProviderStreamEvent`s, applies a gutter timer, and forwards tool-call accumulation.

- [ ] **Step 1: Write failing integration tests (mocked HTTP)**

Append to the test file:

```python
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
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":2}}',
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
    seen_headers = {}

    def handler(request):
        seen_headers.update(dict(request.headers))
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k stream_completion
```
Expected: six FAILs — the stub `stream_completion` always yields `StreamError`.

- [ ] **Step 3: Implement the real `stream_completion`**

Replace the stub in `_xai_http.py`. Add imports at the top:

```python
import asyncio
import time
import os

import httpx

from backend.modules.llm._adapters._events import (
    ContentDelta, StreamAborted, StreamDone, StreamError,
    StreamRefused, StreamSlow, ThinkingDelta, ToolCallEvent,
)
```

Add gutter constants (after `_log`):

```python
GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})
```

Replace the stub with the full implementation:

```python
    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        payload = _build_chat_payload(request)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if request.cache_hint:
            headers["x-grok-conv-id"] = request.cache_hint

        acc = _ToolCallAccumulator()
        seen_done = False
        pending_next: asyncio.Task | None = None

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{url}/chat/completions",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code in (401, 403):
                        yield StreamError(
                            error_code="invalid_api_key",
                            message="xAI rejected the API key",
                        )
                        return
                    if resp.status_code == 429:
                        yield StreamError(
                            error_code="provider_unavailable",
                            message="xAI rate limit hit",
                        )
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:500]
                        _log.error("xai_http upstream %d: %s",
                                   resp.status_code, detail)
                        yield StreamError(
                            error_code="provider_unavailable",
                            message=f"xAI returned {resp.status_code}: {detail}",
                        )
                        return

                    stream_iter = resp.aiter_lines().__aiter__()
                    line_start = time.monotonic()
                    slow_fired = False

                    while True:
                        elapsed = time.monotonic() - line_start
                        budget = (
                            GUTTER_ABORT_SECONDS - elapsed if slow_fired
                            else GUTTER_SLOW_SECONDS - elapsed
                        )
                        if budget <= 0:
                            if not slow_fired:
                                yield StreamSlow()
                                slow_fired = True
                                continue
                            if pending_next is not None:
                                pending_next.cancel()
                            yield StreamAborted(reason="gutter_timeout")
                            return
                        if pending_next is None:
                            pending_next = asyncio.ensure_future(
                                stream_iter.__anext__(),
                            )
                        done, _ = await asyncio.wait(
                            {pending_next}, timeout=budget,
                        )
                        if not done:
                            continue
                        task = done.pop()
                        pending_next = None
                        try:
                            line = task.result()
                        except StopAsyncIteration:
                            break
                        line_start = time.monotonic()
                        slow_fired = False

                        parsed = _parse_sse_line(line)
                        if parsed is None:
                            continue
                        if parsed is _SSE_DONE:
                            break

                        for event in _chunk_to_events(parsed, acc):
                            if isinstance(event, StreamDone):
                                seen_done = True
                            yield event
                            if isinstance(event, (StreamDone,
                                                   StreamRefused,
                                                   StreamError)):
                                return

            except asyncio.CancelledError:
                if pending_next is not None and not pending_next.done():
                    pending_next.cancel()
                raise
            except httpx.ConnectError:
                yield StreamError(
                    error_code="provider_unavailable",
                    message="Cannot connect to xAI",
                )
                return

        if not seen_done:
            yield StreamDone()
```

Add the chunk-mapper helper (module-level, below `_ToolCallAccumulator`):

```python
def _chunk_to_events(
    chunk: dict,
    acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Map one parsed SSE chunk into zero or more provider events.

    `acc` is mutated in-place for tool-call fragment accumulation.
    """
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}
    if not choices:
        return events
    choice = choices[0]
    delta = choice.get("delta") or {}

    reasoning = delta.get("reasoning_content") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))

    content = delta.get("content") or ""
    if content:
        events.append(ContentDelta(delta=content))

    tool_frags = delta.get("tool_calls") or []
    if tool_frags:
        acc.ingest(tool_frags)

    finish = choice.get("finish_reason")
    if finish is None:
        return events

    if finish == "tool_calls":
        for call in acc.finalised():
            events.append(ToolCallEvent(
                id=call["id"], name=call["name"],
                arguments=call["arguments"],
            ))
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        ))
    elif finish in _REFUSAL_REASONS:
        events.append(StreamRefused(
            reason=finish,
            refusal_text=delta.get("refusal") or None,
        ))
    else:
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        ))
    return events
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xai_http: full streaming pipeline with gutter timer

stream_completion wires the payload builder, SSE parser, tool-call
accumulator, and chunk-to-events mapper. HTTP 401/429/5xx mapped to
StreamError; content_filter / refusal mapped to StreamRefused; usage
tokens forwarded on StreamDone. Gutter timer mirrors the Ollama adapter
(30s slow, 120s abort)."
```

---

## Task 10: Sub-router `POST /test`

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py`

- [ ] **Step 1: Write failing tests**

```python
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
    # Stub the repo + event bus dependencies the handler needs.
    from backend.modules.llm._connections import ConnectionRepository
    from backend.ws.event_bus import get_event_bus

    class _FakeRepo:
        async def update_test_status(self, *a, **kw): return None

    class _FakeBus:
        async def publish(self, *a, **kw): return None

    # Adapter router reads these via Depends — override to fakes.
    # If the router's _repo helper is module-private, patch it instead:
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v -k post_test
```
Expected: FAIL — `XaiHttpAdapter.router()` returns `None` (inherited default).

- [ ] **Step 3: Implement the sub-router**

Add to `_xai_http.py`:

```python
from fastapi import APIRouter, Depends


@classmethod
def router(cls) -> APIRouter:  # noqa: keep next to class body
    return _build_adapter_router()
```

Place that `@classmethod` inside the `XaiHttpAdapter` class (after
`config_schema`). Then, module-level, add:

```python
def _build_adapter_router() -> APIRouter:
    from datetime import UTC, datetime

    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._resolver import resolve_connection_for_user
    from backend.ws.event_bus import EventBus, get_event_bus
    from shared.events.llm import LlmConnectionUpdatedEvent
    from shared.topics import Topics

    router = APIRouter()

    def _xai_repo_factory() -> ConnectionRepository:
        return ConnectionRepository(get_db())

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
        repo: ConnectionRepository = Depends(_xai_repo_factory),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        valid = False
        error: str | None = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
            ) as client:
                resp = await client.get(
                    f"{url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code in (401, 403):
                    error = "API key rejected by xAI"
                elif resp.status_code != 200:
                    error = f"xAI returned {resp.status_code}"
                else:
                    valid = True
        except Exception as exc:  # noqa: BLE001 — surface to frontend
            error = str(exc)

        updated = await repo.update_test_status(
            c.user_id, c.id,
            status="valid" if valid else "failed",
            error=error,
        )
        if updated is not None:
            await event_bus.publish(
                Topics.LLM_CONNECTION_UPDATED,
                LlmConnectionUpdatedEvent(
                    connection=ConnectionRepository.to_dto(updated),
                    timestamp=datetime.now(UTC),
                ),
            )
        return {"valid": valid, "error": error}

    return router
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xai_http: POST /test sub-router validates key via GET /models

Reads GET /v1/models with the connection's bearer token. 200 marks the
connection valid; 401/403 reports 'API key rejected by xAI'; other
statuses report the code. Updates the connection's test status and
emits LLM_CONNECTION_UPDATED on change."
```

---

## Task 11: Register adapter in `ADAPTER_REGISTRY`

**Files:**
- Modify: `backend/modules/llm/_registry.py`
- Modify: (or create) `backend/tests/modules/llm/test_registry.py`

- [ ] **Step 1: Write failing test**

Check first whether `backend/tests/modules/llm/test_registry.py` already exists:

```bash
ls backend/tests/modules/llm/test_registry.py 2>&1
```

If it does not exist, create it with:

```python
# backend/tests/modules/llm/test_registry.py
from backend.modules.llm._registry import ADAPTER_REGISTRY


def test_registry_contains_xai_http():
    assert "xai_http" in ADAPTER_REGISTRY
    from backend.modules.llm._adapters._xai_http import XaiHttpAdapter
    assert ADAPTER_REGISTRY["xai_http"] is XaiHttpAdapter
```

If it exists, append just the test.

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest backend/tests/modules/llm/test_registry.py -v
```
Expected: FAIL — `"xai_http" not in ADAPTER_REGISTRY`.

- [ ] **Step 3: Register the adapter**

Open `backend/modules/llm/_registry.py` and add the import plus a dictionary entry:

```python
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "xai_http": XaiHttpAdapter,
}
```

(Keep existing imports and entries exactly as they are.)

- [ ] **Step 4: Run test**

```bash
uv run pytest backend/tests/modules/llm/test_registry.py -v
```
Expected: PASS.

- [ ] **Step 5: Run the full LLM module test suite**

```bash
uv run pytest backend/tests/modules/llm -q
```
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_registry.py backend/tests/modules/llm/test_registry.py
git commit -m "Register XaiHttpAdapter in ADAPTER_REGISTRY

Makes the xAI Cloud provider pickable in the add-connection wizard and
resolvable for streaming. No other module needs to change."
```

---

## Task 12: LLM harness — SSE parsing + `--adapter` flag

**Files:**
- Modify: `backend/llm_harness/_runner.py`
- Modify: `backend/llm_harness/__main__.py`

The harness is a debugging tool, not in the hot path of the product. No unit tests — manual verification against a real xAI endpoint is the point.

- [ ] **Step 1: Add adapter selection to `_runner.py`**

Replace the hard-coded `OllamaHttpAdapter` imports / instantiation. Open `backend/llm_harness/_runner.py` and change:

```python
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
```

to:

```python
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter

_ADAPTERS = {
    "ollama_http": (OllamaHttpAdapter, "https://ollama.com"),
    "xai_http": (XaiHttpAdapter, "https://api.x.ai/v1"),
}
```

Change `HarnessRunner.__init__` to accept an adapter type and default base URL:

```python
def __init__(
    self,
    api_key: str,
    adapter_type: str = "ollama_http",
    base_url: str | None = None,
) -> None:
    if adapter_type not in _ADAPTERS:
        raise ValueError(f"Unknown adapter_type: {adapter_type}")
    self._api_key = api_key
    self._adapter_type = adapter_type
    adapter_cls, default_base_url = _ADAPTERS[adapter_type]
    self._adapter_cls = adapter_cls
    self._base_url = base_url or default_base_url
```

Change `_resolved_connection` to use the selected adapter type:

```python
def _resolved_connection(self) -> ResolvedConnection:
    now = datetime.now(timezone.utc)
    return ResolvedConnection(
        id="harness",
        user_id="harness",
        adapter_type=self._adapter_type,
        display_name=f"{self._adapter_type} (harness)",
        slug="harness",
        config={
            "url": self._base_url,
            "api_key": self._api_key,
            "max_parallel": 3,
        },
        created_at=now,
        updated_at=now,
    )
```

Replace both `adapter = OllamaHttpAdapter()` lines (in `run` and `run_with_tools`) with:

```python
adapter = self._adapter_cls()
```

- [ ] **Step 2: Add `--adapter` CLI flag in `__main__.py`**

Open `backend/llm_harness/__main__.py`. Find the argparse block. Add one argument next to `--key-file`:

```python
parser.add_argument(
    "--adapter",
    default="ollama_http",
    choices=["ollama_http", "xai_http"],
    help="Adapter to exercise (default: ollama_http).",
)
```

Find the `HarnessRunner(...)` constructor call and pass the new argument:

```python
runner = HarnessRunner(
    api_key=api_key,
    adapter_type=args.adapter,
    base_url=args.base_url,
)
```

Also update the `--key-file` default when `--adapter xai_http` is chosen. The cleanest way is to resolve the default after parsing:

```python
args = parser.parse_args()
if args.key_file == ".llm-test-key" and args.adapter == "xai_http":
    args.key_file = ".xai-test-key"
```

- [ ] **Step 3: Smoke-compile**

```bash
uv run python -m py_compile backend/llm_harness/_runner.py backend/llm_harness/__main__.py
```
Expected: exit code 0.

- [ ] **Step 4: Run existing harness against Ollama to verify no regression**

```bash
uv run python -m backend.llm_harness --model llama3.2 \
    --message '{"role":"user","content":"hi"}' --adapter ollama_http
```
Expected: the same output you would have got before the patch (single greeting). Skip this step if you don't have an `.llm-test-key` on hand.

- [ ] **Step 5: Commit**

```bash
git add backend/llm_harness/_runner.py backend/llm_harness/__main__.py
git commit -m "LLM harness: add --adapter flag for xai_http

Harness now selects between ollama_http and xai_http via a CLI flag.
Default behaviour (Ollama, .llm-test-key) is preserved; picking
--adapter xai_http flips the key-file default to .xai-test-key and the
base URL to https://api.x.ai/v1."
```

---

## Task 13: LLM test-harness scenarios for xAI

**Files:**
- Create: `tests/llm_scenarios/xai_grok_fast_non_reasoning.json`
- Create: `tests/llm_scenarios/xai_grok_fast_reasoning.json`

These are fixture files the harness loads via `--from`. They encode reproducible runs against xAI.

- [ ] **Step 1: Locate the existing scenarios folder**

```bash
ls tests/llm_scenarios/ 2>&1 | head
```

Pick an existing scenario to copy the shape. If uncertain, read the harness arg parser in `backend/llm_harness/__main__.py` to see what fields `--from` expects.

- [ ] **Step 2: Create the non-reasoning scenario**

```json
// tests/llm_scenarios/xai_grok_fast_non_reasoning.json
{
    "adapter": "xai_http",
    "model": "grok-4.1-fast",
    "base_url": "https://api.x.ai/v1",
    "key_file": ".xai-test-key",
    "reasoning": false,
    "supports_reasoning": true,
    "messages": [
        {"role": "system", "content": "You are Grok. Be concise."},
        {"role": "user", "content": "Say the word 'pong' and nothing else."}
    ]
}
```

- [ ] **Step 3: Create the reasoning scenario**

```json
// tests/llm_scenarios/xai_grok_fast_reasoning.json
{
    "adapter": "xai_http",
    "model": "grok-4.1-fast",
    "base_url": "https://api.x.ai/v1",
    "key_file": ".xai-test-key",
    "reasoning": true,
    "supports_reasoning": true,
    "messages": [
        {"role": "system", "content": "You are Grok. Think, then answer."},
        {"role": "user", "content": "What is 27 * 14? Show one reasoning sentence."}
    ]
}
```

- [ ] **Step 4: Teach `_run` to consume `adapter`, `base_url`, `key_file` from the scenario file**

The existing `_run` in `backend/llm_harness/__main__.py` only reads `model`, `system`, `messages`, `reasoning`, `temperature`, `tools` from the scenario JSON. The scenario-side `adapter`, `base_url`, `key_file` fields must override the corresponding CLI args before the `HarnessRunner` is built. Edit `_run`:

```python
async def _run(args: argparse.Namespace) -> None:
    # If a scenario file is given, let it override adapter / base_url / key_file
    # before we load the key or construct the runner.
    scenario = _load_scenario(args.scenario_file) if args.scenario_file else None
    if scenario:
        if "adapter" in scenario:
            args.adapter = scenario["adapter"]
        if "base_url" in scenario:
            args.base_url = scenario["base_url"]
        if "key_file" in scenario:
            args.key_file = scenario["key_file"]

    api_key = load_api_key(args.key_file)
    runner = HarnessRunner(
        api_key=api_key,
        adapter_type=args.adapter,
        base_url=args.base_url,
    )

    if scenario:
        model = scenario["model"]
        system = scenario.get("system")
        messages = scenario.get("messages", [])
        reasoning = scenario.get("reasoning", False)
        temperature = scenario.get("temperature")
        tools = scenario.get("tools")
    else:
        # ... existing CLI-path branch stays unchanged below
```

Keep everything below that branch exactly as it is now.

- [ ] **Step 5: Manually exercise the harness (requires `.xai-test-key`)**

```bash
echo "xai-XXXXXXXXXXXX..." > .xai-test-key  # paste the actual key
uv run python -m backend.llm_harness --from tests/llm_scenarios/xai_grok_fast_non_reasoning.json
uv run python -m backend.llm_harness --from tests/llm_scenarios/xai_grok_fast_reasoning.json
```

Expected:
- Non-reasoning run prints `pong` (or close to it) and a `StreamDone` with token counts.
- Reasoning run prints **thinking tokens** (a `reasoning_content` fragment) followed by the numeric answer `378`.

If the reasoning run shows the reasoning path as `content` rather than
`thinking`, the upstream field is not `reasoning_content`. Inspect the
raw SSE lines (the harness logs them when trace is enabled) and adjust
the field name in `_chunk_to_events` in `_xai_http.py`, plus the test in
Task 9 that asserts on `reasoning_content`.

- [ ] **Step 6: Commit**

```bash
git add tests/llm_scenarios/xai_grok_fast_non_reasoning.json tests/llm_scenarios/xai_grok_fast_reasoning.json backend/llm_harness/__main__.py
git commit -m "Add xAI harness scenarios for reasoning + non-reasoning

Reproducible harness runs for Grok 4.1 Fast in both modes. Lets us
verify SSE parsing, the reasoning_content field name, and the
reasoning-vs-non-reasoning upstream model switch end-to-end against
live xAI."
```

---

## Task 14: Manual end-to-end smoke test in the running app

No code changes — this is a documented verification sequence. Keep notes in the commit message or the PR description, not in a new file.

- [ ] **Step 1: Start the backend + frontend stack**

```bash
docker compose up -d mongo redis
cd backend && uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
# separate terminal
cd frontend && pnpm dev
```

- [ ] **Step 2: Add an xAI Cloud connection in the UI**

Log in → LLM Settings → Add Connection → "xAI / Grok" → "xAI Cloud"
template → paste API key → Save.

Expected: save succeeds, connection appears in the list, test status
updates to "valid" (the POST /test hit from the UI).

- [ ] **Step 3: Verify `grok-4.1-fast` appears in the model picker**

Open a persona config or the model picker on the chat screen. The
connection slug prefixed model `<slug>:grok-4.1-fast` should be listed
with the reasoning toggle available and a vision / tools badge.

- [ ] **Step 4: Send a reasoning-off message**

Pick the model, reasoning OFF. Send: "Hello, which upstream model are
you?". Grok should answer without any thinking indicator. Verify in
backend logs that the request used model `grok-4-1-fast-non-reasoning`
and sent the `x-grok-conv-id` header with the session UUID.

- [ ] **Step 5: Toggle reasoning ON, send a follow-up**

Send: "Explain your earlier answer briefly." The chat should show a
thinking indicator, then a content response. Verify the request used
model `grok-4-1-fast-reasoning` and that the TTFT is not higher than
it was for the previous turn — evidence that the cache is reused
across the reasoning / non-reasoning split.

- [ ] **Step 6: Exercise a tool call**

Enable the `web_search` tool group on the session. Send: "Please search
for the xAI pricing page and quote the per-million-token figures." The
chat should stream a tool call, execute the web search via our own
adapter, and resume with a content answer.

- [ ] **Step 7: Clean up**

```bash
docker compose down
```

- [ ] **Step 8: Commit the verification note**

Only if the plan lives in a feature branch and you want a marker on the
branch, commit an empty-tree note. Otherwise skip and include the notes
in the PR description.

```bash
git commit --allow-empty -m "End-to-end smoke test passed for xai_http

Verified: connection create + test, model picker visibility, reasoning
on/off round-trip, cache_hint header presence, tool-call loop with
web_search."
```

---

## Out of Scope (tracked in spec)

- Cache-hit token telemetry in the event contract — INS-024 follow-up
- Additional Grok models (Grok 3, 4, 4.20, `grok-code-fast-1`)
- xAI Responses API / server-side `web_search`

These are documented in the spec's **Follow-ups** section; do not pull them into this PR.
