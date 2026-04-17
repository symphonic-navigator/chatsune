# Ollama Local Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second Ollama upstream adapter (`ollama_local`) that shares all logic with `ollama_cloud` via a base class, treats Ollama Local as a global (no per-user credential) provider, surfaces a "Local Ollama" reachability pill in the topbar, and adds an admin "Invalidate caches & refresh" button.

**Architecture:** Refactor the existing `OllamaCloudAdapter` into an `OllamaBaseAdapter` template-method base class. The two concrete subclasses differ only in `provider_id`, `provider_display_name`, `_auth_headers()`, and `validate_key()`. A new `requires_key_for_listing=False` branch in handlers and orchestrator skips per-user credential lookup for global providers and passes `api_key=None` through. Reachability is derived from the model-refresh outcome and broadcast via a new `LLM_PROVIDER_STATUS_CHANGED` event plus a snapshot on connect.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / httpx / Redis / MongoDB on the backend; Vite + React + TSX + Tailwind on the frontend; WebSocket event bus; pnpm.

**Spec:** `docs/superpowers/specs/2026-04-08-ollama-local-adapter-design.md`

---

## File Structure

**New files:**
- `backend/modules/llm/_adapters/_ollama_base.py` — abstract base class with all shared HTTP, payload-build, model-mapping, and helper logic. Single responsibility: speak the Ollama HTTP API.
- `backend/modules/llm/_adapters/_ollama_local.py` — concrete adapter for local daemon (no auth, no key validation).
- `backend/modules/llm/_provider_status.py` — small helper module that reads/writes per-provider reachability state in Redis and emits diffed status events.
- `frontend/src/app/components/topbar/ProviderPill.tsx` — generic provider-reachability pill, used by Topbar.
- `frontend/src/core/llm/providerStatusStore.ts` — Zustand slice (or equivalent, mirroring existing patterns) holding `Record<providerId, {available: boolean}>`.
- `tests/llm/test_ollama_base.py` — unit tests for the base adapter (payload build, message translation, parameter parsing) using a fake httpx transport.
- `tests/llm/test_ollama_local.py` — unit tests covering the local-specific overrides.
- `tests/llm/test_provider_status.py` — unit tests for the status helper.

**Modified files:**
- `backend/modules/llm/_adapters/_ollama_cloud.py` — slimmed down to a small subclass of `OllamaBaseAdapter`.
- `backend/modules/llm/_registry.py` — register `ollama_local`, add base URL with env override.
- `backend/modules/llm/_metadata.py` — wire status tracking into `refresh_all_providers` and `get_models`.
- `backend/modules/llm/_handlers.py` — branch on `requires_key_for_listing` in `list_providers` and `list_models`; add new admin endpoint `POST /admin/refresh-providers`; add snapshot endpoint `GET /provider-status`.
- `backend/modules/llm/__init__.py` — re-export `LlmProviderStatusChangedEvent`, snapshot helper.
- `shared/topics.py` — add two new topic constants.
- `shared/events/llm.py` — add `LlmProviderStatusChangedEvent` and `LlmProviderStatusSnapshotEvent`.
- `frontend/src/app/components/topbar/Topbar.tsx` — render `<ProviderPill provider="ollama_local" label="Local Ollama" />` left of `LivePill` at both render sites.
- `frontend/src/app/components/admin-modal/ModelsTab.tsx` — add "Invalidate caches & refresh" button.
- `frontend/src/core/api/llm.ts` — add `refreshProviders()` and `getProviderStatusSnapshot()` API calls.
- `.env.example` — document `OLLAMA_LOCAL_BASE_URL`.
- `README.md` — environment-variables section.

---

## Pre-flight

- [ ] **Step 0.1: Sanity check baseline**

Run the existing backend test suite and frontend type check so we have a clean baseline before touching anything.

```bash
cd /home/chris/workspace/chatsune
uv run pytest tests/llm -q
cd frontend && pnpm tsc --noEmit
```

Expected: both pass cleanly. If anything is already broken, stop and report.

---

## Task 1: Introduce `OllamaBaseAdapter` (pure refactor, no behaviour change)

**Files:**
- Create: `backend/modules/llm/_adapters/_ollama_base.py`
- Modify: `backend/modules/llm/_adapters/_ollama_cloud.py`
- Test: `tests/llm/test_ollama_base.py`

- [ ] **Step 1.1: Write the failing test for the shared payload builder**

Create `tests/llm/test_ollama_base.py`:

```python
from shared.dtos.inference import (
    CompletionMessage,
    CompletionMessageContentPart,
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
                content=[CompletionMessageContentPart(type="text", text="hi")],
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
```

