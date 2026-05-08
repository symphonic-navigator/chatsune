# Novita AI Premium Upstream Provider — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Novita AI as a Premium Upstream Provider so users can run open-source models (e.g. MiMo V2.5 Pro/Omni) without going through nano-gpt or OpenRouter.

**Architecture:** New OpenAI-compatible adapter `_novita_http.py`, registered as a premium-only adapter (no user-creatable connection). Slimmed-down clone of `_openrouter_http.py` — no Anthropic-cache logic since Novita is open-source-inference-only, not a router. The five wiring touch points are: provider definition, resolver mapping, reserved-slug list, premium-only adapter map, and the adapter file itself. No frontend changes.

**Tech Stack:** Python 3.13, httpx, FastAPI, Pydantic v2, pytest + pytest-asyncio. Reuses `backend._retry`, `backend.modules.llm._adapters._events`, `backend.modules.llm._adapters._base`, `shared.dtos.inference`, `shared.dtos.llm`.

**Spec:** `devdocs/specs/2026-05-08-novita-premium-provider-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `backend/modules/providers/_registry.py` | Modify | Append Novita `PremiumProviderDefinition` |
| `backend/tests/modules/providers/test_novita_registration.py` | Create | Verify Novita registry entry shape |
| `backend/modules/llm/_resolver.py` | Modify | `_PREMIUM_ADAPTER_TYPE["novita"] = "novita_http"` |
| `backend/modules/llm/_connections.py` | Modify | Add `"novita"` to `RESERVED_SLUGS` |
| `backend/tests/modules/llm/test_resolver_novita.py` | Create | Verify resolver mapping + reserved slug |
| `backend/modules/llm/_adapters/_novita_http.py` | Create | The adapter (full SSE loop, retries, gutter, model fetch) |
| `backend/modules/llm/_registry.py` | Modify | Import + register `NovitaHttpAdapter` in `_PREMIUM_ONLY_ADAPTERS` |
| `backend/tests/modules/llm/adapters/test_novita_http.py` | Create | Adapter unit tests (identity, model mapping, payload, SSE, streaming) |

No frontend changes (`PremiumAccountCard` renders any registered provider). No shared DTO changes. No DB schema changes.

## Constraints (subagent must respect)

- **Stay on the feature branch.** Do **not** merge, **do not** push, **do not** switch branches. Chris merges.
- **Run only the new and adjacent test files** during implementation; the full backend suite is for Chris to run separately.
- **No premature scope expansion.** Don't refactor unrelated files; don't extract the OpenAI-compat SSE helpers (deferred to its own session).

---

## Task 0: Feature branch

**Files:** none (git only)

- [ ] **Step 1: Verify clean working tree**

```bash
cd /home/chris/workspace/chatsune
git status --short
```

Expected: only the spec/plan files from the brainstorming session if any. Stop and ask if anything else is dirty.

- [ ] **Step 2: Create feature branch from master**

```bash
git checkout -b feat/novita-premium-provider master
```

Expected: switched to a new branch.

- [ ] **Step 3: Verify branch**

```bash
git branch --show-current
```

Expected: `feat/novita-premium-provider`.

---

## Task 1: Premium-Provider registry entry

**Files:**
- Modify: `backend/modules/providers/_registry.py:108` (just before `_register_builtins()` call — append a new `register(...)` block inside the function)
- Create: `backend/tests/modules/providers/test_novita_registration.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/providers/test_novita_registration.py`:

```python
"""Verifies the novita provider is registered with the right shape."""

from backend.modules.providers._registry import get
from shared.dtos.providers import Capability


def test_novita_provider_is_registered():
    defn = get("novita")
    assert defn is not None


def test_novita_capabilities_are_llm_only():
    defn = get("novita")
    assert defn.capabilities == [Capability.LLM]


def test_novita_base_url_is_openai_compat_path():
    # Chat-completions and model listing live under /openai/v1.
    defn = get("novita")
    assert defn.base_url == "https://api.novita.ai/openai/v1"


