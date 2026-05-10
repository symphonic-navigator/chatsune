# MCP Streamable HTTP — Session Lifecycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Hard constraint:** Do NOT merge to master, do NOT push, do NOT switch branches. The orchestrator handles branch transitions and merges between tasks.

**Goal:** Make Chatsune compatible with FastMCP-default servers by implementing the MCP Streamable HTTP three-step session lifecycle (`initialize` + `notifications/initialized` + `Mcp-Session-Id` header) on backend executor, backend proxy routes, and frontend `mcpClient.ts`.

**Architecture:** Per-WebSocket-session state on `GatewayHandle.session_id` (backend inference path); per-HTTP-request lifecycle in proxy routes; in-memory store keyed by canonical URL in `mcpStore` (frontend local tier). Stateless servers auto-detected via absence of `Mcp-Session-Id` response header. 404 on tool-call → re-initialise + retry once. Concurrency via `asyncio.Lock` on backend, in-flight Promise dedup on frontend.

**Tech Stack:** Python 3.12 + httpx (async streaming), Pydantic v2, asyncio.Lock; TypeScript + Vite + React + Zustand; pytest + Vitest.

**Spec:** [`devdocs/specs/2026-05-10-mcp-streamable-http-session-lifecycle-design.md`](../specs/2026-05-10-mcp-streamable-http-session-lifecycle-design.md)

**Branch:** `feat/mcp-streamable-http-session-lifecycle` (already created at plan time)

---

## File Structure

**Backend — modify**
- `backend/modules/tools/_mcp_registry.py` — extend `GatewayHandle` with `session_id` and `init_lock`.
- `backend/modules/tools/_mcp_executor.py` — add `initialise()`, `_NullAsyncLock`, `MCP_PROTOCOL_VERSION`, `_client_version()`; extend `call_tool()` and `discover_tools()` with `session_id` parameter; add 404-retry logic; add `*_oneshot` helpers.
- `backend/modules/tools/_mcp_discovery.py` — `_discover_single_gateway` calls `initialise` first, stashes session_id on the returned handle.
- `backend/modules/tools/__init__.py` — at the inference call site (line 227), pass `session_id`, `on_session_refresh`, `init_lock` to `call_tool`.
- `backend/modules/user/_handlers.py` — proxy routes use `*_oneshot` helpers.

**Backend — create**
- `backend/tests/modules/tools/__init__.py`
- `backend/tests/modules/tools/test_mcp_executor_initialise.py`
- `backend/tests/modules/tools/test_mcp_executor_call_tool.py`
- `backend/tests/modules/tools/test_mcp_executor_discover_tools.py`
- `backend/tests/modules/tools/test_mcp_executor_oneshot.py`
- `backend/tests/modules/tools/test_mcp_discovery_lifecycle.py`
- `backend/tests/modules/tools/test_gateway_handle_lock.py`

**Frontend — modify**
- `frontend/src/features/mcp/mcpStore.ts` — add `sessions` slice, `setSession` / `clearSession` / `getSession` actions; clear-on-edit / clear-on-delete in existing mutator paths.
- `frontend/src/features/mcp/mcpClient.ts` — add `MCP_PROTOCOL_VERSION`, `APP_VERSION`, `ensureSession`, `doInitialise`, `readJsonRpcResponse`; rewrap `mcpToolsList` and `mcpToolsCall` with lifecycle.

**Frontend — modify (tests)**
- `frontend/src/features/mcp/__tests__/mcpClient.test.ts` — extend with lifecycle tests.
- `frontend/src/features/mcp/__tests__/mcpStore.test.ts` — extend with session-slice tests.

**Conventions referenced**
- Backend pytest from host: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/tools/...` (see memory `pytest_rootdir_quirk`).
- Frontend build check: `pnpm run build` (not just `tsc --noEmit`, see memory `frontend_build_check`).
- DB-using test files are excluded on host (memory `db_tests_on_host`); tests added in this plan use only mocked `httpx` and do not touch MongoDB.

---

## Task 1: Extend GatewayHandle with session lifecycle state

**Files:**
- Modify: `backend/modules/tools/_mcp_registry.py`
- Create: `backend/tests/modules/tools/__init__.py`
- Create: `backend/tests/modules/tools/test_gateway_handle_lock.py`

- [ ] **Step 1: Create test directory init**

Create `backend/tests/modules/tools/__init__.py` as an empty file.

- [ ] **Step 2: Write failing test for new fields**

Create `backend/tests/modules/tools/test_gateway_handle_lock.py`:

```python
"""GatewayHandle session-lifecycle field tests."""

import asyncio

import pytest

from backend.modules.tools._mcp_registry import GatewayHandle


def _make_handle(**overrides):
    defaults = dict(
        id="gw-1",
        name="ns",
        url="http://example.com/mcp",
        api_key=None,
        tier="admin",
        tool_definitions=[],
    )
    defaults.update(overrides)
    return GatewayHandle(**defaults)


def test_gateway_handle_defaults_session_id_to_none():
    h = _make_handle()
    assert h.session_id is None


def test_gateway_handle_accepts_explicit_session_id():
    h = _make_handle(session_id="abc-123")
    assert h.session_id == "abc-123"


def test_gateway_handle_init_lock_is_asyncio_lock():
    h = _make_handle()
    assert isinstance(h.init_lock, asyncio.Lock)


def test_gateway_handle_init_locks_are_independent_across_handles():
    a = _make_handle(id="a")
    b = _make_handle(id="b")
    assert a.init_lock is not b.init_lock


@pytest.mark.asyncio
async def test_gateway_handle_init_lock_serialises():
    h = _make_handle()
    order: list[str] = []

    async def critical(label: str, hold: float):
        async with h.init_lock:
            order.append(f"{label}-enter")
            await asyncio.sleep(hold)
            order.append(f"{label}-exit")

    await asyncio.gather(critical("A", 0.02), critical("B", 0.01))
    # A acquires first, B waits — strict interleaving
    assert order == ["A-enter", "A-exit", "B-enter", "B-exit"]
```

- [ ] **Step 3: Run test to verify failure**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_gateway_handle_lock.py -v
```

Expected: errors / failures (`AttributeError: 'GatewayHandle' object has no attribute 'session_id'`).

- [ ] **Step 4: Add fields to `GatewayHandle`**

Edit `backend/modules/tools/_mcp_registry.py`. Replace the existing dataclass definition with:

```python
"""Per-connection MCP tool registry — holds discovered gateway tools for one session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from shared.dtos.inference import ToolDefinition


@dataclass
class GatewayHandle:
    """One connected MCP gateway with its discovered tools.

    The ``session_id`` and ``init_lock`` fields support the MCP Streamable
    HTTP session lifecycle (see INS-044). They are populated for backend-
    executed gateways (admin / remote) by ``_mcp_discovery``. For
    ``tier='local'`` gateways the frontend manages session state itself
    and these fields stay at their defaults.
    """

    id: str
    name: str  # = namespace
    url: str
    api_key: str | None
    tier: Literal["admin", "remote", "local"]
    tool_definitions: list[ToolDefinition]
    server_tools: dict[str, list[ToolDefinition]] = field(default_factory=dict)
    collisions: list[str] = field(default_factory=list)
    session_id: str | None = None
    init_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

The remainder of the file (`SessionMcpRegistry`) is unchanged.

- [ ] **Step 5: Run test to verify pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_gateway_handle_lock.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Run py_compile sanity check**

```bash
uv run python -m py_compile backend/modules/tools/_mcp_registry.py
```

Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/tools/_mcp_registry.py \
  backend/tests/modules/tools/__init__.py \
  backend/tests/modules/tools/test_gateway_handle_lock.py
git commit -m "Add session_id and init_lock to GatewayHandle"
```

---

## Task 2: Add MCP_PROTOCOL_VERSION constant and `_client_version` helper

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py`

- [ ] **Step 1: Add constants and helper at top of `_mcp_executor.py`**

Insert after the `_REQUEST_ID_COUNTER = 0` line (~line 13) and before `_next_request_id`:

```python
MCP_PROTOCOL_VERSION = "2025-06-18"


def _client_version() -> str:
    """Resolve the version string sent in MCP `clientInfo`.

    Tries Docker package name first (``chatsune-backend``), falls back
    to host dev package (``chatsune``), then ``"unknown"``. Resolved
    once at import time — version metadata does not change at runtime.
    """
    from importlib.metadata import PackageNotFoundError, version

    for name in ("chatsune-backend", "chatsune"):
        try:
            return version(name)
        except PackageNotFoundError:
            continue
    return "unknown"


_CLIENT_VERSION = _client_version()
```

- [ ] **Step 2: Run py_compile sanity check**

```bash
uv run python -m py_compile backend/modules/tools/_mcp_executor.py
```

Expected: no output.

- [ ] **Step 3: Verify the version resolves at import**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run python -c \
  "from backend.modules.tools._mcp_executor import _CLIENT_VERSION, MCP_PROTOCOL_VERSION; \
   print(repr(_CLIENT_VERSION), repr(MCP_PROTOCOL_VERSION))"
```

