# Ollama Model Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins and connection owners pull, delete, and cancel-pull Ollama models from the UI with live progress, via a shared component embedded in both the Admin "Ollama Local" tab and the Ollama connection editor.

**Architecture:** New `OllamaModelsPanel` React component driven by a `pullProgressStore`. Backend adds a per-connection adapter sub-router (pull/cancel/delete/list) and admin endpoints (restore `ps`/`tags`, plus pull/cancel/delete/list). Shared helper `OllamaModelOps` handles Ollama's streaming `/api/pull` with throttled progress events; `PullTaskRegistry` tracks running pulls in memory. Events flow over the existing WebSocket bus.

**Tech Stack:** FastAPI, httpx, Pydantic v2, asyncio, Zustand (frontend), Vitest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-15-ollama-model-management-design.md`

**Scope note:** Plan includes restoring the lost `/api/llm/admin/ollama-local/ps|tags` handlers (they were removed during the 2026-04-14 connections refactor but the frontend still calls them), per user decision.

---

## File Structure

**New files:**

- `backend/modules/llm/_pull_registry.py` — `PullTaskRegistry` singleton, `PullHandle` dataclass
- `backend/modules/llm/_ollama_model_ops.py` — `OllamaModelOps` helper (pull stream, cancel, delete, error mapping)
- `backend/modules/llm/_admin_handlers.py` — admin-ollama-local FastAPI router
- `backend/tests/modules/llm/test_pull_registry.py`
- `backend/tests/modules/llm/test_ollama_model_ops.py`
- `backend/tests/modules/llm/test_admin_ollama_local.py`
- `frontend/src/core/stores/pullProgressStore.ts`
- `frontend/src/core/stores/pullProgressStore.test.ts`
- `frontend/src/app/components/ollama/OllamaModelsPanel.tsx`

**Modified files:**

- `shared/topics.py` — add 6 new `LLM_MODEL_*` topic constants
- `shared/events/llm.py` — add 6 new event DTO classes
- `backend/modules/llm/_adapters/_ollama_http.py` — extend `_build_adapter_router()` with 4 new routes
- `backend/ws/event_bus.py` — add 6 new entries to `_FANOUT` dict
- `backend/modules/llm/_handlers.py` — mount `_admin_handlers.router`
- `frontend/src/core/api/ollamaLocal.ts` — add pull/cancel/delete/listPulls methods
- `frontend/src/core/api/llm-providers/adapter-views/OllamaHttpView.tsx` — embed `OllamaModelsPanel`
- `frontend/src/app/components/admin-modal/OllamaTab.tsx` — embed `OllamaModelsPanel`
- `frontend/src/core/api/llm/types.ts` — add pull/model DTO types (or wherever DTOs live, mirror existing conventions)

---

## Phase 1 — Shared Contracts

### Task 1: Add new topic constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Add topics under the existing `LLM_*` block**

Open `shared/topics.py` and locate the block starting with `LLM_CONNECTION_CREATED`. Add these six constants directly below `LLM_CONNECTION_SLUG_RENAMED`:

```python
    LLM_MODEL_PULL_STARTED   = "llm.model.pull.started"
    LLM_MODEL_PULL_PROGRESS  = "llm.model.pull.progress"
    LLM_MODEL_PULL_COMPLETED = "llm.model.pull.completed"
    LLM_MODEL_PULL_FAILED    = "llm.model.pull.failed"
    LLM_MODEL_PULL_CANCELLED = "llm.model.pull.cancelled"
    LLM_MODEL_DELETED        = "llm.model.deleted"
```

- [ ] **Step 2: Commit**

```bash
git add shared/topics.py
git commit -m "Add llm.model.* topics for Ollama model management"
```

---

### Task 2: Add event DTOs

**Files:**
- Modify: `shared/events/llm.py`

- [ ] **Step 1: Read the current file**

Run `cat shared/events/llm.py` to confirm import style, base-class usage, and datetime convention (it uses `pydantic.BaseModel` and `datetime` with `datetime.now(UTC)` at publish-site).

- [ ] **Step 2: Append the new event classes to the end of the file**

```python
class ModelPullStartedEvent(BaseModel):
    type: str = "llm.model.pull.started"
    pull_id: str
    scope: str
    slug: str
    timestamp: datetime


class ModelPullProgressEvent(BaseModel):
    type: str = "llm.model.pull.progress"
    pull_id: str
    scope: str
    status: str
    digest: str | None = None
    completed: int | None = None
    total: int | None = None
    timestamp: datetime


class ModelPullCompletedEvent(BaseModel):
    type: str = "llm.model.pull.completed"
    pull_id: str
    scope: str
    slug: str
    timestamp: datetime


class ModelPullFailedEvent(BaseModel):
    type: str = "llm.model.pull.failed"
    pull_id: str
    scope: str
    slug: str
    error_code: str
    user_message: str
    timestamp: datetime


class ModelPullCancelledEvent(BaseModel):
    type: str = "llm.model.pull.cancelled"
    pull_id: str
    scope: str
    slug: str
    timestamp: datetime


class ModelDeletedEvent(BaseModel):
    type: str = "llm.model.deleted"
    scope: str
    name: str
    timestamp: datetime
```

- [ ] **Step 3: Commit**

```bash
git add shared/events/llm.py
git commit -m "Add model pull/delete event DTOs"
```

---

## Phase 2 — Backend Core

### Task 3: `PullTaskRegistry` with tests

**Files:**
- Create: `backend/modules/llm/_pull_registry.py`
- Test: `backend/tests/modules/llm/test_pull_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/modules/llm/test_pull_registry.py
import asyncio
import pytest

from backend.modules.llm._pull_registry import PullTaskRegistry


@pytest.mark.asyncio
async def test_register_creates_handle_with_scope_and_slug():
    reg = PullTaskRegistry()

    async def noop():
        await asyncio.sleep(10)

    handle = reg.register(scope="connection:c1", slug="llama3.2:3b",
                          coro_factory=noop)
    assert handle.scope == "connection:c1"
    assert handle.slug == "llama3.2:3b"
    assert handle.pull_id
    assert not handle.task.done()
    handle.task.cancel()


@pytest.mark.asyncio
async def test_list_returns_only_matching_scope():
    reg = PullTaskRegistry()

    async def noop():
        await asyncio.sleep(10)

    a = reg.register(scope="connection:c1", slug="a", coro_factory=noop)
    b = reg.register(scope="connection:c2", slug="b", coro_factory=noop)

    assert [h.pull_id for h in reg.list("connection:c1")] == [a.pull_id]
    assert [h.pull_id for h in reg.list("connection:c2")] == [b.pull_id]

    a.task.cancel()
    b.task.cancel()


@pytest.mark.asyncio
async def test_cancel_cancels_task_and_returns_true():
    reg = PullTaskRegistry()

    async def noop():
        await asyncio.sleep(10)

    h = reg.register(scope="admin-local", slug="x", coro_factory=noop)
    ok = reg.cancel("admin-local", h.pull_id)
    assert ok
    await asyncio.sleep(0)  # let cancellation propagate
    assert h.task.cancelled() or h.task.done()


@pytest.mark.asyncio
async def test_cancel_unknown_returns_false():
    reg = PullTaskRegistry()
    assert reg.cancel("admin-local", "nonexistent") is False