- [ ] **Step 1.2: Run the test and verify it fails for the right reason**

```bash
uv run pytest tests/llm/test_ollama_base.py -q
```

Expected: `ModuleNotFoundError: No module named 'backend.modules.llm._adapters._ollama_base'`.

- [ ] **Step 1.3: Create `_ollama_base.py` by moving the shared code out of `_ollama_cloud.py`**

Create `backend/modules/llm/_adapters/_ollama_base.py` containing:

```python
import asyncio
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
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)


def _parse_parameter_size(value: str) -> int | None:
    value = value.strip().upper()
    suffixes = {"T": 1_000_000_000_000, "B": 1_000_000_000, "M": 1_000_000, "K": 1_000}
    for suffix, multiplier in suffixes.items():
        if value.endswith(suffix):
            try:
                return int(float(value[:-1]) * multiplier)
            except (ValueError, TypeError):
                return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _format_parameter_count(value: int | None) -> str | None:
    if not value:
        return None
    if value >= 1_000_000_000_000:
        n = value / 1_000_000_000_000
        return f"{int(n)}T" if n == int(n) else f"{n:.1f}T"
    if value >= 1_000_000_000:
        n = value / 1_000_000_000
        return f"{int(n)}B" if n == int(n) else f"{n:.1f}B"
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{int(n)}M" if n == int(n) else f"{n:.1f}M"
    return None


def _build_display_name(model_name: str) -> str:
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


class OllamaBaseAdapter(BaseAdapter):
    """Shared logic for Ollama-compatible HTTP backends.

    Subclasses set ``provider_id`` / ``provider_display_name`` and override
    ``_auth_headers`` (and, where applicable, ``validate_key``).
    """

    # Subclasses MUST override
    provider_id: str = ""
    provider_display_name: str = ""

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----- subclass hooks -----

    def _auth_headers(self, api_key: str | None) -> dict:
        """Return per-request HTTP headers for upstream auth. Default: none."""
        return {}

    async def validate_key(self, api_key: str | None) -> bool:
        """Default no-op validation. Subclasses with real auth override."""
        return True

    # ----- shared implementation -----

    async def fetch_models(self) -> list[ModelMetaDto]:
        tags_resp = await self._client.get(
            f"{self.base_url}/api/tags",
            headers=self._auth_headers(None),
        )
        tags_resp.raise_for_status()
        tag_entries = tags_resp.json().get("models", [])

        sem = asyncio.Semaphore(5)

        async def _fetch_one(name: str) -> tuple[str, dict | None]:
            async with sem:
                try:
                    show_resp = await self._client.post(
                        f"{self.base_url}/api/show",
                        json={"model": name},
                        headers=self._auth_headers(None),
                    )
                    show_resp.raise_for_status()
                    return name, show_resp.json()
                except Exception:
                    _log.warning("Failed to fetch details for model '%s'; skipping.", name)
                    return name, None

        results = await asyncio.gather(
            *(_fetch_one(entry["name"]) for entry in tag_entries),
        )
        return [self._map_to_dto(name, detail) for name, detail in results if detail is not None]

    async def stream_completion(
        self,
        api_key: str | None,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        payload = self._build_chat_payload(request)
        seen_done = False
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                headers=self._auth_headers(api_key),
            ) as resp:
                if resp.status_code in (401, 403):
                    yield StreamError(error_code="invalid_api_key", message="Invalid API key")
                    return
                if resp.status_code != 200:
                    body = await resp.aread()
                    detail = body.decode("utf-8", errors="replace")[:500]
                    _log.error(
                        "Upstream returned %d for model %s: %s",
                        resp.status_code, payload.get("model"), detail,
                    )
                    yield StreamError(
                        error_code="provider_unavailable",
                        message=f"Upstream returned {resp.status_code}: {detail}",
                    )
                    return

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        _log.warning("Skipping malformed NDJSON line: %s", line)
                        continue

                    if chunk.get("done"):
                        seen_done = True
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
        except httpx.ConnectError:
            yield StreamError(error_code="provider_unavailable", message="Connection failed")
            return

        if not seen_done:
            yield StreamDone()

    @staticmethod
    def _build_chat_payload(request: CompletionRequest) -> dict:
        messages = [_translate_message(m) for m in request.messages]
        payload: dict = {
            "model": request.model,
            "messages": messages,
            "stream": True,
        }
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

    def _map_to_dto(self, model_name: str, detail: dict) -> ModelMetaDto:
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
            provider_id=self.provider_id,
            provider_display_name=self.provider_display_name,
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
```

- [ ] **Step 1.4: Slim down `_ollama_cloud.py` to inherit from the base**