Expected: prints something like `'0.1.0' '2025-06-18'` (or `'unknown' '2025-06-18'` if package metadata is missing in the dev environment — both fine).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py
git commit -m "Add MCP_PROTOCOL_VERSION constant and _client_version helper"
```

---

## Task 3: Implement `McpExecutor.initialise()` (three-step handshake)

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py`
- Create: `backend/tests/modules/tools/test_mcp_executor_initialise.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/tools/test_mcp_executor_initialise.py`:

```python
"""Tests for McpExecutor.initialise — the MCP Streamable HTTP handshake."""

import json
from unittest.mock import patch

import httpx
import pytest

from backend.modules.tools._mcp_executor import (
    MCP_PROTOCOL_VERSION,
    McpExecutor,
)


def _json_response(payload: dict, *, headers: dict | None = None) -> httpx.Response:
    """Build a fake JSON httpx.Response with a plausible Request attached."""
    req = httpx.Request("POST", "http://srv/mcp")
    return httpx.Response(
        200,
        request=req,
        headers={"content-type": "application/json", **(headers or {})},
        content=json.dumps(payload).encode(),
    )


def _sse_response(payload: dict, *, headers: dict | None = None) -> httpx.Response:
    """Build a fake SSE httpx.Response — single data line then close."""
    req = httpx.Request("POST", "http://srv/mcp")
    body = f"data: {json.dumps(payload)}\n\n".encode()
    return httpx.Response(
        200,
        request=req,
        headers={"content-type": "text/event-stream", **(headers or {})},
        content=body,
    )


@pytest.mark.asyncio
async def test_initialise_three_step_handshake_with_session_id(monkeypatch):
    """initialise → notifications/initialized; both carry the session id when one is issued."""
    requests: list[tuple[str, dict]] = []  # (method-from-payload, headers)

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append((payload.get("method"), dict(request.headers)))
            method = payload.get("method")
            if method == "initialize":
                return _json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                    headers={"mcp-session-id": "sess-abc"},
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            return httpx.Response(404, request=request)

    mock_transport = _MockTransport()

    def _client_factory(*args, **kwargs):
        return httpx.AsyncClient(transport=mock_transport)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        _client_factory,
    )

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)

    assert session_id == "sess-abc"
    assert [m for m, _ in requests] == ["initialize", "notifications/initialized"]
    # The notification carries Mcp-Session-Id when one was issued
    notif_headers = requests[1][1]
    assert notif_headers.get("mcp-session-id") == "sess-abc"


@pytest.mark.asyncio
async def test_initialise_returns_none_when_no_session_id_header(monkeypatch):
    """Stateless servers respond without Mcp-Session-Id — we treat it as None."""
    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload.get("method") == "initialize":
                # No mcp-session-id header
                return _json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                )
            return httpx.Response(202, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)
    assert session_id is None


@pytest.mark.asyncio
async def test_initialise_returns_none_on_5xx(monkeypatch):
    """Server error → return None so caller can route the error like an unreachable gateway."""
    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)
    assert session_id is None


@pytest.mark.asyncio
async def test_initialise_handles_sse_response_body(monkeypatch):
    """When server replies via SSE, initialise still extracts the session id from the header."""
    requests: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            requests.append(payload.get("method"))
            if payload.get("method") == "initialize":
                return _sse_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                    headers={"mcp-session-id": "sess-sse"},
                )
            return httpx.Response(202, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    session_id = await executor.initialise(url="http://srv/mcp", api_key=None)
    assert session_id == "sess-sse"
    assert requests == ["initialize", "notifications/initialized"]


@pytest.mark.asyncio
async def test_initialise_payload_advertises_protocol_version_and_capabilities(monkeypatch):
    captured: dict = {}

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload.get("method") == "initialize":
                captured.update(payload)
                return _json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                    headers={"mcp-session-id": "x"},
                )
            return httpx.Response(202, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    await executor.initialise(url="http://srv/mcp", api_key=None)

    params = captured["params"]
    assert params["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert params["capabilities"] == {}
    assert params["clientInfo"]["name"] == "chatsune"
    assert isinstance(params["clientInfo"]["version"], str)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_initialise.py -v
```

Expected: errors (`AttributeError: 'McpExecutor' object has no attribute 'initialise'`).

- [ ] **Step 3: Implement `initialise`**

Edit `backend/modules/tools/_mcp_executor.py`. After the `_read_sse_response` function and before the `class McpExecutor:` declaration, add:

```python
class _NullAsyncLock:
    """No-op async context manager used when an explicit lock is not needed."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


_NULL_LOCK = _NullAsyncLock()
```

Inside `class McpExecutor:`, add the new method (place it before `call_tool`):

```python
    async def initialise(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
    ) -> str | None:
        """Run the MCP Streamable HTTP three-step handshake.

        Returns the ``Mcp-Session-Id`` issued by the server, or ``None`` if
        the server is operating in stateless mode (no header issued) or
        if the handshake failed at the protocol level (non-200 status).
        Always sends the ``notifications/initialized`` confirmation when
        the initialize step succeeded with 200.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        init_id = _next_request_id()
        init_payload = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "chatsune", "version": _CLIENT_VERSION},
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, json=init_payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        _log.warning(
                            "MCP initialise failed: HTTP %d from %s",
                            resp.status_code, url,
                        )
                        return None
                    session_id = resp.headers.get("mcp-session-id")
                    ctype = _content_type(resp)
                    if ctype == "application/json":
                        await resp.aread()
                    elif ctype == "text/event-stream":
                        try:
                            await _read_sse_response(resp, expected_id=init_id)
                        except RuntimeError:
                            # Server closed the stream without a matching reply.
                            # Header may still be set — that's the only piece
                            # we actually need from the handshake.
                            pass

                # Step 3: notifications/initialized — fire-and-forget.
                notif_headers = dict(headers)
                if session_id:
                    notif_headers["Mcp-Session-Id"] = session_id
                try:
                    await client.post(
                        url,
                        json={
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized",
                        },
                        headers=notif_headers,
                    )
                except Exception as exc:
                    _log.warning(
                        "MCP notifications/initialized post failed for %s: %s",
                        url, exc,
                    )

            return session_id
        except Exception as exc:
            _log.warning("MCP initialise transport failure for %s: %s", url, exc)
            return None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_initialise.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py \
  backend/tests/modules/tools/test_mcp_executor_initialise.py
git commit -m "Implement McpExecutor.initialise() three-step handshake"
```

---

## Task 4: Add `session_id` parameter to `call_tool` and `discover_tools`

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py`
- Create: `backend/tests/modules/tools/test_mcp_executor_call_tool.py`
- Create: `backend/tests/modules/tools/test_mcp_executor_discover_tools.py`

- [ ] **Step 1: Write failing tests for `call_tool` session header**

Create `backend/tests/modules/tools/test_mcp_executor_call_tool.py`:

```python
"""Tests for McpExecutor.call_tool — session header behaviour."""

import json

import httpx
import pytest

from backend.modules.tools._mcp_executor import McpExecutor


def _ok_call_response(req_id: int) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }).encode(),
    )


@pytest.mark.asyncio
async def test_call_tool_sends_mcp_session_id_header_when_set(monkeypatch):
    captured_headers: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            payload = json.loads(request.content)
            return _ok_call_response(payload["id"])

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-xyz",
    )

    parsed = json.loads(out)
    assert parsed["error"] is None
    assert captured_headers[0].get("mcp-session-id") == "sess-xyz"


@pytest.mark.asyncio
async def test_call_tool_omits_mcp_session_id_header_when_none(monkeypatch):
    captured_headers: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            payload = json.loads(request.content)
            return _ok_call_response(payload["id"])

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        # session_id defaults to None
    )
    assert json.loads(out)["error"] is None
    assert "mcp-session-id" not in captured_headers[0]
```

- [ ] **Step 2: Write failing tests for `discover_tools` session header**

Create `backend/tests/modules/tools/test_mcp_executor_discover_tools.py`:

```python
"""Tests for McpExecutor.discover_tools — session header behaviour."""

import json

import httpx
import pytest

from backend.modules.tools._mcp_executor import McpExecutor


def _tools_list_response(req_id: int) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [{"name": "t1", "description": "", "inputSchema": {}}]},
        }).encode(),
    )


@pytest.mark.asyncio
async def test_discover_tools_sends_mcp_session_id_header_when_set(monkeypatch):
    captured: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.headers))
            payload = json.loads(request.content)
            return _tools_list_response(payload["id"])

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    tools = await executor.discover_tools(
        url="http://srv/mcp", api_key=None,
        session_id="sess-discovery",
    )
    assert len(tools) == 1
    assert captured[0].get("mcp-session-id") == "sess-discovery"