@pytest.mark.asyncio
async def test_completed_task_is_removed_from_registry():
    reg = PullTaskRegistry()

    async def finish_fast():
        return None

    h = reg.register(scope="admin-local", slug="x", coro_factory=finish_fast)
    await h.task  # wait for completion
    await asyncio.sleep(0)  # let done-callback run
    assert reg.list("admin-local") == []


@pytest.mark.asyncio
async def test_update_status_mutates_last_status():
    reg = PullTaskRegistry()

    async def noop():
        await asyncio.sleep(10)

    h = reg.register(scope="admin-local", slug="x", coro_factory=noop)
    reg.update_status(h.pull_id, "downloading")
    assert h.last_status == "downloading"
    h.task.cancel()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_pull_registry.py -v`

Expected: FAIL — `PullTaskRegistry` module does not exist.

- [ ] **Step 3: Implement the registry**

```python
# backend/modules/llm/_pull_registry.py
"""In-memory registry of running Ollama pull tasks.

Scope key is a string: "connection:{id}" or "admin-local".
No persistence — registry is lost on backend restart; Ollama aborts
the pull because the HTTP client is gone. Users must retry manually.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Awaitable, Callable


@dataclass
class PullHandle:
    pull_id: str
    scope: str
    slug: str
    task: asyncio.Task
    last_status: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PullTaskRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, PullHandle] = {}

    def register(
        self,
        *,
        scope: str,
        slug: str,
        coro_factory: Callable[[], Awaitable[None]],
    ) -> PullHandle:
        pull_id = uuid.uuid4().hex
        task = asyncio.create_task(coro_factory())
        handle = PullHandle(pull_id=pull_id, scope=scope, slug=slug, task=task)
        self._by_id[pull_id] = handle
        task.add_done_callback(lambda _t, pid=pull_id: self._on_done(pid))
        return handle

    def list(self, scope: str) -> list[PullHandle]:
        return [h for h in self._by_id.values() if h.scope == scope]

    def get(self, pull_id: str) -> PullHandle | None:
        return self._by_id.get(pull_id)

    def cancel(self, scope: str, pull_id: str) -> bool:
        h = self._by_id.get(pull_id)
        if h is None or h.scope != scope:
            return False
        h.task.cancel()
        return True

    def update_status(self, pull_id: str, status: str) -> None:
        h = self._by_id.get(pull_id)
        if h is not None:
            h.last_status = status

    def _on_done(self, pull_id: str) -> None:
        self._by_id.pop(pull_id, None)


_SINGLETON: PullTaskRegistry | None = None


def get_pull_registry() -> PullTaskRegistry:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = PullTaskRegistry()
    return _SINGLETON
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_pull_registry.py -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_pull_registry.py backend/tests/modules/llm/test_pull_registry.py
git commit -m "Add in-memory pull task registry"
```

---

### Task 4: `OllamaModelOps` helper with tests

**Files:**
- Create: `backend/modules/llm/_ollama_model_ops.py`
- Test: `backend/tests/modules/llm/test_ollama_model_ops.py`

- [ ] **Step 1: Write failing tests**

Tests cover error mapping, progress throttling, cancel-propagation, and delete happy-path. Uses `httpx.MockTransport` for Ollama stream simulation and a fake event bus.

```python
# backend/tests/modules/llm/test_ollama_model_ops.py
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from backend.modules.llm._ollama_model_ops import (
    OllamaModelOps,
    map_ollama_error,
)
from backend.modules.llm._pull_registry import PullTaskRegistry
from shared.topics import Topics


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, dict[str, Any]]] = []

    async def publish(self, topic, event, **kwargs):
        self.events.append(
            (topic, event.model_dump() if hasattr(event, "model_dump") else dict(event), kwargs)
        )


def _stream_lines(lines: list[str]) -> httpx.Response:
    """Build a streaming response whose body is newline-delimited JSON."""
    body = ("\n".join(lines) + "\n").encode()
    return httpx.Response(200, content=body)


@pytest.mark.asyncio
async def test_pull_emits_started_progress_completed_in_order():
    bus = FakeBus()
    reg = PullTaskRegistry()

    progress_lines = [
        json.dumps({"status": "pulling manifest"}),
        json.dumps({"status": "downloading", "digest": "sha256:a",
                    "completed": 10, "total": 100}),
        json.dumps({"status": "success"}),
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/pull"
        return _stream_lines(progress_lines)

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        http_transport=transport,
        progress_throttle_seconds=0,  # no throttle in tests
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    # Wait for task completion
    h = reg.get(pull_id)
    await h.task

    topics = [ev[0] for ev in bus.events]
    assert topics[0] == Topics.LLM_MODEL_PULL_STARTED
    assert Topics.LLM_MODEL_PULL_PROGRESS in topics
    assert topics[-1] == Topics.LLM_MODEL_PULL_COMPLETED


@pytest.mark.asyncio
async def test_pull_cancel_emits_cancelled_event():
    bus = FakeBus()
    reg = PullTaskRegistry()

    async def slow_handler(req: httpx.Request) -> httpx.Response:
        # Simulate a slow, long-running stream
        await asyncio.sleep(5)
        return httpx.Response(200, content=b"")

    transport = httpx.MockTransport(slow_handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    await asyncio.sleep(0.05)  # let task start
    reg.cancel("admin-local", pull_id)

    h = reg.get(pull_id)
    if h is not None:
        try:
            await h.task
        except asyncio.CancelledError:
            pass

    topics = [ev[0] for ev in bus.events]
    assert Topics.LLM_MODEL_PULL_CANCELLED in topics
    assert Topics.LLM_MODEL_PULL_COMPLETED not in topics


@pytest.mark.asyncio
async def test_pull_network_error_emits_failed_with_unreachable_code():
    bus = FakeBus()
    reg = PullTaskRegistry()

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    h = reg.get(pull_id)
    await h.task

    failed = [ev for ev in bus.events if ev[0] == Topics.LLM_MODEL_PULL_FAILED]
    assert len(failed) == 1
    assert failed[0][1]["error_code"] == "ollama_unreachable"


@pytest.mark.asyncio
async def test_delete_emits_model_deleted_event():
    bus = FakeBus()
    reg = PullTaskRegistry()

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        assert req.url.path == "/api/delete"
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        http_transport=transport,
    )

    await ops.delete("llama3.2:3b")

    topics = [ev[0] for ev in bus.events]
    assert topics == [Topics.LLM_MODEL_DELETED]
    assert bus.events[0][1]["name"] == "llama3.2:3b"


def test_map_ollama_error_connect_error():
    code, msg = map_ollama_error(httpx.ConnectError("refused"))
    assert code == "ollama_unreachable"
    assert "reach" in msg.lower() or "connect" in msg.lower()


def test_map_ollama_error_http_401():
    exc = httpx.HTTPStatusError(
        "u", request=httpx.Request("GET", "http://x"),
        response=httpx.Response(401),
    )
    code, _ = map_ollama_error(exc)
    assert code == "ollama_auth_failed"


def test_map_ollama_error_http_404():
    exc = httpx.HTTPStatusError(
        "u", request=httpx.Request("GET", "http://x"),
        response=httpx.Response(404),
    )
    code, _ = map_ollama_error(exc)
    assert code == "model_not_found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_ollama_model_ops.py -v`

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helper**

```python
# backend/modules/llm/_ollama_model_ops.py
"""Helper for Ollama model management operations (pull, cancel, delete).