def test_novita_probe_url_targets_billing_balance():
    # /openai/v1/models is unauthenticated and would falsely accept any
    # key; the billing endpoint requires auth so it is the only valid
    # probe target. See spec §"Endpoints".
    defn = get("novita")
    assert defn.probe_url == (
        "https://api.novita.ai/openapi/v1/billing/balance/detail"
    )
    assert defn.probe_method == "GET"


def test_novita_has_api_key_field():
    defn = get("novita")
    keys = [f["key"] for f in defn.config_fields]
    assert keys == ["api_key"]


def test_novita_has_no_linked_integrations():
    defn = get("novita")
    assert defn.linked_integrations == []


def test_novita_display_name_and_icon():
    defn = get("novita")
    assert defn.display_name == "Novita AI"
    assert defn.icon == "novita"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run pytest backend/tests/modules/providers/test_novita_registration.py -v
```

Expected: 7 tests fail with `assert defn is not None` / `AttributeError: 'NoneType' object has no attribute ...`.

- [ ] **Step 3: Add the registry entry**

In `backend/modules/providers/_registry.py`, inside the `_register_builtins()` function, **append** (after the existing `register(PremiumProviderDefinition(id="openrouter", ...))` block, still inside the function):

```python
    register(PremiumProviderDefinition(
        id="novita",
        display_name="Novita AI",
        icon="novita",
        base_url="https://api.novita.ai/openai/v1",
        capabilities=[Capability.LLM],
        config_fields=[_api_key_field("Novita AI API Key")],
        # /openai/v1/models is unauthenticated, so it cannot validate the
        # key. /openapi/v1/billing/balance/detail requires auth and 401s
        # on a bad key — see spec §"Endpoints".
        probe_url="https://api.novita.ai/openapi/v1/billing/balance/detail",
        probe_method="GET",
        linked_integrations=[],
    ))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/providers/test_novita_registration.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_registry.py backend/tests/modules/providers/test_novita_registration.py
git commit -m "Register Novita AI as a premium provider"
```

---

## Task 2: Resolver mapping + reserved slug

**Files:**
- Modify: `backend/modules/llm/_resolver.py:33-39` (the `_PREMIUM_ADAPTER_TYPE` dict)
- Modify: `backend/modules/llm/_connections.py:49-51` (the `RESERVED_SLUGS` frozenset)
- Create: `backend/tests/modules/llm/test_resolver_novita.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/test_resolver_novita.py`:

```python
"""Verifies the novita slug is wired into resolver and reserved-slug paths."""

from backend.modules.llm._connections import RESERVED_SLUGS
from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE


def test_novita_maps_to_novita_http_adapter():
    assert _PREMIUM_ADAPTER_TYPE["novita"] == "novita_http"


def test_novita_is_a_reserved_slug():
    # RESERVED_SLUGS gates two things: rejecting user-created Connections
    # whose slug would shadow the Premium Provider, and routing the
    # persona model_unique_id validator through the Premium Account
    # check rather than the Connection repository. Both must include
    # novita, otherwise saving a persona with a Novita model fails with
    # "Unknown or unowned connection 'novita'".
    assert "novita" in RESERVED_SLUGS
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_resolver_novita.py -v
```

Expected: both tests fail (`KeyError: 'novita'` and `assert 'novita' in frozenset(...)`).

- [ ] **Step 3: Add the resolver mapping**

In `backend/modules/llm/_resolver.py`, extend `_PREMIUM_ADAPTER_TYPE`:

```python
_PREMIUM_ADAPTER_TYPE: dict[str, str] = {
    "xai": "xai_http",
    "mistral": "mistral_http",
    "ollama_cloud": "ollama_http",
    "nano_gpt": "nano_gpt_http",
    "openrouter": "openrouter_http",
    "novita": "novita_http",
}
```

- [ ] **Step 4: Add to reserved slugs**

In `backend/modules/llm/_connections.py`, extend `RESERVED_SLUGS`:

```python
RESERVED_SLUGS: frozenset[str] = frozenset({
    "xai", "mistral", "ollama_cloud", "nano_gpt", "openrouter", "novita",
})
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_resolver_novita.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_resolver.py backend/modules/llm/_connections.py backend/tests/modules/llm/test_resolver_novita.py
git commit -m "Wire novita into resolver mapping and reserved slugs"
```

---

## Task 3: Adapter skeleton + premium-only registration

**Files:**
- Create: `backend/modules/llm/_adapters/_novita_http.py` (skeleton only)
- Modify: `backend/modules/llm/_registry.py` (import + `_PREMIUM_ONLY_ADAPTERS` entry)
- Create: `backend/tests/modules/llm/adapters/test_novita_http.py` (identity + premium-only tests)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/adapters/test_novita_http.py` with the initial cases:

```python
"""Tests for the Novita AI HTTP adapter.

Mirrors `test_openrouter_http.py`; coverage grows task by task.
"""

from __future__ import annotations

from backend.modules.llm._adapters._novita_http import NovitaHttpAdapter
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    _PREMIUM_ONLY_ADAPTERS,
    get_adapter_class,
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: import error (no module `_novita_http`).

- [ ] **Step 3: Create adapter skeleton**

Create `backend/modules/llm/_adapters/_novita_http.py`:

```python
"""Novita AI HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to Novita's open-source inference platform; we filter to text-
output, serverless, chat-typed models with a >=80k context window.

Structurally a slimmed-down clone of ``_openrouter_http.py``. The diff
vs OR is: no Anthropic-cache logic (Novita is open-source-only, not a
router), no OR-specific app-attribution headers, and a different model-
list schema. The shared OpenAI-compat SSE-helper extraction remains
deferred to its own session — helpers stay cloned per adapter for now.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class NovitaHttpAdapter(BaseAdapter):
    adapter_type = "novita_http"
    display_name = "Novita AI"
    view_id = "novita_http"
    secret_fields = frozenset({"api_key"})

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        raise NotImplementedError

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError
        yield  # pragma: no cover  # makes the body an async generator
```

- [ ] **Step 4: Register in `_PREMIUM_ONLY_ADAPTERS`**

In `backend/modules/llm/_registry.py`, add the import (alphabetically after the mistral/nano_gpt imports) and the registry entry:

```python
from backend.modules.llm._adapters._novita_http import NovitaHttpAdapter
```

```python
_PREMIUM_ONLY_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "xai_http": XaiHttpAdapter,
    "mistral_http": MistralHttpAdapter,
    "nano_gpt_http": NanoGptHttpAdapter,
    "openrouter_http": OpenRouterHttpAdapter,
    "novita_http": NovitaHttpAdapter,
}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/modules/llm/_registry.py backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Add Novita adapter skeleton and premium-only registration"
```

---

## Task 4: SSE helpers — `_parse_sse_line`, `_chunk_to_events`, `_ToolCallAccumulator`

**Files:**
- Modify: `backend/modules/llm/_adapters/_novita_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_novita_http.py`

- [ ] **Step 1: Append failing tests**

In `backend/tests/modules/llm/adapters/test_novita_http.py`, **append** at the bottom:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
)
from backend.modules.llm._adapters._novita_http import (
    _SSE_DONE,
    _chunk_to_events,
    _parse_sse_line,
    _ToolCallAccumulator,
)


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: import errors (no `_SSE_DONE`, `_chunk_to_events`, `_parse_sse_line`, `_ToolCallAccumulator` in the module).

- [ ] **Step 3: Add the helpers to `_novita_http.py`**

Edit `backend/modules/llm/_adapters/_novita_http.py`. **Replace** the file content with:

```python
"""Novita AI HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to Novita's open-source inference platform; we filter to text-
output, serverless, chat-typed models with a >=80k context window.

Structurally a slimmed-down clone of ``_openrouter_http.py``. The diff
vs OR is: no Anthropic-cache logic (Novita is open-source-only, not a
router), no OR-specific app-attribution headers, and a different model-
list schema. The shared OpenAI-compat SSE-helper extraction remains
deferred to its own session — helpers stay cloned per adapter for now.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    ``finalised()`` is idempotent: subsequent calls return an empty list.
    Some upstream providers emit two chunks with
    ``finish_reason="tool_calls"`` for the same call.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}
        self._finalised = False

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
        if self._finalised:
            return []
        self._finalised = True
        calls: list[dict] = []
        for _, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
            })
        return calls


