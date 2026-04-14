# Connections Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the singleton upstream-provider model (`ollama_cloud` + `ollama_local` as globals) with per-user named Connections backed by type-specific adapters. Prepares adapter abstraction for a future `ollama_sidecar` adapter.

**Architecture:** Adapters are code (class per backend-type, declares templates, sub-router, view_id). Connections are user-owned Mongo documents (adapter_type, display_name, slug, plain + encrypted config). Concurrency per-connection via `asyncio.Semaphore(max_parallel)`. Admin curation and `KEY_SOURCES` are removed; web search owns its credentials. Hard-cut migration — no data preservation.

**Tech Stack:** FastAPI + Motor + Redis (backend), React/TSX + Vite + Tailwind (frontend), Pydantic v2 DTOs + events in `shared/`.

**Spec:** `docs/superpowers/specs/2026-04-14-connections-refactor-design.md`

---

## Task Granularity Note

This refactor is monolithic by nature — the hard-cut means backend and frontend must land together for a clean boot. Tasks are sequenced so each commit is syntactically clean (Python compiles, TypeScript builds) even if user-visible features are temporarily broken during the middle of the sequence. Do not skip ahead.

**Verification commands** used across tasks:
- Backend syntax: `docker compose run --rm backend uv run python -m py_compile <path>`
- Backend full import check: `docker compose run --rm backend uv run python -c "from backend.main import app"`
- Frontend typecheck: `docker compose run --rm frontend pnpm tsc --noEmit`
- Frontend build: `docker compose run --rm frontend pnpm run build`
- Backend tests: `docker compose run --rm backend uv run pytest <path> -v`

Build via Docker (project CLAUDE.md convention).

---

## Phase 1 — Shared Contracts

### Task 1: New topic constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Add new connection + websearch topic constants**

Open `shared/topics.py` and locate the `Topics` class. Under a new section `# --- LLM Connections (connections refactor) ---` add:

```python
LLM_CONNECTION_CREATED = "llm.connection.created"
LLM_CONNECTION_UPDATED = "llm.connection.updated"
LLM_CONNECTION_REMOVED = "llm.connection.removed"
LLM_CONNECTION_TESTED = "llm.connection.tested"
LLM_CONNECTION_STATUS_CHANGED = "llm.connection.status_changed"
LLM_CONNECTION_MODELS_REFRESHED = "llm.connection.models_refreshed"
```

Add a new section `# --- Web Search ---`:

```python
WEBSEARCH_CREDENTIAL_SET = "websearch.credential.set"
WEBSEARCH_CREDENTIAL_REMOVED = "websearch.credential.removed"
WEBSEARCH_CREDENTIAL_TESTED = "websearch.credential.tested"
```

- [ ] **Step 2: Remove obsolete topic constants**

Delete these constants from the same file:

```
LLM_CREDENTIAL_SET
LLM_CREDENTIAL_REMOVED
LLM_CREDENTIAL_TESTED
LLM_MODEL_CURATED
LLM_PROVIDER_STATUS_CHANGED
LLM_MODELS_FETCH_STARTED
LLM_MODELS_FETCH_COMPLETED
```

- [ ] **Step 3: Verify syntax**

Run: `docker compose run --rm backend uv run python -m py_compile shared/topics.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add shared/topics.py
git commit -m "Add connection + websearch topics, remove provider credential/curation topics"
```

---

### Task 2: Replace LLM + websearch event models

**Files:**
- Modify: `shared/events/llm.py`
- Create: `shared/events/websearch.py`
- Modify: `shared/events/__init__.py` (if it re-exports)

- [ ] **Step 1: Replace `shared/events/llm.py`**

Rewrite the file as:

```python
from datetime import datetime

from pydantic import Field

from shared.events.base import BaseEvent
from shared.dtos.llm import ConnectionDto, ModelMetaDto, UserModelConfigDto


class LlmConnectionCreatedEvent(BaseEvent):
    connection: ConnectionDto


class LlmConnectionUpdatedEvent(BaseEvent):
    connection: ConnectionDto


class LlmConnectionRemovedEvent(BaseEvent):
    connection_id: str
    affected_persona_ids: list[str] = Field(default_factory=list)


class LlmConnectionTestedEvent(BaseEvent):
    connection_id: str
    valid: bool
    error: str | None = None


class LlmConnectionStatusChangedEvent(BaseEvent):
    connection_id: str
    status: str  # "reachable" | "unreachable" | "unauthorised" | "disconnected"


class LlmConnectionModelsRefreshedEvent(BaseEvent):
    connection_id: str


class LlmUserModelConfigUpdatedEvent(BaseEvent):
    model_unique_id: str
    config: UserModelConfigDto
```

- [ ] **Step 2: Create `shared/events/websearch.py`**

```python
from shared.events.base import BaseEvent


class WebSearchCredentialSetEvent(BaseEvent):
    provider_id: str


class WebSearchCredentialRemovedEvent(BaseEvent):
    provider_id: str


class WebSearchCredentialTestedEvent(BaseEvent):
    provider_id: str
    valid: bool
    error: str | None = None
```

- [ ] **Step 3: Drop obsolete event classes from `shared/events/llm.py`**

Ensure these are gone (step 1 rewrote the file — confirm):
`LlmCredentialSetEvent`, `LlmCredentialRemovedEvent`, `LlmCredentialTestedEvent`, `LlmModelCuratedEvent`, `LlmProviderStatusChangedEvent`, `LlmModelsFetchStartedEvent`, `LlmModelsFetchCompletedEvent`, `LlmModelsRefreshedEvent`.

- [ ] **Step 4: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile shared/events/llm.py shared/events/websearch.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add shared/events/llm.py shared/events/websearch.py
git commit -m "Rewrite llm events for connection model; add websearch events"
```

---

### Task 3: DTO additions and changes

**Files:**
- Modify: `shared/dtos/llm.py`
- Create: `shared/dtos/websearch.py` (augment existing or add connection-related DTOs)

- [ ] **Step 1: Add new DTOs to `shared/dtos/llm.py`**

Append to the file (keep existing `UserModelConfigDto`, `ModelMetaDto` but change the latter as shown):

```python
from pydantic import BaseModel, Field


class AdapterTemplateDto(BaseModel):
    id: str
    display_name: str
    slug_prefix: str
    config_defaults: dict


class AdapterDto(BaseModel):
    adapter_type: str
    display_name: str
    view_id: str
    templates: list[AdapterTemplateDto]
    config_schema: list[dict]  # simple field-hint list for the wizard
    secret_fields: list[str]


class ConnectionDto(BaseModel):
    id: str
    user_id: str
    adapter_type: str
    display_name: str
    slug: str
    config: dict  # safe view: secret fields redacted as {"is_set": bool}
    last_test_status: str | None = None
    last_test_error: str | None = None
    last_test_at: str | None = None  # ISO timestamp
    created_at: str
    updated_at: str


class CreateConnectionDto(BaseModel):
    adapter_type: str
    display_name: str
    slug: str
    config: dict


class UpdateConnectionDto(BaseModel):
    display_name: str | None = None
    slug: str | None = None
    config: dict | None = None
```

- [ ] **Step 2: Update `ModelMetaDto`**

Replace its `provider_id`, `provider_display_name`, and `curation` fields:

```python
class ModelMetaDto(BaseModel):
    connection_id: str
    connection_display_name: str
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_tool_calls: bool = False
    parameter_count: str | None = None
    raw_parameter_count: int | None = None
    quantisation_level: str | None = None
```

Ensure no `curation: ModelCurationDto | None` field remains.

- [ ] **Step 3: Delete removed DTO classes**

From `shared/dtos/llm.py`, remove the following (grep first, then delete each):
`ProviderCredentialDto`, `ModelCurationDto`, `SetModelCurationDto`, `SetProviderKeyDto`, `FaultyProviderDto`.

Run: `grep -n "ProviderCredentialDto\|ModelCurationDto\|SetModelCurationDto\|SetProviderKeyDto\|FaultyProviderDto" shared/dtos/llm.py`
Expected: no matches.

- [ ] **Step 4: Add websearch DTOs**

Append to `shared/dtos/websearch.py`:

```python
class WebSearchProviderDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    last_test_status: str | None = None
    last_test_error: str | None = None


class WebSearchCredentialDto(BaseModel):
    provider_id: str
    is_configured: bool
    last_test_status: str | None = None
    last_test_error: str | None = None
    last_test_at: str | None = None


class SetWebSearchKeyDto(BaseModel):
    api_key: str
```

- [ ] **Step 5: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile shared/dtos/llm.py shared/dtos/websearch.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/llm.py shared/dtos/websearch.py
git commit -m "Replace provider-era LLM DTOs with Connection/Adapter DTOs; add websearch DTOs"
```

---

### Task 4: Update WebSocket event fan-out table

**Files:**
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Open the file and locate `_FANOUT`**

Run: `grep -n "_FANOUT" backend/ws/event_bus.py | head -5`

- [ ] **Step 2: Remove obsolete entries**

Delete the six old-topic entries:
`Topics.LLM_CREDENTIAL_SET`, `Topics.LLM_CREDENTIAL_REMOVED`, `Topics.LLM_CREDENTIAL_TESTED`, `Topics.LLM_MODEL_CURATED`, `Topics.LLM_PROVIDER_STATUS_CHANGED`, `Topics.LLM_MODELS_FETCH_STARTED`, `Topics.LLM_MODELS_FETCH_COMPLETED`, `Topics.LLM_MODELS_REFRESHED`.

- [ ] **Step 3: Add new entries**

For each new topic, add a `_FANOUT` rule matching the existing pattern in the file (likely `FanoutRule(target="user")` for per-user events). Consult the file's existing rule syntax — the rule per entry typically looks like:

```python
Topics.LLM_CONNECTION_CREATED: FanoutRule(target="user"),
Topics.LLM_CONNECTION_UPDATED: FanoutRule(target="user"),
Topics.LLM_CONNECTION_REMOVED: FanoutRule(target="user"),
Topics.LLM_CONNECTION_TESTED: FanoutRule(target="user"),
Topics.LLM_CONNECTION_STATUS_CHANGED: FanoutRule(target="user"),
Topics.LLM_CONNECTION_MODELS_REFRESHED: FanoutRule(target="user"),
Topics.WEBSEARCH_CREDENTIAL_SET: FanoutRule(target="user"),
Topics.WEBSEARCH_CREDENTIAL_REMOVED: FanoutRule(target="user"),
Topics.WEBSEARCH_CREDENTIAL_TESTED: FanoutRule(target="user"),
```

If the target-type helper name or enum differs, match the existing rule for `LLM_USER_MODEL_CONFIG_UPDATED` (also per-user).

- [ ] **Step 4: Compile + verify imports resolve**

Run: `docker compose run --rm backend uv run python -m py_compile backend/ws/event_bus.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add backend/ws/event_bus.py
git commit -m "Update event bus fan-out for connection + websearch topics"
```

---

## Phase 2 — Backend Adapter Abstraction

### Task 5: New `BaseAdapter` interface + helper types

**Files:**
- Modify: `backend/modules/llm/_adapters/_base.py`
- Create: `backend/modules/llm/_adapters/_types.py`

- [ ] **Step 1: Create `_types.py` with ResolvedConnection and AdapterTemplate**

```python
"""Internal types passed into adapters by the generic connection resolver."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ResolvedConnection:
    """Plain + decrypted config for adapter use. Never persist this."""
    id: str
    user_id: str
    adapter_type: str
    display_name: str
    slug: str
    config: dict  # merged plain + decrypted secrets
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdapterTemplate:
    """UX preset shown in the add-connection wizard."""
    id: str
    display_name: str
    slug_prefix: str
    config_defaults: dict


@dataclass(frozen=True)
class ConfigFieldHint:
    """Lightweight form-rendering hint. Not a full schema engine."""
    name: str
    type: str          # "string" | "url" | "secret" | "integer"
    label: str
    required: bool = True
    min: int | None = None
    max: int | None = None
    placeholder: str | None = None
```

- [ ] **Step 2: Rewrite `_base.py`**

```python
"""Abstract base for upstream inference adapters (connections refactor)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from fastapi import APIRouter

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Stateless adapter — one class per backend-type, one instance per request."""

    # Subclasses MUST override
    adapter_type: str = ""
    display_name: str = ""
    view_id: str = ""
    secret_fields: frozenset[str] = frozenset()

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return []

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return []

    @classmethod
    def router(cls) -> APIRouter | None:
        """Optional adapter-specific sub-router (test, diagnostics, pair, ...)."""
        return None

    @abstractmethod
    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        ...

    @abstractmethod
    def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        ...
```