Replace the entire contents of `backend/modules/llm/_adapters/_ollama_cloud.py` with:

```python
from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter


class OllamaCloudAdapter(OllamaBaseAdapter):
    """Ollama Cloud inference adapter (BYOK, /api/me validation)."""

    provider_id = "ollama_cloud"
    provider_display_name = "Ollama Cloud"
    requires_key_for_listing: bool = False

    def _auth_headers(self, api_key: str | None) -> dict:
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}

    async def validate_key(self, api_key: str) -> bool:
        """POST /api/me. Returns True on 200, False on 401/403, raises otherwise."""
        resp = await self._client.post(
            f"{self.base_url}/api/me",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        resp.raise_for_status()
        return False
```

- [ ] **Step 1.5: Run base + existing cloud tests**

```bash
uv run pytest tests/llm -q
```

Expected: all green. If the existing test suite imports any of the helpers (`_translate_message`, etc.) from `_ollama_cloud`, update those imports to point at `_ollama_base`.

- [ ] **Step 1.6: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_base.py \
        backend/modules/llm/_adapters/_ollama_cloud.py \
        tests/llm/test_ollama_base.py
git commit -m "Refactor OllamaCloudAdapter onto shared OllamaBaseAdapter"
```

---

## Task 2: Add `OllamaLocalAdapter` and register it

**Files:**
- Create: `backend/modules/llm/_adapters/_ollama_local.py`
- Modify: `backend/modules/llm/_registry.py`
- Test: `tests/llm/test_ollama_local.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/llm/test_ollama_local.py`:

```python
import pytest

from backend.modules.llm._adapters._ollama_local import OllamaLocalAdapter
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    PROVIDER_BASE_URLS,
    PROVIDER_DISPLAY_NAMES,
)


def test_local_adapter_metadata():
    adapter = OllamaLocalAdapter(base_url="http://localhost:11434")
    assert adapter.provider_id == "ollama_local"
    assert adapter.provider_display_name == "Ollama Local"
    assert adapter.requires_key_for_listing is False
    assert adapter._auth_headers(None) == {}
    assert adapter._auth_headers("anything") == {}


@pytest.mark.asyncio
async def test_local_adapter_validate_key_is_noop():
    adapter = OllamaLocalAdapter(base_url="http://localhost:11434")
    assert await adapter.validate_key(None) is True
    assert await adapter.validate_key("ignored") is True


def test_local_adapter_registered():
    assert "ollama_local" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["ollama_local"] is OllamaLocalAdapter
    assert PROVIDER_DISPLAY_NAMES["ollama_local"] == "Ollama Local"
    assert PROVIDER_BASE_URLS["ollama_local"].startswith("http://")
```

- [ ] **Step 2.2: Run test, expect import failure**

```bash
uv run pytest tests/llm/test_ollama_local.py -q
```

Expected: `ModuleNotFoundError: ... _ollama_local`.

- [ ] **Step 2.3: Create the local adapter**

Create `backend/modules/llm/_adapters/_ollama_local.py`:

```python
from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter


class OllamaLocalAdapter(OllamaBaseAdapter):
    """Ollama Local adapter — talks to a self-hosted Ollama daemon, no API key."""

    provider_id = "ollama_local"
    provider_display_name = "Ollama Local"
    requires_key_for_listing: bool = False

    def _auth_headers(self, api_key: str | None) -> dict:
        return {}

    async def validate_key(self, api_key: str | None) -> bool:
        return True
```

- [ ] **Step 2.4: Register the adapter and add the env-overridable base URL**

Replace `backend/modules/llm/_registry.py` with:

```python
import os

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from backend.modules.llm._adapters._ollama_local import OllamaLocalAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_cloud": OllamaCloudAdapter,
    "ollama_local": OllamaLocalAdapter,
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud": "Ollama Cloud",
    "ollama_local": "Ollama Local",
}

PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud": "https://ollama.com",
    "ollama_local": os.environ.get("OLLAMA_LOCAL_BASE_URL", "http://localhost:11434"),
}
```

- [ ] **Step 2.5: Run all llm tests**

```bash
uv run pytest tests/llm -q
```

Expected: green.

- [ ] **Step 2.6: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_local.py \
        backend/modules/llm/_registry.py \
        tests/llm/test_ollama_local.py
git commit -m "Add OllamaLocalAdapter and register it as a global provider"
```

---

## Task 3: Provider-status helper + new shared events

**Files:**
- Create: `backend/modules/llm/_provider_status.py`
- Modify: `shared/topics.py`, `shared/events/llm.py`
- Test: `tests/llm/test_provider_status.py`