@pytest.mark.asyncio
async def test_discover_tools_omits_mcp_session_id_header_when_none(monkeypatch):
    captured: list[dict] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.headers))
            payload = json.loads(request.content)
            return _tools_list_response(payload["id"])

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    tools = await executor.discover_tools(url="http://srv/mcp", api_key=None)
    assert len(tools) == 1
    assert "mcp-session-id" not in captured[0]
```

- [ ] **Step 3: Run tests to verify failure**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_call_tool.py \
  backend/tests/modules/tools/test_mcp_executor_discover_tools.py -v
```

Expected: errors (unexpected keyword argument `session_id`).

- [ ] **Step 4: Add `session_id` parameter to `call_tool` and `discover_tools`**

In `backend/modules/tools/_mcp_executor.py`:

In `McpExecutor.call_tool`, change the signature to:

```python
    async def call_tool(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
        session_id: str | None = None,
    ) -> str:
```

And right after the existing `if api_key: headers["Authorization"] = f"Bearer {api_key}"` line, insert:

```python
        if session_id:
            headers["Mcp-Session-Id"] = session_id
```

In `McpExecutor.discover_tools`, change the signature to:

```python
    async def discover_tools(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
        session_id: str | None = None,
    ) -> list[dict]:
```

Insert after the `Authorization` block:

```python
        if session_id:
            headers["Mcp-Session-Id"] = session_id
```

- [ ] **Step 5: Run tests to verify pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_call_tool.py \
  backend/tests/modules/tools/test_mcp_executor_discover_tools.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py \
  backend/tests/modules/tools/test_mcp_executor_call_tool.py \
  backend/tests/modules/tools/test_mcp_executor_discover_tools.py
git commit -m "Add session_id parameter to call_tool and discover_tools"
```

---

## Task 5: Implement 404-retry-on-reinit in `call_tool`

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py`
- Modify: `backend/tests/modules/tools/test_mcp_executor_call_tool.py`

- [ ] **Step 1: Append failing tests**

Append the following to `backend/tests/modules/tools/test_mcp_executor_call_tool.py`:

```python
@pytest.mark.asyncio
async def test_call_tool_on_404_reinitialises_and_retries(monkeypatch):
    """First call returns 404; executor re-runs initialise and retries; second call succeeds."""
    requests_log: list[tuple[str, dict]] = []
    state = {"new_session_id": "sess-fresh"}

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            requests_log.append((method, dict(request.headers)))
            if method == "tools/call":
                # Stale session id → 404; fresh one → 200.
                if request.headers.get("mcp-session-id") == "sess-stale":
                    return httpx.Response(404, request=request)
                return _ok_call_response(payload["id"])
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": state["new_session_id"],
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            # notifications/initialized
            return httpx.Response(202, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    refreshed: list[str] = []

    async def _on_refresh(new_id: str) -> None:
        refreshed.append(new_id)

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-stale",
        on_session_refresh=_on_refresh,
    )

    assert json.loads(out)["error"] is None
    assert refreshed == ["sess-fresh"]

    methods = [m for m, _ in requests_log]
    # 1st tools/call (404), then initialize, notifications/initialized, retry tools/call
    assert methods == [
        "tools/call",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    # Retry call carried the fresh session id
    retry_headers = requests_log[-1][1]
    assert retry_headers.get("mcp-session-id") == "sess-fresh"


@pytest.mark.asyncio
async def test_call_tool_on_404_does_not_retry_when_no_session_id(monkeypatch):
    """Stateless servers don't have a session id; a 404 must not trigger reinit."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            methods.append(payload.get("method"))
            return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        # session_id=None
    )
    parsed = json.loads(out)
    assert parsed["error"]  # some error string
    assert methods == ["tools/call"]  # no retry attempted


@pytest.mark.asyncio
async def test_call_tool_on_404_returns_error_when_reinit_fails(monkeypatch):
    """Re-init also fails → executor returns an error string instead of raising."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "tools/call":
                return httpx.Response(404, request=request)
            if method == "initialize":
                return httpx.Response(503, request=request)
            return httpx.Response(202, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-stale",
    )
    parsed = json.loads(out)
    assert "re-initialise" in parsed["error"].lower() or "session" in parsed["error"].lower()
    # tools/call (404) → initialize (503); no retry call attempted
    assert "tools/call" in methods
    assert methods.count("tools/call") == 1


@pytest.mark.asyncio
async def test_call_tool_no_double_retry_after_second_404(monkeypatch):
    """After a successful re-init, if the retry call ALSO returns 404, do not loop further."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "tools/call":
                return httpx.Response(404, request=request)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": "sess-fresh",
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            return httpx.Response(202, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
        session_id="sess-stale",
    )
    parsed = json.loads(out)
    assert parsed["error"]
    # Two tools/call attempts: original + one retry. No third.
    assert methods.count("tools/call") == 2
    assert methods.count("initialize") == 1
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_call_tool.py -v
```

Expected: 4 new tests fail (unexpected kwarg `on_session_refresh`, no retry).

- [ ] **Step 3: Implement retry logic in `call_tool`**

Replace the entire `call_tool` method with the following. The structure: stream the request, peek at status before consuming body, branch on 404+session_id+_retry to re-initialise and recurse with `_retry=False`.

```python
    async def call_tool(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
        session_id: str | None = None,
        on_session_refresh: "Callable[[str], Awaitable[None]] | None" = None,
        init_lock: "asyncio.Lock | None" = None,
        _retry: bool = True,
    ) -> str:
        """Call a tool on a gateway and return JSON string {"stdout": ..., "error": ...}.

        Never raises. All failure modes produce an error in the returned JSON.
        Speaks the MCP Streamable HTTP transport: advertises support for both
        application/json and text/event-stream, and handles whichever the
        server picks. When ``session_id`` is provided and the server
        responds 404 (session expired), the executor re-runs ``initialise``
        once (under ``init_lock`` if provided), notifies the caller of the
        new id via ``on_session_refresh``, and retries the call once.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        request_id = _next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 404 and session_id and _retry:
                        # Drain to free the connection before re-initialising.
                        await resp.aread()
                        async with (init_lock or _NULL_LOCK):
                            new_session_id = await self.initialise(url=url, api_key=api_key)
                            if new_session_id is None:
                                return json.dumps({
                                    "stdout": "",
                                    "error": "MCP session expired and re-initialise failed",
                                })
                            if on_session_refresh:
                                await on_session_refresh(new_session_id)
                        return await self.call_tool(
                            url=url, api_key=api_key,
                            tool_name=tool_name, arguments=arguments,
                            session_id=new_session_id,
                            on_session_refresh=on_session_refresh,
                            init_lock=init_lock,
                            _retry=False,
                        )

                    if resp.status_code != 200:
                        await resp.aread()
                        return json.dumps({
                            "stdout": "",
                            "error": f"MCP gateway returned HTTP {resp.status_code}",
                        })

                    ctype = _content_type(resp)

                    if ctype == "application/json":
                        body_bytes = await resp.aread()
                        body = json.loads(body_bytes)

                    elif ctype == "text/event-stream":
                        body = await _read_sse_response(resp, expected_id=request_id)

                    else:
                        _log.warning("MCP unexpected content-type from %s: %r", url, ctype)
                        return json.dumps({
                            "stdout": "",
                            "error": f"MCP gateway returned unexpected content-type: {ctype!r}",
                        })

            if "error" in body:
                err = body["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                _log.warning("MCP JSON-RPC error from %s: %s", url, msg)
                return json.dumps({"stdout": "", "error": f"MCP error: {msg}"})

            result = body.get("result", {})
            if result.get("isError"):
                content_parts = result.get("content", [])
                text = "\n".join(
                    p.get("text", "") for p in content_parts if p.get("type") == "text"
                )
                return json.dumps({"stdout": "", "error": text or "Tool returned an error"})

            content_parts = result.get("content", [])
            text = "\n".join(
                p.get("text", "") for p in content_parts if p.get("type") == "text"
            )
            return json.dumps({"stdout": text, "error": None})

        except httpx.TimeoutException:
            _log.warning("MCP call timed out: %s tool=%s", url, tool_name)
            return json.dumps({
                "stdout": "",
                "error": f"MCP gateway timeout after {_MCP_HTTP_TIMEOUT_S}s",
            })
        except Exception as exc:
            _log.warning("MCP call failed: %s tool=%s error=%s", url, tool_name, exc)
            return json.dumps({"stdout": "", "error": f"MCP gateway unreachable: {exc}"})
```

Add the necessary import at the top of `_mcp_executor.py` (after the existing imports):

```python
from typing import Awaitable, Callable
```

(`asyncio` is already imported transitively via `httpx`/`_mcp_registry`. If type-checkers complain about the string-quoted `asyncio.Lock`, add `import asyncio` explicitly at the top.)

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_call_tool.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Verify earlier tests still pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py \
  backend/tests/modules/tools/test_mcp_executor_call_tool.py
git commit -m "Add 404-retry-on-reinit logic to McpExecutor.call_tool"
```

---

## Task 6: Add `*_oneshot` proxy helpers

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py`
- Create: `backend/tests/modules/tools/test_mcp_executor_oneshot.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/tools/test_mcp_executor_oneshot.py`:

```python
"""Tests for McpExecutor.*_oneshot — proxy-route helpers that run init+call per request."""

import json

import httpx
import pytest

from backend.modules.tools._mcp_executor import McpExecutor


@pytest.mark.asyncio
async def test_call_tool_oneshot_runs_initialise_then_call(monkeypatch):
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": "sess-oneshot",
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            if method == "tools/call":
                # Confirm session id is forwarded.
                assert request.headers.get("mcp-session-id") == "sess-oneshot"
                return httpx.Response(
                    200, request=request,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"],
                        "result": {"content": [{"type": "text", "text": "hi"}]},
                    }).encode(),
                )
            return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool_oneshot(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
    )
    assert json.loads(out)["stdout"] == "hi"
    assert methods == ["initialize", "notifications/initialized", "tools/call"]


@pytest.mark.asyncio
async def test_discover_tools_oneshot_runs_initialise_then_list(monkeypatch):
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={
                        "content-type": "application/json",
                        "mcp-session-id": "sess-discover",
                    },
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            if method == "tools/list":
                assert request.headers.get("mcp-session-id") == "sess-discover"
                return httpx.Response(
                    200, request=request,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"],
                        "result": {"tools": [{"name": "t1", "description": "", "inputSchema": {}}]},
                    }).encode(),
                )
            return httpx.Response(404, request=request)

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    tools = await executor.discover_tools_oneshot(url="http://srv/mcp", api_key=None)
    assert len(tools) == 1
    assert methods == ["initialize", "notifications/initialized", "tools/list"]


@pytest.mark.asyncio
async def test_oneshot_helpers_work_with_stateless_server(monkeypatch):
    """When initialise returns no session id, the call still proceeds without header."""
    methods: list[str] = []

    class _MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            method = payload.get("method")
            methods.append(method)
            if method == "initialize":
                return httpx.Response(
                    200, request=request,
                    headers={"content-type": "application/json"},
                    content=json.dumps({
                        "jsonrpc": "2.0", "id": payload["id"], "result": {},
                    }).encode(),
                )
            if method == "notifications/initialized":
                return httpx.Response(202, request=request)
            assert "mcp-session-id" not in request.headers
            return httpx.Response(
                200, request=request,
                headers={"content-type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0", "id": payload["id"],
                    "result": {"content": [{"type": "text", "text": "ok"}]},
                }).encode(),
            )

    monkeypatch.setattr(
        "backend.modules.tools._mcp_executor.httpx.AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=_MockTransport()),
    )

    executor = McpExecutor()
    out = await executor.call_tool_oneshot(
        url="http://srv/mcp", api_key=None,
        tool_name="t", arguments={},
    )
    assert json.loads(out)["error"] is None
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_oneshot.py -v
```

Expected: errors (`AttributeError: 'McpExecutor' object has no attribute 'call_tool_oneshot'`).

- [ ] **Step 3: Add helpers to `McpExecutor`**

In `backend/modules/tools/_mcp_executor.py`, append two methods at the end of class `McpExecutor`:

```python
    async def call_tool_oneshot(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """Initialise → call_tool → return. Used by stateless proxy routes.

        Each invocation runs the full handshake; session state is not
        retained between calls. See spec section 3 (proxy lifecycle).
        """
        session_id = await self.initialise(url=url, api_key=api_key)
        return await self.call_tool(
            url=url, api_key=api_key,
            tool_name=tool_name, arguments=arguments,
            session_id=session_id,
        )

    async def discover_tools_oneshot(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
    ) -> list[dict]:
        """Initialise → tools/list → return. Used by stateless proxy routes."""
        session_id = await self.initialise(url=url, api_key=api_key, timeout=timeout)
        return await self.discover_tools(
            url=url, api_key=api_key, timeout=timeout, session_id=session_id,
        )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_executor_oneshot.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py \
  backend/tests/modules/tools/test_mcp_executor_oneshot.py
git commit -m "Add call_tool_oneshot and discover_tools_oneshot helpers"
```

---

## Task 7: Wire discovery to call `initialise` and stash session id

**Files:**
- Modify: `backend/modules/tools/_mcp_discovery.py`
- Create: `backend/tests/modules/tools/test_mcp_discovery_lifecycle.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/modules/tools/test_mcp_discovery_lifecycle.py`:

```python
"""Tests for _discover_single_gateway lifecycle integration."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.tools._mcp_discovery import _discover_single_gateway
from shared.dtos.mcp import McpGatewayConfigDto


def _config(**overrides) -> McpGatewayConfigDto:
    defaults = dict(
        id="gw-1",
        name="testgw",
        url="http://example.com",
        api_key=None,
        enabled=True,
        disabled_tools=[],
        server_configs={},
        tool_overrides=[],
    )
    defaults.update(overrides)
    return McpGatewayConfigDto(**defaults)


@pytest.mark.asyncio
async def test_discover_single_gateway_initialises_and_stashes_session_id():
    raw_tools = [{"name": "t", "description": "", "inputSchema": {}, "_gateway_server": "s"}]

    with patch(
        "backend.modules.tools._mcp_discovery._executor.initialise",
        new=AsyncMock(return_value="sess-from-init"),
    ), patch(
        "backend.modules.tools._mcp_discovery._executor.discover_tools",
        new=AsyncMock(return_value=raw_tools),
    ) as discover_mock:
        handle, status = await _discover_single_gateway(_config(), tier="admin")

    assert handle is not None
    assert handle.session_id == "sess-from-init"
    assert status.reachable is True
    discover_mock.assert_awaited_once()
    # session id is forwarded into discover_tools
    call_kwargs = discover_mock.await_args.kwargs
    assert call_kwargs.get("session_id") == "sess-from-init"


@pytest.mark.asyncio
async def test_discover_single_gateway_handles_stateless_initialise():
    raw_tools = [{"name": "t", "description": "", "inputSchema": {}, "_gateway_server": "s"}]
    with patch(
        "backend.modules.tools._mcp_discovery._executor.initialise",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.tools._mcp_discovery._executor.discover_tools",
        new=AsyncMock(return_value=raw_tools),
    ) as discover_mock:
        handle, status = await _discover_single_gateway(_config(), tier="admin")

    assert handle is not None
    assert handle.session_id is None
    assert status.reachable is True
    assert discover_mock.await_args.kwargs.get("session_id") is None


@pytest.mark.asyncio
async def test_discover_single_gateway_unreachable_when_init_and_list_both_fail():
    with patch(
        "backend.modules.tools._mcp_discovery._executor.initialise",
        new=AsyncMock(return_value=None),
    ), patch(
        "backend.modules.tools._mcp_discovery._executor.discover_tools",
        new=AsyncMock(return_value=[]),
    ):
        handle, status = await _discover_single_gateway(_config(), tier="admin")

    assert handle is None
    assert status.reachable is False
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_discovery_lifecycle.py -v
```

Expected: failures (handle.session_id not set, discover_tools not called with session_id kwarg).

- [ ] **Step 3: Update `_discover_single_gateway`**

In `backend/modules/tools/_mcp_discovery.py`, replace the body of `_discover_single_gateway` with:

```python
async def _discover_single_gateway(
    config: McpGatewayConfigDto,
    tier: str,
) -> tuple[GatewayHandle | None, McpGatewayStatusDto]:
    """Discover tools from one gateway. Returns (handle_or_None, status)."""
    namespace = normalise_namespace(config.name)
    mcp_url = config.url.rstrip("/") + "/mcp"

    # Step 1: initialise — populates session_id for stateful servers, returns
    # None for stateless servers OR for protocol failures. Both cases are
    # handled by tools/list below; an unreachable server simply returns no
    # tools, which keeps the existing `reachable=False` path active.
    session_id = await _executor.initialise(url=mcp_url, api_key=config.api_key)

    raw_tools = await _executor.discover_tools(
        url=mcp_url, api_key=config.api_key, session_id=session_id,
    )
    reachable = isinstance(raw_tools, list) and len(raw_tools) > 0

    tool_defs, server_tools, collisions = _raw_tools_to_definitions(
        namespace, raw_tools, config.disabled_tools,
        config.server_configs, config.tool_overrides,
    )

    if not reachable:
        return None, McpGatewayStatusDto(
            id=config.id, name=namespace, tier=tier, tool_count=0, reachable=False,
        )

    handle = GatewayHandle(
        id=config.id,
        name=namespace,
        url=mcp_url,
        api_key=config.api_key,
        tier=tier,
        tool_definitions=tool_defs,
        server_tools=server_tools,
        collisions=collisions,
        session_id=session_id,
    )
    status = McpGatewayStatusDto(
        id=config.id, name=namespace, tier=tier, tool_count=len(tool_defs), reachable=True,
    )
    return handle, status
```

