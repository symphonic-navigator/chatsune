# Community Provisioning — Community Adapter + Consumer Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the consumer-side `community` adapter — a new
registered adapter in `backend/modules/llm/_adapters/` that lets a
consumer connect to a host's Homelab via `homelab://<id>` URL + an
API-Key. The adapter proxies `fetch_models` and `stream_completion`
through the `SidecarRegistry`, enforces the API-Key's model
allowlist, and exposes a `/test` endpoint. Adds a frontend adapter
view for the "Add Connection" wizard.

**Architecture:** The adapter is stateless per-request; on each call
it looks up the live `SidecarConnection` via
`get_sidecar_registry()`, verifies `homelab_id` + `api_key` via
`HomelabService.validate_consumer_access()`, and either returns the
filtered model list or yields the translated `ProviderStreamEvent`s
produced by decoded CSP frames.

**Hard rule (engine-agnostic boundary).** The adapter MUST NOT
branch on `engine.type`, `engine_family`, or any engine-specific
field of a model. The protocol abstracts all engines uniformly —
this adapter is the proof that the abstraction holds.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, FastAPI.

**Depends on:** Plan 1 (HomelabService), Plan 3 (SidecarRegistry,
SidecarConnection, CSP frames).

**Parent spec:** `docs/superpowers/specs/2026-04-16-community-provisioning-design.md` §6.

---

## File Structure

**New files:**

- `backend/modules/llm/_adapters/_community.py` — adapter class
- `backend/tests/modules/llm/adapters/test_community.py`
- `frontend/src/app/components/llm-providers/CommunityConnectionView.tsx` (or wherever existing adapter views live — grep `view_id.*ollama_http` to find the exact path)

**Modified files:**

- `backend/modules/llm/_registry.py` — register `CommunityAdapter`
- `frontend/src/core/adapters/AdapterViewRegistry.ts` (or wherever the frontend adapter-view registry lives) — register the `community` view

---

## Task 1: CommunityAdapter Skeleton

**Files:**
- Create: `backend/modules/llm/_adapters/_community.py`
- Create: `backend/tests/modules/llm/adapters/test_community.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/adapters/test_community.py`:

```python
import pytest

from backend.modules.llm._adapters._community import CommunityAdapter


def test_adapter_identity():
    assert CommunityAdapter.adapter_type == "community"
    assert CommunityAdapter.display_name == "Community"
    assert CommunityAdapter.view_id == "community"
    assert "api_key" in CommunityAdapter.secret_fields
    assert "homelab_id" not in CommunityAdapter.secret_fields


def test_adapter_has_one_template():
    tmpls = CommunityAdapter.templates()
    assert len(tmpls) == 1
    t = tmpls[0]
    assert t.required_config_fields == ["homelab_id", "api_key"]


def test_adapter_config_schema_has_two_fields():
    schema = CommunityAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"homelab_id", "api_key"}
```