- [ ] **Step 3.1: Add the new topic constants**

Edit `shared/topics.py`. In the `Topics` class, after the existing `LLM_*` entries, add:

```python
    LLM_PROVIDER_STATUS_CHANGED = "llm.provider_status.changed"
    LLM_PROVIDER_STATUS_SNAPSHOT = "llm.provider_status.snapshot"
```

- [ ] **Step 3.2: Add the new event classes**

Edit `shared/events/llm.py`. Append:

```python
class LlmProviderStatusChangedEvent(BaseModel):
    type: str = "llm.provider_status.changed"
    provider_id: str
    available: bool
    model_count: int
    timestamp: datetime


class LlmProviderStatusSnapshotEvent(BaseModel):
    type: str = "llm.provider_status.snapshot"
    statuses: dict[str, bool]
    timestamp: datetime
```

(`BaseModel` and `datetime` are already imported in this file.)

- [ ] **Step 3.3: Write the failing test for the status helper**

Create `tests/llm/test_provider_status.py`:

```python
from datetime import datetime, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from backend.modules.llm._provider_status import (
    get_all_statuses,
    set_status,
)


@pytest.mark.asyncio
async def test_set_and_read_status():
    redis = FakeRedis()
    changed = await set_status(redis, "ollama_local", available=True, model_count=3)
    assert changed is True  # first write is always a change

    snap = await get_all_statuses(redis, ["ollama_local", "ollama_cloud"])
    assert snap == {"ollama_local": True, "ollama_cloud": False}


@pytest.mark.asyncio
async def test_status_change_only_signals_when_flipped():
    redis = FakeRedis()
    await set_status(redis, "ollama_local", available=True, model_count=2)
    again = await set_status(redis, "ollama_local", available=True, model_count=5)
    assert again is False  # model_count alone does not flip availability

    flipped = await set_status(redis, "ollama_local", available=False, model_count=0)
    assert flipped is True
```

- [ ] **Step 3.4: Run test, expect failure**

```bash
uv run pytest tests/llm/test_provider_status.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3.5: Implement the helper**

Create `backend/modules/llm/_provider_status.py`:

```python
"""Per-provider reachability state, persisted in Redis.

Reachability is derived from model-refresh outcomes (no separate health-poll).
A provider is "available" iff its most recent refresh produced >= 1 model.
"""

import json
from datetime import datetime, timezone

from redis.asyncio import Redis

_KEY_PREFIX = "llm:provider_status:"


def _key(provider_id: str) -> str:
    return f"{_KEY_PREFIX}{provider_id}"