def _chunk_to_events(
    chunk: dict, acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}

    if usage and not choices:
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        ))
        return events

    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta") or {}

    reasoning_content = delta.get("reasoning_content") or ""
    if reasoning_content:
        events.append(ThinkingDelta(delta=reasoning_content))

    reasoning = delta.get("reasoning") or ""
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
    elif finish in _REFUSAL_REASONS:
        events.append(StreamRefused(
            reason=finish,
            refusal_text=delta.get("refusal") or None,
        ))

    return events


def _parse_sse_line(line: str) -> dict | object | None:
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


class NovitaHttpAdapter(BaseAdapter):
    adapter_type = "novita_http"
    display_name = "Novita AI"
    view_id = "novita_http"
    secret_fields = frozenset({"api_key"})

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        raise NotImplementedError

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError
        yield  # pragma: no cover
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: 13 tests pass (3 prior + 10 new).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Add SSE parsing helpers to Novita adapter"
```

---

## Task 5: Message translation + payload building

**Files:**
- Modify: `backend/modules/llm/_adapters/_novita_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_novita_http.py`

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/modules/llm/adapters/test_novita_http.py`:

```python
from backend.modules.llm._adapters._novita_http import (
    _build_chat_payload,
    _translate_message,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)


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
    from shared.dtos.inference import ToolCallResult
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: import errors for `_translate_message` and `_build_chat_payload`.

- [ ] **Step 3: Add the functions to `_novita_http.py`**

After `_parse_sse_line` and before the `NovitaHttpAdapter` class, **insert**:

```python
def _translate_message(msg) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat
    message. Plain text collapses to a string; images force the array
    form. No cache_control markers — Novita does not route to Anthropic."""
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    if not image_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{p.media_type};base64,{p.data}"},
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


def _build_chat_payload(request: CompletionRequest) -> dict:
    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    # Reasoning toggle: ``exclude: true`` only when the user wants
    # thinking hidden on a reasoning-capable model. Built-in reasoners
    # ignore the field; non-reasoners shouldn't see it at all.
    if request.supports_reasoning and not request.reasoning_enabled:
        payload["reasoning"] = {"exclude": True}
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: 24 tests pass (13 prior + 11 new).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Add message translation and chat payload builder for Novita"
```

---

## Task 6: Filter rules and `_entry_to_meta` mapping

**Files:**
- Modify: `backend/modules/llm/_adapters/_novita_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_novita_http.py`

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/modules/llm/adapters/test_novita_http.py`:

```python
from datetime import UTC, datetime

from backend.modules.llm._adapters._novita_http import (
    MIN_CONTEXT_TOKENS,
    _entry_to_meta,
)
from backend.modules.llm._adapters._types import ResolvedConnection


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: import errors for `_entry_to_meta`, `MIN_CONTEXT_TOKENS`.

- [ ] **Step 3: Add the constant and function to `_novita_http.py`**

Add the import for `ModelMetaDto` if not yet present (it is — confirm). Then, **before** `_translate_message`, **insert**:

```python
# Mirrors nano-gpt / OpenRouter — sub-80k models leave no breathing
# room once chat history and tool definitions stack up. Spec §"Filter
# Rules".
MIN_CONTEXT_TOKENS = 80_000


def _entry_to_meta(entry: dict, c: ResolvedConnection) -> ModelMetaDto | None:
    """Map one Novita catalogue entry to a ``ModelMetaDto`` or ``None``.

    Filter rules — all must pass; see spec §"Model Filter Rules":
    1. ``output_modalities == ["text"]``
    2. ``context_size >= MIN_CONTEXT_TOKENS``
    3. ``"chat/completions" in endpoints``
    4. ``"serverless" in features``
    5. ``model_type == "chat"``
    6. ``status == 1``
    """
    output_mods = entry.get("output_modalities") or []
    if output_mods != ["text"]:
        return None

    context_size = int(entry.get("context_size") or 0)
    if context_size < MIN_CONTEXT_TOKENS:
        return None

    endpoints = entry.get("endpoints") or []
    if "chat/completions" not in endpoints:
        return None

    features = entry.get("features") or []
    if "serverless" not in features:
        return None

    if entry.get("model_type") != "chat":
        return None

    if entry.get("status") != 1:
        return None

    input_mods = entry.get("input_modalities") or []
    in_price = entry.get("input_token_price_per_m") or 0
    out_price = entry.get("output_token_price_per_m") or 0
    billing = "free" if in_price == 0 and out_price == 0 else "pay_per_token"

    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=entry["id"],
        display_name=entry.get("display_name") or entry["id"],
        context_window=context_size,
        supports_reasoning="reasoning" in features,
        supports_vision="image" in input_mods,
        supports_tool_calls="function-calling" in features,
        is_deprecated=False,
        billing_category=billing,
        is_moderated=None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: 38 tests pass (24 prior + 14 new).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Add Novita model filter rules and entry-to-meta mapping"
```

---

## Task 7: `fetch_models` HTTP layer

**Files:**
- Modify: `backend/modules/llm/_adapters/_novita_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_novita_http.py`

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/modules/llm/adapters/test_novita_http.py`:

```python
import json
from unittest.mock import patch

import httpx
import pytest


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: `NotImplementedError` for the 5 new async tests.

- [ ] **Step 3: Implement `fetch_models`**

In `_novita_http.py`, add `httpx` import (top of file, alongside `json`):

```python
import httpx
```

Add the timeout constant near the existing module-level constants (after `_REFUSAL_REASONS`):

```python
_PROBE_TIMEOUT = httpx.Timeout(10.0)
```

Replace the `fetch_models` body:

```python
    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(f"{url}/models", headers=headers)
        except httpx.HTTPError as exc:
            _log.warning("novita_http.fetch_models transport: %s", exc)
            return []

        if resp.status_code in (401, 403):
            _log.warning(
                "novita_http.fetch_models auth failure: status=%d",
                resp.status_code,
            )
            return []
        if resp.status_code != 200:
            _log.warning(
                "novita_http.fetch_models upstream %d: %s",
                resp.status_code, resp.text[:200],
            )
            return []

        try:
            data = resp.json()
        except ValueError:
            _log.warning("novita_http.fetch_models malformed JSON")
            return []

        entries = data.get("data") or []
        if not isinstance(entries, list):
            return []

        metas: list[ModelMetaDto] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            meta = _entry_to_meta(entry, c)
            if meta is not None:
                metas.append(meta)
        return metas
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: 43 tests pass (38 prior + 5 new).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Implement Novita fetch_models with HTTP error fallbacks"
```

---

## Task 8: `stream_completion` SSE loop with retries and gutter timer

**Files:**
- Modify: `backend/modules/llm/_adapters/_novita_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_novita_http.py`

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/modules/llm/adapters/test_novita_http.py`:

```python
import asyncio

from backend.modules.llm._adapters._events import StreamError


class _FakeStreamResponse:
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


class _FakeStreamingClientWithStatusSeq(_FakeStreamingClient):
    """Returns one response per attempt, controlled by ``status_codes_seq``."""

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
async def test_stream_completion_emits_content_then_done():
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[{"finish_reason":"stop","delta":{}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClient(lines)

    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="xiaomimimo/mimo-v2.5-pro",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )

    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
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
async def test_stream_completion_sends_authorization_header():
    lines = [
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClient(lines)

    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )

    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_args, **_kw: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass

    assert fake.captured_headers is not None
    assert fake.captured_headers["Authorization"].startswith("Bearer ")
    assert fake.captured_headers["Content-Type"] == "application/json"
    # Novita has no app-attribution headers — must NOT send OR-style ones.
    assert "HTTP-Referer" not in fake.captured_headers
    assert "X-OpenRouter-Title" not in fake.captured_headers


@pytest.mark.asyncio
async def test_stream_completion_401_yields_invalid_api_key():
    fake = _FakeStreamingClient([], status_code=401)
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "invalid_api_key"
    assert "Novita" in errs[0].message


@pytest.mark.asyncio
async def test_stream_completion_retries_on_429_then_succeeds(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"OK"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClientWithStatusSeq(lines, status_codes_seq=[429, 200])
    monkeypatch.setattr(
        "backend.modules.llm._adapters._novita_http.asyncio.sleep",
        _async_noop,
    )

    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]

    contents = [e for e in events if isinstance(e, ContentDelta)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert "".join(c.delta for c in contents) == "OK"
    assert len(dones) == 1
    assert errs == []
    assert fake.attempts == 2


@pytest.mark.asyncio
async def test_stream_completion_429_yields_provider_unavailable_after_retries(monkeypatch):
    fake = _FakeStreamingClient([], status_code=429)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._novita_http.asyncio.sleep",
        _async_noop,
    )
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"
    assert "429" in errs[0].message


@pytest.mark.asyncio
async def test_stream_completion_5xx_yields_provider_unavailable():
    fake = _FakeStreamingClient([], status_code=500)
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"


@pytest.mark.asyncio
async def test_stream_completion_does_not_retry_on_5xx():
    """500/502 are NOT retryable here — they signal a downstream model
    error rather than a transient backoff signal. Surface immediately."""
    fake = _FakeStreamingClientWithStatusSeq([], status_codes_seq=[500])
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass
    assert fake.attempts == 1


@pytest.mark.asyncio
async def test_stream_completion_does_not_retry_on_401():
    fake = _FakeStreamingClientWithStatusSeq([], status_codes_seq=[401])
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass
    assert fake.attempts == 1


@pytest.mark.asyncio
async def test_stream_completion_429_honours_retry_after_header(monkeypatch):
    captured: list[float] = []

    async def capture_sleep(delay: float) -> None:
        captured.append(delay)

    monkeypatch.setattr(
        "backend.modules.llm._adapters._novita_http.asyncio.sleep",
        capture_sleep,
    )

    fake = _FakeStreamingClientWithStatusSeq(
        ['data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
         "data: [DONE]"],
        status_codes_seq=[429, 200],
        response_headers={"Retry-After": "7"},
    )
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        async for _ in a.stream_completion(_resolved(), req):
            pass

    backoff_sleeps = [s for s in captured if s > 0]
    assert backoff_sleeps == [7.0]


@pytest.mark.asyncio
async def test_stream_completion_connect_error_yields_provider_unavailable():
    class _ConnectError(_FakeStreamingClient):
        def stream(self, method, url, json=None, headers=None):  # noqa: ARG002
            raise httpx.ConnectError("network down")

    fake = _ConnectError([], 200)
    a = NovitaHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._novita_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"
    assert "Novita" in errs[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: `NotImplementedError` for the 10 new streaming tests.

- [ ] **Step 3: Implement `stream_completion`**

In `_novita_http.py`, **extend the existing** `from backend.modules.llm._adapters._events import (...)` block to also include `StreamAborted`, `StreamError`, `StreamSlow` (alphabetical order). Resulting block:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
```

**Add** new top-level stdlib imports next to the existing `json` / `logging` imports:

```python
import asyncio
import os
import time
```

**Add** the `_retry` import block alongside the other `from backend.*` imports:

```python
from backend._retry import (
    MAX_RETRY_ATTEMPTS,
    compute_retry_delay,
    log_retry,
    parse_retry_after,
    should_retry_status,
)
```

Add the streaming-specific module constants (after `_PROBE_TIMEOUT`):

```python
GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"
```

Replace the `stream_completion` body with the full implementation:

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

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=novita-out url=%s payload=%s",
                url, json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                retry_delay: float | None = None
                try:
                    async with client.stream(
                        "POST", f"{url}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        if (
                            should_retry_status(resp.status_code)
                            and attempt < MAX_RETRY_ATTEMPTS
                        ):
                            retry_delay = compute_retry_delay(
                                attempt,
                                parse_retry_after(resp.headers),
                            )
                            log_retry(
                                _log,
                                operation="novita_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Novita rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Novita returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} "
                                    f"attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode(
                                "utf-8", errors="replace",
                            )[:500]
                            _log.error(
                                "novita_http upstream %d: %s",
                                resp.status_code, detail,
                            )
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Novita returned {resp.status_code}: "
                                    f"{detail}"
                                ),
                            )
                            return
                        else:
                            acc = _ToolCallAccumulator()
                            seen_done = False
                            last_usage: dict = {}
                            pending_next: asyncio.Task | None = None
                            try:
                                stream_iter = resp.aiter_lines().__aiter__()
                                line_start = time.monotonic()
                                slow_fired = False

                                while True:
                                    elapsed = time.monotonic() - line_start
                                    budget = (
                                        GUTTER_ABORT_SECONDS - elapsed
                                        if slow_fired
                                        else GUTTER_SLOW_SECONDS - elapsed
                                    )
                                    if budget <= 0:
                                        if not slow_fired:
                                            _log.info(
                                                "novita_http.gutter_slow "
                                                "model=%s idle=%.1fs",
                                                payload.get("model"),
                                                elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "novita_http.gutter_abort "
                                            "model=%s idle=%.1fs",
                                            payload.get("model"), elapsed,
                                        )
                                        if pending_next is not None:
                                            pending_next.cancel()
                                        yield StreamAborted(
                                            reason="gutter_timeout",
                                        )
                                        return
                                    if pending_next is None:
                                        pending_next = asyncio.ensure_future(
                                            stream_iter.__anext__(),
                                        )
                                    done, _pending = await asyncio.wait(
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

                                    if (
                                        isinstance(parsed, dict)
                                        and parsed.get("usage")
                                    ):
                                        last_usage = parsed["usage"]

                                    for event in _chunk_to_events(parsed, acc):
                                        if isinstance(event, StreamDone):
                                            seen_done = True
                                        yield event
                                        if isinstance(event, (
                                            StreamDone, StreamRefused,
                                            StreamError,
                                        )):
                                            return
                            except asyncio.CancelledError:
                                if (
                                    pending_next is not None
                                    and not pending_next.done()
                                ):
                                    pending_next.cancel()
                                raise
                            if not seen_done:
                                yield StreamDone(
                                    input_tokens=last_usage.get("prompt_tokens"),
                                    output_tokens=last_usage.get(
                                        "completion_tokens",
                                    ),
                                )
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Novita",
                    )
                    return

                # Retry path: a 429 with attempts remaining set retry_delay.
                # Sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v
```

Expected: 53 tests pass (43 prior + 10 new).

- [ ] **Step 5: Run a syntax/import check on the full module**

```bash
PYTHONPATH=. uv run python -m py_compile backend/modules/llm/_adapters/_novita_http.py
```

Expected: no output (clean compile).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Implement Novita stream_completion with retries and gutter timer"
```

---

## Task 9: Cross-cutting build & test verification

**Files:** none (verification only)

- [ ] **Step 1: py_compile every changed Python file**

```bash
PYTHONPATH=. uv run python -m py_compile \
  backend/modules/providers/_registry.py \
  backend/modules/llm/_resolver.py \
  backend/modules/llm/_connections.py \
  backend/modules/llm/_registry.py \
  backend/modules/llm/_adapters/_novita_http.py
```

Expected: no output (all compile cleanly).

- [ ] **Step 2: Run all newly-added tests together**

```bash
PYTHONPATH=. uv run pytest \
  backend/tests/modules/providers/test_novita_registration.py \
  backend/tests/modules/llm/test_resolver_novita.py \
  backend/tests/modules/llm/adapters/test_novita_http.py \
  -v
```

Expected: 62 tests pass total (7 + 2 + 53).

- [ ] **Step 3: Run the broader LLM module unit suite**

These exclude the four MongoDB-dependent files that need Docker on host (per project convention — those run in CI / via compose):

```bash
PYTHONPATH=. uv run pytest \
  backend/tests/modules/llm/test_registry.py \
  backend/tests/modules/llm/test_resolver_openrouter.py \
  backend/tests/modules/llm/test_resolver_novita.py \
  backend/tests/modules/llm/adapters/ \
  backend/tests/modules/providers/ \
  -v
```

Expected: all green; no pre-existing tests regressed by the Novita changes.

- [ ] **Step 4: No extra commit**

This task introduces no new code; the verification simply confirms the prior commits hold together.

---

## Task 10: Manual verification (Chris executes)

**Files:** none

This task is for Chris to run on the dev environment with the API key in `.novita-test-key`. The implementing subagent **must not** attempt to run these — they require a real account and real network.

- [ ] **Step 1: UserModal → Integrations → Novita AI card visible**

Open the running app, navigate to the Integrations tab — confirm "Novita AI" appears in the list, status `not set`.

- [ ] **Step 2: Save API key from `.novita-test-key`, run Test → status `ok`**

Paste the key, click Save, click Test. Status should transition to `ok` and the green dot should appear.

- [ ] **Step 3: Replace with a known-bad key, Test → status `error`**

Edit the key to `sk-invalid-test`, Save, Test. Expect `error: ...` with the upstream's 401 surfaced.

- [ ] **Step 4: Restore good key. Model Browser shows expected entries**

Confirm:
- `xiaomimimo/mimo-v2.5-pro` listed under Novita AI
- `xiaomimimo/mimo-v2.5-omni` listed
- No model with context_size < 80k visible
- No image-output / non-serverless models visible

- [ ] **Step 5: Persona with `novita:xiaomimimo/mimo-v2.5-pro` chats successfully**

Create or edit a persona, set default model to the MiMo Pro novita slug, send a short message — receive a streamed response.

- [ ] **Step 6: Reasoning toggle ON → thinking pill appears**

With reasoning enabled in the persona, ask a reasoning-provoking question (e.g. "Solve x^2 + 5x + 6 = 0 step by step"). Confirm a thinking pill streams reasoning content before the answer.

- [ ] **Step 7: Reasoning toggle OFF → no thinking pill**

Disable reasoning on the same persona/model, repeat. No thinking pill — just the answer.

- [ ] **Step 8: Tool-calling model invokes a tool**

Pick a Novita model with `supports_tool_calls=True`, configure a persona with one tool group enabled (e.g. websearch), send a message that should trigger the tool. Tool call event fires, tool runs, follow-up assistant message lands.

- [ ] **Step 9 (optional): Vision-capable model handles an image**

Only if the filtered list includes a vision-capable Novita model. Attach an image, send "describe this image". Confirm a sensible response.

- [ ] **Step 10: Mid-stream invalid key → recoverable error event**

Manually corrupt the stored API key in MongoDB (e.g. via `mongosh`), start a chat — confirm the user sees an `invalid_api_key` error event with `recoverable=true`.

If anything fails, capture: which step, what was the symptom (UI screenshot, console error, backend log line), and report back. **Do not** patch silently.

---

## Self-Review Checklist (run before declaring the plan complete)

These notes are for the implementing agent's final review.

- [ ] Spec coverage: every section of `devdocs/specs/2026-05-08-novita-premium-provider-design.md` has at least one task implementing it (Architecture → Tasks 3–8; Endpoints → Tasks 1, 7, 8; Registry Wiring → Tasks 1, 2, 3; Adapter → Tasks 3–8; Filter Rules → Task 6; Field Mapping → Task 6; Probe / Test → Task 1 (registration), Task 10 (manual probe); Frontend Impact → none required, verified in Task 10; Manual Verification → Task 10; Out of Scope → respected throughout).
- [ ] All test files have unique test names (no duplicates introduced when growing them across tasks).
- [ ] Type and signature consistency: `_chunk_to_events`, `_ToolCallAccumulator`, `_parse_sse_line`, `_translate_message`, `_build_chat_payload`, `_entry_to_meta`, `MIN_CONTEXT_TOKENS`, `_SSE_DONE`, `_PROBE_TIMEOUT`, `_TIMEOUT`, `GUTTER_SLOW_SECONDS`, `GUTTER_ABORT_SECONDS` are introduced exactly once and referenced by the same name in tests.
- [ ] No commits skipped between tasks; the branch ends with one commit per task that introduces code.
- [ ] No file was modified outside the file-structure table.

## Execution Handoff

**Plan complete and saved to `devdocs/plans/2026-05-08-novita-premium-provider.md`.**

Per project convention (memory: "Subagent driven implementation always" in Chatsune), this plan is intended for **Subagent-Driven execution**: dispatch a fresh subagent per task, review between tasks, with the explicit constraint **"do not merge, do not push, do not switch branches"** baked into every dispatch prompt. Chris merges at the end.