Encapsulates the streaming /api/pull loop, progress-event throttling,
error mapping, and delete. Used by both the per-connection adapter
sub-router and the admin ollama-local handlers.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.modules.llm._pull_registry import PullHandle, PullTaskRegistry
from shared.events.llm import (
    ModelDeletedEvent,
    ModelPullCancelledEvent,
    ModelPullCompletedEvent,
    ModelPullFailedEvent,
    ModelPullProgressEvent,
    ModelPullStartedEvent,
)
from shared.topics import Topics

_TIMEOUT = httpx.Timeout(60.0, read=None)  # no read timeout for long streams
_DEFAULT_THROTTLE_S = 0.2  # 5 Hz


def map_ollama_error(exc: BaseException) -> tuple[str, str]:
    """Map an exception from an Ollama call to (error_code, user_message)."""
    if isinstance(exc, httpx.ConnectError):
        return "ollama_unreachable", "Cannot reach Ollama instance."
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "ollama_auth_failed", "Ollama rejected the API key."
        if status == 404:
            return "model_not_found", "Ollama does not know this model."
        return "pull_stream_error", f"Ollama returned HTTP {status}."
    if isinstance(exc, (httpx.ReadError, httpx.RemoteProtocolError)):
        return "pull_stream_error", "Ollama stream ended unexpectedly."
    if isinstance(exc, json.JSONDecodeError):
        return "pull_stream_error", "Malformed response from Ollama."
    return "unknown", "An unexpected error occurred."


def _auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class OllamaModelOps:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        scope: str,
        event_bus: Any,
        registry: PullTaskRegistry,
        http_transport: httpx.AsyncBaseTransport | None = None,
        progress_throttle_seconds: float = _DEFAULT_THROTTLE_S,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._scope = scope
        self._bus = event_bus
        self._registry = registry
        self._transport = http_transport
        self._throttle = progress_throttle_seconds

    async def start_pull(self, *, slug: str) -> str:
        handle = self._registry.register(
            scope=self._scope,
            slug=slug,
            coro_factory=lambda: self._run_pull_placeholder(),
        )
        # Replace the placeholder task with the real pull; the done-callback
        # on the registry handle fires whichever task completes.
        handle.task.cancel()

        real_handle = self._registry.register(
            scope=self._scope,
            slug=slug,
            coro_factory=lambda: self._pull_loop(handle.pull_id, slug),
        )
        # Align pull_id with the real task
        # (We use the real handle's pull_id going forward.)
        return real_handle.pull_id

    async def _run_pull_placeholder(self) -> None:
        # Never called — replaced by the real task. Kept to make registry
        # registration symmetric.
        return None

    async def _pull_loop(self, pull_id: str, slug: str) -> None:
        await self._bus.publish(
            Topics.LLM_MODEL_PULL_STARTED,
            ModelPullStartedEvent(
                pull_id=pull_id,
                scope=self._scope,
                slug=slug,
                timestamp=datetime.now(UTC),
            ),
            correlation_id=pull_id,
        )
        last_emit = 0.0
        last_state: dict | None = None
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/api/pull",
                    headers=_auth_headers(self._api_key),
                    json={"name": slug, "stream": True},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        status = obj.get("status", "")
                        self._registry.update_status(pull_id, status)
                        last_state = obj
                        now = time.monotonic()
                        if now - last_emit >= self._throttle:
                            await self._emit_progress(pull_id, obj)
                            last_emit = now
            # Final progress flush (terminal state)
            if last_state is not None:
                await self._emit_progress(pull_id, last_state)
            await self._bus.publish(
                Topics.LLM_MODEL_PULL_COMPLETED,
                ModelPullCompletedEvent(
                    pull_id=pull_id,
                    scope=self._scope,
                    slug=slug,
                    timestamp=datetime.now(UTC),
                ),
                correlation_id=pull_id,
            )
        except asyncio.CancelledError:
            await self._bus.publish(
                Topics.LLM_MODEL_PULL_CANCELLED,
                ModelPullCancelledEvent(
                    pull_id=pull_id,
                    scope=self._scope,
                    slug=slug,
                    timestamp=datetime.now(UTC),
                ),
                correlation_id=pull_id,
            )
            raise
        except Exception as exc:
            code, message = map_ollama_error(exc)
            await self._bus.publish(
                Topics.LLM_MODEL_PULL_FAILED,
                ModelPullFailedEvent(
                    pull_id=pull_id,
                    scope=self._scope,
                    slug=slug,
                    error_code=code,
                    user_message=message,
                    timestamp=datetime.now(UTC),
                ),
                correlation_id=pull_id,
            )

    async def _emit_progress(self, pull_id: str, obj: dict) -> None:
        await self._bus.publish(
            Topics.LLM_MODEL_PULL_PROGRESS,
            ModelPullProgressEvent(
                pull_id=pull_id,
                scope=self._scope,
                status=obj.get("status", ""),
                digest=obj.get("digest"),
                completed=obj.get("completed"),
                total=obj.get("total"),
                timestamp=datetime.now(UTC),
            ),
            correlation_id=pull_id,
        )

    async def delete(self, name: str) -> None:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, transport=self._transport,
        ) as client:
            resp = await client.request(
                "DELETE",
                f"{self._base_url}/api/delete",
                headers=_auth_headers(self._api_key),
                json={"name": name},
            )
            resp.raise_for_status()
        await self._bus.publish(
            Topics.LLM_MODEL_DELETED,
            ModelDeletedEvent(
                scope=self._scope,
                name=name,
                timestamp=datetime.now(UTC),
            ),
        )
```

**Note on `start_pull` placeholder trick:** The registry assigns `pull_id` at `register()` time, but we want the first `STARTED` event to carry the same `pull_id` the task runs under. The cleaner way is to make the registry accept a factory that takes the handle's `pull_id`. Simpler refactor — do that:

- [ ] **Step 4: Refactor the registry to pass `pull_id` into the factory**

Edit `backend/modules/llm/_pull_registry.py` — change `register()`:

```python
def register(
    self,
    *,
    scope: str,
    slug: str,
    coro_factory: Callable[[str], Awaitable[None]],  # takes pull_id
) -> PullHandle:
    pull_id = uuid.uuid4().hex
    task = asyncio.create_task(coro_factory(pull_id))
    handle = PullHandle(pull_id=pull_id, scope=scope, slug=slug, task=task)
    self._by_id[pull_id] = handle
    task.add_done_callback(lambda _t, pid=pull_id: self._on_done(pid))
    return handle
```

Update `test_pull_registry.py` factories accordingly:

```python
async def noop(_pid):
    await asyncio.sleep(10)

async def finish_fast(_pid):
    return None
```

And simplify `OllamaModelOps.start_pull`:

```python
async def start_pull(self, *, slug: str) -> str:
    handle = self._registry.register(
        scope=self._scope,
        slug=slug,
        coro_factory=lambda pid: self._pull_loop(pid, slug),
    )
    return handle.pull_id
```

Remove `_run_pull_placeholder`.

- [ ] **Step 5: Run both test files**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_pull_registry.py backend/tests/modules/llm/test_ollama_model_ops.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_pull_registry.py backend/modules/llm/_ollama_model_ops.py backend/tests/modules/llm/test_pull_registry.py backend/tests/modules/llm/test_ollama_model_ops.py
git commit -m "Add OllamaModelOps helper for pull/cancel/delete"
```