(Note: `init_lock` defaults to a fresh `asyncio.Lock()` via the dataclass `field(default_factory=...)`, so we do not pass it explicitly.)

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/test_mcp_discovery_lifecycle.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full tools test suite**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/ -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_discovery.py \
  backend/tests/modules/tools/test_mcp_discovery_lifecycle.py
git commit -m "Wire MCP discovery to initialise and stash session id on handle"
```

---

## Task 8: Wire inference call site to forward session id, lock, refresh callback

**Files:**
- Modify: `backend/modules/tools/__init__.py`

This change is small and tightly coupled to the existing inference flow. The integration is best validated end-to-end via manual verification (Task 17); we do not write a dedicated unit test for this glue (the executor's retry behaviour is covered in Task 5; the discovery integration in Task 7).

- [ ] **Step 1: Update inference call site**

In `backend/modules/tools/__init__.py`, find the block at line 226–232 that currently reads:

```python
                else:
                    # Backend-executed: use McpExecutor
                    return await _mcp_executor.call_tool(
                        url=gw.url,
                        api_key=gw.api_key,
                        tool_name=original_name,
                        arguments=arguments,
                    )
```

Replace with:

```python
                else:
                    # Backend-executed: use McpExecutor with session lifecycle.
                    async def _refresh_session(new_id: str) -> None:
                        gw.session_id = new_id

                    return await _mcp_executor.call_tool(
                        url=gw.url,
                        api_key=gw.api_key,
                        tool_name=original_name,
                        arguments=arguments,
                        session_id=gw.session_id,
                        on_session_refresh=_refresh_session,
                        init_lock=gw.init_lock,
                    )
```

- [ ] **Step 2: Verify py_compile**

```bash
uv run python -m py_compile backend/modules/tools/__init__.py
```

Expected: no output.

- [ ] **Step 3: Run module tests for regressions**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/ backend/tests/modules/chat/ -v
```

Expected: all green (the chat-tests also exercise the tool dispatch path).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/tools/__init__.py
git commit -m "Forward session_id, init_lock, on_session_refresh from inference call site"
```

---

## Task 9: Wire backend proxy routes to use `*_oneshot` helpers

**Files:**
- Modify: `backend/modules/user/_handlers.py`

- [ ] **Step 1: Update `proxy_mcp_tools_list`**

In `backend/modules/user/_handlers.py` around line 1533, replace the body of `proxy_mcp_tools_list` so that it uses the oneshot helper:

```python
@router.get("/mcp/gateways/{gateway_id}/tools")
async def proxy_mcp_tools_list(
    gateway_id: str,
    user: dict = Depends(require_active_session),
):
    """Proxy tools/list to a backend-reachable MCP gateway.

    Runs the full Streamable HTTP lifecycle (initialise + list) per HTTP
    request — proxy routes do not share session state with WebSocket-bound
    discovery.
    """
    from backend.modules.tools._mcp_executor import McpExecutor

    gw = await _resolve_gateway(gateway_id, user)
    executor = McpExecutor()
    mcp_url = gw.url.rstrip("/") + "/mcp"
    tools = await executor.discover_tools_oneshot(url=mcp_url, api_key=gw.api_key)
    return {"tools": tools}
```

- [ ] **Step 2: Update `proxy_mcp_tool_call`**

In the same file around line 1548, replace the body:

```python
@router.post("/mcp/gateways/{gateway_id}/call")
async def proxy_mcp_tool_call(
    gateway_id: str,
    body: _McpProxyCallRequest,
    user: dict = Depends(require_active_session),
):
    """Proxy tools/call to a backend-reachable MCP gateway with full lifecycle."""
    import json as _json

    from backend.modules.tools._mcp_executor import McpExecutor

    gw = await _resolve_gateway(gateway_id, user)
    executor = McpExecutor()
    mcp_url = gw.url.rstrip("/") + "/mcp"
    result_json = await executor.call_tool_oneshot(
        url=mcp_url, api_key=gw.api_key,
        tool_name=body.tool_name, arguments=body.arguments,
    )
    return _json.loads(result_json)
```

- [ ] **Step 3: Verify py_compile**

```bash
uv run python -m py_compile backend/modules/user/_handlers.py
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/user/_handlers.py
git commit -m "Use oneshot lifecycle helpers in MCP proxy routes"
```

---

## Task 10: Frontend — protocol/version constants + supporting types

**Files:**
- Modify: `frontend/src/features/mcp/mcpClient.ts`

- [ ] **Step 1: Add constants and version import**

At the top of `frontend/src/features/mcp/mcpClient.ts`, after the existing imports, add:

```typescript
import packageJson from '../../../package.json'

const MCP_PROTOCOL_VERSION = '2025-06-18'
const APP_VERSION = (packageJson as { version: string }).version
```

If TypeScript complains about the JSON import, ensure `frontend/tsconfig.json` (or the relevant `tsconfig.app.json`) has `"resolveJsonModule": true` under `compilerOptions`. Check before assuming an edit is needed:

```bash
grep -n resolveJsonModule frontend/tsconfig*.json
```

If the option is absent, add it. If present, no change needed.

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/mcp/mcpClient.ts \
  frontend/tsconfig.json frontend/tsconfig.app.json
# Only stage tsconfig files if you actually edited them.
git commit -m "Add MCP protocol version and APP_VERSION constants to mcpClient"
```

---

## Task 11: Frontend — `mcpStore` session slice

**Files:**
- Modify: `frontend/src/features/mcp/mcpStore.ts`
- Modify: `frontend/src/features/mcp/__tests__/mcpStore.test.ts`

- [ ] **Step 1: Append failing tests for the session slice**

Append to `frontend/src/features/mcp/__tests__/mcpStore.test.ts`:

```typescript
import { useMcpStore } from '../mcpStore'

describe('mcpStore — session slice', () => {
  beforeEach(() => {
    // Reset the sessions slice between tests
    useMcpStore.setState({ sessions: {} })
  })

  it('setSession stores the session id keyed by URL', () => {
    useMcpStore.getState().setSession('http://srv/mcp', 'sess-1')
    expect(useMcpStore.getState().getSession('http://srv/mcp')).toEqual({
      sessionId: 'sess-1',
      initialising: null,
    })
  })

  it('setSession can mark a server as stateless with null', () => {
    useMcpStore.getState().setSession('http://srv/mcp', null)
    expect(useMcpStore.getState().getSession('http://srv/mcp')?.sessionId).toBeNull()
  })

  it('clearSession removes the entry', () => {
    useMcpStore.getState().setSession('http://srv/mcp', 'sess-1')
    useMcpStore.getState().clearSession('http://srv/mcp')
    expect(useMcpStore.getState().getSession('http://srv/mcp')).toBeUndefined()
  })

  it('setSession overwrites an existing entry (URL edit scenario)', () => {
    useMcpStore.getState().setSession('http://srv/mcp', 'old')
    useMcpStore.getState().setSession('http://srv/mcp', 'new')
    expect(useMcpStore.getState().getSession('http://srv/mcp')?.sessionId).toEqual('new')
  })
})
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpStore.test.ts
```

Expected: failures (`getSession is not a function`).

- [ ] **Step 3: Add session slice to the store**

Open `frontend/src/features/mcp/mcpStore.ts`. Locate the `interface McpStore` (or whatever the store interface is named) and the `create<McpStore>(...)` call. Add the following without disturbing existing fields/actions:

Inside the type definition (alongside existing fields):

```typescript
  // ── Streamable HTTP session lifecycle ─────────────────────
  sessions: Record<string, { sessionId: string | null | undefined; initialising: Promise<string | null> | null }>
  setSession: (url: string, sessionId: string | null) => void
  clearSession: (url: string) => void
  getSession: (url: string) => { sessionId: string | null | undefined; initialising: Promise<string | null> | null } | undefined
```

Inside the `create<McpStore>((set, get) => ({ ... }))` body, add the initial value and three actions:

```typescript
  sessions: {},
  setSession: (url, sessionId) =>
    set((s) => ({
      sessions: { ...s.sessions, [url]: { sessionId, initialising: null } },
    })),
  clearSession: (url) =>
    set((s) => {
      if (!(url in s.sessions)) return {}
      const next = { ...s.sessions }
      delete next[url]
      return { sessions: next }
    }),
  getSession: (url) => get().sessions[url],
```

(Adjust the import of `Promise` etc. as your repo's existing store style requires; the Zustand `create` helper in this project's `mcpStore.ts` already uses `set` and `get` callbacks.)

- [ ] **Step 4: Run tests to verify pass**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpStore.test.ts
```

Expected: 4 new passing, plus any existing tests still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/mcp/mcpStore.ts \
  frontend/src/features/mcp/__tests__/mcpStore.test.ts
git commit -m "Add session-slice to mcpStore (setSession / clearSession / getSession)"
```

---

## Task 12: Frontend — clear session on gateway URL edit / delete

**Files:**
- Modify: `frontend/src/features/mcp/mcpStore.ts`

The `mcpStore` already has mutator paths for editing and deleting `localGateways`. We need to call `clearSession(canonicalUrl)` from each mutator that changes or removes a gateway URL, so that a freshly-edited gateway gets a fresh handshake on its next call.