async def set_status(
    redis: Redis,
    provider_id: str,
    *,
    available: bool,
    model_count: int,
) -> bool:
    """Persist status. Returns True iff `available` flipped from previous value
    (or no previous value existed)."""
    raw = await redis.get(_key(provider_id))
    previous_available: bool | None = None
    if raw:
        try:
            previous_available = bool(json.loads(raw).get("available"))
        except (ValueError, TypeError):
            previous_available = None

    payload = {
        "available": available,
        "model_count": model_count,
        "last_refresh_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis.set(_key(provider_id), json.dumps(payload))

    return previous_available is None or previous_available != available


async def get_all_statuses(redis: Redis, provider_ids: list[str]) -> dict[str, bool]:
    """Return {provider_id: available} for the given provider IDs.
    Unknown providers default to False."""
    result: dict[str, bool] = {}
    for pid in provider_ids:
        raw = await redis.get(_key(pid))
        if not raw:
            result[pid] = False
            continue
        try:
            result[pid] = bool(json.loads(raw).get("available"))
        except (ValueError, TypeError):
            result[pid] = False
    return result
```

- [ ] **Step 3.6: Run the helper tests**

```bash
uv run pytest tests/llm/test_provider_status.py -q
```

Expected: green. If `fakeredis` is not yet a dev dependency, install it with `uv add --dev fakeredis` and re-run.

- [ ] **Step 3.7: Commit**

```bash
git add backend/modules/llm/_provider_status.py \
        shared/topics.py shared/events/llm.py \
        tests/llm/test_provider_status.py
git commit -m "Add per-provider reachability helper and status events"
```

---

## Task 4: Wire status tracking into model refresh

**Files:**
- Modify: `backend/modules/llm/_metadata.py`

- [ ] **Step 4.1: Update `refresh_all_providers` to record status and publish change events**

In `backend/modules/llm/_metadata.py`, add at the top of the imports (alongside the existing imports):

```python
from backend.modules.llm._provider_status import set_status
from shared.events.llm import LlmProviderStatusChangedEvent
```

Inside the `for provider_id in provider_ids:` loop in `refresh_all_providers`, replace the body so that every iteration records status and emits a flip event when needed:

```python
    for provider_id in provider_ids:
        adapter = registry[provider_id](base_url=base_urls[provider_id])
        models: list[ModelMetaDto] = []
        provider_failed = False
        try:
            models = await _fetch_and_cache_provider(provider_id, redis, adapter)
            all_models.extend(models)
        except NotImplementedError:
            _log.debug("Provider %s has not implemented fetch_models", provider_id)
            provider_failed = True
        except Exception as exc:
            _log.warning("Failed to fetch models from %s: %s", provider_id, exc)
            faulty.append(FaultyProviderDto(
                provider_id=provider_id,
                display_name=display_names.get(provider_id, provider_id),
                error_message=str(exc),
            ))
            provider_failed = True

        available = (not provider_failed) and len(models) > 0
        flipped = await set_status(
            redis, provider_id, available=available, model_count=len(models),
        )
        if flipped:
            await event_bus.publish(
                Topics.LLM_PROVIDER_STATUS_CHANGED,
                LlmProviderStatusChangedEvent(
                    provider_id=provider_id,
                    available=available,
                    model_count=len(models),
                    timestamp=datetime.now(timezone.utc),
                ),
            )
```

- [ ] **Step 4.2: Update the failure-classification block**

Below the loop, the existing `if not faulty: status = "success" ...` block must continue to use `len(faulty) < len(provider_ids)` for "partial". Leave it as-is.

- [ ] **Step 4.3: Run lints / py_compile**

```bash
uv run python -m py_compile backend/modules/llm/_metadata.py
uv run pytest tests/llm -q
```

Expected: clean compile, all tests pass.

- [ ] **Step 4.4: Commit**

```bash
git add backend/modules/llm/_metadata.py
git commit -m "Track per-provider reachability during model refresh"
```

---

## Task 5: Skip credential lookup for global providers + admin refresh endpoint + snapshot endpoint

**Files:**
- Modify: `backend/modules/llm/_handlers.py`
- Modify: `backend/modules/llm/__init__.py` (`stream_completion` wrapper)

- [ ] **Step 5.1: Add a new `is_global` class attribute on `BaseAdapter`**

`requires_key_for_listing` is about *listing*, not inference. Ollama Cloud's `/api/tags` is public (no key) but inference DOES require a key, so we cannot reuse that flag to decide whether to skip credential lookup. Introduce a new orthogonal flag.

Edit `backend/modules/llm/_adapters/_base.py`. Add a class attribute alongside `requires_key_for_listing`:

```python
class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    requires_key_for_listing: bool = True
    # If True, this provider has no per-user credential and is shared across
    # all users (e.g. a self-hosted local daemon). When set, neither listing
    # nor inference performs a credential lookup.
    is_global: bool = False

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
    # ... rest unchanged
```

Set `is_global = True` on the local adapter. Edit `backend/modules/llm/_adapters/_ollama_local.py`:

```python
class OllamaLocalAdapter(OllamaBaseAdapter):
    provider_id = "ollama_local"
    provider_display_name = "Ollama Local"
    requires_key_for_listing: bool = False
    is_global: bool = True
    # ... unchanged
```

Leave `OllamaCloudAdapter`'s flags exactly as they are (`requires_key_for_listing = False`, `is_global` defaults to `False`). Cloud's listing-without-key behaviour is unchanged; only inference still requires a credential.

- [ ] **Step 5.1b: Update `stream_completion` in `backend/modules/llm/__init__.py`**

Find the existing `stream_completion` function (around lines 47–72). Replace its body so that global providers skip the credential lookup:

```python
async def stream_completion(
    user_id: str,
    provider_id: str,
    request: CompletionRequest,
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve user's API key (if required), instantiate adapter, stream completion."""
    if provider_id not in ADAPTER_REGISTRY:
        raise LlmProviderNotFoundError(f"Unknown provider: {provider_id}")

    adapter_cls = ADAPTER_REGISTRY[provider_id]
    api_key: str | None = None

    if not adapter_cls.is_global:
        repo = CredentialRepository(get_db())
        cred = await repo.find(user_id, provider_id)
        if not cred:
            raise LlmCredentialNotFoundError(
                f"No API key configured for provider '{provider_id}'"
            )
        api_key = repo.get_raw_key(cred)

    adapter = adapter_cls(base_url=PROVIDER_BASE_URLS[provider_id])
    async for event in adapter.stream_completion(api_key, request):
        yield event
```

- [ ] **Step 5.2: Update `list_providers` in `_handlers.py` to mark global providers as configured**

In `backend/modules/llm/_handlers.py`, replace the body of `list_providers` (lines 38–62) with:

```python
@router.get("/providers")
async def list_providers(user: dict = Depends(require_active_session)):
    repo = _credential_repo()
    configured = {
        doc["provider_id"]: doc
        for doc in await repo.list_for_user(user["sub"])
    }
    result = []
    for provider_id, adapter_cls in ADAPTER_REGISTRY.items():
        requires_key = adapter_cls.requires_key_for_listing
        doc = configured.get(provider_id)
        if doc:
            dto = CredentialRepository.to_dto(doc, PROVIDER_DISPLAY_NAMES[provider_id])
            dto = dto.model_copy(update={"requires_key_for_listing": requires_key})
            result.append(dto)
        else:
            result.append(
                ProviderCredentialDto(
                    provider_id=provider_id,
                    display_name=PROVIDER_DISPLAY_NAMES[provider_id],
                    is_configured=adapter_cls.is_global,  # global providers are always "configured"
                    requires_key_for_listing=requires_key,
                )
            )
    return result
```

- [ ] **Step 5.3: Add the admin refresh endpoint**

Add at the bottom of `backend/modules/llm/_handlers.py`:

```python
@router.post("/admin/refresh-providers", status_code=200)
async def refresh_providers_handler(
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    """Wipe model caches for all providers and trigger a fresh fetch."""
    redis = get_redis()
    # Wipe per-provider model cache so removed models actually disappear.
    for provider_id in ADAPTER_REGISTRY.keys():
        await redis.delete(f"llm:models:{provider_id}")

    models = await refresh_all_providers(
        redis=redis,
        registry=ADAPTER_REGISTRY,
        base_urls=PROVIDER_BASE_URLS,
        display_names=PROVIDER_DISPLAY_NAMES,
        event_bus=event_bus,
    )
    return {"status": "ok", "total_models": len(models)}
```

You will also need to import `refresh_all_providers` at the top of `_handlers.py`:

```python
from backend.modules.llm._metadata import get_models, refresh_all_providers
```

- [ ] **Step 5.4: Add the provider-status snapshot endpoint**

Append to `_handlers.py`:

```python
@router.get("/provider-status")
async def get_provider_status(user: dict = Depends(require_active_session)):
    """Return current per-provider reachability snapshot."""
    from backend.modules.llm._provider_status import get_all_statuses

    redis = get_redis()
    statuses = await get_all_statuses(redis, list(ADAPTER_REGISTRY.keys()))
    return {"statuses": statuses}
```

- [ ] **Step 5.5: Compile and run tests**

```bash
uv run python -m py_compile backend/modules/llm/_handlers.py backend/modules/llm/__init__.py
uv run pytest tests/llm -q
```

Expected: green.

- [ ] **Step 5.6: Commit**

```bash
git add backend/modules/llm/_handlers.py \
        backend/modules/llm/__init__.py \
        backend/modules/llm/_adapters/_base.py \
        backend/modules/llm/_adapters/_ollama_local.py
git commit -m "Skip credential lookup for global providers and add admin refresh endpoint"
```

---

## Task 6: Frontend — provider-status store, snapshot fetch, and event subscription

**Files:**
- Create: `frontend/src/core/llm/providerStatusStore.ts`
- Modify: `frontend/src/core/api/llm.ts`
- Modify: wherever the websocket event bus dispatches typed events (the explorer report identified `frontend/src/core/websocket/eventBus.ts` and existing usage in `ModelsTab.tsx` via `eventBus.on(...)`)

- [ ] **Step 6.1: Add the API client functions**

Edit `frontend/src/core/api/llm.ts`. Inside the `llmApi` object, add:

```typescript
  refreshProviders: () =>
    api.post<{ status: string; total_models: number }>("/api/llm/admin/refresh-providers"),

  getProviderStatuses: () =>
    api.get<{ statuses: Record<string, boolean> }>("/api/llm/provider-status"),
```

If `api.post` does not yet support a body-less call, follow the same shape as other body-less posts in the file.

- [ ] **Step 6.2: Create the Zustand store**

Create `frontend/src/core/llm/providerStatusStore.ts`:

```typescript
import { create } from "zustand"

interface ProviderStatusState {
  statuses: Record<string, boolean>
  setStatus: (providerId: string, available: boolean) => void
  setAll: (statuses: Record<string, boolean>) => void
}

export const useProviderStatusStore = create<ProviderStatusState>((set) => ({
  statuses: {},
  setStatus: (providerId, available) =>
    set((s) => ({ statuses: { ...s.statuses, [providerId]: available } })),
  setAll: (statuses) => set({ statuses }),
}))
```

(If the project uses a different state library — check existing `useEventStore` — mirror the same pattern instead.)

- [ ] **Step 6.3: Wire snapshot + event subscription at app startup**

Find the place where the app subscribes to websocket events on connect (the Topbar.tsx report referenced `useEventStore` and `eventBus.on(...)` patterns in `ModelsTab.tsx`). Add a single bootstrap effect — the natural place is `Topbar.tsx`'s top-level component or a dedicated `App` effect — that:

1. Calls `llmApi.getProviderStatuses()` once on mount and `setAll()`s the result.
2. Subscribes to `Topics.LLM_PROVIDER_STATUS_CHANGED` and updates the matching entry.
3. Subscribes to `Topics.LLM_PROVIDER_STATUS_SNAPSHOT` (in case the backend sends one over the bus on reconnect — defensive).
4. Returns an unsubscribe.

Concrete code (place inside `Topbar.tsx` near the other `useEffect` blocks, OR — preferred — in the same module that already handles other LLM events; mirror the existing convention):

```typescript
import { useEffect } from "react"
import { useProviderStatusStore } from "@/core/llm/providerStatusStore"
import { llmApi } from "@/core/api/llm"
import { eventBus } from "@/core/websocket/eventBus"
import { Topics } from "@/shared/topics"

function useProviderStatusBootstrap() {
  const setStatus = useProviderStatusStore((s) => s.setStatus)
  const setAll = useProviderStatusStore((s) => s.setAll)

  useEffect(() => {
    let cancelled = false
    llmApi.getProviderStatuses().then((res) => {
      if (!cancelled) setAll(res.statuses)
    })

    const unsubChanged = eventBus.on(
      Topics.LLM_PROVIDER_STATUS_CHANGED,
      (event: { provider_id: string; available: boolean }) => {
        setStatus(event.provider_id, event.available)
      },
    )
    const unsubSnapshot = eventBus.on(
      Topics.LLM_PROVIDER_STATUS_SNAPSHOT,
      (event: { statuses: Record<string, boolean> }) => {
        setAll(event.statuses)
      },
    )

    return () => {
      cancelled = true
      unsubChanged()
      unsubSnapshot()
    }
  }, [setStatus, setAll])
}
```

If `Topics` is not yet exposed to the frontend as a TS const, define a local `const PROVIDER_STATUS_CHANGED = "llm.provider_status.changed"` matching the backend constant — but check the codebase first; the explorer report indicated topic constants are referenced in the frontend already.

- [ ] **Step 6.4: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 6.5: Commit**

```bash
git add frontend/src/core/llm/providerStatusStore.ts \
        frontend/src/core/api/llm.ts \
        frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Add provider status store, snapshot fetch, and event subscription"
```

---

## Task 7: Frontend — `ProviderPill` component and Topbar render

**Files:**
- Create: `frontend/src/app/components/topbar/ProviderPill.tsx`
- Modify: `frontend/src/app/components/topbar/Topbar.tsx`

- [ ] **Step 7.1: Create the `ProviderPill` component**

Create `frontend/src/app/components/topbar/ProviderPill.tsx`:

```tsx
import { useProviderStatusStore } from "@/core/llm/providerStatusStore"

interface ProviderPillProps {
  provider: string
  label: string
}

/**
 * Generic provider reachability pill. Renders a green-dot pill matching the
 * existing LivePill styling, and only renders when the provider is reachable.
 * Used today for "Local Ollama"; new providers can opt in by adding another
 * `<ProviderPill provider="..." label="..." />` to the topbar.
 */
export function ProviderPill({ provider, label }: ProviderPillProps) {
  const available = useProviderStatusStore((s) => s.statuses[provider] ?? false)
  if (!available) return null
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-white/7 bg-white/4 px-2.5 py-0.5 font-mono text-[11px] text-white/35">
      <span className="h-1.5 w-1.5 rounded-full bg-live" />
      {label}
    </span>
  )
}
```

- [ ] **Step 7.2: Render it left of `LivePill` at both render sites**

Edit `frontend/src/app/components/topbar/Topbar.tsx`:

Add the import near the top:

```tsx
import { ProviderPill } from "./ProviderPill"
```

At line ~136 (chat view) and line ~149 (other view), replace the lone `<LivePill .../>` with:

```tsx
<ProviderPill provider="ollama_local" label="Local Ollama" />
<LivePill isLive={isLive} wsStatus={wsStatus} />
```

(They will sit in the same flex container, so they automatically gain the parent's gap. If the parent has no gap, wrap them in a `<div className="flex items-center gap-2">`.)

- [ ] **Step 7.3: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 7.4: Build**

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 7.5: Commit**

```bash
git add frontend/src/app/components/topbar/ProviderPill.tsx \
        frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Render Local Ollama reachability pill in topbar"
```

---

## Task 8: Admin "Invalidate caches & refresh" button

**Files:**
- Modify: `frontend/src/app/components/admin-modal/ModelsTab.tsx`

- [ ] **Step 8.1: Add the button next to "Refresh providers"**

In `frontend/src/app/components/admin-modal/ModelsTab.tsx`, near lines 103–109 where the existing `Refresh providers` button is rendered, add a new button immediately after it:

```tsx
<button
  type="button"
  onClick={async () => {
    setLoading(true)
    setError(null)
    try {
      await llmApi.refreshProviders()
      // ModelsTab is already subscribed to LLM_MODELS_FETCH_COMPLETED, so the
      // model list refreshes itself once the backend is done.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to invalidate caches")
      setLoading(false)
    }
  }}
  disabled={loading}
  className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[11px] font-medium text-gold transition-colors hover:bg-gold/20 cursor-pointer disabled:opacity-50"
>
  Invalidate caches & refresh
</button>
```

- [ ] **Step 8.2: Type-check + build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: clean.

- [ ] **Step 8.3: Commit**

```bash
git add frontend/src/app/components/admin-modal/ModelsTab.tsx
git commit -m "Add admin button to invalidate model caches and refresh"
```

---

## Task 9: Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 9.1: Document the env var**

Append to `.env.example`:

```
# Override the base URL the backend uses to talk to a local Ollama daemon.
# Defaults to http://localhost:11434 if unset.
OLLAMA_LOCAL_BASE_URL=http://localhost:11434
```

- [ ] **Step 9.2: Update the README environment-variables section**

In `README.md`, find the environment-variables section (or the place where `.env.example` keys are documented). Add an entry:

> **`OLLAMA_LOCAL_BASE_URL`** — Optional. Base URL of a self-hosted Ollama daemon. If reachable, all of its locally pulled models become available to every authenticated user automatically as the "Ollama Local" provider — no per-user API key required. Defaults to `http://localhost:11434`. Leave unset if you do not run Ollama locally; the provider simply remains hidden in the UI.

- [ ] **Step 9.3: Commit**

```bash
git add .env.example README.md
git commit -m "Document OLLAMA_LOCAL_BASE_URL and the Ollama Local provider"
```

---

## Task 10: End-to-end verification

- [ ] **Step 10.1: Backend test suite**

```bash
uv run pytest tests/llm -q
```

Expected: green.

- [ ] **Step 10.2: Frontend type check + build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: clean.

- [ ] **Step 10.3: Manual smoke test (with local Ollama running)**

Start the stack via `docker compose up -d` (or however the project is normally started). Then:

1. Log in. Verify the topbar shows **"Local Ollama"** pill (green) IF a local Ollama daemon is reachable on the configured base URL. If not running, the pill must NOT appear and the page must work normally.
2. Open admin → Models. Click **"Invalidate caches & refresh"**. Spinner appears, model list reloads, ollama_local models (if any) appear in the list with provider id `ollama_local`.
3. Stop the local Ollama daemon. Click "Invalidate caches & refresh" again. The Local Ollama pill should disappear after the refresh completes.
4. With ollama_local models listed, pick one in the chat model picker and send a message. The completion should stream successfully without any API key in the user's settings for ollama_local.
5. Sanity-check that ollama_cloud still works exactly as before for users with a configured key.

- [ ] **Step 10.4: Final merge to master**

Per `CLAUDE.md`: "always merge to master after implementation". From the worktree branch:

```bash
git checkout master
git merge --no-ff <worktree-branch>
```

Resolve any conflicts, run the test suite once more on master, push.

---

## Notes for the implementing engineer

- **Module boundary discipline:** Do NOT import `_provider_status` from outside `backend/modules/llm/`. The frontend talks to the snapshot endpoint via the API client; other backend modules talk to it (if ever needed) through `backend/modules/llm/__init__.py`.
- **Event correctness:** `LLM_PROVIDER_STATUS_CHANGED` must only fire when `available` flips, not on every refresh. The `set_status` helper returns a `flipped` bool exactly for this.
- **No silent fallbacks:** If a frontend type or topic constant is missing, fix the missing definition rather than adding a `// @ts-ignore`.
- **British English** in comments, docstrings, identifiers, and user-visible strings (e.g. "quantisation_level", "Authorise"). The plan above already uses British spellings where possible.
- **Tests are the contract.** When in doubt about what a function should do, the test name is the spec.