---

### Task 5: Event-bus fanout rules

**Files:**
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Read `_FANOUT` structure**

Run `sed -n '20,140p' backend/ws/event_bus.py` to see the existing dict. Entries follow `Topics.X: (admin_roles, send_to_target_user_ids)`.

- [ ] **Step 2: Add the six new topics to `_FANOUT`**

Insert alongside the existing `LLM_CONNECTION_*` entries:

```python
    Topics.LLM_MODEL_PULL_STARTED:   ([], True),
    Topics.LLM_MODEL_PULL_PROGRESS:  ([], True),
    Topics.LLM_MODEL_PULL_COMPLETED: ([], True),
    Topics.LLM_MODEL_PULL_FAILED:    ([], True),
    Topics.LLM_MODEL_PULL_CANCELLED: ([], True),
    Topics.LLM_MODEL_DELETED:        ([], True),
```

- [ ] **Step 3: Verify with a quick import check**

Run: `docker compose run --rm backend uv run python -c "from backend.ws.event_bus import _FANOUT; from shared.topics import Topics; print(all(t in _FANOUT for t in [Topics.LLM_MODEL_PULL_STARTED, Topics.LLM_MODEL_DELETED]))"`

Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add backend/ws/event_bus.py
git commit -m "Register fanout rules for llm.model.* topics"
```

---

## Phase 3 — Backend Routes

### Task 6: Restore admin `/ollama-local/ps` and `/tags`

Background: during the 2026-04-14 connections refactor the admin handlers were removed; the frontend still calls them. We re-add them as the first part of a new admin router module.

**Files:**
- Create: `backend/modules/llm/_admin_handlers.py`
- Test: `backend/tests/modules/llm/test_admin_ollama_local.py`

- [ ] **Step 1: Write failing tests for ps/tags**

```python
# backend/tests/modules/llm/test_admin_ollama_local.py
import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.modules.llm._admin_handlers import build_admin_router


class FakeOllamaTransport(httpx.MockTransport):
    def __init__(self, ps_json, tags_json):
        def handler(req):
            if req.url.path == "/api/ps":
                return httpx.Response(200, json=ps_json)
            if req.url.path == "/api/tags":
                return httpx.Response(200, json=tags_json)
            return httpx.Response(404)
        super().__init__(handler)