- [ ] **Step 2: Run — verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_community.py -v`
Expected: module not found.

- [ ] **Step 3: Implement the skeleton**

Create `backend/modules/llm/_adapters/_community.py`:

```python
"""Consumer-side adapter for Community Provisioning (CSP/1).

This adapter is strictly engine-agnostic — no branching on engine
type is allowed anywhere in this file. If you feel the urge to do
so, the right answer is to extend CSP, not to leak engine identity
into the backend.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)


class CommunityAdapter(BaseAdapter):
    adapter_type = "community"
    display_name = "Community"
    view_id = "community"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="homelab_via_community",
                display_name="Homelab via Community",
                slug_prefix="community",
                config_defaults={"homelab_id": "", "api_key": ""},
                required_config_fields=("homelab_id", "api_key"),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="homelab_id",
                type="text",
                label="Homelab-ID",
                required=True,
                min=11,
                max=11,
            ),
            ConfigFieldHint(
                name="api_key",
                type="password",
                label="API-Key",
                required=True,
            ),
        ]

    async def fetch_models(
        self, connection: ResolvedConnection
    ) -> list[ModelMetaDto]:
        raise NotImplementedError  # Task 3

    def stream_completion(
        self,
        connection: ResolvedConnection,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError  # Task 4

    @classmethod
    def router(cls) -> APIRouter | None:
        return None  # Task 5 mounts this
```

If the exact shape of `AdapterTemplate` / `ConfigFieldHint` differs
in the current codebase, adapt to match — they are imported from
`backend/modules/llm/_adapters/_types.py`.

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_community.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_community.py backend/tests/modules/llm/adapters/test_community.py
git commit -m "Add Community adapter skeleton with identity and schema"
```

---

## Task 2: Register Adapter in `_registry.py`

**Files:**
- Modify: `backend/modules/llm/_registry.py`

- [ ] **Step 1: Add import + registry entry**

Open `backend/modules/llm/_registry.py`. Import and register:

```python
from backend.modules.llm._adapters._community import CommunityAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    # ... existing entries
    "community": CommunityAdapter,
}
```

- [ ] **Step 2: Verify it loads**

Run: `uv run python -c "from backend.modules.llm._registry import ADAPTER_REGISTRY; assert 'community' in ADAPTER_REGISTRY"`
Expected: no output, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_registry.py
git commit -m "Register CommunityAdapter in adapter registry"
```

---

## Task 3: `fetch_models` + Access Check

**Files:**
- Modify: `backend/modules/llm/_adapters/_community.py`
- Modify: `backend/tests/modules/llm/adapters/test_community.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/modules/llm/adapters/test_community.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _resolved_conn(homelab_id: str = "H1", api_key: str = "csapi_xyz"):
    rc = MagicMock()
    rc.config = {"homelab_id": homelab_id}
    rc.secrets = {"api_key": api_key}
    rc.user_id = "u2"  # the consumer, not the host
    rc.connection_id = "conn-1"
    rc.connection_slug = "alices-gpu"
    rc.display_name = "Alice's GPU"
    return rc


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_when_sidecar_offline(monkeypatch):
    from backend.modules.llm._adapters import _community

    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda hid: None),
    )
    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert out == []


@pytest.mark.asyncio
async def test_fetch_models_filters_by_allowlist(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_conn = MagicMock()
    fake_conn.rpc_list_models = AsyncMock(
        return_value=[
            {
                "slug": "llama3.2:8b", "display_name": "Llama 3.2 8B",
                "context_length": 131072, "capabilities": ["text"],
            },
            {
                "slug": "mistral:7b", "display_name": "Mistral 7B",
                "context_length": 32768, "capabilities": ["text"],
            },
        ]
    )
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda hid: fake_conn),
    )
    fake_svc = AsyncMock()
    fake_svc.validate_consumer_access_key = AsyncMock(
        return_value={"allowed_model_slugs": ["llama3.2:8b"]}
    )
    monkeypatch.setattr(
        _community, "_homelab_service", lambda: fake_svc,
    )

    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert [m.model_id for m in out] == ["llama3.2:8b"]


@pytest.mark.asyncio
async def test_fetch_models_empty_when_api_key_invalid(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_conn = MagicMock()
    fake_conn.rpc_list_models = AsyncMock(return_value=[])
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda hid: fake_conn),
    )
    fake_svc = AsyncMock()
    fake_svc.validate_consumer_access_key = AsyncMock(return_value=None)
    monkeypatch.setattr(
        _community, "_homelab_service", lambda: fake_svc,
    )

    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert out == []
```

- [ ] **Step 2: Extend HomelabService with a key-only validation helper**

In `backend/modules/llm/_homelabs.py`, add a method that looks up an
api-key by plaintext and returns the doc without needing a model
slug (the model-slug check happens per-request). Append to
`HomelabService`:

```python
    async def validate_consumer_access_key(
        self, homelab_id: str, api_key_plaintext: str
    ) -> dict | None:
        return await self._keys.find_active_by_hash(
            homelab_id=homelab_id,
            api_key_hash=hash_token(api_key_plaintext),
        )
```

- [ ] **Step 3: Implement `fetch_models`**

Replace `NotImplementedError` in `backend/modules/llm/_adapters/_community.py` with:

```python
from backend.database import get_db
from backend.modules.llm._csp._registry import get_sidecar_registry
from backend.ws.event_bus import get_event_bus


def _homelab_service():
    # Factory so tests can monkeypatch; real call just constructs per-use.
    from backend.modules.llm._homelabs import HomelabService

    return HomelabService(get_db(), get_event_bus())


class CommunityAdapter(BaseAdapter):
    # ... existing class body above ...

    async def fetch_models(
        self, connection: ResolvedConnection
    ) -> list[ModelMetaDto]:
        homelab_id = connection.config.get("homelab_id")
        api_key = (connection.secrets or {}).get("api_key")
        if not homelab_id or not api_key:
            return []
        reg = get_sidecar_registry()
        conn = reg.get(homelab_id)
        if conn is None:
            return []

        svc = _homelab_service()
        key_doc = await svc.validate_consumer_access_key(
            homelab_id=homelab_id, api_key_plaintext=api_key
        )
        if key_doc is None:
            return []
        allowlist = set(key_doc.get("allowed_model_slugs", []))

        try:
            raw_models = await conn.rpc_list_models()
        except Exception as exc:  # noqa: BLE001
            _log.warning("community.fetch_models failed: %s", exc)
            return []

        out: list[ModelMetaDto] = []
        for m in raw_models:
            slug = m.get("slug")
            if slug not in allowlist:
                continue
            caps = set(m.get("capabilities", []))
            out.append(
                ModelMetaDto(
                    connection_id=connection.connection_id,
                    connection_slug=connection.connection_slug,
                    connection_display_name=connection.display_name,
                    model_id=slug,
                    display_name=m.get("display_name", slug),
                    context_window=int(m["context_length"]),
                    supports_reasoning="reasoning" in caps,
                    supports_vision="vision" in caps,
                    supports_tool_calls="tool_calling" in caps,
                    parameter_count=None,
                    raw_parameter_count=m.get("parameter_count"),
                    quantisation_level=m.get("quantisation"),
                )
            )
        return out
```

If `ResolvedConnection.secrets` is named differently in the
codebase (e.g. `decrypted_secrets` or the secrets merged into
`config`), adjust — inspect `backend/modules/llm/_adapters/_types.py`
and the existing `_ollama_http.py` to see how secrets are accessed.

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_community.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_community.py backend/modules/llm/_homelabs.py backend/tests/modules/llm/adapters/test_community.py
git commit -m "Implement CommunityAdapter.fetch_models with allowlist filter"
```

---

## Task 4: `stream_completion` + Frame Translation

**Files:**
- Modify: `backend/modules/llm/_adapters/_community.py`
- Modify: `backend/tests/modules/llm/adapters/test_community.py`

The adapter translates CSP frames into `ProviderStreamEvent`s. The
exact `ProviderStreamEvent` subclasses live in
`backend/modules/llm/_adapters/_events.py` — inspect that module
first to see the full catalogue. Typical names:

- `ContentDelta(content: str)`
- `ThinkingDelta(reasoning: str)` or `ReasoningDelta`
- `ToolCallDelta(...)` or a similar fragment event
- `StreamDone(usage: ...)`
- `StreamError(code, message, recoverable)`
- `StreamRefused(reason)`
- `StreamAborted()`

Map:

| CSP frame | Provider event |
|---|---|
| `stream` with `delta.content` | `ContentDelta` |
| `stream` with `delta.reasoning` | reasoning-channel event |
| `stream` with `delta.tool_calls` | tool-call event |
| `stream_end(finish_reason=stop|length|tool_calls)` | `StreamDone` |
| `stream_end(finish_reason=cancelled)` | `StreamAborted` |
| `err` + `stream_end(error)` | `StreamError` |

- [ ] **Step 1: Write failing test**

Append to `test_community.py`:

```python
@pytest.mark.asyncio
async def test_stream_completion_translates_frames(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._csp._frames import (
        StreamDelta,
        StreamEndFrame,
        StreamFrame,
    )

    frames = [
        StreamFrame(id="r", delta=StreamDelta(content="He")),
        StreamFrame(id="r", delta=StreamDelta(content="llo")),
        StreamEndFrame(id="r", finish_reason="stop", usage={"total_tokens": 5}),
    ]

    async def gen():
        for f in frames:
            yield f

    fake_conn = MagicMock()

    def rpc_generate_chat(body):
        return gen()

    fake_conn.rpc_generate_chat = rpc_generate_chat

    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda hid: fake_conn),
    )
    fake_svc = AsyncMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={"allowed_model_slugs": ["llama3.2:8b"]}
    )
    monkeypatch.setattr(
        _community, "_homelab_service", lambda: fake_svc,
    )

    adapter = _community.CommunityAdapter()
    from shared.dtos.inference import CompletionRequest

    req = CompletionRequest(
        model="alices-gpu:llama3.2:8b",
        messages=[{"role": "user", "content": "hi"}],
    )
    events = []
    async for ev in adapter.stream_completion(_resolved_conn(), req):
        events.append(ev)
    # Expect two content deltas + one terminal StreamDone
    assert any(getattr(e, "content", None) == "He" for e in events)
    assert any(getattr(e, "content", None) == "llo" for e in events)
    assert events[-1].__class__.__name__ == "StreamDone"


@pytest.mark.asyncio
async def test_stream_completion_refused_when_model_not_allowed(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_conn = MagicMock()
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda hid: fake_conn),
    )
    fake_svc = AsyncMock()
    fake_svc.validate_consumer_access = AsyncMock(return_value=None)
    monkeypatch.setattr(
        _community, "_homelab_service", lambda: fake_svc,
    )

    adapter = _community.CommunityAdapter()
    from shared.dtos.inference import CompletionRequest

    req = CompletionRequest(
        model="alices-gpu:denied-model",
        messages=[{"role": "user", "content": "hi"}],
    )
    events = [ev async for ev in adapter.stream_completion(_resolved_conn(), req)]
    assert len(events) == 1
    assert events[0].__class__.__name__ in {"StreamRefused", "StreamError"}
```

- [ ] **Step 2: Implement `stream_completion`**

Replace the `NotImplementedError` in `_community.py`:

```python
    async def stream_completion(
        self,
        connection: ResolvedConnection,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        from backend.modules.llm._adapters._events import (
            ContentDelta,
            StreamAborted,
            StreamDone,
            StreamError,
            StreamRefused,
        )

        homelab_id = connection.config.get("homelab_id")
        api_key = (connection.secrets or {}).get("api_key")
        model_slug = self._extract_model_slug(request)

        if not homelab_id or not api_key or not model_slug:
            yield StreamRefused(reason="incomplete configuration")
            return

        svc = _homelab_service()
        key_doc = await svc.validate_consumer_access(
            homelab_id=homelab_id,
            api_key_plaintext=api_key,
            model_slug=model_slug,
        )
        if key_doc is None:
            yield StreamRefused(
                reason="API-Key invalid, revoked, or model not in allowlist",
            )
            return

        conn = get_sidecar_registry().get(homelab_id)
        if conn is None:
            yield StreamError(
                code="engine_unavailable",
                message="Homelab is offline.",
                recoverable=True,
            )
            return

        body = self._to_generate_chat_body(model_slug, request)
        try:
            async for frame in await conn.rpc_generate_chat(body):
                ev = self._frame_to_event(frame)
                if ev is not None:
                    yield ev
        except Exception as exc:  # noqa: BLE001
            _log.exception("community.stream_completion failed")
            yield StreamError(
                code="internal", message=str(exc), recoverable=False,
            )

    # --- private helpers ---

    @staticmethod
    def _extract_model_slug(request: CompletionRequest) -> str | None:
        # model_unique_id format is "<connection_slug>:<model_slug>"
        model_id = getattr(request, "model", None) or getattr(
            request, "model_unique_id", None
        )
        if not model_id or ":" not in model_id:
            return None
        return model_id.split(":", 1)[1]

    @staticmethod
    def _to_generate_chat_body(
        model_slug: str, request: CompletionRequest
    ) -> dict:
        payload = request.model_dump(exclude_none=True) if hasattr(request, "model_dump") else dict(request)
        return {
            "model_slug": model_slug,
            "messages": payload.get("messages", []),
            "tools": payload.get("tools"),
            "parameters": {
                k: v
                for k, v in {
                    "temperature": payload.get("temperature"),
                    "top_p": payload.get("top_p"),
                    "max_tokens": payload.get("max_tokens"),
                    "stop": payload.get("stop"),
                }.items()
                if v is not None
            },
            "options": {
                "reasoning": payload.get("reasoning", False),
            },
        }

    @staticmethod
    def _frame_to_event(frame):
        from backend.modules.llm._adapters._events import (
            ContentDelta,
            StreamAborted,
            StreamDone,
            StreamError,
        )
        from backend.modules.llm._csp._frames import (
            ErrFrame,
            StreamEndFrame,
            StreamFrame,
        )

        if isinstance(frame, StreamFrame):
            delta = frame.delta
            if delta.content is not None:
                return ContentDelta(content=delta.content)
            if delta.reasoning is not None:
                # If the events module has ReasoningDelta/ThinkingDelta, use it;
                # otherwise fold into a tagged ContentDelta. Verify names in
                # backend/modules/llm/_adapters/_events.py and use the real one.
                try:
                    from backend.modules.llm._adapters._events import (
                        ReasoningDelta,
                    )
                    return ReasoningDelta(reasoning=delta.reasoning)
                except ImportError:
                    return None
            if delta.tool_calls:
                try:
                    from backend.modules.llm._adapters._events import (
                        ToolCallDelta,
                    )
                    return ToolCallDelta(fragments=delta.tool_calls)
                except ImportError:
                    return None
            return None
        if isinstance(frame, StreamEndFrame):
            if frame.finish_reason == "cancelled":
                return StreamAborted()
            if frame.finish_reason == "error":
                return StreamError(
                    code="engine_error",
                    message="Engine error; see host logs.",
                    recoverable=True,
                )
            return StreamDone(usage=frame.usage)
        if isinstance(frame, ErrFrame):
            return StreamError(
                code=frame.code,
                message=frame.message,
                recoverable=frame.recoverable,
            )
        return None
```

The `ProviderStreamEvent` subclass names above (`ContentDelta`,
`ReasoningDelta`, `ToolCallDelta`, `StreamDone`, `StreamError`,
`StreamAborted`, `StreamRefused`) are the expected house names —
verify against `backend/modules/llm/_adapters/_events.py` and
rename uses accordingly. This is the one place where following the
existing pattern is non-negotiable (the chat stream integration
relies on those exact classes).

- [ ] **Step 3: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_community.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_community.py backend/tests/modules/llm/adapters/test_community.py
git commit -m "Implement CommunityAdapter.stream_completion with CSP frame translation"
```

---

## Task 5: Adapter Sub-Router — Test + Diagnostics

**Files:**
- Modify: `backend/modules/llm/_adapters/_community.py`

- [ ] **Step 1: Write the failing handler test**

Append to `test_community.py`:

```python
@pytest.mark.asyncio
async def test_test_endpoint_returns_model_count_and_rtt(
    authed_client, created_homelab, running_sidecar
):
    # Setup: an API-key with one slug allowed; a live sidecar serving that slug.
    # Create a consumer connection of adapter_type=community with the homelab_id and api_key.
    # POST /api/llm/connections/{id}/adapter/test → { valid: true, model_count: 1, latency_ms: int }
    ...
```

The fixtures (`running_sidecar`, `created_homelab`, `authed_client`)
must be added to `backend/tests/conftest.py`. `running_sidecar` runs
a minimal fake sidecar against the test app's `/ws/sidecar` that
responds to `list_models`. If the fixture is nontrivial, put it in
its own conftest helper and import.

- [ ] **Step 2: Implement the sub-router**

Append to `backend/modules/llm/_adapters/_community.py` (in
`CommunityAdapter`):

```python
    @classmethod
    def router(cls) -> APIRouter | None:
        from time import monotonic

        from backend.modules.llm._resolver import resolve_connection_for_user

        r = APIRouter()

        @r.post("/test")
        async def _test(
            c: ResolvedConnection = Depends(resolve_connection_for_user),
        ):
            homelab_id = c.config.get("homelab_id")
            api_key = (c.secrets or {}).get("api_key")
            if not homelab_id or not api_key:
                return {"valid": False, "error": "homelab_id or api_key missing"}
            conn = get_sidecar_registry().get(homelab_id)
            if conn is None:
                return {"valid": False, "error": "homelab offline"}
            svc = _homelab_service()
            key_doc = await svc.validate_consumer_access_key(
                homelab_id=homelab_id, api_key_plaintext=api_key
            )
            if key_doc is None:
                return {"valid": False, "error": "API-Key invalid or revoked"}
            t0 = monotonic()
            try:
                models = await conn.rpc_list_models()
            except Exception as exc:  # noqa: BLE001
                return {"valid": False, "error": f"sidecar error: {exc}"}
            latency_ms = int((monotonic() - t0) * 1000)
            allow = set(key_doc.get("allowed_model_slugs", []))
            visible = [m for m in models if m.get("slug") in allow]
            return {
                "valid": True,
                "latency_ms": latency_ms,
                "model_count": len(visible),
                "total_models_on_homelab": len(models),
                "error": None,
            }

        @r.get("/diagnostics")
        async def _diagnostics(
            c: ResolvedConnection = Depends(resolve_connection_for_user),
        ):
            conn = get_sidecar_registry().get(c.config.get("homelab_id", ""))
            if conn is None:
                return {"online": False}
            return {
                "online": True,
                "sidecar_version": conn.sidecar_version,
                "engine": conn.engine_info,
                "capabilities": sorted(conn.capabilities),
                "max_concurrent": conn.max_concurrent,
                "display_name": conn.display_name,
            }

        return r
```

- [ ] **Step 3: Run**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_community.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_community.py backend/tests/modules/llm/adapters/test_community.py
git commit -m "Add /test and /diagnostics endpoints to community adapter"
```

---

## Task 6: Frontend — CommunityConnectionView

**Files:**
- Create: `frontend/src/app/components/llm-providers/CommunityConnectionView.tsx` (path may differ — see existing adapter views)
- Modify: the frontend adapter-view registry (grep `view_id.*ollama_http` to locate)

- [ ] **Step 1: Study an existing adapter view**

Look at the existing `ollama_http` view. Note: the form layout, how
it reads/writes the connection config, how secrets are rendered
(password field with "is_set" indicator vs. plain input), how the
Test button is wired. Match the house style exactly.

- [ ] **Step 2: Implement the community view**

```tsx
// frontend/src/app/components/llm-providers/CommunityConnectionView.tsx
import { useState } from "react";

interface Props {
  connection: {
    id: string;
    slug: string;
    display_name: string;
    config: { homelab_id?: string };
    secrets: { api_key?: { is_set: boolean } };
  };
  onSave: (patch: {
    display_name?: string;
    config?: Record<string, unknown>;
    secrets?: Record<string, unknown>;
  }) => Promise<void>;
}

export function CommunityConnectionView({ connection, onSave }: Props) {
  const [homelabId, setHomelabId] = useState(connection.config.homelab_id ?? "");
  const [apiKey, setApiKey] = useState("");
  const [displayName, setDisplayName] = useState(connection.display_name);
  const [test, setTest] = useState<null | {
    valid: boolean;
    latency_ms?: number;
    model_count?: number;
    error?: string | null;
  }>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      const patch: Parameters<typeof onSave>[0] = {
        display_name: displayName,
        config: { homelab_id: homelabId.trim() },
      };
      if (apiKey) patch.secrets = { api_key: apiKey };
      await onSave(patch);
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    setTest(null);
    try {
      const res = await fetch(
        `/api/llm/connections/${connection.id}/adapter/test`,
        { method: "POST" },
      );
      setTest(await res.json());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-white/70">Display name</label>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          className="mt-1 w-full rounded bg-black/40 p-2"
        />
      </div>

      <div>
        <label className="block text-sm text-white/70">Homelab-ID</label>
        <div className="mt-1 flex items-center gap-2">
          <span className="rounded bg-black/30 px-2 py-2 font-mono text-white/50">
            homelab://
          </span>
          <input
            value={homelabId}
            onChange={(e) => setHomelabId(e.target.value)}
            placeholder="Xk7bQ2eJn9m"
            className="flex-1 rounded bg-black/40 p-2 font-mono"
            maxLength={11}
            minLength={11}
          />
        </div>
      </div>

      <div>
        <label className="block text-sm text-white/70">
          API-Key {connection.secrets.api_key?.is_set && !apiKey && <span className="ml-2 text-xs text-white/50">(set — leave blank to keep)</span>}
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="csapi_…"
          className="mt-1 w-full rounded bg-black/40 p-2 font-mono"
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          disabled={busy}
          onClick={save}
          className="rounded bg-amber-400 px-4 py-2 font-medium text-black disabled:opacity-50"
        >
          Save
        </button>
        <button
          disabled={busy}
          onClick={runTest}
          className="rounded bg-white/10 px-4 py-2 text-white disabled:opacity-50"
        >
          Test
        </button>
        {test && (
          <span
            className={`text-sm ${
              test.valid ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {test.valid
              ? `OK — ${test.model_count} model${test.model_count === 1 ? "" : "s"}, ${test.latency_ms} ms`
              : `Failed — ${test.error}`}
          </span>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Register the view**

In the adapter-view registry (find via `rg "view_id" frontend/src --type ts --type tsx -l`), add:

```typescript
import { CommunityConnectionView } from "../app/components/llm-providers/CommunityConnectionView";

export const AdapterViewRegistry = {
  // ... existing
  community: CommunityConnectionView,
};
```

- [ ] **Step 4: Build + smoke**

Run: `pnpm --dir frontend run build`
Expected: exit 0.

Manually: start the backend and frontend, log in, create a
community Connection, paste a dummy homelab-id + api-key, click
Test. Should show a friendly "homelab offline" message (no crash).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/llm-providers/CommunityConnectionView.tsx frontend/src/core/adapters/AdapterViewRegistry.ts
git commit -m "Add Community adapter view for the consumer-side connection wizard"
```

---

## Task 7: End-to-End Test

**Files:**
- Create: `backend/tests/integration/test_community_e2e.py`

- [ ] **Step 1: Minimal end-to-end fixture + test**

Create a test that:

1. Authenticates as user1 (the host).
2. POST `/api/llm/homelabs` → gets Host-Key.
3. Spawns a minimal fake sidecar in the same asyncio loop, which
   connects via TestClient's WebSocket, handshakes successfully,
   and answers `list_models` with one model.
4. POST `/api/llm/homelabs/{hid}/api-keys` with
   `allowed_model_slugs=["llama3.2:8b"]`.
5. Switches to user2 (consumer).
6. POST `/api/llm/connections` with `adapter_type="community"`,
   config = `{ homelab_id, api_key }`.
7. POST `/api/llm/connections/{conn_id}/adapter/test`.
8. Assert response: `{ valid: true, model_count: 1, ... }`.

Test code (skeleton, adapt fixtures to the existing harness):

```python
import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_community_e2e(
    app_client,
    authed_client_user1,
    authed_client_user2,
):
    # 1. Host creates homelab
    r = await authed_client_user1.post(
        "/api/llm/homelabs", json={"display_name": "Test-Lab"},
    )
    assert r.status_code == 201
    homelab = r.json()
    host_key = homelab["plaintext_host_key"]
    hid = homelab["homelab_id"]

    # 2. Fake sidecar that answers list_models
    async def run_sidecar():
        with app_client.websocket_connect(
            "/ws/sidecar", headers={"authorization": f"Bearer {host_key}"},
        ) as ws:
            ws.send_text(json.dumps({
                "type": "handshake",
                "csp_version": "1.0",
                "sidecar_version": "1.0.0",
                "engine": {"type": "ollama", "version": "0.5.0"},
                "max_concurrent_requests": 1,
                "capabilities": ["chat_streaming"],
            }))
            ws.receive_text()  # ack
            # Respond to the first list_models req
            req = json.loads(ws.receive_text())
            ws.send_text(json.dumps({
                "type": "res", "id": req["id"], "ok": True,
                "body": {
                    "models": [
                        {"slug": "llama3.2:8b", "display_name": "Llama",
                         "context_length": 131072, "capabilities": ["text"]}
                    ]
                },
            }))

    sidecar_task = asyncio.create_task(asyncio.to_thread(run_sidecar))
    await asyncio.sleep(0.2)

    # 3. Host issues API-Key with allowlist
    r = await authed_client_user1.post(
        f"/api/llm/homelabs/{hid}/api-keys",
        json={"display_name": "Bob", "allowed_model_slugs": ["llama3.2:8b"]},
    )
    assert r.status_code == 201
    api_key = r.json()["plaintext_api_key"]

    # 4. Consumer creates community Connection
    r = await authed_client_user2.post(
        "/api/llm/connections",
        json={
            "adapter_type": "community",
            "display_name": "Alices Lab",
            "slug": "alices-lab",
            "config": {"homelab_id": hid, "api_key": api_key},
        },
    )
    assert r.status_code == 201
    conn_id = r.json()["id"]

    # 5. Test the connection
    r = await authed_client_user2.post(
        f"/api/llm/connections/{conn_id}/adapter/test",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["model_count"] == 1

    await sidecar_task
```

- [ ] **Step 2: Run**

Run: `uv run pytest backend/tests/integration/test_community_e2e.py -v`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_community_e2e.py
git commit -m "Add end-to-end test for community provisioning"
```

---

## Self-Review

1. Adapter registered: `rg "\"community\"" backend/modules/llm/_registry.py` returns a hit.
2. Engine-agnostic rule upheld: `rg "engine.type|engine_family|engine_model_id" backend/modules/llm/_adapters/_community.py backend/modules/llm/_csp/` only matches the frame-model definitions, never a backend branch.
3. Access checks: model-slug → `validate_consumer_access`, key-only → `validate_consumer_access_key`. Both used in the right places.
4. `stream_completion` maps all terminal frames to a terminal event exactly once (`StreamDone`, `StreamAborted`, `StreamRefused`, or `StreamError`).
5. Frontend: `homelab://` is hardcoded as UI label, not in the data. User pastes only the 11-char id.
6. `/test` response shape matches what Task 5 documented.
7. E2E test exercises the full chain: host creates homelab → sidecar connects → host issues key → consumer adds connection → consumer tests → gets 1 model visible.