- [ ] **Step 1: Identify the mutator paths**

```bash
grep -n "localGateways" frontend/src/features/mcp/mcpStore.ts
```

Look for actions like `addLocalGateway`, `updateLocalGateway`, `deleteLocalGateway` (exact names will differ — adapt to whatever the store currently uses).

- [ ] **Step 2: Compute the canonical URL form once**

The session is keyed by `url.replace(/\/+$/, '') + '/mcp'`. Add a small helper near the top of the file (or alongside the mutators):

```typescript
function canonicaliseGatewayUrl(rawUrl: string): string {
  return rawUrl.replace(/\/+$/, '') + '/mcp'
}
```

- [ ] **Step 3: Wire the mutators**

In the **delete** mutator, after removing the gateway from `localGateways` array, call:

```typescript
get().clearSession(canonicaliseGatewayUrl(deletedGateway.url))
```

In the **update** mutator, *before* mutating the gateway, capture the old URL; if the new URL differs from the old one, call:

```typescript
const oldKey = canonicaliseGatewayUrl(oldGateway.url)
get().clearSession(oldKey)
```

(If the URL is unchanged, no clear is necessary; the existing session keeps working.)

If the store style uses a different idiom (e.g. immer drafts, or pre-existing `set((s) => ...)` returns), adapt the integration without changing the semantics: after the array mutation, invoke `clearSession`.

- [ ] **Step 4: Add a regression test**

Append to `frontend/src/features/mcp/__tests__/mcpStore.test.ts`:

```typescript
describe('mcpStore — session lifecycle wiring', () => {
  beforeEach(() => {
    useMcpStore.setState({ sessions: {}, localGateways: [] })
  })

  it('deleting a local gateway clears its session', () => {
    const url = 'http://srv'
    useMcpStore.setState({
      localGateways: [
        { id: 'g', name: 'g', url, apiKey: null, enabled: true, tools: [] } as never,
      ],
    })
    useMcpStore.getState().setSession(`${url}/mcp`, 'sess-1')

    // Use whatever the actual delete-action name is in this project:
    // useMcpStore.getState().deleteLocalGateway('g')
    // The test must call the same action that production code calls.
    // (Adjust this line to match the actual action name discovered in Step 1.)
    const { deleteLocalGateway } = useMcpStore.getState() as never
    deleteLocalGateway?.('g')

    expect(useMcpStore.getState().getSession(`${url}/mcp`)).toBeUndefined()
  })

  it('changing a local gateway URL clears the old session', () => {
    const oldUrl = 'http://old'
    const newUrl = 'http://new'
    useMcpStore.setState({
      localGateways: [
        { id: 'g', name: 'g', url: oldUrl, apiKey: null, enabled: true, tools: [] } as never,
      ],
    })
    useMcpStore.getState().setSession(`${oldUrl}/mcp`, 'sess-old')

    const { updateLocalGateway } = useMcpStore.getState() as never
    updateLocalGateway?.('g', { url: newUrl })

    expect(useMcpStore.getState().getSession(`${oldUrl}/mcp`)).toBeUndefined()
  })
})
```

If the action names in this project are different (e.g. `removeLocalGateway`, `editLocalGateway`), substitute them. The test asserts the *behaviour* — the wiring deletes the session when the gateway changes URL or disappears. If after Step 1 you find the store uses entirely different idioms (e.g. local gateway state lives in a separate hook), adapt this task: the goal is "session evicted on URL change / delete", and the test should encode that.

- [ ] **Step 5: Run tests to verify pass**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpStore.test.ts
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/mcp/mcpStore.ts \
  frontend/src/features/mcp/__tests__/mcpStore.test.ts
git commit -m "Evict mcpStore session on local gateway URL edit or delete"
```

---

## Task 13: Frontend — `readJsonRpcResponse` (SSE-aware reader)

**Files:**
- Modify: `frontend/src/features/mcp/mcpClient.ts`

- [ ] **Step 1: Add the helper near the top of mcpClient.ts**

After the constants from Task 10, add:

```typescript
type JsonRpcReply = {
  jsonrpc: string
  id?: number
  result?: unknown
  error?: { code: number; message: string }
}

async function readJsonRpcResponse(resp: Response, expectedId?: number): Promise<JsonRpcReply> {
  const ctype = (resp.headers.get('content-type') || '').split(';')[0].trim().toLowerCase()

  if (ctype === 'application/json') {
    return (await resp.json()) as JsonRpcReply
  }
  if (ctype === 'text/event-stream') {
    if (!resp.body) throw new Error('SSE response has no body')
    const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += value
      let nl: number
      while ((nl = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, nl).replace(/\r$/, '')
        buffer = buffer.slice(nl + 1)
        if (!line.startsWith('data:')) continue
        const data = line.slice(5).trimStart()
        if (!data) continue
        try {
          const obj = JSON.parse(data) as JsonRpcReply
          if (expectedId === undefined || obj.id === expectedId) return obj
        } catch {
          // malformed — skip, keep reading
        }
      }
    }
    throw new Error('SSE stream closed without matching response')
  }
  throw new Error(`Unexpected content-type from MCP gateway: ${ctype}`)
}
```

The existing `mcpToolsList` / `mcpToolsCall` will be rewired in Tasks 15 & 16 to call this helper instead of `await resp.json()`.

- [ ] **Step 2: Add unit test**

In `frontend/src/features/mcp/__tests__/mcpClient.test.ts`, append:

```typescript
import { describe, it, expect } from 'vitest'

describe('readJsonRpcResponse', () => {
  it('parses a JSON response', async () => {
    const resp = new Response(JSON.stringify({ jsonrpc: '2.0', id: 7, result: 'x' }), {
      headers: { 'content-type': 'application/json' },
    })
    // Re-import via test-only access path; if the helper is not exported,
    // this test should be moved to mcpClient.ts as a private-export-for-test.
    // Project convention: export `readJsonRpcResponse` for tests by adding
    // it to the `mcpClient.ts` exports.
    const { readJsonRpcResponse } = await import('../mcpClient')
    const out = await readJsonRpcResponse(resp)
    expect(out.id).toEqual(7)
    expect(out.result).toEqual('x')
  })

  it('parses an SSE response and matches by id', async () => {
    const sseBody =
      `data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"x":1}}\n\n` +
      `data: {"jsonrpc":"2.0","id":42,"result":"hit"}\n\n`
    const resp = new Response(sseBody, {
      headers: { 'content-type': 'text/event-stream' },
    })
    const { readJsonRpcResponse } = await import('../mcpClient')
    const out = await readJsonRpcResponse(resp, 42)
    expect(out.id).toEqual(42)
    expect(out.result).toEqual('hit')
  })

  it('throws on SSE close without matching id', async () => {
    const resp = new Response(`data: {"jsonrpc":"2.0","id":1,"result":"a"}\n\n`, {
      headers: { 'content-type': 'text/event-stream' },
    })
    const { readJsonRpcResponse } = await import('../mcpClient')
    await expect(readJsonRpcResponse(resp, 999)).rejects.toThrow(/SSE stream closed/)
  })

  it('throws on unexpected content-type', async () => {
    const resp = new Response('hello', { headers: { 'content-type': 'text/plain' } })
    const { readJsonRpcResponse } = await import('../mcpClient')
    await expect(readJsonRpcResponse(resp)).rejects.toThrow(/Unexpected content-type/)
  })
})
```

For these tests to work, **export** the helper from `mcpClient.ts`:

```typescript
export async function readJsonRpcResponse(resp: Response, expectedId?: number): Promise<JsonRpcReply> {
  // ... body as above ...
}
```

- [ ] **Step 3: Run tests to verify pass**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: 4 new passing. Earlier mcpClient tests should still be green (they do not depend on `readJsonRpcResponse`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/mcp/mcpClient.ts \
  frontend/src/features/mcp/__tests__/mcpClient.test.ts
git commit -m "Add readJsonRpcResponse SSE-aware reader to mcpClient"
```

---

## Task 14: Frontend — `ensureSession` and `doInitialise`

**Files:**
- Modify: `frontend/src/features/mcp/mcpClient.ts`
- Modify: `frontend/src/features/mcp/__tests__/mcpClient.test.ts`

- [ ] **Step 1: Append failing tests**

Append to `frontend/src/features/mcp/__tests__/mcpClient.test.ts`:

```typescript
describe('ensureSession', () => {
  let fetchSpy: ReturnType<typeof vi.fn>
  let initCount = 0

  beforeEach(async () => {
    initCount = 0
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })

    fetchSpy = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      const method = body.method
      if (method === 'initialize') {
        initCount += 1
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-it-' + initCount,
            },
          },
        )
      }
      // notifications/initialized — no body needed
      return new Response('', { status: 202 })
    })
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('sends initialize then notifications/initialized in that order', async () => {
    const { ensureSession } = await import('../mcpClient')
    await ensureSession('http://srv', null)

    const calls = fetchSpy.mock.calls
    const methods = calls.map(([, init]) => JSON.parse(String((init as RequestInit).body)).method)
    expect(methods).toEqual(['initialize', 'notifications/initialized'])
  })

  it('parses Mcp-Session-Id from response header and caches it', async () => {
    const { ensureSession } = await import('../mcpClient')
    const sid = await ensureSession('http://srv', null)
    expect(sid).toEqual('sess-it-1')

    const { useMcpStore } = await import('../mcpStore')
    expect(useMcpStore.getState().getSession('http://srv/mcp')?.sessionId).toEqual('sess-it-1')
  })

  it('returns null for stateless server (no Mcp-Session-Id header)', async () => {
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          { headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response('', { status: 202 })
    })

    const { ensureSession } = await import('../mcpClient')
    const sid = await ensureSession('http://srv', null)
    expect(sid).toBeNull()
  })

  it('dedupes concurrent calls into a single initialise', async () => {
    const { ensureSession } = await import('../mcpClient')
    const [a, b] = await Promise.all([
      ensureSession('http://srv', null),
      ensureSession('http://srv', null),
    ])
    expect(a).toEqual(b)
    expect(initCount).toEqual(1)
  })
})
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: failures (no exported `ensureSession`).

- [ ] **Step 3: Add `ensureSession` and `doInitialise`**

In `frontend/src/features/mcp/mcpClient.ts` (after the `readJsonRpcResponse` helper, before `mcpProxyToolsList`), add:

```typescript
import { useMcpStore } from './mcpStore'

async function doInitialise(url: string, apiKey: string | null): Promise<string | null> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
  }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  const initId = nextId()
  const initResp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: initId,
      method: 'initialize',
      params: {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: 'chatsune', version: APP_VERSION },
      },
    }),
  })
  if (!initResp.ok) {
    throw new Error(`MCP initialise failed: HTTP ${initResp.status}`)
  }
  const sessionId = initResp.headers.get('mcp-session-id')
  // Drain body — for SSE we want to consume up to the matching reply,
  // for JSON we just discard.
  try {
    await readJsonRpcResponse(initResp, initId)
  } catch {
    // Stream may close without a strict match; the session id header is
    // what we need from this step.
  }

  const notifHeaders = { ...headers }
  if (sessionId) notifHeaders['Mcp-Session-Id'] = sessionId
  await fetch(url, {
    method: 'POST',
    headers: notifHeaders,
    body: JSON.stringify({
      jsonrpc: '2.0',
      method: 'notifications/initialized',
    }),
  })

  return sessionId
}

export async function ensureSession(
  gatewayUrl: string,
  apiKey: string | null,
): Promise<string | null> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const store = useMcpStore.getState()
  const existing = store.getSession(url)

  if (existing && existing.sessionId !== undefined) return existing.sessionId
  if (existing?.initialising) return existing.initialising

  const initPromise = doInitialise(url, apiKey)
  useMcpStore.setState((s) => ({
    sessions: {
      ...s.sessions,
      [url]: { sessionId: undefined, initialising: initPromise },
    },
  }))

  try {
    const sessionId = await initPromise
    store.setSession(url, sessionId)
    return sessionId
  } catch (e) {
    store.clearSession(url)
    throw e
  }
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: 4 new passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/mcp/mcpClient.ts \
  frontend/src/features/mcp/__tests__/mcpClient.test.ts
git commit -m "Add ensureSession and doInitialise to mcpClient with in-flight dedup"
```

---

## Task 15: Frontend — wrap `mcpToolsCall` with lifecycle + 404 retry

**Files:**
- Modify: `frontend/src/features/mcp/mcpClient.ts`
- Modify: `frontend/src/features/mcp/__tests__/mcpClient.test.ts`

- [ ] **Step 1: Append failing tests**

Append to `frontend/src/features/mcp/__tests__/mcpClient.test.ts`:

```typescript
describe('mcpToolsCall lifecycle', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(async () => {
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })
    fetchSpy = vi.fn()
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('sends Mcp-Session-Id on tool call after initialise', async () => {
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-tc',
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/call
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { content: [{ type: 'text', text: 'ok' }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })

    const { mcpToolsCall } = await import('../mcpClient')
    const out = await mcpToolsCall('http://srv', null, 't', {})
    expect(out.error).toBeNull()
    expect(out.stdout).toEqual('ok')

    const callRequest = fetchSpy.mock.calls.find(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).method === 'tools/call',
    )!
    const headers = (callRequest[1] as RequestInit).headers as Record<string, string>
    expect(headers['Mcp-Session-Id']).toEqual('sess-tc')
  })

  it('on 404 clears session, re-initialises, retries once', async () => {
    let initCount = 0
    let callCount = 0
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        initCount += 1
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-' + initCount,
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/call
      callCount += 1
      const headers = init.headers as Record<string, string>
      if (headers['Mcp-Session-Id'] === 'sess-1' && callCount === 1) {
        return new Response('', { status: 404 })
      }
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { content: [{ type: 'text', text: 'recovered' }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })

    const { mcpToolsCall } = await import('../mcpClient')
    const out = await mcpToolsCall('http://srv', null, 't', {})
    expect(out.error).toBeNull()
    expect(out.stdout).toEqual('recovered')
    expect(initCount).toEqual(2)
    expect(callCount).toEqual(2)
  })

  it('does not retry when there is no session id (stateless server)', async () => {
    let callCount = 0
    fetchSpy.mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          { headers: { 'content-type': 'application/json' } }, // no mcp-session-id
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      callCount += 1
      return new Response('', { status: 404 })
    })

    const { mcpToolsCall } = await import('../mcpClient')
    const out = await mcpToolsCall('http://srv', null, 't', {})
    expect(out.error).toBeTruthy()
    expect(callCount).toEqual(1)  // no retry
  })
})
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: 3 new tests fail.

- [ ] **Step 3: Rewrite `mcpToolsCall`**

In `frontend/src/features/mcp/mcpClient.ts`, replace the existing `mcpToolsCall` export with:

```typescript
export async function mcpToolsCall(
  gatewayUrl: string,
  apiKey: string | null,
  toolName: string,
  args: Record<string, unknown>,
  timeoutMs: number = 30_000,
): Promise<{ stdout: string; error: string | null }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'

  let sessionId: string | null
  try {
    sessionId = await ensureSession(gatewayUrl, apiKey)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return { stdout: '', error: `MCP initialise failed: ${msg}` }
  }

  const doCall = async (sid: string | null): Promise<Response> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
    }
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
    if (sid) headers['Mcp-Session-Id'] = sid

    return fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: nextId(),
        method: 'tools/call',
        params: { name: toolName, arguments: args },
      }),
      signal: AbortSignal.timeout(timeoutMs),
    })
  }

  let resp: Response
  try {
    resp = await doCall(sessionId)
    if (resp.status === 404 && sessionId) {
      useMcpStore.getState().clearSession(url)
      try {
        sessionId = await ensureSession(gatewayUrl, apiKey)
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        return { stdout: '', error: `MCP re-initialise failed: ${msg}` }
      }
      resp = await doCall(sessionId)
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      return { stdout: '', error: `MCP gateway timed out after ${timeoutMs}ms` }
    }
    const msg = e instanceof Error ? e.message : String(e)
    return { stdout: '', error: `MCP gateway unreachable: ${msg}` }
  }

  if (!resp.ok) {
    return { stdout: '', error: `MCP gateway returned HTTP ${resp.status}` }
  }

  let body: JsonRpcReply
  try {
    body = await readJsonRpcResponse(resp)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return { stdout: '', error: `MCP gateway response read failed: ${msg}` }
  }

  if (body.error) {
    return { stdout: '', error: `MCP error: ${body.error.message || JSON.stringify(body.error)}` }
  }

  const result = (body.result || {}) as { isError?: boolean; content?: Array<{ type: string; text?: string }> }
  if (result.isError) {
    const text = (result.content || [])
      .filter((c) => c.type === 'text')
      .map((c) => c.text || '')
      .join('\n')
    return { stdout: '', error: text || 'Tool returned an error' }
  }

  const text = (result.content || [])
    .filter((c) => c.type === 'text')
    .map((c) => c.text || '')
    .join('\n')
  return { stdout: text, error: null }
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/mcp/mcpClient.ts \
  frontend/src/features/mcp/__tests__/mcpClient.test.ts
git commit -m "Wrap mcpToolsCall with session lifecycle and 404 retry"
```

---

## Task 16: Frontend — wrap `mcpToolsList` with lifecycle

**Files:**
- Modify: `frontend/src/features/mcp/mcpClient.ts`
- Modify: `frontend/src/features/mcp/__tests__/mcpClient.test.ts`

- [ ] **Step 1: Append failing test**

Append to `frontend/src/features/mcp/__tests__/mcpClient.test.ts`:

```typescript
describe('mcpToolsList lifecycle', () => {
  let fetchSpy: ReturnType<typeof vi.fn>

  beforeEach(async () => {
    const { useMcpStore } = await import('../mcpStore')
    useMcpStore.setState({ sessions: {} })
    fetchSpy = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if (body.method === 'initialize') {
        return new Response(
          JSON.stringify({ jsonrpc: '2.0', id: body.id, result: {} }),
          {
            headers: {
              'content-type': 'application/json',
              'mcp-session-id': 'sess-list',
            },
          },
        )
      }
      if (body.method === 'notifications/initialized') {
        return new Response('', { status: 202 })
      }
      // tools/list
      return new Response(
        JSON.stringify({
          jsonrpc: '2.0',
          id: body.id,
          result: { tools: [{ name: 't1', description: '', inputSchema: {} }] },
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    })
    // @ts-expect-error - test override
    globalThis.fetch = fetchSpy
  })

  it('runs initialise then sends Mcp-Session-Id on tools/list', async () => {
    const { mcpToolsList } = await import('../mcpClient')
    const out = await mcpToolsList('http://srv', null)
    expect(out.tools.length).toEqual(1)

    const listCall = fetchSpy.mock.calls.find(
      ([, init]) => JSON.parse(String((init as RequestInit).body)).method === 'tools/list',
    )!
    const headers = (listCall[1] as RequestInit).headers as Record<string, string>
    expect(headers['Mcp-Session-Id']).toEqual('sess-list')
  })
})
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: failure (no Mcp-Session-Id header on tools/list).

- [ ] **Step 3: Rewrite `mcpToolsList`**

In `frontend/src/features/mcp/mcpClient.ts`, replace the existing `mcpToolsList`:

```typescript
export async function mcpToolsList(
  gatewayUrl: string,
  apiKey: string | null,
  timeoutMs: number = 10_000,
): Promise<{ tools: McpToolDefinition[]; errors: Array<{ server: string; error: string }> }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'

  let sessionId: string | null
  try {
    sessionId = await ensureSession(gatewayUrl, apiKey)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    throw new Error(`MCP initialise failed: ${msg}`)
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
  }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
  if (sessionId) headers['Mcp-Session-Id'] = sessionId

  const resp = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ jsonrpc: '2.0', id: nextId(), method: 'tools/list' }),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!resp.ok) {
    if (resp.status === 404 && sessionId) {
      useMcpStore.getState().clearSession(url)
    }
    throw new Error(`MCP tools/list failed: HTTP ${resp.status}`)
  }
  const body = await readJsonRpcResponse(resp)
  if (body.error) {
    throw new Error(body.error.message || JSON.stringify(body.error))
  }
  const result = (body.result || {}) as {
    tools?: McpToolDefinition[]
    _errors?: Array<{ server: string; error: string }>
  }
  return {
    tools: result.tools || [],
    errors: result._errors || [],
  }
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpClient.test.ts
```

Expected: all green.

- [ ] **Step 5: Run full mcp test suite for regressions**

```bash
cd frontend && pnpm vitest run src/features/mcp/__tests__/
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/mcp/mcpClient.ts \
  frontend/src/features/mcp/__tests__/mcpClient.test.ts
git commit -m "Wrap mcpToolsList with session lifecycle"
```

---

## Task 17: Build verification + manual matrix

**Files:**
- Read-only: spec §8 (manual verification matrix)

This task is the green-light gate before merge. No code changes — just verification.

- [ ] **Step 1: Backend syntax sanity**

```bash
uv run python -m py_compile \
  backend/modules/tools/_mcp_executor.py \
  backend/modules/tools/_mcp_registry.py \
  backend/modules/tools/_mcp_discovery.py \
  backend/modules/tools/__init__.py \
  backend/modules/user/_handlers.py
```

Expected: no output, exit 0.

- [ ] **Step 2: Backend pytest (host-safe subset)**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/tests/modules/tools/ -v
```

Expected: all green. Then run a wider sweep that excludes the four DB-using files (per memory `db_tests_on_host`):

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests \
  --ignore=backend/tests/modules/persona \
  --ignore=backend/tests/integration \
  -v
```

(If the exclusion paths differ from the memory's expected set, list them via `find backend/tests -name '*.py' | xargs grep -l 'mongo\|MongoClient'` first, then exclude those files.)

Expected: all green (or at least no new failures versus the master baseline).

- [ ] **Step 3: Frontend type-check + build**

```bash
cd frontend && pnpm run build
```

Expected: completes without TypeScript errors. (`pnpm run build` runs `tsc -b && vite build` — both stages must succeed.)

- [ ] **Step 4: Frontend test sweep**

```bash
cd frontend && pnpm vitest run src/features/mcp
```

Expected: all green.

- [ ] **Step 5: Manual verification — Mode C (stateful + JSON), local tier**

In one terminal:
```bash
cd /home/chris/projects/simple_mcp
MCP_STATELESS_HTTP=false MCP_JSON_RESPONSE=true uv run python server.py
```
Banner should print `stateless_http=False  json_response=True  listening on http://127.0.0.1:3333/mcp`.

Start the Chatsune dev stack (frontend + backend). In the user-modal MCP tab, add a local gateway:
- URL: `http://127.0.0.1:3333`
- API key: empty

Open a chat, ask the model to call `get_datetime`. Browser DevTools → Network. Check:
- `POST /mcp` with `method: initialize` — response carries `mcp-session-id` header
- `POST /mcp` with `method: notifications/initialized` — carries `Mcp-Session-Id`
- `POST /mcp` with `method: tools/list` — carries `Mcp-Session-Id`
- `POST /mcp` with `method: tools/call` — carries `Mcp-Session-Id`
- The pill in chat shows the timestamp.

- [ ] **Step 6: Manual verification — Mode D (stateful + SSE), local tier**

Restart `simple_mcp` with `MCP_STATELESS_HTTP=false MCP_JSON_RESPONSE=false`. Repeat the call. The `tools/call` response should arrive as `text/event-stream`. Pill still shows the timestamp.

- [ ] **Step 7: Manual verification — Mode C, admin tier (proxy route)**

Configure `simple_mcp` as an admin gateway (admin modal). Open the Tool-Explorer modal. The tool list should populate. Click the tool, run it from the explorer. Backend logs should show `initialise` then `tools/list` (and on the call, `initialise` then `tools/call`) — one initialise per HTTP request to `/api/mcp/gateways/{id}/...`.

- [ ] **Step 8: Manual verification — Mode C, remote tier**

Configure `simple_mcp` as a user-remote gateway. Note: the URL must be reachable from the backend container — when running `simple_mcp` on the host while Chatsune backend runs in Docker, use `http://host.docker.internal:3333` (or run `simple_mcp` on the host network). Run a chat tool call. Expected: pill shows result; backend log shows one `initialise` at session start, multiple `tools/call` reusing the session id.

- [ ] **Step 9: Manual verification — Re-init trigger**

While Mode C local-tier session is active and a chat is open, kill `simple_mcp` (Ctrl-C) and restart it (same env). Issue another tool call from chat. Expected backend log: `tools/call` returns 404, `initialise` runs again, retry succeeds. The pill shows result without user-visible error.

- [ ] **Step 10: Manual verification — Page reload (frontend)**

Mode C local-tier, after a successful call, reload the browser tab. Issue another tool call. Network tab: fresh `initialize` happens before `tools/call`. (Confirms in-memory `mcpStore.sessions` was dropped.)

- [ ] **Step 11: Final commit (if any tweaks were made during verification)**

If the verification surfaced fixes that landed in commits during steps 5–10, this step is a no-op. Otherwise:

```bash
git status
# If clean: nothing to do.
# If tweaks: stage + commit per change.
```

---

## Self-review checklist (writer's pass)

- [x] Every spec section is covered:
  - §3 (Architecture) → Tasks 1, 8, 9, 11, 12, 14, 15, 16
  - §4 (Backend Detail) → Tasks 1–9
  - §5 (Frontend Detail) → Tasks 10–16
  - §6 (Error Handling) → exercised by tests in Tasks 5, 14, 15
  - §7 (Testing) → Tasks 1–16 (TDD throughout)
  - §8 (Manual Verification) → Task 17
- [x] No placeholders: all code blocks contain runnable code, all commands are concrete.
- [x] Type / API consistency: `session_id` parameter naming consistent; `on_session_refresh` callback shape consistent across executor and inference call site; `setSession` / `clearSession` / `getSession` consistent across store and consumers; `MCP_PROTOCOL_VERSION` value identical in backend and frontend.
- [x] No new dependencies — `httpx`, `asyncio`, `pytest-asyncio`, Vitest, Zustand are all already present.
- [x] Pytest invocations include `PYTHONPATH=/home/chris/workspace/chatsune` (memory `pytest_rootdir_quirk`).
- [x] Frontend build uses `pnpm run build`, not `pnpm tsc --noEmit` (memory `frontend_build_check`).
- [x] DB-using tests are not touched (memory `db_tests_on_host`).
- [x] Each task ends with a commit.