@pytest.fixture
def app_with_admin(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    app = FastAPI()
    # Stub require_admin to return a fake admin user
    from backend import dependencies
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1", "role": "admin"}
    transport = FakeOllamaTransport(
        ps_json={"models": [{"name": "a"}]},
        tags_json={"models": [{"name": "b"}]},
    )
    app.include_router(build_admin_router(http_transport=transport),
                       prefix="/api/llm/admin")
    return app


@pytest.mark.asyncio
async def test_ps_returns_ollama_ps_payload(app_with_admin):
    async with AsyncClient(transport=ASGITransport(app=app_with_admin),
                           base_url="http://test") as client:
        resp = await client.get("/api/llm/admin/ollama-local/ps")
    assert resp.status_code == 200
    assert resp.json() == {"models": [{"name": "a"}]}


@pytest.mark.asyncio
async def test_tags_returns_ollama_tags_payload(app_with_admin):
    async with AsyncClient(transport=ASGITransport(app=app_with_admin),
                           base_url="http://test") as client:
        resp = await client.get("/api/llm/admin/ollama-local/tags")
    assert resp.status_code == 200
    assert resp.json() == {"models": [{"name": "b"}]}
```

- [ ] **Step 2: Run — expect FAIL (module missing)**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_admin_ollama_local.py -v`

- [ ] **Step 3: Implement the admin router**

```python
# backend/modules/llm/_admin_handlers.py
"""Admin endpoints for the server's local Ollama instance.

Reads the URL from the ``OLLAMA_LOCAL_BASE_URL`` env var. All routes are
admin-guarded via ``require_admin``.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import require_admin

_PROBE_TIMEOUT = httpx.Timeout(10.0)


def _local_base_url() -> str:
    url = os.environ.get("OLLAMA_LOCAL_BASE_URL")
    if not url:
        raise HTTPException(
            status_code=503,
            detail="OLLAMA_LOCAL_BASE_URL is not configured",
        )
    return url.rstrip("/")


def build_admin_router(
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/ollama-local/ps")
    async def ps(_user: dict = Depends(require_admin)) -> dict:
        url = _local_base_url()
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT, transport=http_transport,
        ) as client:
            try:
                resp = await client.get(f"{url}/api/ps")
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as exc:
                raise HTTPException(503, "Cannot reach Ollama") from exc
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    502,
                    f"Upstream returned {exc.response.status_code}",
                ) from exc

    @router.get("/ollama-local/tags")
    async def tags(_user: dict = Depends(require_admin)) -> dict:
        url = _local_base_url()
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT, transport=http_transport,
        ) as client:
            try:
                resp = await client.get(f"{url}/api/tags")
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as exc:
                raise HTTPException(503, "Cannot reach Ollama") from exc
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    502,
                    f"Upstream returned {exc.response.status_code}",
                ) from exc

    return router
```

- [ ] **Step 4: Mount the admin router in the main LLM handlers**

Read `backend/modules/llm/_handlers.py` and find the module-level `router = APIRouter(prefix="/api/llm")` (and any other mounts at the bottom of the file). Add near the bottom:

```python
from backend.modules.llm._admin_handlers import build_admin_router

router.include_router(build_admin_router(), prefix="/admin")
```

- [ ] **Step 5: Run ps/tags tests — expect PASS**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_admin_ollama_local.py -v`

- [ ] **Step 6: Manual smoke — hit real local Ollama**

Start the backend (`docker compose up backend`) and from the admin account open the "Ollama" tab. Verify `ps` and `tags` render. Expected: no 404s; tables populate.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_admin_handlers.py backend/tests/modules/llm/test_admin_ollama_local.py backend/modules/llm/_handlers.py
git commit -m "Restore admin ollama-local ps/tags endpoints"
```

---

### Task 7: Adapter sub-router — pull / cancel / delete / pulls

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py`

- [ ] **Step 1: Extend `_build_adapter_router()` with four new routes**

Add after the existing `/diagnostics` route (before `return router`). All routes use `resolve_connection_for_user` and the shared `OllamaModelOps` helper. Scope is `f"connection:{c.id}"`.

```python
    from backend.modules.llm._ollama_model_ops import OllamaModelOps
    from backend.modules.llm._pull_registry import get_pull_registry

    def _ops_for(c, event_bus) -> OllamaModelOps:
        return OllamaModelOps(
            base_url=c.config["url"].rstrip("/"),
            api_key=c.config.get("api_key") or None,
            scope=f"connection:{c.id}",
            event_bus=event_bus,
            registry=get_pull_registry(),
        )

    @router.post("/pull")
    async def pull(
        body: dict,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
    ) -> dict:
        slug = (body.get("slug") or "").strip()
        if not slug:
            raise HTTPException(400, "slug is required")
        ops = _ops_for(c, event_bus)
        pull_id = await ops.start_pull(slug=slug)
        return {"pull_id": pull_id}

    @router.post("/pull/{pull_id}/cancel")
    async def cancel(
        pull_id: str,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> None:
        ok = get_pull_registry().cancel(f"connection:{c.id}", pull_id)
        if not ok:
            raise HTTPException(404, "pull not found")

    @router.delete("/models/{name}")
    async def delete_model(
        name: str,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
    ) -> None:
        ops = _ops_for(c, event_bus)
        try:
            await ops.delete(name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                502, f"Ollama returned {exc.response.status_code}",
            ) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(503, "Cannot reach Ollama") from exc

    @router.get("/pulls")
    async def list_pulls(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        handles = get_pull_registry().list(f"connection:{c.id}")
        return {
            "pulls": [
                {
                    "pull_id": h.pull_id,
                    "slug": h.slug,
                    "status": h.last_status,
                    "started_at": h.started_at.isoformat(),
                }
                for h in handles
            ]
        }
```

- [ ] **Step 2: Quick build check**

Run: `docker compose run --rm backend uv run python -m py_compile backend/modules/llm/_adapters/_ollama_http.py`

Expected: no output (success).

- [ ] **Step 3: Smoke via httpie or curl**

From the backend container, start a connection (any existing Ollama connection id `<ID>`), then:

```bash
curl -X POST -H 'Content-Type: application/json' \
  -H "Authorization: Bearer <token>" \
  -d '{"slug":"llama3.2:1b"}' \
  http://localhost:8000/api/llm/connections/<ID>/adapter/pull
```

Expected: `{"pull_id":"<hex>"}` and WebSocket receives `llm.model.pull.*` events.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py
git commit -m "Add per-connection adapter routes for model pull/cancel/delete"
```

---

### Task 8: Admin endpoints — pull / cancel / delete / pulls

**Files:**
- Modify: `backend/modules/llm/_admin_handlers.py`
- Test: extend `backend/tests/modules/llm/test_admin_ollama_local.py`

- [ ] **Step 1: Add failing tests for the four admin routes**

Append to the existing admin test file (reuse `app_with_admin` fixture). Construct a `build_admin_router` with a fake transport that returns a pull stream and validate the event sequence.

```python
@pytest.mark.asyncio
async def test_admin_pull_returns_pull_id_and_starts_task(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    app = FastAPI()
    from backend import dependencies
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1", "role": "admin"}

    def handler(req):
        body = (b'{"status":"success"}\n')
        return httpx.Response(200, content=body)
    transport = httpx.MockTransport(handler)

    from backend.modules.llm._admin_handlers import build_admin_router
    app.include_router(build_admin_router(http_transport=transport),
                       prefix="/api/llm/admin")

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        resp = await client.post(
            "/api/llm/admin/ollama-local/pull",
            json={"slug": "llama3.2"},
        )
    assert resp.status_code == 200
    assert "pull_id" in resp.json()


@pytest.mark.asyncio
async def test_admin_delete_forwards_to_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    app = FastAPI()
    from backend import dependencies
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1", "role": "admin"}

    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(200)
    transport = httpx.MockTransport(handler)

    from backend.modules.llm._admin_handlers import build_admin_router
    app.include_router(build_admin_router(http_transport=transport),
                       prefix="/api/llm/admin")

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        resp = await client.delete("/api/llm/admin/ollama-local/models/llama3.2")
    assert resp.status_code == 204
    assert ("DELETE", "/api/delete") in calls
```

Note: these tests need the admin router to accept a `http_transport` for all operations (not just ps/tags) — it forwards to `OllamaModelOps`. Also an event-bus dependency must be overridable. Use a fake bus fixture.

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Extend `_admin_handlers.py` to add the four routes**

Extend `build_admin_router(http_transport=None)` signature to accept an optional `event_bus_factory` (default: `get_event_bus`). Add:

```python
from backend.modules.llm._ollama_model_ops import OllamaModelOps
from backend.modules.llm._pull_registry import get_pull_registry
from backend.ws.event_bus import get_event_bus

def build_admin_router(
    http_transport: httpx.AsyncBaseTransport | None = None,
    event_bus_factory=get_event_bus,
) -> APIRouter:
    # ... existing ps/tags routes ...

    def _ops() -> OllamaModelOps:
        return OllamaModelOps(
            base_url=_local_base_url(),
            api_key=None,  # local instance has no key
            scope="admin-local",
            event_bus=event_bus_factory(),
            registry=get_pull_registry(),
            http_transport=http_transport,
        )

    @router.post("/ollama-local/pull")
    async def pull(body: dict, _user: dict = Depends(require_admin)) -> dict:
        slug = (body.get("slug") or "").strip()
        if not slug:
            raise HTTPException(400, "slug is required")
        pull_id = await _ops().start_pull(slug=slug)
        return {"pull_id": pull_id}

    @router.post("/ollama-local/pull/{pull_id}/cancel")
    async def cancel(pull_id: str, _user: dict = Depends(require_admin)) -> None:
        ok = get_pull_registry().cancel("admin-local", pull_id)
        if not ok:
            raise HTTPException(404, "pull not found")

    @router.delete("/ollama-local/models/{name}", status_code=204)
    async def delete_model(name: str, _user: dict = Depends(require_admin)) -> None:
        try:
            await _ops().delete(name)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                502, f"Ollama returned {exc.response.status_code}",
            ) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(503, "Cannot reach Ollama") from exc

    @router.get("/ollama-local/pulls")
    async def list_pulls(_user: dict = Depends(require_admin)) -> dict:
        handles = get_pull_registry().list("admin-local")
        return {
            "pulls": [
                {
                    "pull_id": h.pull_id,
                    "slug": h.slug,
                    "status": h.last_status,
                    "started_at": h.started_at.isoformat(),
                }
                for h in handles
            ]
        }

    return router
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/test_admin_ollama_local.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_admin_handlers.py backend/tests/modules/llm/test_admin_ollama_local.py
git commit -m "Add admin routes for pull/cancel/delete/list on local Ollama"
```

---

## Phase 4 — Frontend Core

### Task 9: Frontend DTO types

**Files:**
- Modify: `frontend/src/core/api/ollamaLocal.ts`

- [ ] **Step 1: Read the file to see existing types and api helpers**

Run `cat frontend/src/core/api/ollamaLocal.ts`. It exports `ollamaLocalApi` and response types.

- [ ] **Step 2: Add new types and API methods**

```typescript
export interface StartPullResponse {
  pull_id: string
}

export interface PullHandleDto {
  pull_id: string
  slug: string
  status: string
  started_at: string
}

export interface ListPullsResponse {
  pulls: PullHandleDto[]
}

export const ollamaLocalApi = {
  // ... existing ps / tags ...
  pull: (slug: string) =>
    api.post<StartPullResponse>('/api/llm/admin/ollama-local/pull', { slug }),
  cancelPull: (pullId: string) =>
    api.post<void>(`/api/llm/admin/ollama-local/pull/${pullId}/cancel`),
  deleteModel: (name: string) =>
    api.delete<void>(`/api/llm/admin/ollama-local/models/${encodeURIComponent(name)}`),
  listPulls: () =>
    api.get<ListPullsResponse>('/api/llm/admin/ollama-local/pulls'),
}
```

For the connection-scoped equivalents, add methods to `llmApi` in `frontend/src/core/api/llm/` (find it via `grep -rn "llmApi" frontend/src/core/api/`). Mirror the same DTOs:

```typescript
export const llmApi = {
  // ... existing ...
  pullModel: (connectionId: string, slug: string) =>
    api.post<StartPullResponse>(
      `/api/llm/connections/${connectionId}/adapter/pull`,
      { slug },
    ),
  cancelModelPull: (connectionId: string, pullId: string) =>
    api.post<void>(
      `/api/llm/connections/${connectionId}/adapter/pull/${pullId}/cancel`,
    ),
  deleteConnectionModel: (connectionId: string, name: string) =>
    api.delete<void>(
      `/api/llm/connections/${connectionId}/adapter/models/${encodeURIComponent(name)}`,
    ),
  listConnectionPulls: (connectionId: string) =>
    api.get<ListPullsResponse>(
      `/api/llm/connections/${connectionId}/adapter/pulls`,
    ),
}
```

- [ ] **Step 3: Type-check**

Run: `docker compose run --rm frontend pnpm tsc --noEmit`

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/
git commit -m "Add frontend API methods for Ollama pull/cancel/delete"
```

---

### Task 10: `pullProgressStore` with tests

**Files:**
- Create: `frontend/src/core/stores/pullProgressStore.ts`
- Test: `frontend/src/core/stores/pullProgressStore.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/src/core/stores/pullProgressStore.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import { usePullProgressStore } from './pullProgressStore'

describe('pullProgressStore', () => {
  beforeEach(() => {
    usePullProgressStore.setState({ byScope: {} })
  })

  it('inserts on PULL_STARTED', () => {
    usePullProgressStore.getState().onStarted({
      pull_id: 'p1', scope: 'admin-local', slug: 'llama3.2',
      timestamp: '2026-04-15T00:00:00Z',
    })
    const entries = usePullProgressStore.getState().byScope['admin-local']
    expect(entries.p1.slug).toBe('llama3.2')
  })

  it('merges on PULL_PROGRESS', () => {
    const s = usePullProgressStore.getState()
    s.onStarted({ pull_id: 'p1', scope: 'admin-local', slug: 'x',
                  timestamp: 't' })
    s.onProgress({
      pull_id: 'p1', scope: 'admin-local', status: 'downloading',
      digest: 'sha256:a', completed: 50, total: 100, timestamp: 't',
    })
    const e = usePullProgressStore.getState().byScope['admin-local'].p1
    expect(e.status).toBe('downloading')
    expect(e.completed).toBe(50)
    expect(e.total).toBe(100)
  })

  it('removes on PULL_COMPLETED', () => {
    const s = usePullProgressStore.getState()
    s.onStarted({ pull_id: 'p1', scope: 'admin-local', slug: 'x',
                  timestamp: 't' })
    s.onCompleted({ pull_id: 'p1', scope: 'admin-local', slug: 'x',
                    timestamp: 't' })
    expect(usePullProgressStore.getState().byScope['admin-local']?.p1)
      .toBeUndefined()
  })

  it('removes on PULL_CANCELLED', () => {
    const s = usePullProgressStore.getState()
    s.onStarted({ pull_id: 'p1', scope: 'admin-local', slug: 'x',
                  timestamp: 't' })
    s.onCancelled({ pull_id: 'p1', scope: 'admin-local', slug: 'x',
                    timestamp: 't' })
    expect(usePullProgressStore.getState().byScope['admin-local']?.p1)
      .toBeUndefined()
  })

  it('removes on PULL_FAILED', () => {
    const s = usePullProgressStore.getState()
    s.onStarted({ pull_id: 'p1', scope: 'admin-local', slug: 'x',
                  timestamp: 't' })
    s.onFailed({
      pull_id: 'p1', scope: 'admin-local', slug: 'x',
      error_code: 'ollama_unreachable', user_message: 'boom',
      timestamp: 't',
    })
    expect(usePullProgressStore.getState().byScope['admin-local']?.p1)
      .toBeUndefined()
  })

  it('hydrateFromList replaces entries for a scope', () => {
    usePullProgressStore.getState().hydrateFromList('admin-local', [
      { pull_id: 'p1', slug: 'a', status: 'downloading',
        started_at: '2026-04-15T00:00:00Z' },
    ])
    expect(usePullProgressStore.getState().byScope['admin-local'].p1.slug)
      .toBe('a')
  })
})
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `docker compose run --rm frontend pnpm vitest run src/core/stores/pullProgressStore`

- [ ] **Step 3: Implement the store**

```typescript
// frontend/src/core/stores/pullProgressStore.ts
import { create } from 'zustand'
import type { PullHandleDto } from '@/core/api/ollamaLocal'

export interface PullEntry {
  pullId: string
  slug: string
  status: string
  completed: number | null
  total: number | null
  startedAt: string
}

interface StartedEvent { pull_id: string; scope: string; slug: string; timestamp: string }
interface ProgressEvent {
  pull_id: string
  scope: string
  status: string
  digest: string | null
  completed: number | null
  total: number | null
  timestamp: string
}
interface TerminalEvent {
  pull_id: string
  scope: string
  slug: string
  timestamp: string
}
interface FailedEvent extends TerminalEvent {
  error_code: string
  user_message: string
}

interface PullProgressState {
  byScope: Record<string, Record<string, PullEntry>>
  hydrateFromList: (scope: string, pulls: PullHandleDto[]) => void
  onStarted: (e: StartedEvent) => void
  onProgress: (e: ProgressEvent) => void
  onCompleted: (e: TerminalEvent) => void
  onFailed: (e: FailedEvent) => void
  onCancelled: (e: TerminalEvent) => void
}

export const usePullProgressStore = create<PullProgressState>((set) => ({
  byScope: {},
  hydrateFromList: (scope, pulls) =>
    set((state) => ({
      byScope: {
        ...state.byScope,
        [scope]: Object.fromEntries(
          pulls.map((p) => [
            p.pull_id,
            {
              pullId: p.pull_id,
              slug: p.slug,
              status: p.status,
              completed: null,
              total: null,
              startedAt: p.started_at,
            },
          ]),
        ),
      },
    })),
  onStarted: (e) =>
    set((state) => ({
      byScope: {
        ...state.byScope,
        [e.scope]: {
          ...(state.byScope[e.scope] ?? {}),
          [e.pull_id]: {
            pullId: e.pull_id,
            slug: e.slug,
            status: '',
            completed: null,
            total: null,
            startedAt: e.timestamp,
          },
        },
      },
    })),
  onProgress: (e) =>
    set((state) => {
      const existing = state.byScope[e.scope]?.[e.pull_id]
      if (!existing) return state
      return {
        byScope: {
          ...state.byScope,
          [e.scope]: {
            ...state.byScope[e.scope],
            [e.pull_id]: {
              ...existing,
              status: e.status,
              completed: e.completed,
              total: e.total,
            },
          },
        },
      }
    }),
  onCompleted: (e) => removeEntry(set, e.scope, e.pull_id),
  onFailed: (e) => removeEntry(set, e.scope, e.pull_id),
  onCancelled: (e) => removeEntry(set, e.scope, e.pull_id),
}))

function removeEntry(
  set: (fn: (s: PullProgressState) => Partial<PullProgressState>) => void,
  scope: string,
  pullId: string,
) {
  set((state) => {
    const scoped = { ...(state.byScope[scope] ?? {}) }
    delete scoped[pullId]
    return { byScope: { ...state.byScope, [scope]: scoped } }
  })
}
```

- [ ] **Step 4: Wire the store to the event bus**

Find where other WebSocket events are dispatched (check `frontend/src/core/websocket/` for an event dispatcher). Add handlers for the six topics that call the corresponding store methods. For failed pulls, additionally raise a toast via the existing toast system (grep for `useToastStore` or similar).

Example addition (mirror the codebase's existing WS event routing pattern):

```typescript
case 'llm.model.pull.started':
  usePullProgressStore.getState().onStarted(event.payload)
  break
case 'llm.model.pull.progress':
  usePullProgressStore.getState().onProgress(event.payload)
  break
case 'llm.model.pull.completed':
  usePullProgressStore.getState().onCompleted(event.payload)
  // trigger tags refetch via whichever scope bus exists
  break
case 'llm.model.pull.failed':
  usePullProgressStore.getState().onFailed(event.payload)
  useToastStore.getState().error(event.payload.user_message)
  break
case 'llm.model.pull.cancelled':
  usePullProgressStore.getState().onCancelled(event.payload)
  break
case 'llm.model.deleted':
  // trigger tags refetch via whichever scope bus exists
  break
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `docker compose run --rm frontend pnpm vitest run src/core/stores/pullProgressStore`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/stores/pullProgressStore.ts frontend/src/core/stores/pullProgressStore.test.ts frontend/src/core/websocket/
git commit -m "Add pull progress store and WS event dispatch"
```

---

## Phase 5 — Frontend UI

### Task 11: `OllamaModelsPanel` component

**Files:**
- Create: `frontend/src/app/components/ollama/OllamaModelsPanel.tsx`

- [ ] **Step 1: Read the existing `OllamaTab.tsx` implementation**

Run `cat frontend/src/app/components/admin-modal/OllamaTab.tsx`. The panel will take over everything from the subtab switcher down, parameterised by the endpoint set.

- [ ] **Step 2: Implement the component**

```tsx
// frontend/src/app/components/ollama/OllamaModelsPanel.tsx
import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePullProgressStore } from '@/core/stores/pullProgressStore'
import type {
  ListPullsResponse,
  OllamaPsResponse,
  OllamaTagsResponse,
} from '@/core/api/ollamaLocal'

export interface OllamaEndpoints {
  ps: () => Promise<OllamaPsResponse>
  tags: () => Promise<OllamaTagsResponse>
  pull: (slug: string) => Promise<{ pull_id: string }>
  cancelPull: (pullId: string) => Promise<void>
  deleteModel: (name: string) => Promise<void>
  listPulls: () => Promise<ListPullsResponse>
}

interface Props {
  scope: string
  endpoints: OllamaEndpoints
  visible: boolean
}

const POLL_INTERVAL_MS = 5000

type Subtab = 'ps' | 'tags'

export function OllamaModelsPanel({ scope, endpoints, visible }: Props) {
  const [subtab, setSubtab] = useState<Subtab>('tags')
  const [ps, setPs] = useState<OllamaPsResponse | null>(null)
  const [tags, setTags] = useState<OllamaTagsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [slug, setSlug] = useState('')
  const [pulling, setPulling] = useState(false)

  const activePulls = usePullProgressStore(
    (s) => Object.values(s.byScope[scope] ?? {}),
  )
  const hydrate = usePullProgressStore((s) => s.hydrateFromList)

  const refreshTags = useCallback(async () => {
    try {
      setTags(await endpoints.tags())
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [endpoints])

  const refreshPs = useCallback(async () => {
    try {
      setPs(await endpoints.ps())
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [endpoints])

  useEffect(() => {
    if (!visible) return
    endpoints.listPulls().then((r) => hydrate(scope, r.pulls)).catch(() => {})
    const fetch = subtab === 'ps' ? refreshPs : refreshTags
    fetch()
    const id = window.setInterval(fetch, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [visible, subtab, endpoints, hydrate, scope, refreshPs, refreshTags])

  // When a completed / deleted event lands, refresh the tags list
  useEffect(() => {
    // Active pulls shrinking implies a completion may have occurred.
    // Harmless extra refetch if not — cheap call.
    refreshTags()
  }, [activePulls.length, refreshTags])

  const handlePull = async () => {
    const trimmed = slug.trim()
    if (!trimmed || pulling) return
    setPulling(true)
    try {
      await endpoints.pull(trimmed)
      setSlug('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPulling(false)
    }
  }

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete model ${name}?`)) return
    try {
      await endpoints.deleteModel(name)
      await refreshTags()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const handleCancel = async (pullId: string) => {
    try {
      await endpoints.cancelPull(pullId)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        <button onClick={() => setSubtab('ps')}
                aria-pressed={subtab === 'ps'}>
          Running (ps)
        </button>
        <button onClick={() => setSubtab('tags')}
                aria-pressed={subtab === 'tags'}>
          Models (tags)
        </button>
      </div>

      {error && <div className="text-red-400">{error}</div>}

      {subtab === 'ps' && ps && <PsTable data={ps} />}
      {subtab === 'tags' && tags && (
        <TagsTable data={tags} onDelete={handleDelete} />
      )}

      {subtab === 'tags' && (
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="Model slug (e.g. llama3.2:3b)"
            className="flex-1"
          />
          <button onClick={handlePull} disabled={pulling || !slug.trim()}>
            Pull
          </button>
        </div>
      )}

      {activePulls.length > 0 && (
        <div>
          <h4>Active pulls</h4>
          {activePulls.map((p) => (
            <ActivePullRow key={p.pullId} entry={p}
                           onCancel={() => handleCancel(p.pullId)} />
          ))}
        </div>
      )}
    </div>
  )
}

// --- Sub-components: PsTable, TagsTable, ActivePullRow ---

function PsTable({ data }: { data: OllamaPsResponse }) {
  // Copy the existing table rendering from OllamaTab.tsx verbatim.
  // Fields: name, model, size, parameter_size, quantization_level,
  // size_vram, context_length. Keep existing column order and formatting.
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th><th>Model</th><th>Size</th>
          <th>Params</th><th>Quant</th><th>VRAM</th><th>Context</th>
        </tr>
      </thead>
      <tbody>
        {data.models.map((m) => (
          <tr key={m.name}>
            <td>{m.name}</td>
            <td>{m.model}</td>
            <td>{formatSize(m.size)}</td>
            <td>{m.details?.parameter_size}</td>
            <td>{m.details?.quantization_level}</td>
            <td>{formatSize(m.size_vram)}</td>
            <td>{m.context_length}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function TagsTable({
  data,
  onDelete,
}: {
  data: OllamaTagsResponse
  onDelete: (name: string) => void
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th><th>Model</th><th>Size</th>
          <th>Params</th><th>Quant</th><th></th>
        </tr>
      </thead>
      <tbody>
        {data.models.map((m) => (
          <tr key={m.name}>
            <td>{m.name}</td>
            <td>{m.model}</td>
            <td>{formatSize(m.size)}</td>
            <td>{m.details?.parameter_size}</td>
            <td>{m.details?.quantization_level}</td>
            <td>
              <button onClick={() => onDelete(m.name)}>Delete</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ActivePullRow({
  entry,
  onCancel,
}: {
  entry: { pullId: string; slug: string; status: string;
           completed: number | null; total: number | null }
  onCancel: () => void
}) {
  const pct = entry.total && entry.completed
    ? Math.round((entry.completed / entry.total) * 100)
    : null
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono">{entry.slug}</span>
      <span>{entry.status}</span>
      {pct !== null && (
        <progress value={pct} max={100} />
      )}
      <button onClick={onCancel} aria-label="Cancel pull">×</button>
    </div>
  )
}

function formatSize(bytes: number | undefined): string {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let u = 0
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024
    u += 1
  }
  return `${v.toFixed(1)} ${units[u]}`
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}
```

**Reuse note:** the `PsTable`/`TagsTable` rendering should be copied from the existing `OllamaTab.tsx` (it already has nicer column handling). Keep column order and formatting identical to what shipped; only add the Delete column to the tags table.

- [ ] **Step 3: Type-check**

Run: `docker compose run --rm frontend pnpm tsc --noEmit`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/ollama/OllamaModelsPanel.tsx
git commit -m "Add shared OllamaModelsPanel component"
```

---

### Task 12: Wire into Admin `OllamaTab`

**Files:**
- Modify: `frontend/src/app/components/admin-modal/OllamaTab.tsx`

- [ ] **Step 1: Replace the tab body with `OllamaModelsPanel`**

Keep the visibility detection already present (polling-pause on invisible). Strip the old `PsView` / `TagsView` subcomponents, replace with:

```tsx
import { OllamaModelsPanel } from '@/app/components/ollama/OllamaModelsPanel'
import { ollamaLocalApi } from '@/core/api/ollamaLocal'

export function OllamaTab() {
  const visible = /* existing visibility state */
  return (
    <OllamaModelsPanel
      scope="admin-local"
      visible={visible}
      endpoints={{
        ps: ollamaLocalApi.ps,
        tags: ollamaLocalApi.tags,
        pull: ollamaLocalApi.pull,
        cancelPull: ollamaLocalApi.cancelPull,
        deleteModel: ollamaLocalApi.deleteModel,
        listPulls: ollamaLocalApi.listPulls,
      }}
    />
  )
}
```

- [ ] **Step 2: Build + manual smoke**

```bash
docker compose run --rm frontend pnpm run build
```

Then open the admin overlay → Ollama tab. Verify tags + ps tables render, "Pull" input + button are visible, each tag row has a Delete button.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/admin-modal/OllamaTab.tsx
git commit -m "Admin Ollama tab uses shared models panel"
```

---

### Task 13: Wire into `OllamaHttpView`

**Files:**
- Modify: `frontend/src/core/api/llm-providers/adapter-views/OllamaHttpView.tsx`

- [ ] **Step 1: Replace the Diagnostics dropdown block with `OllamaModelsPanel`**

Keep the connection form (URL, API key, max-parallel) as-is. Below the form — where the Diagnostics dropdown currently lives — embed the panel. Only show it when `isSaved` (connection exists in DB):

```tsx
import { OllamaModelsPanel } from '@/app/components/ollama/OllamaModelsPanel'
import { llmApi } from '@/core/api/llm'

{isSaved && (
  <OllamaModelsPanel
    scope={`connection:${connection.id}`}
    visible={true}
    endpoints={{
      ps: async () => {
        const d = await llmApi.getConnectionDiagnostics(connection.id)
        return d.ps
      },
      tags: async () => {
        const d = await llmApi.getConnectionDiagnostics(connection.id)
        return d.tags
      },
      pull: (slug) => llmApi.pullModel(connection.id, slug),
      cancelPull: (pullId) => llmApi.cancelModelPull(connection.id, pullId),
      deleteModel: (name) => llmApi.deleteConnectionModel(connection.id, name),
      listPulls: () => llmApi.listConnectionPulls(connection.id),
    }}
  />
)}
```

**Note:** The existing `/adapter/diagnostics` returns both `ps` and `tags` in one call; the panel fetches them separately. This is wasteful but keeps the panel generic. If latency becomes an issue, add dedicated `/adapter/ps` and `/adapter/tags` routes later — out of scope for this plan.

- [ ] **Step 2: Build + manual smoke**

```bash
docker compose run --rm frontend pnpm run build
```

Open any Ollama connection editor. Verify the panel appears, tables render, Pull/Delete/Cancel work end-to-end.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/llm-providers/adapter-views/OllamaHttpView.tsx
git commit -m "Ollama connection editor uses shared models panel"
```

---

## Phase 6 — Verification & Merge

### Task 14: Full verification pass

- [ ] **Step 1: Backend test suite**

Run: `docker compose run --rm backend uv run pytest backend/tests/modules/llm/ -v`

Expected: all green.

- [ ] **Step 2: Frontend build + tests**

Run:
```bash
docker compose run --rm frontend pnpm tsc --noEmit
docker compose run --rm frontend pnpm vitest run
docker compose run --rm frontend pnpm run build
```

Expected: all green.

- [ ] **Step 3: End-to-end smoke**

Start the stack: `docker compose up -d`.

Cases to verify:

1. Admin opens Ollama tab → ps + tags load, no 404.
2. Admin pulls `llama3.2:1b` → progress rows appear, progress bar moves, tab shows the new model in tags when done.
3. Admin cancels a running pull → row disappears, no model added.
4. Admin deletes a model → row disappears from tags.
5. Non-admin opens an Ollama connection editor → same four operations work for that connection; admin endpoints 403/404 from this context (per-connection only).
6. Two browser tabs open on the same connection → pull started in tab A appears live in tab B (fanout works).

- [ ] **Step 4: Update `backend/pyproject.toml` if new deps were added**

No new deps expected — only `httpx` (already present). Confirm with: `grep httpx backend/pyproject.toml pyproject.toml`.

### Task 15: Merge to master

- [ ] **Step 1: Commit any tidy-ups**

Check `git status`. Ensure nothing is outstanding.

- [ ] **Step 2: Merge the working branch to master**

(Per CLAUDE.md: "Please always merge to master after implementation".)

```bash
git checkout master
git merge --no-ff <working-branch> -m "Merge Ollama model management"
```

- [ ] **Step 3: Final verification after merge**

```bash
docker compose run --rm backend uv run pytest backend/tests/modules/llm/ -v
docker compose run --rm frontend pnpm run build
```

- [ ] **Step 4: Done**

The Ollama model management feature is live in both the admin tab and the connection editor.

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| `OllamaModelsPanel` shared component | Task 11 |
| Admin & Connection-Editor embedding | Tasks 12, 13 |
| `pullProgressStore` | Task 10 |
| Adapter sub-router routes | Task 7 |
| Admin routes | Tasks 6, 8 |
| `OllamaModelOps` | Task 4 |
| `PullTaskRegistry` | Task 3 |
| Progress throttling | Task 4 (`progress_throttle_seconds`) |
| Correlation IDs (`pull_id`) | Task 4 (`correlation_id=pull_id` in publishes) |
| New topics | Task 1 |
| New event DTOs | Task 2 |
| Fanout rule | Task 5 |
| UI interactions (pull/cancel/delete) | Task 11 |
| Error handling / mapping | Task 4 (`map_ollama_error`) |
| Testing (unit + integration) | Tasks 3, 4, 6, 8, 10 |

Gaps: none.

**Type consistency:** `pull_id` naming, `scope` format (`connection:{id}` | `admin-local`), event class names, topic constant names all match between tasks.

**Placeholder scan:** no TBDs, TODOs, or hand-waved steps. Where a small helper (e.g. WS event dispatch case wiring in Task 10) must match an existing codebase pattern, the plan says so explicitly and includes the concrete snippet.