- [ ] **Step 3: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_adapters/_base.py backend/modules/llm/_adapters/_types.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_base.py backend/modules/llm/_adapters/_types.py
git commit -m "Introduce ResolvedConnection + AdapterTemplate; rewrite BaseAdapter for connection model"
```

---

### Task 6: Unified Ollama HTTP adapter

**Files:**
- Create: `backend/modules/llm/_adapters/_ollama_http.py`
- Keep (read-only): `backend/modules/llm/_adapters/_ollama_base.py` — contents will be moved into the new file as private helpers; the base file is deleted in Task 22.

- [ ] **Step 1: Create `_ollama_http.py` with the adapter class skeleton**

```python
"""Ollama HTTP adapter — unified for local, cloud, and custom instances."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.config import settings
from backend.modules.llm._adapters._base import BaseAdapter
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
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"))


# ----- helpers (moved from _ollama_base.py) -----

def _is_refusal_reason(reason: str | None) -> bool:
    if not reason:
        return False
    return reason.lower() in _REFUSAL_REASONS


def _parse_parameter_size(value: str) -> int | None:
    value = value.strip().upper()
    suffixes = {"T": 10**12, "B": 10**9, "M": 10**6, "K": 10**3}
    for suffix, mul in suffixes.items():
        if value.endswith(suffix):
            try:
                return int(float(value[:-1]) * mul)
            except (ValueError, TypeError):
                return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _format_parameter_count(value: int | None) -> str | None:
    if not value:
        return None
    if value >= 10**12:
        n = value / 10**12
        return f"{int(n)}T" if n == int(n) else f"{n:.1f}T"
    if value >= 10**9:
        n = value / 10**9
        return f"{int(n)}B" if n == int(n) else f"{n:.1f}B"
    if value >= 10**6:
        n = value / 10**6
        return f"{int(n)}M" if n == int(n) else f"{n:.1f}M"
    return None


def _build_display_name(model_name: str) -> str:
    colon = model_name.find(":")
    if colon >= 0:
        name_part = model_name[:colon]
        tag = model_name[colon + 1:]
    else:
        name_part = model_name
        tag = None
    title = " ".join(w.capitalize() for w in name_part.split("-"))
    if not tag or tag.lower() == "latest":
        return title
    return f"{title} ({tag.upper()})"


def _translate_message(msg: CompletionMessage) -> dict:
    text_parts = [p.text for p in msg.content if p.type == "text" and p.text]
    images = [p.data for p in msg.content if p.type == "image" and p.data]
    result: dict = {
        "role": msg.role,
        "content": "".join(text_parts) if text_parts else "",
    }
    if images:
        result["images"] = images
    if msg.tool_calls:
        result["tool_calls"] = [
            {"function": {"name": tc.name, "arguments": json.loads(tc.arguments)}}
            for tc in msg.tool_calls
        ]
    return result


def _build_chat_payload(request: CompletionRequest) -> dict:
    messages = [_translate_message(m) for m in request.messages]
    payload: dict = {"model": request.model, "messages": messages, "stream": True}
    if request.supports_reasoning:
        payload["think"] = request.reasoning_enabled
    if request.temperature is not None:
        payload["options"] = {"temperature": request.temperature}
    if request.tools:
        payload["tools"] = [
            {
                "type": t.type,
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload


def _auth_headers(api_key: str | None) -> dict:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _map_to_dto(
    connection_id: str, connection_display_name: str,
    model_name: str, detail: dict,
) -> ModelMetaDto:
    capabilities = detail.get("capabilities", [])
    model_info = detail.get("model_info", {})
    details = detail.get("details", {})
    context_window = 0
    for key, value in model_info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            context_window = value
            break
    raw_params = None
    param_str = details.get("parameter_size")
    if param_str is not None:
        raw_params = _parse_parameter_size(param_str)
    if raw_params is None:
        raw_params = model_info.get("general.parameter_count")
        if raw_params is not None and not isinstance(raw_params, int):
            try:
                raw_params = int(raw_params)
            except (ValueError, TypeError):
                raw_params = None
    return ModelMetaDto(
        connection_id=connection_id,
        connection_display_name=connection_display_name,
        model_id=model_name,
        display_name=_build_display_name(model_name),
        context_window=context_window,
        supports_reasoning="thinking" in capabilities,
        supports_vision="vision" in capabilities,
        supports_tool_calls="tools" in capabilities,
        parameter_count=_format_parameter_count(raw_params),
        raw_parameter_count=raw_params,
        quantisation_level=details.get("quantization_level"),
    )


# ----- adapter -----

class OllamaHttpAdapter(BaseAdapter):
    adapter_type = "ollama_http"
    display_name = "Ollama"
    view_id = "ollama_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="ollama_local",
                display_name="Ollama Local",
                slug_prefix="ollama-local",
                config_defaults={
                    "url": "http://localhost:11434",
                    "api_key": "",
                    "max_parallel": 1,
                },
            ),
            AdapterTemplate(
                id="ollama_cloud",
                display_name="Ollama Cloud",
                slug_prefix="ollama-cloud",
                config_defaults={
                    "url": "https://ollama.com",
                    "api_key": "",
                    "max_parallel": 3,
                },
            ),
            AdapterTemplate(
                id="custom",
                display_name="Custom",
                slug_prefix="ollama",
                config_defaults={"url": "", "api_key": "", "max_parallel": 1},
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(name="url", type="url", label="URL",
                            placeholder="http://localhost:11434"),
            ConfigFieldHint(name="api_key", type="secret", label="API Key",
                            required=False),
            ConfigFieldHint(name="max_parallel", type="integer",
                            label="Max parallel inferences",
                            min=1, max=32),
        ]

    @classmethod
    def router(cls) -> APIRouter:
        # Defined below to keep handler functions close to the adapter.
        return _build_adapter_router()

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tags_resp = await client.get(
                f"{url}/api/tags", headers=_auth_headers(api_key),
            )
            tags_resp.raise_for_status()
            tag_entries = tags_resp.json().get("models", [])

            sem = asyncio.Semaphore(5)

            async def _fetch_one(name: str) -> tuple[str, dict | None]:
                async with sem:
                    try:
                        show_resp = await client.post(
                            f"{url}/api/show",
                            json={"model": name},
                            headers=_auth_headers(api_key),
                        )
                        show_resp.raise_for_status()
                        return name, show_resp.json()
                    except Exception:
                        _log.warning("Failed detail fetch for model '%s'", name)
                        return name, None

            results = await asyncio.gather(
                *(_fetch_one(e["name"]) for e in tag_entries),
            )
        return [
            _map_to_dto(c.id, c.display_name, name, detail)
            for name, detail in results if detail is not None
        ]

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        payload = _build_chat_payload(request)
        seen_done = False
        pending_next: asyncio.Task | None = None
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{url}/api/chat",
                    json=payload, headers=_auth_headers(api_key),
                ) as resp:
                    if resp.status_code in (401, 403):
                        yield StreamError(error_code="invalid_api_key", message="Invalid API key")
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:500]
                        _log.error("Upstream %d for model %s: %s",
                                   resp.status_code, payload.get("model"), detail)
                        yield StreamError(
                            error_code="provider_unavailable",
                            message=f"Upstream returned {resp.status_code}: {detail}",
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
                            pending_next = asyncio.ensure_future(stream_iter.__anext__())
                        done, _ = await asyncio.wait({pending_next}, timeout=budget)
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
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            _log.warning("Skipping malformed NDJSON: %s", line)
                            continue
                        if chunk.get("done"):
                            seen_done = True
                            reason = chunk.get("done_reason")
                            if _is_refusal_reason(reason):
                                msg = chunk.get("message", {})
                                yield StreamRefused(
                                    reason=reason,
                                    refusal_text=msg.get("refusal") or None,
                                )
                                return
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
                            fn = tc.get("function", {})
                            yield ToolCallEvent(
                                id=f"call_{uuid4().hex[:12]}",
                                name=fn.get("name", ""),
                                arguments=json.dumps(fn.get("arguments", {})),
                            )
            except asyncio.CancelledError:
                if pending_next is not None and not pending_next.done():
                    pending_next.cancel()
                _log.warning("Stream cancelled mid-flight (model=%s)",
                             payload.get("model"))
                raise
            except httpx.ConnectError:
                yield StreamError(error_code="provider_unavailable", message="Connection failed")
                return
        if not seen_done:
            yield StreamDone()


# ----- adapter sub-router (test + diagnostics) -----

def _build_adapter_router() -> APIRouter:
    from backend.modules.llm._resolver import resolve_connection_for_user
    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(f"{url}/api/tags",
                                        headers=_auth_headers(api_key))
                if resp.status_code in (401, 403):
                    return {"valid": False, "error": "Invalid API key"}
                resp.raise_for_status()
                return {"valid": True, "error": None}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    @router.get("/diagnostics")
    async def diagnostics(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            try:
                ps_resp, tags_resp = await asyncio.gather(
                    client.get(f"{url}/api/ps", headers=_auth_headers(api_key)),
                    client.get(f"{url}/api/tags", headers=_auth_headers(api_key)),
                )
                ps_resp.raise_for_status()
                tags_resp.raise_for_status()
                return {"ps": ps_resp.json(), "tags": tags_resp.json()}
            except httpx.ConnectError:
                raise HTTPException(status_code=503, detail="Cannot connect")
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Upstream returned {exc.response.status_code}",
                )

    return router
```

- [ ] **Step 2: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_adapters/_ollama_http.py`
Expected: no output — but note this file references `backend.modules.llm._resolver` which does not exist yet. Compile succeeds because the import is inside a function; resolution happens at router-build time. If compile fails on `from backend.modules.llm._adapters._types import ...`, confirm Task 5 ran.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py
git commit -m "Add unified OllamaHttpAdapter with templates, sub-router (test + diagnostics)"
```

---

### Task 7: Adapter registry points only at `ollama_http`

**Files:**
- Modify: `backend/modules/llm/_registry.py`

- [ ] **Step 1: Rewrite `_registry.py`**

```python
"""Adapter registry — maps adapter_type string to adapter class."""

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
}
```

Note: `PROVIDER_DISPLAY_NAMES` and `PROVIDER_BASE_URLS` are intentionally removed. Old adapters (`_ollama_cloud.py`, `_ollama_local.py`) stay on disk for one more commit — they are deleted in Task 22. They will no longer be imported after this step.

- [ ] **Step 2: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_registry.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_registry.py
git commit -m "Point adapter registry at unified OllamaHttpAdapter; drop provider globals"
```

---

### Task 8: Connection repository

**Files:**
- Create: `backend/modules/llm/_connections.py`
- Test: `backend/tests/modules/llm/test_connections_repo.py`

- [ ] **Step 1: Create `_connections.py`**

```python
"""Connection repository — per-user LLM backend instances."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.llm._registry import ADAPTER_REGISTRY
from shared.dtos.llm import ConnectionDto

_log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _encrypt(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode()


def _decrypt(v: str) -> str:
    return _fernet().decrypt(v.encode()).decode()


class InvalidSlugError(ValueError):
    pass


class InvalidAdapterTypeError(ValueError):
    pass


class SlugAlreadyExistsError(ValueError):
    def __init__(self, slug: str, suggested: str) -> None:
        super().__init__(f"Slug '{slug}' already exists")
        self.slug = slug
        self.suggested = suggested


class ConnectionNotFoundError(KeyError):
    pass


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise InvalidSlugError(
            f"Slug '{slug}' must be lowercase alphanumeric with hyphens, 1-63 chars"
        )


def _split_config(adapter_type: str, config: dict) -> tuple[dict, dict]:
    adapter_cls = ADAPTER_REGISTRY.get(adapter_type)
    if adapter_cls is None:
        raise InvalidAdapterTypeError(adapter_type)
    plain: dict = {}
    encrypted: dict = {}
    for k, v in config.items():
        if k in adapter_cls.secret_fields:
            if v is None or v == "":
                continue
            encrypted[k] = _encrypt(str(v))
        else:
            plain[k] = v
    return plain, encrypted


def _redact_config(adapter_type: str, plain: dict, encrypted: dict) -> dict:
    adapter_cls = ADAPTER_REGISTRY.get(adapter_type)
    secret_fields = adapter_cls.secret_fields if adapter_cls else frozenset()
    out = dict(plain)
    for k in secret_fields:
        out[k] = {"is_set": k in encrypted}
    return out


class ConnectionRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["llm_connections"]

    async def create_indexes(self) -> None:
        await self._col.create_index([("user_id", 1), ("slug", 1)], unique=True)
        await self._col.create_index([("user_id", 1), ("created_at", 1)])

    async def suggest_slug(self, user_id: str, base: str) -> str:
        _validate_slug(base)
        existing = {
            doc["slug"]
            async for doc in self._col.find({"user_id": user_id}, {"slug": 1})
        }
        if base not in existing:
            return base
        n = 2
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    async def create(
        self, user_id: str, adapter_type: str,
        display_name: str, slug: str, config: dict,
    ) -> dict:
        _validate_slug(slug)
        if adapter_type not in ADAPTER_REGISTRY:
            raise InvalidAdapterTypeError(adapter_type)
        if await self._col.find_one({"user_id": user_id, "slug": slug}):
            suggested = await self.suggest_slug(user_id, slug)
            raise SlugAlreadyExistsError(slug, suggested)
        plain, encrypted = _split_config(adapter_type, config)
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "adapter_type": adapter_type,
            "display_name": display_name,
            "slug": slug,
            "config": plain,
            "config_encrypted": encrypted,
            "last_test_status": None,
            "last_test_error": None,
            "last_test_at": None,
            "created_at": now,
            "updated_at": now,
        }
        await self._col.insert_one(doc)
        return doc

    async def find(self, user_id: str, connection_id: str) -> dict | None:
        return await self._col.find_one(
            {"_id": connection_id, "user_id": user_id}
        )

    async def find_any(self, connection_id: str) -> dict | None:
        """Owner-agnostic lookup — use only for internal tracker enrichment."""
        return await self._col.find_one({"_id": connection_id})

    async def list_for_user(self, user_id: str) -> list[dict]:
        return [d async for d in self._col.find({"user_id": user_id}).sort("created_at", 1)]

    async def update(
        self, user_id: str, connection_id: str,
        display_name: str | None = None,
        slug: str | None = None,
        config: dict | None = None,
    ) -> dict:
        doc = await self.find(user_id, connection_id)
        if doc is None:
            raise ConnectionNotFoundError(connection_id)
        update: dict = {"updated_at": datetime.now(UTC)}
        if display_name is not None:
            update["display_name"] = display_name
        if slug is not None and slug != doc["slug"]:
            _validate_slug(slug)
            dup = await self._col.find_one(
                {"user_id": user_id, "slug": slug, "_id": {"$ne": connection_id}}
            )
            if dup:
                suggested = await self.suggest_slug(user_id, slug)
                raise SlugAlreadyExistsError(slug, suggested)
            update["slug"] = slug
        if config is not None:
            plain, encrypted = _split_config(doc["adapter_type"], config)
            update["config"] = plain
            update["config_encrypted"] = encrypted
        updated = await self._col.find_one_and_update(
            {"_id": connection_id, "user_id": user_id},
            {"$set": update}, return_document=True,
        )
        return updated

    async def delete(self, user_id: str, connection_id: str) -> bool:
        result = await self._col.delete_one(
            {"_id": connection_id, "user_id": user_id}
        )
        return result.deleted_count > 0

    async def update_test_status(
        self, user_id: str, connection_id: str, *,
        status: str, error: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        return await self._col.find_one_and_update(
            {"_id": connection_id, "user_id": user_id},
            {"$set": {
                "last_test_status": status,
                "last_test_error": error,
                "last_test_at": now,
                "updated_at": now,
            }}, return_document=True,
        )

    @staticmethod
    def to_dto(doc: dict) -> ConnectionDto:
        return ConnectionDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            adapter_type=doc["adapter_type"],
            display_name=doc["display_name"],
            slug=doc["slug"],
            config=_redact_config(
                doc["adapter_type"], doc.get("config", {}),
                doc.get("config_encrypted", {}),
            ),
            last_test_status=doc.get("last_test_status"),
            last_test_error=doc.get("last_test_error"),
            last_test_at=(doc["last_test_at"].isoformat()
                          if doc.get("last_test_at") else None),
            created_at=doc["created_at"].isoformat(),
            updated_at=doc["updated_at"].isoformat(),
        )

    @staticmethod
    def get_decrypted_secret(doc: dict, field: str) -> str | None:
        enc = doc.get("config_encrypted", {})
        if field not in enc:
            return None
        return _decrypt(enc[field])
```

- [ ] **Step 2: Write repo tests**

Create `backend/tests/modules/llm/test_connections_repo.py`:

```python
import pytest

from backend.modules.llm._connections import (
    ConnectionRepository,
    InvalidAdapterTypeError,
    InvalidSlugError,
    SlugAlreadyExistsError,
)


@pytest.mark.asyncio
async def test_suggest_slug_returns_base_when_unused(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    assert await repo.suggest_slug("u1", "ollama-local") == "ollama-local"


@pytest.mark.asyncio
async def test_suggest_slug_auto_increments_on_duplicate(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    await repo.create("u1", "ollama_http", "X", "ollama-local",
                     {"url": "x", "max_parallel": 1})
    assert await repo.suggest_slug("u1", "ollama-local") == "ollama-local-2"
    await repo.create("u1", "ollama_http", "Y", "ollama-local-2",
                     {"url": "x", "max_parallel": 1})
    assert await repo.suggest_slug("u1", "ollama-local") == "ollama-local-3"


@pytest.mark.asyncio
async def test_create_rejects_unknown_adapter(test_db):
    repo = ConnectionRepository(test_db)
    with pytest.raises(InvalidAdapterTypeError):
        await repo.create("u1", "nope", "X", "s", {})


@pytest.mark.asyncio
async def test_create_rejects_invalid_slug(test_db):
    repo = ConnectionRepository(test_db)
    with pytest.raises(InvalidSlugError):
        await repo.create("u1", "ollama_http", "X", "Bad Slug", {})


@pytest.mark.asyncio
async def test_create_duplicate_slug_raises_with_suggestion(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    await repo.create("u1", "ollama_http", "X", "ollama-local",
                     {"url": "x", "max_parallel": 1})
    with pytest.raises(SlugAlreadyExistsError) as exc:
        await repo.create("u1", "ollama_http", "Y", "ollama-local",
                         {"url": "y", "max_parallel": 1})
    assert exc.value.suggested == "ollama-local-2"


@pytest.mark.asyncio
async def test_secret_field_is_encrypted(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    doc = await repo.create("u1", "ollama_http", "X", "s",
                            {"url": "u", "api_key": "SECRET", "max_parallel": 1})
    assert "api_key" not in doc["config"]
    assert "api_key" in doc["config_encrypted"]
    assert repo.get_decrypted_secret(doc, "api_key") == "SECRET"


@pytest.mark.asyncio
async def test_dto_redacts_secrets(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    doc = await repo.create("u1", "ollama_http", "X", "s",
                            {"url": "u", "api_key": "SECRET", "max_parallel": 1})
    dto = ConnectionRepository.to_dto(doc)
    assert dto.config["api_key"] == {"is_set": True}
    assert dto.config["url"] == "u"
```

- [ ] **Step 3: Run tests (expect failures until fixture provided)**

If `test_db` fixture doesn't exist in the test conftest, add it to `backend/tests/conftest.py` using the existing Mongo test harness pattern. Inspect the file and replicate.

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_connections_repo.py -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_connections.py backend/tests/modules/llm/test_connections_repo.py
git commit -m "Add ConnectionRepository with slug uniqueness, auto-suffix, encrypted secret handling"
```

---

### Task 9: Connection semaphore registry

**Files:**
- Create: `backend/modules/llm/_semaphores.py`
- Test: `backend/tests/modules/llm/test_semaphores.py`

- [ ] **Step 1: Create `_semaphores.py`**

```python
"""Per-connection asyncio semaphore registry."""

from __future__ import annotations

import asyncio


class ConnectionSemaphoreRegistry:
    """Process-local registry. Semaphore size == connection.config.max_parallel."""

    def __init__(self) -> None:
        self._map: dict[str, tuple[int, asyncio.Semaphore]] = {}

    def get(self, connection_id: str, max_parallel: int) -> asyncio.Semaphore:
        max_parallel = max(1, int(max_parallel))
        existing = self._map.get(connection_id)
        if existing is None or existing[0] != max_parallel:
            sem = asyncio.Semaphore(max_parallel)
            self._map[connection_id] = (max_parallel, sem)
            return sem
        return existing[1]

    def evict(self, connection_id: str) -> None:
        self._map.pop(connection_id, None)


_registry: ConnectionSemaphoreRegistry | None = None


def get_semaphore_registry() -> ConnectionSemaphoreRegistry:
    global _registry
    if _registry is None:
        _registry = ConnectionSemaphoreRegistry()
    return _registry
```

- [ ] **Step 2: Write tests**

Create `backend/tests/modules/llm/test_semaphores.py`:

```python
import asyncio

import pytest

from backend.modules.llm._semaphores import ConnectionSemaphoreRegistry


def test_returns_stable_semaphore_for_same_id_and_size():
    r = ConnectionSemaphoreRegistry()
    a = r.get("c1", 3)
    b = r.get("c1", 3)
    assert a is b


def test_recreates_on_size_change():
    r = ConnectionSemaphoreRegistry()
    a = r.get("c1", 3)
    b = r.get("c1", 5)
    assert a is not b


def test_evict_removes_entry():
    r = ConnectionSemaphoreRegistry()
    a = r.get("c1", 3)
    r.evict("c1")
    b = r.get("c1", 3)
    assert a is not b


def test_size_clamped_to_minimum_one():
    r = ConnectionSemaphoreRegistry()
    sem = r.get("c1", 0)
    # Semaphore built with _value=1 — can acquire exactly once without await.
    assert sem._value == 1
```

- [ ] **Step 3: Run tests**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_semaphores.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_semaphores.py backend/tests/modules/llm/test_semaphores.py
git commit -m "Add per-connection semaphore registry with size-aware re-creation"
```

---

### Task 10: Connection resolver + FastAPI dependency

**Files:**
- Create: `backend/modules/llm/_resolver.py`

- [ ] **Step 1: Create `_resolver.py`**

```python
"""Resolve a connection_id + current user into a ResolvedConnection."""

from fastapi import Depends, HTTPException, Path

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import ConnectionRepository


async def resolve_connection_for_user(
    connection_id: str = Path(...),
    user: dict = Depends(require_active_session),
) -> ResolvedConnection:
    repo = ConnectionRepository(get_db())
    doc = await repo.find(user["sub"], connection_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    merged = dict(doc.get("config", {}))
    for field in doc.get("config_encrypted", {}):
        merged[field] = ConnectionRepository.get_decrypted_secret(doc, field)
    return ResolvedConnection(
        id=doc["_id"],
        user_id=doc["user_id"],
        adapter_type=doc["adapter_type"],
        display_name=doc["display_name"],
        slug=doc["slug"],
        config=merged,
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def resolve_owned_connection(
    user_id: str, connection_id: str,
) -> ResolvedConnection | None:
    """Non-HTTP variant used from internal call sites (stream_completion)."""
    repo = ConnectionRepository(get_db())
    doc = await repo.find(user_id, connection_id)
    if doc is None:
        return None
    merged = dict(doc.get("config", {}))
    for field in doc.get("config_encrypted", {}):
        merged[field] = ConnectionRepository.get_decrypted_secret(doc, field)
    return ResolvedConnection(
        id=doc["_id"],
        user_id=doc["user_id"],
        adapter_type=doc["adapter_type"],
        display_name=doc["display_name"],
        slug=doc["slug"],
        config=merged,
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )
```

- [ ] **Step 2: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_resolver.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_resolver.py
git commit -m "Add connection resolver (FastAPI dependency + internal variant)"
```

---

## Phase 3 — Backend Handlers

### Task 11: Connection CRUD endpoints

**Files:**
- Replace: `backend/modules/llm/_handlers.py`

- [ ] **Step 1: Rewrite `_handlers.py` in full**

Replace the entire file content with connection-era handlers. Key points:

- Router prefix stays `/api/llm`.
- Generic connection endpoints list/create/get/patch/delete.
- Model-list + refresh endpoints wired to a new `_metadata` helper (Task 12).
- User-model-config endpoints take `{connection_id}` in the URL.
- Adapter discovery endpoint.
- All old provider/credential/curation routes removed.

Write:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import (
    ConnectionNotFoundError,
    ConnectionRepository,
    InvalidAdapterTypeError,
    InvalidSlugError,
    SlugAlreadyExistsError,
)
from backend.modules.llm._metadata import (
    get_models_for_connection, refresh_connection_models,
)
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._resolver import resolve_connection_for_user
from backend.modules.llm._semaphores import get_semaphore_registry
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import (
    AdapterDto,
    AdapterTemplateDto,
    ConnectionDto,
    CreateConnectionDto,
    SetUserModelConfigDto,
    UpdateConnectionDto,
    UserModelConfigDto,
)
from shared.events.llm import (
    LlmConnectionCreatedEvent,
    LlmConnectionModelsRefreshedEvent,
    LlmConnectionRemovedEvent,
    LlmConnectionUpdatedEvent,
    LlmUserModelConfigUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/llm")


def _repo() -> ConnectionRepository:
    return ConnectionRepository(get_db())


def _user_config_repo() -> UserModelConfigRepository:
    return UserModelConfigRepository(get_db())


@router.get("/adapters")
async def list_adapters(user: dict = Depends(require_active_session)) -> list[AdapterDto]:
    out: list[AdapterDto] = []
    for adapter_type, cls in ADAPTER_REGISTRY.items():
        templates = [
            AdapterTemplateDto(
                id=t.id, display_name=t.display_name,
                slug_prefix=t.slug_prefix, config_defaults=t.config_defaults,
            )
            for t in cls.templates()
        ]
        schema = [
            {
                "name": h.name, "type": h.type, "label": h.label,
                "required": h.required, "min": h.min, "max": h.max,
                "placeholder": h.placeholder,
            }
            for h in cls.config_schema()
        ]
        out.append(AdapterDto(
            adapter_type=adapter_type,
            display_name=cls.display_name,
            view_id=cls.view_id,
            templates=templates,
            config_schema=schema,
            secret_fields=sorted(cls.secret_fields),
        ))
    return out


@router.get("/connections")
async def list_connections(
    user: dict = Depends(require_active_session),
) -> list[ConnectionDto]:
    docs = await _repo().list_for_user(user["sub"])
    return [ConnectionRepository.to_dto(d) for d in docs]


@router.post("/connections", status_code=201)
async def create_connection(
    body: CreateConnectionDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> ConnectionDto:
    try:
        doc = await _repo().create(
            user["sub"], body.adapter_type,
            body.display_name, body.slug, body.config,
        )
    except InvalidAdapterTypeError:
        raise HTTPException(status_code=400, detail="Unknown adapter_type")
    except InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SlugAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "slug_exists", "suggested_slug": exc.suggested},
        )
    dto = ConnectionRepository.to_dto(doc)
    await event_bus.publish(
        Topics.LLM_CONNECTION_CREATED,
        LlmConnectionCreatedEvent(connection=dto, timestamp=datetime.now(timezone.utc)),
        target_user_ids=[user["sub"]],
    )
    return dto


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: str, user: dict = Depends(require_active_session),
) -> ConnectionDto:
    doc = await _repo().find(user["sub"], connection_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    return ConnectionRepository.to_dto(doc)


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: str, body: UpdateConnectionDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> ConnectionDto:
    try:
        doc = await _repo().update(
            user["sub"], connection_id,
            display_name=body.display_name, slug=body.slug, config=body.config,
        )
    except ConnectionNotFoundError:
        raise HTTPException(status_code=404, detail="Not found")
    except InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SlugAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "slug_exists", "suggested_slug": exc.suggested},
        )
    # Config change may have changed max_parallel — evict semaphore.
    get_semaphore_registry().evict(connection_id)
    dto = ConnectionRepository.to_dto(doc)
    await event_bus.publish(
        Topics.LLM_CONNECTION_UPDATED,
        LlmConnectionUpdatedEvent(connection=dto, timestamp=datetime.now(timezone.utc)),
        target_user_ids=[user["sub"]],
    )
    return dto


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str, user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    affected = await _unwire_personas_for_connection(user["sub"], connection_id)
    deleted = await _repo().delete(user["sub"], connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    get_semaphore_registry().evict(connection_id)
    redis = get_redis()
    await redis.delete(f"llm:models:{connection_id}")
    await event_bus.publish(
        Topics.LLM_CONNECTION_REMOVED,
        LlmConnectionRemovedEvent(
            connection_id=connection_id,
            affected_persona_ids=affected,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )


async def _unwire_personas_for_connection(user_id: str, connection_id: str) -> list[str]:
    """Set model_unique_id=None on every persona of this user that
    references the connection. Returns the list of affected persona IDs."""
    db = get_db()
    prefix = f"{connection_id}:"
    cursor = db["personas"].find({
        "user_id": user_id,
        "model_unique_id": {"$regex": f"^{prefix}"},
    }, {"_id": 1})
    ids = [d["_id"] async for d in cursor]
    if ids:
        await db["personas"].update_many(
            {"_id": {"$in": ids}},
            {"$set": {"model_unique_id": None}},
        )
    return ids


@router.get("/connections/{connection_id}/models")
async def list_models(
    c: ResolvedConnection = Depends(resolve_connection_for_user),
):
    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    redis = get_redis()
    return await get_models_for_connection(c, adapter_cls, redis)


@router.post("/connections/{connection_id}/refresh", status_code=202)
async def refresh_models(
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
):
    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    redis = get_redis()
    await refresh_connection_models(c, adapter_cls, redis)
    await event_bus.publish(
        Topics.LLM_CONNECTION_MODELS_REFRESHED,
        LlmConnectionModelsRefreshedEvent(
            connection_id=c.id, timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[c.user_id],
    )
    return {"status": "ok"}


# ----- User model config endpoints -----

@router.get("/user-model-configs")
async def list_user_model_configs(
    user: dict = Depends(require_active_session),
) -> list[UserModelConfigDto]:
    docs = await _user_config_repo().list_for_user(user["sub"])
    return [UserModelConfigRepository.to_dto(d) for d in docs]


@router.get("/connections/{connection_id}/models/{model_slug:path}/user-config")
async def get_user_model_config(
    model_slug: str,
    c: ResolvedConnection = Depends(resolve_connection_for_user),
) -> UserModelConfigDto:
    mid = f"{c.id}:{model_slug}"
    repo = _user_config_repo()
    doc = await repo.find(c.user_id, mid)
    if doc:
        return UserModelConfigRepository.to_dto(doc)
    return UserModelConfigRepository.default_dto(mid)


@router.put("/connections/{connection_id}/models/{model_slug:path}/user-config")
async def set_user_model_config(
    model_slug: str, body: SetUserModelConfigDto,
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
) -> UserModelConfigDto:
    mid = f"{c.id}:{model_slug}"
    repo = _user_config_repo()
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    doc = await repo.upsert(user_id=c.user_id, model_unique_id=mid, fields=fields)
    dto = UserModelConfigRepository.to_dto(doc)
    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=mid, config=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[c.user_id],
    )
    return dto


@router.delete("/connections/{connection_id}/models/{model_slug:path}/user-config")
async def delete_user_model_config(
    model_slug: str,
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
) -> UserModelConfigDto:
    mid = f"{c.id}:{model_slug}"
    await _user_config_repo().delete(c.user_id, mid)
    default = UserModelConfigRepository.default_dto(mid)
    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=mid, config=default,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[c.user_id],
    )
    return default
```

- [ ] **Step 2: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_handlers.py`
Expected: errors on `_metadata` imports — the helpers don't exist yet; add in Task 12. Commit is held to Step 4.

- [ ] **Step 3: Commit**

Skip — held until Task 12 lands.

- [ ] **Step 4: (Deferred)**

Commit handlers after Task 12.

---

### Task 12: Model-list helpers per connection

**Files:**
- Replace: `backend/modules/llm/_metadata.py`

- [ ] **Step 1: Rewrite `_metadata.py`**

```python
"""Per-connection model listing: Redis cache (30min TTL) + adapter fallback."""

import json
import logging

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)
_TTL_SECONDS = 30 * 60


def _cache_key(connection_id: str) -> str:
    return f"llm:models:{connection_id}"


async def get_models_for_connection(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    cached = await redis.get(_cache_key(c.id))
    if cached:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    try:
        adapter = adapter_cls()
        models = await adapter.fetch_models(c)
    except NotImplementedError:
        return []
    except Exception as exc:
        _log.warning("fetch_models failed for connection=%s: %s", c.id, exc)
        return []
    await redis.set(
        _cache_key(c.id),
        json.dumps([m.model_dump() for m in models]),
        ex=_TTL_SECONDS,
    )
    return models


async def refresh_connection_models(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    await redis.delete(_cache_key(c.id))
    return await get_models_for_connection(c, adapter_cls, redis)
```

- [ ] **Step 2: Compile both files**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_metadata.py backend/modules/llm/_handlers.py`
Expected: no output.

- [ ] **Step 3: Commit Tasks 11 + 12 together**

```bash
git add backend/modules/llm/_handlers.py backend/modules/llm/_metadata.py
git commit -m "Replace LLM handlers + metadata with connection-scoped variants"
```

---

### Task 13: Mount adapter sub-routers

**Files:**
- Modify: `backend/modules/llm/_handlers.py` (append sub-router mounts) or `backend/main.py` if the project centralises router registration

- [ ] **Step 1: Discover how the LLM router is mounted**

Run: `grep -n "llm.router\|llm_router\|from backend.modules.llm import router" backend/main.py`

- [ ] **Step 2: Mount adapter routers**

In `backend/modules/llm/_handlers.py` at the bottom, add:

```python
from backend.modules.llm._registry import ADAPTER_REGISTRY as _AR


def _mount_adapter_routers() -> None:
    for adapter_type, cls in _AR.items():
        sub = cls.router()
        if sub is None:
            continue
        router.include_router(
            sub,
            prefix=f"/connections/{{connection_id}}/adapter",
            tags=[f"adapter:{adapter_type}"],
        )


_mount_adapter_routers()
```

Note: `_mount_adapter_routers()` runs at import time. If Python complains about `{connection_id}` in prefix, switch to a per-adapter-type prefix and parse `connection_id` via `Path(...)` in each sub-handler (already done in the Ollama router). Concretely the Ollama sub-router's `resolve_connection_for_user` dependency reads `connection_id` from the path, so the prefix `{connection_id}/adapter` is fine and FastAPI handles it.

- [ ] **Step 3: Import check**

Run: `docker compose run --rm backend uv run python -c "from backend.main import app; print(len(app.routes))"`
Expected: a number > 0, no exceptions.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_handlers.py
git commit -m "Mount adapter-specific sub-routers under /api/llm/connections/{id}/adapter"
```

---

## Phase 4 — Stream Completion Refactor

### Task 14: Rewrite LLM module public API

**Files:**
- Replace: `backend/modules/llm/__init__.py`

- [ ] **Step 1: Rewrite `__init__.py`**

```python
"""LLM module — connection-scoped inference facade.

Public API: import only from this file.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from backend.database import get_db, get_redis
from backend.modules.llm import _tracker
from backend.modules.llm._adapters._events import (
    ContentDelta, ProviderStreamEvent, StreamAborted, StreamDone, StreamError,
    StreamRefused, StreamSlow, ThinkingDelta, ToolCallEvent,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import ConnectionRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._metadata import (
    get_models_for_connection, refresh_connection_models,
)
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._resolver import resolve_owned_connection
from backend.modules.llm._semaphores import get_semaphore_registry
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.modules.metrics import inference_duration_seconds, inference_total
from shared.dtos.debug import ActiveInferenceDto
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


_log = logging.getLogger(__name__)


class LlmConnectionNotFoundError(Exception):
    """Connection not found or not owned by the caller."""

    def __init__(self, connection_id: str) -> None:
        super().__init__(f"Connection not found: {connection_id}")
        self.connection_id = connection_id


class LlmInvalidModelUniqueIdError(Exception):
    """model_unique_id is not in `<connection_id>:<model_slug>` format."""


async def init_indexes(db) -> None:
    await ConnectionRepository(db).create_indexes()
    await UserModelConfigRepository(db).create_indexes()


def parse_model_unique_id(model_unique_id: str) -> tuple[str, str]:
    """Split `<connection_id>:<model_slug>` into (connection_id, model_slug)."""
    if ":" not in model_unique_id:
        raise LlmInvalidModelUniqueIdError(model_unique_id)
    connection_id, model_slug = model_unique_id.split(":", 1)
    if not connection_id or not model_slug:
        raise LlmInvalidModelUniqueIdError(model_unique_id)
    return connection_id, model_slug


async def stream_completion(
    user_id: str,
    model_unique_id: str,
    request: CompletionRequest,
    source: str = "chat",
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve connection, enforce semaphore, stream adapter events."""
    connection_id, _ = parse_model_unique_id(model_unique_id)
    c = await resolve_owned_connection(user_id, connection_id)
    if c is None:
        raise LlmConnectionNotFoundError(connection_id)

    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    adapter = adapter_cls()
    max_parallel = int(c.config.get("max_parallel") or 1)
    sem = get_semaphore_registry().get(c.id, max_parallel)

    inference_id = _tracker.register(
        user_id=user_id,
        connection_id=c.id,
        connection_slug=c.slug,
        adapter_type=c.adapter_type,
        model_slug=request.model,
        source=source,
    )
    await _publish_inference_started(
        inference_id=inference_id,
        user_id=user_id, connection_id=c.id, connection_slug=c.slug,
        adapter_type=c.adapter_type,
        model_slug=request.model, source=source,
    )
    started_perf = time.monotonic()
    inference_total.labels(
        model=request.model, provider=c.adapter_type, source=source,
    ).inc()
    try:
        async with sem:
            async for event in adapter.stream_completion(c, request):
                yield event
    finally:
        _tracker.unregister(inference_id)
        inference_duration_seconds.labels(
            model=request.model, provider=c.adapter_type,
        ).observe(time.monotonic() - started_perf)
        await _publish_inference_finished(
            inference_id=inference_id, user_id=user_id,
            duration_seconds=time.monotonic() - started_perf,
        )


async def _publish_inference_started(**fields) -> None:
    try:
        from backend.ws.event_bus import get_event_bus
        from shared.events.debug import DebugInferenceStartedEvent
        from shared.topics import Topics

        bus = get_event_bus()
        username = await _resolve_username(fields["user_id"])
        await bus.publish(
            Topics.DEBUG_INFERENCE_STARTED,
            DebugInferenceStartedEvent(
                inference_id=fields["inference_id"],
                user_id=fields["user_id"],
                username=username,
                connection_id=fields["connection_id"],
                connection_slug=fields["connection_slug"],
                adapter_type=fields["adapter_type"],
                model_slug=fields["model_slug"],
                model_unique_id=f"{fields['connection_id']}:{fields['model_slug']}",
                source=fields["source"],
                started_at=datetime.now(timezone.utc),
                correlation_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        _log.warning("Failed to publish DEBUG_INFERENCE_STARTED", exc_info=True)


async def _publish_inference_finished(
    inference_id: str, user_id: str, duration_seconds: float,
) -> None:
    try:
        from backend.ws.event_bus import get_event_bus
        from shared.events.debug import DebugInferenceFinishedEvent
        from shared.topics import Topics

        bus = get_event_bus()
        await bus.publish(
            Topics.DEBUG_INFERENCE_FINISHED,
            DebugInferenceFinishedEvent(
                inference_id=inference_id, user_id=user_id,
                duration_seconds=duration_seconds,
                correlation_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
            ),
        )
    except Exception:
        _log.warning("Failed to publish DEBUG_INFERENCE_FINISHED", exc_info=True)


async def _resolve_username(user_id: str) -> str | None:
    try:
        from backend.modules.user import get_username
        return await get_username(user_id)
    except Exception:
        return None


def get_active_inferences(
    usernames: dict[str, str] | None = None,
) -> list[ActiveInferenceDto]:
    return _tracker.snapshot(usernames)


@asynccontextmanager
async def track_inference(
    user_id: str, connection_id: str, connection_slug: str,
    adapter_type: str, model_slug: str, source: str,
):
    inference_id = _tracker.register(
        user_id=user_id,
        connection_id=connection_id, connection_slug=connection_slug,
        adapter_type=adapter_type, model_slug=model_slug, source=source,
    )
    started_perf = time.monotonic()
    await _publish_inference_started(
        inference_id=inference_id, user_id=user_id,
        connection_id=connection_id, connection_slug=connection_slug,
        adapter_type=adapter_type, model_slug=model_slug, source=source,
    )
    try:
        yield inference_id
    finally:
        _tracker.unregister(inference_id)
        await _publish_inference_finished(
            inference_id=inference_id, user_id=user_id,
            duration_seconds=time.monotonic() - started_perf,
        )


def active_inference_count() -> int:
    return _tracker.active_count()


async def get_model_metadata(
    user_id: str, model_unique_id: str,
) -> ModelMetaDto | None:
    connection_id, model_slug = parse_model_unique_id(model_unique_id)
    c = await resolve_owned_connection(user_id, connection_id)
    if c is None:
        return None
    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    models = await get_models_for_connection(c, adapter_cls, get_redis())
    for m in models:
        if m.model_id == model_slug:
            return m
    return None


async def get_model_context_window(
    user_id: str, model_unique_id: str,
) -> int | None:
    meta = await get_model_metadata(user_id, model_unique_id)
    return meta.context_window if meta else None


async def get_model_supports_vision(
    user_id: str, model_unique_id: str,
) -> bool:
    meta = await get_model_metadata(user_id, model_unique_id)
    return meta.supports_vision if meta else False


async def get_model_supports_reasoning(
    user_id: str, model_unique_id: str,
) -> bool:
    meta = await get_model_metadata(user_id, model_unique_id)
    return meta.supports_reasoning if meta else False


async def get_effective_context_window(
    user_id: str, model_unique_id: str,
) -> int | None:
    model_max = await get_model_context_window(user_id, model_unique_id)
    if model_max is None:
        return None
    repo = UserModelConfigRepository(get_db())
    doc = await repo.find(user_id, model_unique_id)
    if doc and doc.get("custom_context_window"):
        return min(model_max, doc["custom_context_window"])
    return model_max


__all__ = [
    "router",
    "init_indexes",
    "stream_completion",
    "parse_model_unique_id",
    "ContentDelta", "ThinkingDelta", "StreamAborted", "StreamDone",
    "StreamError", "StreamRefused", "StreamSlow",
    "ProviderStreamEvent", "ToolCallEvent",
    "LlmConnectionNotFoundError",
    "LlmInvalidModelUniqueIdError",
    "UserModelConfigRepository",
    "get_model_context_window",
    "get_effective_context_window",
    "get_model_supports_vision",
    "get_model_supports_reasoning",
    "get_model_metadata",
    "get_active_inferences",
    "active_inference_count",
    "track_inference",
    "ModelMetaDto",
    "ResolvedConnection",
    "resolve_owned_connection",
]
```

- [ ] **Step 2: Update `_tracker.py` signature (field names + snapshot output)**

In `backend/modules/llm/_tracker.py`, replace `provider_id` with `connection_id` + `connection_slug` + `adapter_type`. Review the file, update `register(...)` kwargs, the in-memory record dataclass, and `snapshot()` DTO mapping. Reflect the rename in the DTO at `shared/dtos/debug.py::ActiveInferenceDto` (rename field + keep a `connection_slug` + `adapter_type`). Also update `shared/events/debug.py::DebugInferenceStartedEvent`.

- [ ] **Step 3: Compile**

Run: `docker compose run --rm backend uv run python -c "from backend.main import app"` — expect import errors elsewhere (chat/vision references stale symbols). These will be fixed in Tasks 15-18. Hold the commit.

- [ ] **Step 4: Commit**

Skip — commit after Task 18 when imports resolve throughout.

---

### Task 15: Update chat orchestrator

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Replace model-metadata lookups**

Change every call using the old signature. Example find-and-replace logic:

- `provider_id, model_slug = model_unique_id.split(":", 1)` → keep this split as-is where only the slug is needed, but relabel the first var to `connection_id` for clarity.
- `await get_model_supports_reasoning(provider_id, model_slug)` → `await get_model_supports_reasoning(user_id, model_unique_id)`.
- `await get_model_supports_vision(provider_id, model_slug)` → `await get_model_supports_vision(user_id, model_unique_id)`.
- `await get_effective_context_window(user_id, provider_id, model_slug)` → `await get_effective_context_window(user_id, model_unique_id)`.
- `from backend.modules.llm import PROVIDER_DISPLAY_NAMES` → DELETE; replace the `provider_display_name` usage by resolving the connection:
  ```python
  connection_id, model_slug = model_unique_id.split(":", 1)
  c = await resolve_owned_connection(user_id, connection_id)
  connection_display_name = c.display_name if c else connection_id
  ```
  (add `from backend.modules.llm import resolve_owned_connection` at the top).
- `is_inference_lock_held(provider_id, user_id)` → remove entirely; the corresponding "wait for lock" UX event should be dropped, or reworked to query the semaphore registry via a new public helper. If the helper is wanted, add a function in `__init__.py`:
  ```python
  def connection_semaphore_in_use(connection_id: str, max_parallel: int) -> bool:
      sem = get_semaphore_registry().get(connection_id, max_parallel)
      # A Semaphore has no public "is full" API. Best-effort: compare the
      # private counter. Accept this limitation — queue-wait UX was always
      # approximate.
      return sem._value <= 0
  ```
  Use it from the orchestrator if and only if that UX still exists.
- `llm_stream_completion(user_id, provider_id, req)` → `llm_stream_completion(user_id, model_unique_id, req)`.

- [ ] **Step 2: Compile file**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/chat/_orchestrator.py`
Expected: no output.

- [ ] **Step 3: Hold commit until Task 18**

---

### Task 16: Update vision fallback

**Files:**
- Modify: `backend/modules/chat/_vision_fallback.py`

- [ ] **Step 1: Replace the custom adapter/lock resolution**

The current file reaches into `ADAPTER_REGISTRY`, `PROVIDER_BASE_URLS`, and the old lock registry. Rewrite the pertinent section to:

```python
from backend.modules.llm import (
    ResolvedConnection,
    resolve_owned_connection,
    parse_model_unique_id,
    track_inference,
)
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._semaphores import get_semaphore_registry
```

And update the core path — instead of `get_api_key` + `ADAPTER_REGISTRY[provider_id]`, use:

```python
connection_id, model_slug = parse_model_unique_id(model_unique_id)
c = await resolve_owned_connection(user_id, connection_id)
if c is None:
    raise LlmConnectionNotFoundError(connection_id)
adapter = ADAPTER_REGISTRY[c.adapter_type]()
max_parallel = int(c.config.get("max_parallel") or 1)
sem = get_semaphore_registry().get(c.id, max_parallel)
async with sem:
    async with track_inference(
        user_id=user_id, connection_id=c.id, connection_slug=c.slug,
        adapter_type=c.adapter_type, model_slug=model_slug, source="vision",
    ) as _inf_id:
        async for event in adapter.stream_completion(c, request):
            yield event
```

Adapt the surrounding function to drop `get_inference_lock` and old key-lookup plumbing.

- [ ] **Step 2: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/chat/_vision_fallback.py`
Expected: no output.

- [ ] **Step 3: Hold commit until Task 18**

---

### Task 17: Update other chat-module call sites

**Files:**
- Modify: `backend/modules/chat/_inference.py`
- Modify: `backend/modules/chat/_soft_cot_parser.py`
- Modify: `backend/modules/chat/_handlers_ws.py`
- Modify: `backend/modules/chat/_prompt_assembler.py`

- [ ] **Step 1: Grep each file for references to the old API**

Run: `grep -n "provider_id\|stream_completion\|PROVIDER_\|get_api_key\|get_inference_lock\|is_inference_lock_held\|LlmProviderNotFoundError\|LlmCredentialNotFoundError\|LlmInferenceLockTimeoutError" backend/modules/chat/_inference.py backend/modules/chat/_soft_cot_parser.py backend/modules/chat/_handlers_ws.py backend/modules/chat/_prompt_assembler.py`

- [ ] **Step 2: Replace each reference**

For each match:

- Rename local variables `provider_id` → `connection_id` where the semantic is `model_unique_id.split(":")[0]`.
- `stream_completion(user_id, provider_id, req)` → `stream_completion(user_id, model_unique_id, req)`.
- `get_api_key(user_id, provider_id)` → remove; if an adapter-specific call path needs the key, re-route through `resolve_owned_connection` and read `c.config.get("api_key")`. For anything outside the LLM module, this should now be unreachable — if it isn't, the call is violating INS-002/module-boundary.
- `LlmProviderNotFoundError` / `LlmCredentialNotFoundError` / `LlmInferenceLockTimeoutError` → replace with `LlmConnectionNotFoundError` where an error is surfaced to the user.
- `PROVIDER_DISPLAY_NAMES` lookups → resolve via the connection document (see Task 15 for pattern).

- [ ] **Step 3: Compile each file**

Run:
```
docker compose run --rm backend uv run python -m py_compile \
    backend/modules/chat/_inference.py \
    backend/modules/chat/_soft_cot_parser.py \
    backend/modules/chat/_handlers_ws.py \
    backend/modules/chat/_prompt_assembler.py
```
Expected: no output.

- [ ] **Step 4: Hold commit until Task 18**

---

### Task 18: Update jobs / memory consolidation / other LLM callers

**Files:**
- Modify: any files from Task 17 search that referenced old API — grep is authoritative:
  ```
  grep -rln "provider_id\|PROVIDER_DISPLAY_NAMES\|PROVIDER_BASE_URLS\|get_inference_lock\|is_inference_lock_held\|LlmProviderNotFoundError\|LlmCredentialNotFoundError\|LlmInferenceLockTimeoutError\|\.stream_completion(.*provider" backend/ shared/ | grep -v __pycache__
  ```

- [ ] **Step 1: Run the grep and enumerate call sites**

- [ ] **Step 2: For each file, apply the same transformations as Task 17**

If a call site lives outside `backend/modules/llm/` and reaches into internals (e.g., `from backend.modules.llm._registry import ...`), this is a module-boundary violation — fix by extending the LLM public API rather than importing internals.

- [ ] **Step 3: Full-app import check**

Run: `docker compose run --rm backend uv run python -c "from backend.main import app; print(len(app.routes))"`
Expected: clean output, no import errors.

- [ ] **Step 4: Commit Tasks 14–18 together**

```bash
git add backend/modules/llm/__init__.py backend/modules/llm/_tracker.py \
       shared/events/debug.py shared/dtos/debug.py \
       backend/modules/chat/_orchestrator.py backend/modules/chat/_vision_fallback.py \
       backend/modules/chat/_inference.py backend/modules/chat/_soft_cot_parser.py \
       backend/modules/chat/_handlers_ws.py backend/modules/chat/_prompt_assembler.py
# any additional files Task 18's grep surfaced
git commit -m "Rewrite LLM public API + all call sites for connection-scoped inference"
```

---

## Phase 5 — Web Search Refactor

### Task 19: Web-search credentials store

**Files:**
- Create: `backend/modules/websearch/_credentials.py`
- Create: `backend/modules/websearch/_handlers.py`

- [ ] **Step 1: Create credentials repository**

```python
"""Web-search credentials — one API key per user per provider."""

from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from shared.dtos.websearch import WebSearchCredentialDto


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


class WebSearchCredentialRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["websearch_user_credentials"]

    async def create_indexes(self) -> None:
        await self._col.create_index(
            [("user_id", 1), ("provider_id", 1)], unique=True
        )

    async def find(self, user_id: str, provider_id: str) -> dict | None:
        return await self._col.find_one(
            {"user_id": user_id, "provider_id": provider_id}
        )

    async def upsert(self, user_id: str, provider_id: str, api_key: str) -> dict:
        now = datetime.now(UTC)
        encrypted = _fernet().encrypt(api_key.encode()).decode()
        return await self._col.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": {
                "api_key_encrypted": encrypted,
                "last_test_status": None,
                "last_test_error": None,
                "last_test_at": None,
                "updated_at": now,
            }, "$setOnInsert": {
                "_id": str(uuid4()),
                "user_id": user_id,
                "provider_id": provider_id,
                "created_at": now,
            }},
            upsert=True, return_document=True,
        )

    async def delete(self, user_id: str, provider_id: str) -> bool:
        res = await self._col.delete_one(
            {"user_id": user_id, "provider_id": provider_id}
        )
        return res.deleted_count > 0

    async def update_test(
        self, user_id: str, provider_id: str, *,
        status: str, error: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        return await self._col.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": {
                "last_test_status": status,
                "last_test_error": error,
                "last_test_at": now,
                "updated_at": now,
            }}, return_document=True,
        )

    def get_raw_key(self, doc: dict) -> str:
        return _fernet().decrypt(doc["api_key_encrypted"].encode()).decode()

    @staticmethod
    def to_dto(doc: dict | None, provider_id: str) -> WebSearchCredentialDto:
        if doc is None:
            return WebSearchCredentialDto(
                provider_id=provider_id, is_configured=False,
            )
        return WebSearchCredentialDto(
            provider_id=provider_id,
            is_configured=True,
            last_test_status=doc.get("last_test_status"),
            last_test_error=doc.get("last_test_error"),
            last_test_at=(doc["last_test_at"].isoformat()
                          if doc.get("last_test_at") else None),
        )
```

- [ ] **Step 2: Create websearch handlers**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.websearch._credentials import WebSearchCredentialRepository
from backend.modules.websearch._registry import (
    SEARCH_ADAPTER_REGISTRY, SEARCH_PROVIDER_BASE_URLS,
    SEARCH_PROVIDER_DISPLAY_NAMES,
)
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.websearch import (
    SetWebSearchKeyDto, WebSearchCredentialDto, WebSearchProviderDto,
)
from shared.events.websearch import (
    WebSearchCredentialRemovedEvent, WebSearchCredentialSetEvent,
    WebSearchCredentialTestedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/websearch")


def _repo() -> WebSearchCredentialRepository:
    return WebSearchCredentialRepository(get_db())


@router.get("/providers")
async def list_providers(
    user: dict = Depends(require_active_session),
) -> list[WebSearchProviderDto]:
    repo = _repo()
    out: list[WebSearchProviderDto] = []
    for pid, cls in SEARCH_ADAPTER_REGISTRY.items():
        doc = await repo.find(user["sub"], pid)
        out.append(WebSearchProviderDto(
            provider_id=pid,
            display_name=SEARCH_PROVIDER_DISPLAY_NAMES.get(pid, pid),
            is_configured=doc is not None,
            last_test_status=doc.get("last_test_status") if doc else None,
            last_test_error=doc.get("last_test_error") if doc else None,
        ))
    return out


@router.get("/providers/{provider_id}/credential")
async def get_credential(
    provider_id: str, user: dict = Depends(require_active_session),
) -> WebSearchCredentialDto:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    doc = await _repo().find(user["sub"], provider_id)
    return WebSearchCredentialRepository.to_dto(doc, provider_id)


@router.put("/providers/{provider_id}/credential")
async def set_credential(
    provider_id: str, body: SetWebSearchKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> WebSearchCredentialDto:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    doc = await _repo().upsert(user["sub"], provider_id, body.api_key)
    dto = WebSearchCredentialRepository.to_dto(doc, provider_id)
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_SET,
        WebSearchCredentialSetEvent(
            provider_id=provider_id, timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    return dto


@router.delete("/providers/{provider_id}/credential", status_code=204)
async def delete_credential(
    provider_id: str, user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    deleted = await _repo().delete(user["sub"], provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No credential configured")
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_REMOVED,
        WebSearchCredentialRemovedEvent(
            provider_id=provider_id, timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )


@router.post("/providers/{provider_id}/test")
async def test_credential(
    provider_id: str, body: SetWebSearchKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](
        base_url=SEARCH_PROVIDER_BASE_URLS[provider_id],
    )
    valid = False
    error: str | None = None
    try:
        # Minimal validation: search a canary query.
        await adapter.search(body.api_key, "chatsune_test", 1)
        valid = True
    except Exception as exc:
        error = str(exc)
    await _repo().update_test(
        user["sub"], provider_id,
        status="valid" if valid else "failed", error=error,
    )
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_TESTED,
        WebSearchCredentialTestedEvent(
            provider_id=provider_id, valid=valid, error=error,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    return {"valid": valid, "error": error}
```

- [ ] **Step 3: Compile**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/websearch/_credentials.py backend/modules/websearch/_handlers.py`
Expected: no output.

- [ ] **Step 4: Hold commit until Task 20**

---

### Task 20: Rewrite websearch public API to use own credentials

**Files:**
- Replace: `backend/modules/websearch/__init__.py`
- Replace: `backend/modules/websearch/_registry.py`

- [ ] **Step 1: Rewrite `_registry.py`** (remove `KEY_SOURCES`)

```python
from backend.modules.websearch._adapters._base import BaseSearchAdapter
from backend.modules.websearch._adapters._ollama_cloud import OllamaCloudSearchAdapter

SEARCH_ADAPTER_REGISTRY: dict[str, type[BaseSearchAdapter]] = {
    "ollama_cloud_search": OllamaCloudSearchAdapter,
}

SEARCH_PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud_search": "https://ollama.com",
}

SEARCH_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud_search": "Ollama Web Search",
}
```

Provider ID is renamed to `ollama_cloud_search` to avoid clashing with the former LLM provider ID. (The search provider namespace is now independent of LLM adapter types.)

- [ ] **Step 2: Rewrite `__init__.py`**

```python
"""Websearch module — pluggable web-search adapters with own credential store."""

import logging

from backend.database import get_db
from backend.modules.websearch._credentials import WebSearchCredentialRepository
from backend.modules.websearch._handlers import router
from backend.modules.websearch._registry import (
    SEARCH_ADAPTER_REGISTRY, SEARCH_PROVIDER_BASE_URLS,
    SEARCH_PROVIDER_DISPLAY_NAMES,
)
from shared.dtos.inference import ToolDefinition
from shared.dtos.websearch import WebFetchResultDto, WebSearchResultDto

logger = logging.getLogger(__name__)


class WebSearchProviderNotFoundError(Exception):
    pass


class WebSearchCredentialNotFoundError(Exception):
    pass


_TOOL_WEB_SEARCH = ToolDefinition(
    name="web_search",
    description=(
        "Search the web for current information. Use this when the user "
        "explicitly asks you to search the web or look something up online. "
        "Do not use this tool unless the user requests a web search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {"type": "integer", "description": "1-10, default 5"},
        },
        "required": ["query"],
    },
)

_TOOL_WEB_FETCH = ToolDefinition(
    name="web_fetch",
    description="Fetch the full content of a web page by URL.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
)


def get_tool_definitions() -> list[ToolDefinition]:
    return [_TOOL_WEB_SEARCH, _TOOL_WEB_FETCH]


async def init_indexes(db) -> None:
    await WebSearchCredentialRepository(db).create_indexes()


async def _resolve_api_key(user_id: str, provider_id: str) -> str:
    repo = WebSearchCredentialRepository(get_db())
    doc = await repo.find(user_id, provider_id)
    if doc is None:
        raise WebSearchCredentialNotFoundError(provider_id)
    return repo.get_raw_key(doc)


async def search(
    user_id: str, provider_id: str, query: str, max_results: int = 5,
) -> list[WebSearchResultDto]:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise WebSearchProviderNotFoundError(provider_id)
    api_key = await _resolve_api_key(user_id, provider_id)
    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](
        base_url=SEARCH_PROVIDER_BASE_URLS[provider_id],
    )
    return await adapter.search(api_key, query, max_results)


async def fetch(
    user_id: str, provider_id: str, url: str,
) -> WebFetchResultDto:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise WebSearchProviderNotFoundError(provider_id)
    api_key = await _resolve_api_key(user_id, provider_id)
    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](
        base_url=SEARCH_PROVIDER_BASE_URLS[provider_id],
    )
    return await adapter.fetch(api_key, url)


__all__ = [
    "router",
    "init_indexes",
    "get_tool_definitions",
    "search",
    "fetch",
    "WebSearchProviderNotFoundError",
    "WebSearchCredentialNotFoundError",
]
```

- [ ] **Step 2: Update callers of `search` / `fetch`**

Run: `grep -rn "modules.websearch import" backend/ | grep -v __pycache__`
Adjust any caller that previously passed the old `ollama_cloud` provider ID — change to `ollama_cloud_search`.

- [ ] **Step 3: Update main.py / router-mount logic to include the websearch router**

Run: `grep -n "websearch" backend/main.py`
Add `from backend.modules.websearch import router as websearch_router` and `app.include_router(websearch_router)` in the same location where the LLM router is mounted.

- [ ] **Step 4: Update startup to call `websearch.init_indexes`**

Locate where `llm.init_indexes` is called at startup, add a sibling call for `websearch.init_indexes`.

- [ ] **Step 5: Compile entire app**

Run: `docker compose run --rm backend uv run python -c "from backend.main import app; print(len(app.routes))"`
Expected: imports resolve; route count includes new websearch endpoints.

- [ ] **Step 6: Commit Tasks 19 + 20**

```bash
git add backend/modules/websearch/_credentials.py \
        backend/modules/websearch/_handlers.py \
        backend/modules/websearch/_registry.py \
        backend/modules/websearch/__init__.py \
        backend/main.py \
        backend/modules/chat   # only if callers were updated
git commit -m "Web search owns its credential store; rename search provider id"
```

---

## Phase 6 — Migration & Cleanup

### Task 21: Hard-cut migration with marker

**Files:**
- Create: `backend/modules/llm/_migration_connections_refactor.py`
- Modify: backend startup hook (e.g., `backend/main.py` or wherever `init_indexes` is invoked)

- [ ] **Step 1: Create migration module**

```python
"""One-shot cleanup for the Connections Refactor (v1).

Runs once per database on startup, gated by a marker document in the
`_migrations` collection. Idempotent: re-runs are no-ops.
"""

import logging
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

_log = logging.getLogger(__name__)

_MARKER_ID = "connections_refactor_v1"


async def run_if_needed(db: AsyncIOMotorDatabase, redis: Redis) -> None:
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return
    _log.warning("connections_refactor_v1: running one-shot cleanup")

    # Drop obsolete collections
    await db["llm_user_credentials"].drop()
    await db["llm_model_curations"].drop()
    await db["llm_user_model_configs"].drop()

    # Null stale persona references
    result = await db["personas"].update_many(
        {}, {"$set": {"model_unique_id": None}},
    )
    _log.warning("connections_refactor_v1: unwired %d personas",
                 result.modified_count)

    # Clear legacy Redis keys
    async for key in redis.scan_iter(match="llm:models:*", count=100):
        await redis.delete(key)
    async for key in redis.scan_iter(match="llm:provider:status:*", count=100):
        await redis.delete(key)

    await db["_migrations"].insert_one(
        {"_id": _MARKER_ID, "at": datetime.now(UTC)}
    )
    _log.warning("connections_refactor_v1: cleanup complete")
```

- [ ] **Step 2: Call it at startup**

Locate the startup lifecycle in `backend/main.py` (e.g., `on_startup` / FastAPI lifespan). Insert immediately before the index-creation calls:

```python
from backend.modules.llm._migration_connections_refactor import (
    run_if_needed as run_connections_refactor_cleanup,
)

await run_connections_refactor_cleanup(get_db(), get_redis())
```

- [ ] **Step 3: Compile + bring up backend**

Run: `docker compose run --rm backend uv run python -c "from backend.main import app"`

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_migration_connections_refactor.py backend/main.py
git commit -m "Hard-cut migration: drop provider-era collections, unwire personas, clear redis caches"
```

---

### Task 22: Delete deprecated files + final backend cleanup

**Files to delete:**
- `backend/modules/llm/_credentials.py`
- `backend/modules/llm/_curation.py`
- `backend/modules/llm/_concurrency.py`
- `backend/modules/llm/_provider_status.py`
- `backend/modules/llm/_adapters/_ollama_cloud.py`
- `backend/modules/llm/_adapters/_ollama_local.py`
- `backend/modules/llm/_adapters/_ollama_base.py` (contents moved to `_ollama_http.py` in Task 6)

- [ ] **Step 1: Delete files**

```bash
rm backend/modules/llm/_credentials.py \
   backend/modules/llm/_curation.py \
   backend/modules/llm/_concurrency.py \
   backend/modules/llm/_provider_status.py \
   backend/modules/llm/_adapters/_ollama_cloud.py \
   backend/modules/llm/_adapters/_ollama_local.py \
   backend/modules/llm/_adapters/_ollama_base.py
```

- [ ] **Step 2: Check no stray references remain**

Run:
```
grep -rn "ConcurrencyPolicy\|CredentialRepository\|CurationRepository\|_provider_status\|OllamaCloudAdapter\|OllamaLocalAdapter\|OllamaBaseAdapter" backend/ shared/ | grep -v __pycache__
```
Expected: no matches.

- [ ] **Step 3: Full app import**

Run: `docker compose run --rm backend uv run python -c "from backend.main import app; print(len(app.routes))"`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add -A backend/modules/llm backend/modules/websearch
git commit -m "Delete deprecated LLM provider/credential/curation modules"
```

---

## Phase 7 — Frontend Foundation

### Task 23: Frontend type updates

**Files:**
- Modify: `frontend/src/core/types/llm.ts`
- Create or modify: `frontend/src/core/types/websearch.ts`
- Modify: `frontend/src/core/types/events.ts`

- [ ] **Step 1: Rewrite `frontend/src/core/types/llm.ts`**

Replace the existing provider-era types with:

```ts
export type AdapterConfigFieldType = 'string' | 'url' | 'secret' | 'integer'

export interface AdapterConfigFieldHint {
  name: string
  type: AdapterConfigFieldType
  label: string
  required: boolean
  min: number | null
  max: number | null
  placeholder: string | null
}

export interface AdapterTemplate {
  id: string
  display_name: string
  slug_prefix: string
  config_defaults: Record<string, unknown>
}

export interface Adapter {
  adapter_type: string
  display_name: string
  view_id: string
  templates: AdapterTemplate[]
  config_schema: AdapterConfigFieldHint[]
  secret_fields: string[]
}

export interface Connection {
  id: string
  user_id: string
  adapter_type: string
  display_name: string
  slug: string
  config: Record<string, unknown>  // secrets appear as { is_set: boolean }
  last_test_status: string | null
  last_test_error: string | null
  last_test_at: string | null
  created_at: string
  updated_at: string
}

export interface CreateConnectionRequest {
  adapter_type: string
  display_name: string
  slug: string
  config: Record<string, unknown>
}

export interface UpdateConnectionRequest {
  display_name?: string
  slug?: string
  config?: Record<string, unknown>
}

export interface ModelMeta {
  connection_id: string
  connection_display_name: string
  model_id: string
  display_name: string
  context_window: number
  supports_reasoning: boolean
  supports_vision: boolean
  supports_tool_calls: boolean
  parameter_count: string | null
  raw_parameter_count: number | null
  quantisation_level: string | null
}

export interface UserModelConfig {
  model_unique_id: string
  is_favourite: boolean
  is_hidden: boolean
  custom_display_name: string | null
  custom_context_window: number | null
  notes: string | null
  system_prompt_addition: string | null
}
```

Delete exports for `ProviderCredential`, `ModelCuration`, `ProviderModelsFetchStatus`, `FaultyProvider`, and any `provider_id`-keyed shapes.

- [ ] **Step 2: Write `frontend/src/core/types/websearch.ts`**

```ts
export interface WebSearchProvider {
  provider_id: string
  display_name: string
  is_configured: boolean
  last_test_status: string | null
  last_test_error: string | null
}

export interface WebSearchCredential {
  provider_id: string
  is_configured: boolean
  last_test_status: string | null
  last_test_error: string | null
  last_test_at: string | null
}
```

- [ ] **Step 3: Update `frontend/src/core/types/events.ts`**

Remove: `llm.credential.*`, `llm.model.curated`, `llm.provider.status_changed`, `llm.models.fetch_started`, `llm.models.fetch_completed`, `llm.models.refreshed` entries.

Add: `llm.connection.created|updated|removed|tested|status_changed|models_refreshed`, `websearch.credential.set|removed|tested`.

The exact type shape mirrors the backend events — the literal topic strings under `Topic`, the payload interfaces, and the discriminated union.

- [ ] **Step 4: Typecheck**

Run: `docker compose run --rm frontend pnpm tsc --noEmit`
Expected: errors from downstream files that still reference deleted types — these are fixed in later tasks. Don't commit yet.

- [ ] **Step 5: Hold commit until Task 25**

---

### Task 24: API clients

**Files:**
- Replace: `frontend/src/core/api/llm.ts`
- Create: `frontend/src/core/api/websearch.ts`

- [ ] **Step 1: Rewrite `frontend/src/core/api/llm.ts`**

```ts
import type {
  Adapter, Connection, CreateConnectionRequest, ModelMeta,
  UpdateConnectionRequest, UserModelConfig,
} from '@/core/types/llm'
import { apiFetch } from '@/core/api/_fetch'

export async function listAdapters(): Promise<Adapter[]> {
  return apiFetch('/api/llm/adapters')
}

export async function listConnections(): Promise<Connection[]> {
  return apiFetch('/api/llm/connections')
}

export async function createConnection(
  body: CreateConnectionRequest,
): Promise<Connection> {
  return apiFetch('/api/llm/connections', {
    method: 'POST', body: JSON.stringify(body),
  })
}

export async function getConnection(id: string): Promise<Connection> {
  return apiFetch(`/api/llm/connections/${id}`)
}

export async function updateConnection(
  id: string, body: UpdateConnectionRequest,
): Promise<Connection> {
  return apiFetch(`/api/llm/connections/${id}`, {
    method: 'PATCH', body: JSON.stringify(body),
  })
}

export async function deleteConnection(id: string): Promise<void> {
  await apiFetch(`/api/llm/connections/${id}`, { method: 'DELETE' })
}

export async function listConnectionModels(id: string): Promise<ModelMeta[]> {
  return apiFetch(`/api/llm/connections/${id}/models`)
}

export async function refreshConnectionModels(id: string): Promise<void> {
  await apiFetch(`/api/llm/connections/${id}/refresh`, { method: 'POST' })
}

// Adapter-specific (Ollama HTTP)
export async function testConnection(id: string): Promise<{ valid: boolean; error: string | null }> {
  return apiFetch(`/api/llm/connections/${id}/adapter/test`, { method: 'POST' })
}

export interface OllamaDiagnostics {
  ps: unknown
  tags: unknown
}

export async function getConnectionDiagnostics(id: string): Promise<OllamaDiagnostics> {
  return apiFetch(`/api/llm/connections/${id}/adapter/diagnostics`)
}

// User model config
export async function getUserModelConfig(
  connectionId: string, modelSlug: string,
): Promise<UserModelConfig> {
  return apiFetch(
    `/api/llm/connections/${connectionId}/models/${encodeURIComponent(modelSlug)}/user-config`,
  )
}

export async function setUserModelConfig(
  connectionId: string, modelSlug: string,
  body: Partial<Omit<UserModelConfig, 'model_unique_id'>>,
): Promise<UserModelConfig> {
  return apiFetch(
    `/api/llm/connections/${connectionId}/models/${encodeURIComponent(modelSlug)}/user-config`,
    { method: 'PUT', body: JSON.stringify(body) },
  )
}

export async function deleteUserModelConfig(
  connectionId: string, modelSlug: string,
): Promise<UserModelConfig> {
  return apiFetch(
    `/api/llm/connections/${connectionId}/models/${encodeURIComponent(modelSlug)}/user-config`,
    { method: 'DELETE' },
  )
}

export async function listUserModelConfigs(): Promise<UserModelConfig[]> {
  return apiFetch('/api/llm/user-model-configs')
}
```

Delete any exports referencing the old `/providers/...` URL scheme.

- [ ] **Step 2: Create `frontend/src/core/api/websearch.ts`**

```ts
import type { WebSearchCredential, WebSearchProvider } from '@/core/types/websearch'
import { apiFetch } from '@/core/api/_fetch'

export async function listWebSearchProviders(): Promise<WebSearchProvider[]> {
  return apiFetch('/api/websearch/providers')
}

export async function getWebSearchCredential(pid: string): Promise<WebSearchCredential> {
  return apiFetch(`/api/websearch/providers/${pid}/credential`)
}

export async function setWebSearchKey(
  pid: string, apiKey: string,
): Promise<WebSearchCredential> {
  return apiFetch(`/api/websearch/providers/${pid}/credential`, {
    method: 'PUT', body: JSON.stringify({ api_key: apiKey }),
  })
}

export async function deleteWebSearchKey(pid: string): Promise<void> {
  await apiFetch(`/api/websearch/providers/${pid}/credential`, { method: 'DELETE' })
}

export async function testWebSearchKey(
  pid: string, apiKey: string,
): Promise<{ valid: boolean; error: string | null }> {
  return apiFetch(`/api/websearch/providers/${pid}/test`, {
    method: 'POST', body: JSON.stringify({ api_key: apiKey }),
  })
}
```

- [ ] **Step 3: Hold commit until Task 25**

---

### Task 25: AdapterViewRegistry + OllamaHttpView scaffolding

**Files:**
- Create: `frontend/src/core/adapters/AdapterViewRegistry.tsx`
- Create: `frontend/src/app/components/llm-providers/adapter-views/OllamaHttpView.tsx` (skeleton; full body in Task 29)

- [ ] **Step 1: Create the view registry**

```tsx
import type { ComponentType } from 'react'
import type { Connection } from '@/core/types/llm'
import { OllamaHttpView } from '@/app/components/llm-providers/adapter-views/OllamaHttpView'

export interface AdapterViewProps {
  connection: Connection
  onConfigChange: (config: Record<string, unknown>) => void
  onDisplayNameChange: (name: string) => void
  onSlugChange: (slug: string) => void
  readOnlyAdapterType?: boolean
}

export const ADAPTER_VIEW_REGISTRY: Record<string, ComponentType<AdapterViewProps>> = {
  ollama_http: OllamaHttpView,
}

export function resolveAdapterView(viewId: string): ComponentType<AdapterViewProps> | null {
  return ADAPTER_VIEW_REGISTRY[viewId] ?? null
}
```

- [ ] **Step 2: Create the OllamaHttpView skeleton**

```tsx
import type { AdapterViewProps } from '@/core/adapters/AdapterViewRegistry'

export function OllamaHttpView(props: AdapterViewProps): JSX.Element {
  // Full implementation in Task 29.
  return (
    <div className="p-4 text-sm text-white/60">
      Ollama HTTP configuration (fields pending)
    </div>
  )
}
```

- [ ] **Step 3: Typecheck**

Run: `docker compose run --rm frontend pnpm tsc --noEmit`
Expected: frontend-wide errors in files that reference removed types (ApiKeysTab, ModelBrowser, etc.). Don't commit yet — the remaining tasks fix those.

Hmm — the typecheck gate will fail for a while. Strategy: temporarily comment out (not delete) the broken imports/usage in `ApiKeysTab.tsx`, `ModelBrowser.tsx`, and other affected files just enough to get a green typecheck, land Tasks 23–25 together, then rebuild those components properly in later tasks. Or: bundle Tasks 23–33 into one mega-commit.

Recommend the latter if you are using subagent-driven execution and want one-commit-per-task — create a `TODO: gutted for connections refactor` stub component so typecheck passes, and replace in later tasks.

- [ ] **Step 4: Insert stub components to restore typecheck**

For files that reference removed types and must compile, replace their body with a minimal no-op export:
- `frontend/src/app/components/user-modal/ApiKeysTab.tsx` → `export function ApiKeysTab() { return <div>Pending web-search rewrite</div> }`
- `frontend/src/app/components/user-modal/ModelsTab.tsx` → similar
- `frontend/src/app/components/model-browser/ModelBrowser.tsx` → similar (keep the default export shape the consumers expect)
- `frontend/src/app/components/admin-modal/ModelList.tsx`, `ModelsTab.tsx`, `DebugTab.tsx`, `CurationModal.tsx` → similar, or keep references removed in later tasks

Also: remove imports in any file that imported deleted exports (e.g., `PROVIDER_DISPLAY_NAMES` type, curation types).

Keep test files that will be rewritten later: stub them out so Vitest collects them cleanly.

- [ ] **Step 5: Confirm green typecheck**

Run: `docker compose run --rm frontend pnpm tsc --noEmit`
Expected: pass.

- [ ] **Step 6: Commit Tasks 23–25**

```bash
git add frontend/src/core/types frontend/src/core/api \
        frontend/src/core/adapters \
        frontend/src/app/components/llm-providers \
        frontend/src/app/components/user-modal \
        frontend/src/app/components/model-browser \
        frontend/src/app/components/admin-modal
git commit -m "Frontend types + api client for connections; stub deprecated components"
```

---

## Phase 8 — Frontend LLM Providers UI

### Task 26: LlmProvidersTab — list view + empty state

**Files:**
- Create: `frontend/src/app/components/user-modal/LlmProvidersTab.tsx`
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx` (or wherever tabs are registered) to add the new tab.

- [ ] **Step 1: Create the component skeleton**

```tsx
import { useEffect, useState } from 'react'
import { listConnections } from '@/core/api/llm'
import type { Connection } from '@/core/types/llm'
import { ConnectionListItem } from '@/app/components/llm-providers/ConnectionListItem'
import { AddConnectionWizard } from '@/app/components/llm-providers/AddConnectionWizard'
import { ConnectionConfigModal } from '@/app/components/llm-providers/ConnectionConfigModal'

export function LlmProvidersTab(): JSX.Element {
  const [items, setItems] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [editing, setEditing] = useState<Connection | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      setItems(await listConnections())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  // TODO Task 30: subscribe to llm.connection.* events + live status pill updates.

  if (loading) return <div className="p-6 text-white/60">Laden…</div>

  if (items.length === 0) {
    return (
      <div className="p-6 text-center space-y-4">
        <div className="text-white/70">
          Du hast noch keine LLM-Verbindung eingerichtet.
        </div>
        <button
          className="px-4 py-2 bg-purple/70 text-white rounded"
          onClick={() => setWizardOpen(true)}
        >
          Verbindung einrichten
        </button>
        {wizardOpen && (
          <AddConnectionWizard
            onClose={() => setWizardOpen(false)}
            onCreated={async () => {
              setWizardOpen(false)
              await refresh()
            }}
          />
        )}
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      <div className="flex justify-between items-center">
        <h3 className="text-lg text-white/90">LLM Providers</h3>
        <button
          className="px-3 py-1 bg-purple/70 rounded text-sm"
          onClick={() => setWizardOpen(true)}
        >
          + Connection
        </button>
      </div>
      <ul className="divide-y divide-white/5">
        {items.map((c) => (
          <ConnectionListItem
            key={c.id}
            connection={c}
            onClick={() => setEditing(c)}
          />
        ))}
      </ul>
      {wizardOpen && (
        <AddConnectionWizard
          onClose={() => setWizardOpen(false)}
          onCreated={async () => { setWizardOpen(false); await refresh() }}
        />
      )}
      {editing && (
        <ConnectionConfigModal
          connection={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await refresh() }}
          onDeleted={async () => { setEditing(null); await refresh() }}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create `ConnectionListItem`**

```tsx
import type { Connection } from '@/core/types/llm'

export function ConnectionListItem(props: {
  connection: Connection
  onClick: () => void
}): JSX.Element {
  const { connection: c, onClick } = props
  const statusLabel = c.last_test_status ?? 'untested'
  return (
    <li
      onClick={onClick}
      className="py-3 px-2 cursor-pointer hover:bg-white/5 flex items-center gap-3"
    >
      <div className="flex-1">
        <div className="text-white/90">{c.display_name}</div>
        <div className="text-xs text-white/50 font-mono">{c.slug}</div>
      </div>
      <span className="text-xs px-2 py-0.5 rounded bg-white/10 text-white/70">
        {c.adapter_type}
      </span>
      <span className={`text-xs px-2 py-0.5 rounded ${statusColour(statusLabel)}`}>
        {statusLabel}
      </span>
    </li>
  )
}

function statusColour(status: string): string {
  if (status === 'valid') return 'bg-green-700/60 text-white'
  if (status === 'failed') return 'bg-red-700/60 text-white'
  return 'bg-white/10 text-white/60'
}
```

- [ ] **Step 3: Add the tab to UserModal tab registry**

Edit `UserModal.tsx`: add `{ id: 'llm', label: 'LLM Providers', component: LlmProvidersTab }` (match existing tab-registration pattern).

- [ ] **Step 4: Typecheck**

Run: `docker compose run --rm frontend pnpm tsc --noEmit`
Expected: new errors only about `AddConnectionWizard` and `ConnectionConfigModal` not existing. Tasks 27+28 add them.

- [ ] **Step 5: Hold commit until Task 28**

---

### Task 27: Add-Connection wizard

**Files:**
- Create: `frontend/src/app/components/llm-providers/AddConnectionWizard.tsx`

- [ ] **Step 1: Write the wizard**

```tsx
import { useEffect, useMemo, useState } from 'react'
import { createConnection, listAdapters, listConnections } from '@/core/api/llm'
import type { Adapter, AdapterTemplate, Connection } from '@/core/types/llm'
import { ConnectionConfigModal } from './ConnectionConfigModal'

export function AddConnectionWizard(props: {
  onClose: () => void
  onCreated: () => void
}): JSX.Element | null {
  const [adapters, setAdapters] = useState<Adapter[]>([])
  const [existing, setExisting] = useState<Connection[]>([])
  const [selectedAdapter, setSelectedAdapter] = useState<Adapter | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState<AdapterTemplate | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      const [a, e] = await Promise.all([listAdapters(), listConnections()])
      setAdapters(a)
      setExisting(e)
      setLoading(false)
    })()
  }, [])

  const existingSlugs = useMemo(() => new Set(existing.map((c) => c.slug)), [existing])

  if (loading) return <div className="modal">Laden…</div>

  if (!selectedAdapter) {
    return (
      <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
        <div className="bg-[#0f0d16] p-6 rounded-lg w-[600px] space-y-4">
          <h3 className="text-white/90">Adapter wählen</h3>
          <div className="grid grid-cols-2 gap-3">
            {adapters.map((a) => (
              <button
                key={a.adapter_type}
                onClick={() => setSelectedAdapter(a)}
                className="p-4 border border-white/10 rounded hover:border-purple/50 text-left"
              >
                <div className="text-white/90">{a.display_name}</div>
                <div className="text-xs text-white/50 font-mono">{a.adapter_type}</div>
              </button>
            ))}
          </div>
          <button onClick={props.onClose} className="text-white/60 text-sm">Abbrechen</button>
        </div>
      </div>
    )
  }

  if (!selectedTemplate) {
    return (
      <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
        <div className="bg-[#0f0d16] p-6 rounded-lg w-[600px] space-y-4">
          <h3 className="text-white/90">Template wählen — {selectedAdapter.display_name}</h3>
          <div className="grid grid-cols-3 gap-3">
            {selectedAdapter.templates.map((t) => (
              <button
                key={t.id}
                onClick={() => setSelectedTemplate(t)}
                className="p-4 border border-white/10 rounded hover:border-purple/50 text-left"
              >
                <div className="text-white/90">{t.display_name}</div>
                <div className="text-xs text-white/50 font-mono">{t.slug_prefix}</div>
              </button>
            ))}
          </div>
          <button onClick={() => setSelectedAdapter(null)} className="text-white/60 text-sm">
            Zurück
          </button>
        </div>
      </div>
    )
  }

  const candidateName = selectedTemplate.display_name
  const baseSlug = selectedTemplate.slug_prefix
  const finalSlug = pickFreeSlug(baseSlug, existingSlugs)

  return (
    <ConnectionConfigModal
      newConnectionPreset={{
        adapter: selectedAdapter,
        template: selectedTemplate,
        display_name: candidateName,
        slug: finalSlug,
        config: { ...selectedTemplate.config_defaults },
      }}
      onClose={props.onClose}
      onSaved={async () => props.onCreated()}
      onDeleted={props.onClose}
    />
  )
}

function pickFreeSlug(base: string, taken: Set<string>): string {
  if (!taken.has(base)) return base
  let n = 2
  while (taken.has(`${base}-${n}`)) n += 1
  return `${base}-${n}`
}
```

- [ ] **Step 2: Hold commit until Task 28**

---

### Task 28: Connection Config Modal + adapter view mounting

**Files:**
- Create: `frontend/src/app/components/llm-providers/ConnectionConfigModal.tsx`

- [ ] **Step 1: Write the modal**

```tsx
import { useEffect, useState } from 'react'
import { createConnection, deleteConnection, updateConnection } from '@/core/api/llm'
import { resolveAdapterView } from '@/core/adapters/AdapterViewRegistry'
import type { Adapter, AdapterTemplate, Connection } from '@/core/types/llm'

export interface NewConnectionPreset {
  adapter: Adapter
  template: AdapterTemplate
  display_name: string
  slug: string
  config: Record<string, unknown>
}

export function ConnectionConfigModal(props: {
  connection?: Connection
  newConnectionPreset?: NewConnectionPreset
  onClose: () => void
  onSaved: () => void | Promise<void>
  onDeleted: () => void | Promise<void>
}): JSX.Element {
  const isNew = !props.connection
  const [displayName, setDisplayName] = useState(
    props.connection?.display_name ?? props.newConnectionPreset?.display_name ?? '',
  )
  const [slug, setSlug] = useState(
    props.connection?.slug ?? props.newConnectionPreset?.slug ?? '',
  )
  const [config, setConfig] = useState<Record<string, unknown>>(
    props.connection?.config ?? props.newConnectionPreset?.config ?? {},
  )
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const adapterType = props.connection?.adapter_type ?? props.newConnectionPreset?.adapter.adapter_type ?? ''
  const viewId = props.newConnectionPreset?.adapter.view_id
    ?? guessViewIdFromAdapterType(adapterType)
  const AdapterView = viewId ? resolveAdapterView(viewId) : null

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      if (isNew && props.newConnectionPreset) {
        await createConnection({
          adapter_type: props.newConnectionPreset.adapter.adapter_type,
          display_name: displayName,
          slug,
          config,
        })
      } else if (props.connection) {
        await updateConnection(props.connection.id, {
          display_name: displayName, slug, config,
        })
      }
      await props.onSaved()
    } catch (e: unknown) {
      setError(extractError(e))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!props.connection) return
    if (!confirm('Wirklich löschen?')) return
    await deleteConnection(props.connection.id)
    await props.onDeleted()
  }

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-4 z-50">
      <div className="bg-[#0f0d16] p-6 rounded-lg w-[640px] space-y-4">
        <div className="flex justify-between">
          <h3 className="text-white/90">
            {isNew ? 'Neue Verbindung' : displayName}
          </h3>
          <button onClick={props.onClose} className="text-white/60">✕</button>
        </div>
        <label className="block text-sm space-y-1">
          <span className="text-white/70">Anzeigename</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full bg-white/5 rounded px-2 py-1"
          />
        </label>
        <label className="block text-sm space-y-1">
          <span className="text-white/70">Slug</span>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            className="w-full bg-white/5 rounded px-2 py-1 font-mono"
          />
        </label>
        {AdapterView ? (
          <AdapterView
            connection={{
              ...(props.connection ?? {
                id: 'new', user_id: '', adapter_type: adapterType,
                display_name: displayName, slug, config,
                last_test_status: null, last_test_error: null, last_test_at: null,
                created_at: '', updated_at: '',
              }),
              config,
            }}
            onConfigChange={setConfig}
            onDisplayNameChange={setDisplayName}
            onSlugChange={setSlug}
          />
        ) : (
          <div className="text-white/50 text-sm">Keine Adapter-Ansicht für {viewId}</div>
        )}
        {error && <div className="text-red-400 text-sm">{error}</div>}
        <div className="flex justify-between">
          {props.connection ? (
            <button onClick={handleDelete} className="text-red-400 text-sm">Löschen</button>
          ) : <span />}
          <div className="space-x-2">
            <button onClick={props.onClose} className="text-white/60 text-sm">Abbrechen</button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-3 py-1 bg-purple/70 rounded text-sm disabled:opacity-50"
            >
              Speichern
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function extractError(e: unknown): string {
  if (typeof e === 'object' && e && 'message' in e) {
    return String((e as { message: unknown }).message)
  }
  return 'Unbekannter Fehler'
}

function guessViewIdFromAdapterType(at: string): string {
  // v1: adapter_type == view_id always. Kept as a function so later adapters can diverge.
  return at
}
```

- [ ] **Step 2: Typecheck + build**

Run:
```
docker compose run --rm frontend pnpm tsc --noEmit
docker compose run --rm frontend pnpm run build
```
Expected: pass.

- [ ] **Step 3: Commit Tasks 26, 27, 28**

```bash
git add frontend/src/app/components/llm-providers \
        frontend/src/app/components/user-modal
git commit -m "LLM Providers tab: list, wizard, config modal (adapter view slot)"
```

---

### Task 29: OllamaHttpView body (fields, test, diagnostics)

**Files:**
- Replace: `frontend/src/app/components/llm-providers/adapter-views/OllamaHttpView.tsx`

- [ ] **Step 1: Write the full component**

```tsx
import { useEffect, useMemo, useState } from 'react'
import { getConnectionDiagnostics, listConnections, testConnection } from '@/core/api/llm'
import type { AdapterViewProps } from '@/core/adapters/AdapterViewRegistry'

export function OllamaHttpView(props: AdapterViewProps): JSX.Element {
  const { connection, onConfigChange } = props
  const [showKey, setShowKey] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ valid: boolean; error: string | null } | null>(null)
  const [diagOpen, setDiagOpen] = useState(false)
  const [diag, setDiag] = useState<{ ps: unknown; tags: unknown } | null>(null)
  const [urlCollision, setUrlCollision] = useState<string | null>(null)

  const cfg = connection.config as Record<string, unknown>
  const url = String(cfg.url ?? '')
  const apiKeyField = cfg.api_key
  const hasStoredKey = typeof apiKeyField === 'object' && apiKeyField !== null
    && 'is_set' in apiKeyField && (apiKeyField as { is_set: boolean }).is_set
  const apiKeyDraft = typeof apiKeyField === 'string' ? apiKeyField : ''
  const maxParallel = Number(cfg.max_parallel ?? 1)

  useEffect(() => {
    // URL collision check against user's other connections.
    void (async () => {
      if (!url) { setUrlCollision(null); return }
      try {
        const all = await listConnections()
        const others = all.filter((c) => c.id !== connection.id)
        const clash = others.find((c) => normaliseUrl(String(c.config.url ?? '')) === normaliseUrl(url))
        setUrlCollision(clash ? clash.slug : null)
      } catch {
        setUrlCollision(null)
      }
    })()
  }, [url, connection.id])

  function set(key: string, value: unknown) {
    onConfigChange({ ...cfg, [key]: value })
  }

  async function runTest() {
    setTesting(true)
    setTestResult(null)
    try {
      setTestResult(await testConnection(connection.id))
    } catch (e: unknown) {
      setTestResult({ valid: false, error: String(e) })
    } finally {
      setTesting(false)
    }
  }

  async function runDiag() {
    setDiagOpen(true)
    setDiag(null)
    try {
      setDiag(await getConnectionDiagnostics(connection.id))
    } catch (e: unknown) {
      setDiag({ ps: null, tags: { error: String(e) } })
    }
  }

  return (
    <div className="space-y-3">
      <label className="block text-sm space-y-1">
        <span className="text-white/70">URL</span>
        <input
          value={url}
          onChange={(e) => set('url', e.target.value)}
          placeholder="http://localhost:11434"
          className="w-full bg-white/5 rounded px-2 py-1"
        />
        {urlCollision && (
          <div className="text-yellow-400 text-xs">
            Du hast bereits eine Verbindung zu dieser URL (slug: {urlCollision}).
            Das kann zu unerwartetem Queuing-Verhalten am Backend führen.
          </div>
        )}
      </label>

      <label className="block text-sm space-y-1">
        <span className="text-white/70">
          API Key {hasStoredKey && <span className="text-green-400 text-xs">(gespeichert)</span>}
        </span>
        <div className="flex gap-2">
          <input
            type={showKey ? 'text' : 'password'}
            value={apiKeyDraft}
            onChange={(e) => set('api_key', e.target.value)}
            placeholder={hasStoredKey ? '••• unverändert lassen' : ''}
            className="flex-1 bg-white/5 rounded px-2 py-1"
          />
          <button
            type="button"
            onClick={() => setShowKey((s) => !s)}
            className="text-xs text-white/60"
          >
            {showKey ? 'verbergen' : 'anzeigen'}
          </button>
        </div>
      </label>

      <label className="block text-sm space-y-1">
        <span className="text-white/70">Max parallel inferences</span>
        <input
          type="number" min={1} max={32}
          value={maxParallel}
          onChange={(e) => set('max_parallel', Number(e.target.value))}
          className="w-24 bg-white/5 rounded px-2 py-1"
        />
      </label>

      <div className="flex gap-2 items-center">
        <button
          onClick={runTest} disabled={testing}
          className="px-3 py-1 bg-white/10 rounded text-sm disabled:opacity-50"
        >
          {testing ? 'Teste…' : 'Test'}
        </button>
        {testResult && (
          <span className={`text-xs ${testResult.valid ? 'text-green-400' : 'text-red-400'}`}>
            {testResult.valid ? 'ok' : testResult.error ?? 'failed'}
          </span>
        )}
      </div>

      <details open={diagOpen} onToggle={(e) => e.currentTarget.open ? runDiag() : null}
        className="border border-white/10 rounded">
        <summary className="px-3 py-2 cursor-pointer text-sm text-white/80">Diagnostics</summary>
        <div className="p-3 text-xs text-white/70 space-y-3">
          {diag === null ? (
            <div>Lade…</div>
          ) : (
            <>
              <div>
                <div className="text-white/60 mb-1">Running (ps)</div>
                <pre className="bg-black/30 p-2 rounded overflow-auto">
                  {JSON.stringify(diag.ps, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-white/60 mb-1">Available (tags)</div>
                <pre className="bg-black/30 p-2 rounded overflow-auto">
                  {JSON.stringify(diag.tags, null, 2)}
                </pre>
              </div>
            </>
          )}
        </div>
      </details>
    </div>
  )
}

function normaliseUrl(u: string): string {
  return u.trim().replace(/\/+$/, '').toLowerCase()
}
```

- [ ] **Step 2: Typecheck + build**

Run:
```
docker compose run --rm frontend pnpm tsc --noEmit
docker compose run --rm frontend pnpm run build
```
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/llm-providers/adapter-views/OllamaHttpView.tsx
git commit -m "OllamaHttpView: URL/key/max_parallel fields, test + diagnostics panel, URL collision warning"
```

---

### Task 30: Tab badge + live event wiring

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
- Modify: `frontend/src/app/components/user-modal/LlmProvidersTab.tsx`

- [ ] **Step 1: Surface zero-connections indicator on the tab**

In `UserModal.tsx`, replicate the existing pattern used for the API Keys tab's exclamation indicator. Source of truth: `listConnections().length === 0` cached at tab-registry render time (likely a hook call in the parent). Mirror whatever mechanism the API Keys tab uses.

- [ ] **Step 2: Subscribe to WebSocket events in LlmProvidersTab**

Extend the tab with a subscription:

```tsx
import { useWsSubscribe } from '@/core/hooks/useWsSubscribe' // whatever the project's helper is named
// ...
useWsSubscribe('llm.connection.created', () => { void refresh() })
useWsSubscribe('llm.connection.updated', () => { void refresh() })
useWsSubscribe('llm.connection.removed', () => { void refresh() })
useWsSubscribe('llm.connection.status_changed', () => { void refresh() })
```

If the project's hook name differs, inspect an existing subscriber component (e.g., a ModelBrowser subscription or the persona list) and match its pattern.

- [ ] **Step 3: Build + smoke the UI manually (see Task 36 for end-to-end)**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal
git commit -m "LLM Providers tab: zero-connections badge + live event subscriptions"
```

---

## Phase 9 — Other Frontend Surfaces

### Task 31: Rewrite API Keys tab to web-search-only

**Files:**
- Replace: `frontend/src/app/components/user-modal/ApiKeysTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { useEffect, useState } from 'react'
import {
  deleteWebSearchKey, listWebSearchProviders,
  setWebSearchKey, testWebSearchKey,
} from '@/core/api/websearch'
import type { WebSearchProvider } from '@/core/types/websearch'

export function ApiKeysTab(): JSX.Element {
  const [items, setItems] = useState<WebSearchProvider[]>([])
  const [loading, setLoading] = useState(true)

  async function refresh() {
    setLoading(true)
    try { setItems(await listWebSearchProviders()) } finally { setLoading(false) }
  }

  useEffect(() => { void refresh() }, [])

  if (loading) return <div className="p-6 text-white/60">Laden…</div>

  return (
    <div className="p-4 space-y-3">
      <h3 className="text-lg text-white/90">API Keys (Web Search)</h3>
      <ul className="space-y-2">
        {items.map((p) => (
          <WebSearchRow key={p.provider_id} provider={p} onChanged={refresh} />
        ))}
      </ul>
    </div>
  )
}

function WebSearchRow(props: {
  provider: WebSearchProvider; onChanged: () => void
}): JSX.Element {
  const { provider: p, onChanged } = props
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true); setError(null)
    try {
      await setWebSearchKey(p.provider_id, draft)
      setDraft('')
      onChanged()
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  async function remove() {
    setBusy(true); setError(null)
    try { await deleteWebSearchKey(p.provider_id); onChanged() }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  async function test() {
    setBusy(true); setError(null)
    try {
      const r = await testWebSearchKey(p.provider_id, draft)
      if (!r.valid) setError(r.error ?? 'failed')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  return (
    <li className="p-3 border border-white/10 rounded flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-white/90 flex-1">{p.display_name}</span>
        {p.is_configured && <span className="text-xs text-green-400">konfiguriert</span>}
      </div>
      <div className="flex gap-2">
        <input
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={p.is_configured ? '••• (unverändert lassen)' : 'API Key'}
          className="flex-1 bg-white/5 rounded px-2 py-1"
        />
        <button onClick={test} disabled={!draft || busy} className="px-2 py-1 bg-white/10 rounded text-sm disabled:opacity-50">
          Test
        </button>
        <button onClick={save} disabled={!draft || busy} className="px-2 py-1 bg-purple/70 rounded text-sm disabled:opacity-50">
          Speichern
        </button>
        {p.is_configured && (
          <button onClick={remove} disabled={busy} className="px-2 py-1 bg-red-700/60 rounded text-sm disabled:opacity-50">
            Entfernen
          </button>
        )}
      </div>
      {error && <div className="text-red-400 text-xs">{error}</div>}
    </li>
  )
}
```

- [ ] **Step 2: Typecheck + build**

Run:
```
docker compose run --rm frontend pnpm tsc --noEmit
docker compose run --rm frontend pnpm run build
```
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/user-modal/ApiKeysTab.tsx
git commit -m "Rewrite API Keys tab for web-search-only (Ollama Web Search)"
```

---

### Task 32: Model browser regrouping + curation removal

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`
- Modify: `frontend/src/app/components/model-browser/ModelConfigModal.tsx`
- Modify: `frontend/src/app/components/model-browser/modelFilters.ts`
- Modify: `frontend/src/app/components/model-browser/ModelSelectionModal.tsx`
- Delete: `frontend/src/app/components/admin-modal/CurationModal.tsx`, `ModelList.tsx`, `ModelsTab.tsx`
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts`

- [ ] **Step 1: Rewrite `useEnrichedModels.ts`**

The hook today groups by `provider_id` and fetches per-provider. Change it to:

1. Fetch `listConnections()`.
2. For each Connection, fetch `listConnectionModels(id)`.
3. Merge with the user's UserModelConfigs (already loaded via existing hook — keep the merge step but match on new `model_unique_id` format).
4. Group returned rows by `connection_id`.
5. Return `{ groups: { connection: Connection; models: EnrichedModel[] }[] }`.

- [ ] **Step 2: Update the browser to render groups by Connection**

Where the old code rendered one group per `provider_id`, render one per Connection with `connection.display_name (connection.slug)` as heading. Remove star/hidden/admin-description UI entirely.

- [ ] **Step 3: Update ModelConfigModal to build `model_unique_id` from `connection_id + model_id`**

Current code likely does `` `${provider_id}:${model_id}` ``. Replace with `` `${connection_id}:${model_id}` ``.

- [ ] **Step 4: Update modelFilters.ts**

Any filter predicates that key off `provider_id` should now use `connection_id` (or whatever the UX groups by). Review `modelFilters.ts:test.ts` — kept tests must be updated or deleted.

- [ ] **Step 5: Remove admin curation UI**

```bash
rm frontend/src/app/components/admin-modal/CurationModal.tsx
rm frontend/src/app/components/admin-modal/ModelList.tsx
rm frontend/src/app/components/admin-modal/ModelsTab.tsx
```

Update `frontend/src/app/components/admin-modal/AdminModal.tsx` (or the admin tab registry) to drop the Models tab entry.

- [ ] **Step 6: Typecheck + build**

Run:
```
docker compose run --rm frontend pnpm tsc --noEmit
docker compose run --rm frontend pnpm run build
```
Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/model-browser frontend/src/app/components/admin-modal frontend/src/core/hooks/useEnrichedModels.ts
git commit -m "Model browser: group by connection, drop admin curation UI"
```

---

### Task 33: Persona model picker updates

**Files:**
- Modify: `frontend/src/app/components/persona-card/PersonaCard.tsx`
- Modify: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` (if relevant)
- Modify: `frontend/src/core/types/persona.ts` if it references `provider_id`

- [ ] **Step 1: Update split logic**

Any code doing `const [providerId, slug] = modelUniqueId.split(':')` should be renamed:
```ts
const [connectionId, slug] = modelUniqueId.split(':', 2) as [string, string]
```
Semantics are the same, name is clearer.

- [ ] **Step 2: Replace `PROVIDER_DISPLAY_NAMES` lookups**

Any frontend usage of a static provider-display-name map should be replaced by a lookup against the current connection list (fetched via `listConnections()` and keyed by `id`).

- [ ] **Step 3: Render "model not available" banner**

For any persona whose `model_unique_id` references a `connection_id` not in the current connections list, render a banner on the persona overlay (Overview + Edit tabs):

```tsx
<div className="p-3 bg-yellow-700/20 border border-yellow-600/40 rounded text-sm text-yellow-200">
  Diese Persona verweist auf eine Verbindung, die nicht mehr existiert.
  Bitte ein Modell neu wählen.
</div>
```

Disable chat-initiation for this persona until a valid model is selected.

- [ ] **Step 4: Build**

Run: `docker compose run --rm frontend pnpm run build`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/persona-card frontend/src/app/components/persona-overlay frontend/src/core/types/persona.ts
git commit -m "Persona: adopt connection_id naming; banner when referenced connection missing"
```

---

### Task 34: Chat empty-state when no connections

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Block chat entry and show CTA**

Near the top of the view, check if the user has zero connections (via the same hook used for the tab badge). If so, render:

```tsx
<div className="flex-1 flex items-center justify-center p-6 text-center space-y-3">
  <div>
    <div className="text-white/80 mb-3">
      Du hast noch keine LLM-Verbindung konfiguriert.
    </div>
    <button
      onClick={openLlmProvidersTab}
      className="px-4 py-2 bg-purple/70 rounded"
    >
      Jetzt einrichten
    </button>
  </div>
</div>
```

`openLlmProvidersTab` opens the user modal on the LLM Providers tab. Source the navigation helper from the existing user-modal store.

- [ ] **Step 2: Build**

Run: `docker compose run --rm frontend pnpm run build`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Chat view: empty-state CTA when no LLM connection"
```

---

## Phase 10 — Docs & Verification

### Task 35: INSIGHTS + CLAUDE.md updates

**Files:**
- Modify: `INSIGHTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update INSIGHTS**

- INS-004: replace the text with: `model_unique_id = "<connection_id>:<model_slug>"`. Keep the validation note (adapter_type segment is gone; only the Connection owner check remains).
- INS-005 + INS-006: annotate both as **SUPERSEDED 2026-04-14 (Connections Refactor)**. Model metadata is now two-layer: Redis cache per Connection + user config per user.
- INS-009: annotate as **SUPERSEDED 2026-04-14**. Web search has its own credential store.
- Append a new INS-016 block:
  ```
  ## INS-016 — Adapter vs. Connection (Connections Refactor, 2026-04-14)
  Adapter = code (class per backend-type, declares templates, sub-router, view_id, secret_fields).
  Connection = user-owned Mongo document with adapter-specific config (URL, API key, max_parallel).
  Adapters are stateless; a ResolvedConnection is built at every request and handed to the adapter.
  Adapter routes live under /api/llm/connections/{id}/adapter/... — the generic CRUD never handles adapter-specific endpoints.
  Frontend: AdapterViewRegistry keyed by `view_id` resolves to a bespoke React component per adapter.
  ```
- Append an INS-017 block:
  ```
  ## INS-017 — Per-Connection Concurrency
  asyncio.Semaphore(max_parallel) keyed by connection_id. ConcurrencyPolicy enum removed.
  Lock granularity per id (not per URL) — wizard warns on URL collision but does not block.
  Semaphore is re-created on max_parallel change; in-flight inferences continue under the old budget.
  ```
- Append an INS-018 block:
  ```
  ## INS-018 — Hard-Cut Migration Policy
  Pre-production refactors drop affected collections via a gated startup script.
  A `_migrations` collection marker prevents re-runs. No preservation code.
  Operator communicates "re-configure Connections and re-wire personas" out-of-band.
  ```

- [ ] **Step 2: Update CLAUDE.md**

Under the **What NOT to Do** section, revise:

- Replace: *"Never call Ollama from anywhere except backend/modules/llm/"* → unchanged, still correct.
- Add: *"Never reach into another module's adapter sub-router — the sub-router is mounted under /api/llm/connections/{id}/adapter/ only; other modules talk to LLM via its public `__init__.py`."*

Under **Technology Stack → LLM Inference**, replace the bullet about `ollama_cloud` / `ollama_local` with:

- *Adapters register in `ADAPTER_REGISTRY` (`backend/modules/llm/_registry.py`). Each Adapter declares templates exposed in the "+ Connection" wizard. Users own any number of Connections of any adapter_type.*

- [ ] **Step 3: Commit**

```bash
git add INSIGHTS.md CLAUDE.md
git commit -m "Update INSIGHTS + CLAUDE.md for connections refactor (INS-004/5/6/9 superseded, INS-016/17/18 added)"
```

---

### Task 36: End-to-end smoke test

**Files:** (none created; manual procedure)

- [ ] **Step 1: Full stack build**

Run: `docker compose build backend frontend`
Expected: green.

- [ ] **Step 2: Reset database and bring up stack**

```bash
docker compose down -v
docker compose up -d
```
Expected: backend starts, migration runs once (grep logs for `connections_refactor_v1`).

- [ ] **Step 3: Log in and verify the LLM Providers tab is empty**

Open the frontend in a browser, log in as your usual account. The LLM Providers tab shows the empty state with "Verbindung einrichten" CTA. The API Keys tab shows only "Ollama Web Search".

- [ ] **Step 4: Create Ollama Cloud connection via wizard**

- Click "+ Connection" → Adapter card "Ollama" → Template "Ollama Cloud".
- Config Modal opens with pre-filled `url = https://ollama.com`, `max_parallel = 3`.
- Enter your Ollama Cloud key, click Test → green "ok".
- Click Speichern. Connection appears in the list with status pill `valid`.

- [ ] **Step 5: Verify model listing**

Navigate to the model browser (or persona model picker). Expect a group titled "Ollama Cloud (ollama-cloud)" populated with models.

- [ ] **Step 6: Wire a Persona and run an inference**

- Open an existing persona (which had its `model_unique_id` nulled by the migration).
- Pick a model from the new Ollama Cloud group.
- Start a chat, send a message. Confirm the response streams correctly.

- [ ] **Step 7: Create Ollama Local connection (if applicable)**

Template "Ollama Local", url `http://host.docker.internal:11434`, `max_parallel = 1`. If you run Ollama on the same host as Chatsune via Docker, adjust the URL to the network-visible address. Test + save. Verify Diagnostics panel shows `ps` + `tags` output.

- [ ] **Step 8: Delete a connection**

Delete the Ollama Local connection. Expect:
- The list refreshes (event-driven).
- Any persona that was wired to it shows the "Verbindung fehlt" banner.
- Backend logs show no errors.

- [ ] **Step 9: Web Search**

In API Keys tab, enter your Ollama Cloud key (same value) as the Ollama Web Search key, click Test → valid. Verify that enabling the Web Search tool group and asking a persona to search works end-to-end.

- [ ] **Step 10: Commit any doc or lint fixes surfaced by the smoke test**

```bash
git add -A
git commit -m "Smoke test fixes for connections refactor"
```

If nothing needed fixing, no commit.

---

## Self-Review Notes

- **Spec coverage:** all spec sections are covered (core concepts → Tasks 5-10; data model → Tasks 8, 19, 21; backend API → Tasks 11-13; events → Tasks 1-4; adapter contract → Tasks 5-6; frontend UX → Tasks 23-34; hard-cut migration → Task 21; removed code → Task 22; INSIGHTS updates → Task 35; testing posture → Task 36).
- **Placeholder scan:** no "TBD" / "fill in later" items in the code bodies; every step either contains the full content or references another specific task. Two deliberate cases where precise edits depend on local code shape (Task 15 orchestrator, Task 30 tab-badge wiring): each names the call sites to inspect and the transformation to apply.
- **Type consistency:** `ConnectionDto`, `AdapterDto`, `AdapterTemplateDto`, `ModelMetaDto`, `UserModelConfigDto` used consistently across Python (`shared/dtos/llm.py`) and TypeScript (`frontend/src/core/types/llm.ts`). Topic names consistent across backend events + FANOUT + frontend events.ts. `connection_id` is the canonical identifier throughout — `provider_id` appears only in code being deleted.

End of plan.
