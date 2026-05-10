# MCP Gateway Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mutations on local, remote, and admin MCP gateways propagate live to
the persona-McpTab and chat-cockpit "tools" mouseover, with no duplicates on
WebSocket reconnect.

**Architecture:** Lock down tier ownership: local gateways are entirely
frontend-driven (mutators sync `sessionGateways` and notify the backend via
WS messages); admin/remote gateways are backend-driven (REST mutation
handlers proactively re-discover and emit `MCP_TOOLS_REGISTERED` so the
frontend reflects the change without waiting for the next inference). The
event payload itself is filtered to `tier ∈ {admin, remote}` so the frontend
never re-merges a local entry it already owns.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest;
React / TypeScript / Zustand / Vitest.

**Spec:** `devdocs/specs/2026-05-10-mcp-gateway-sync-design.md`

**Branch:** `fix/mcp-gateway-sync` (already created)

---

## File structure

Backend, modified:
- `backend/modules/tools/__init__.py` — `eager_discover_mcp` filters local-tier out of event payload
- `backend/modules/tools/_mcp_registry.py` — new `unregister_by_id` method
- `backend/ws/router.py` — new `mcp.tools.deregister` WS handler case
- `backend/modules/user/_handlers.py` — replace `_invalidate_user_mcp` calls with `_refresh_user_mcp`; replace bare `invalidate_mcp_registries()` with `_refresh_all_mcp`

Backend, new tests:
- `tests/modules/tools/test_eager_discover_mcp_filters_local.py`
- `tests/test_mcp_registry.py` — extend existing file
- `tests/ws/test_router_mcp_deregister.py`
- `tests/modules/user/test_refresh_mcp_helpers.py` (or similar location matching existing user-handler test layout)

Frontend, modified:
- `frontend/src/features/mcp/useMcpEvents.ts` — extract `syncLocalGatewayToBackend` helper from `registerLocalGateways`
- `frontend/src/features/mcp/mcpStore.ts` — extend three mutators to keep `sessionGateways` in sync and notify backend
- `frontend/src/app/components/user-modal/McpTab.tsx` — `await` the now-async `addLocalGateway`/`updateLocalGateway`

Frontend, new tests:
- `frontend/src/features/mcp/__tests__/mcpStore.test.ts`
- `frontend/src/features/mcp/__tests__/useMcpEvents.test.ts`

---

## Task ordering rationale

Backend first (DTO/contract changes ripple forward), and within backend the
smallest isolated fix first (Task 1 → Bug #2 alone). Frontend after backend
is stable. Final verification last.

---

## Task 1: Backend — filter `tier="local"` out of `MCP_TOOLS_REGISTERED`

This single-line guard fixes Bug #2 (duplicate local entries after Strg+F5)
in isolation. Locking it in first means subsequent tasks see a clean event
contract.

**Files:**
- Modify: `backend/modules/tools/__init__.py:357-371`
- Test: `tests/modules/tools/test_eager_discover_mcp_filters_local.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/modules/tools/test_eager_discover_mcp_filters_local.py`:

```python
"""Regression: MCP_TOOLS_REGISTERED must not echo local-tier gateways back."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from shared.dtos.inference import ToolDefinition


def _make_handle(name: str, tier: str) -> GatewayHandle:
    return GatewayHandle(
        id=f"gw-{name}",
        name=name,
        url=f"http://{name}.example/mcp",
        api_key=None,
        tier=tier,
        tool_definitions=[
            ToolDefinition(
                name=f"{name}__ping",
                description="ping",
                parameters={},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_eager_discover_mcp_event_excludes_local_tier():
    """Pre-populate the registry with local + remote, force eager_discover_mcp
    to emit, and assert the published event payload contains no tier=local
    entries."""
    from backend.modules.tools import (
        eager_discover_mcp,
        set_mcp_registry,
        remove_mcp_registry,
    )

    connection_id = "conn-test-filter-local"
    user_id = "user-test"

    registry = SessionMcpRegistry()
    registry.register(_make_handle("local_gw", "local"))
    registry.register(_make_handle("remote_gw", "remote"))
    # Mark backend_discovered=False so eager_discover_mcp does NOT short-circuit
    set_mcp_registry(connection_id, registry)

    captured: list = []

    class _FakeBus:
        async def publish(self, topic, event, **kwargs):
            captured.append((topic, event))

    with patch(
        "backend.modules.user.get_admin_mcp_gateways",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.modules.user.get_user_mcp_gateways",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.ws.event_bus.get_event_bus",
        return_value=_FakeBus(),
    ):
        await eager_discover_mcp(connection_id, user_id)

    remove_mcp_registry(connection_id)

    # Event was emitted because the registry already had gateways
    assert len(captured) == 1, f"Expected 1 event, got {len(captured)}"
    _topic, event = captured[0]
    namespaces = [g.namespace for g in event.gateways]
    assert "remote_gw" in namespaces
    assert "local_gw" not in namespaces, (
        f"Local-tier gateway leaked into MCP_TOOLS_REGISTERED payload: "
        f"{namespaces}"
    )
```

- [ ] **Step 2: Run the test, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/modules/tools/test_eager_discover_mcp_filters_local.py -v`
Expected: FAIL — `local_gw` is currently included in the event payload.

- [ ] **Step 3: Add the filter in `tools/__init__.py:357-371`**

Locate the comprehension in `eager_discover_mcp`:

```python
gateway_entries = [
    McpGatewayToolEntry(
        namespace=gw.name,
        tier=gw.tier,
        tools=[
            {
                "name": td.name,
                "description": td.description,
                "server_name": mcp_registry.server_name_for_tool(td.name) or "_unknown",
            }
            for td in gw.tool_definitions
        ],
        collisions=gw.collisions,
    )
    for gw in mcp_registry.gateways.values()
]
```

Add a tier guard on the source iteration:

```python
gateway_entries = [
    McpGatewayToolEntry(
        namespace=gw.name,
        tier=gw.tier,
        tools=[
            {
                "name": td.name,
                "description": td.description,
                "server_name": mcp_registry.server_name_for_tool(td.name) or "_unknown",
            }
            for td in gw.tool_definitions
        ],
        collisions=gw.collisions,
    )
    for gw in mcp_registry.gateways.values()
    if gw.tier != "local"
]
```

Note the surrounding `if mcp_registry.gateways:` guard at the start of the
emission block: leave it as is. The block still emits when there is at
least one non-local gateway; if the only gateway in the registry is a
local one, no event is needed (the frontend already owns that state).
Actually — to be safe, guard the emit on a non-empty `gateway_entries`:

```python
if gateway_entries:
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.MCP_TOOLS_REGISTERED,
        ...
    )
```

Replace the existing `if mcp_registry.gateways:` with `if gateway_entries:`.

- [ ] **Step 4: Run the test, expect pass**

Run: `PYTHONPATH=. uv run pytest tests/modules/tools/test_eager_discover_mcp_filters_local.py -v`
Expected: PASS.

- [ ] **Step 5: Run the surrounding test suite (regression)**

Run: `PYTHONPATH=. uv run pytest tests/modules/tools/ tests/test_mcp_registry.py tests/test_mcp_executor.py -v`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/__init__.py tests/modules/tools/test_eager_discover_mcp_filters_local.py
git commit -m "MCP_TOOLS_REGISTERED event excludes tier=local entries"
```

---

## Task 2: Backend — `SessionMcpRegistry.unregister_by_id`

Pure method addition; no behaviour change unless called.

**Files:**
- Modify: `backend/modules/tools/_mcp_registry.py`
- Test: `tests/test_mcp_registry.py` (extend existing file)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_registry.py` inside `class TestSessionMcpRegistry:`:

```python
    def test_unregister_by_id_removes_handle_and_indices(self):
        reg = SessionMcpRegistry()
        handle = _make_handle(name="gw1")
        reg.register(handle)
        # Sanity: tool resolvable before unregister
        gw, _ = reg.resolve("gw1__read_file")
        assert gw.id == "gw-1"

        removed = reg.unregister_by_id("gw-1")
        assert removed is True

        # Gateway gone
        assert reg.gateway_for_id("gw-1") is None
        assert "gw1" not in reg.gateways
        # Tool indices pruned — resolve raises KeyError
        with pytest.raises(KeyError):
            reg.resolve("gw1__read_file")
        assert reg.is_mcp_tool("gw1__read_file") is False

    def test_unregister_by_id_unknown_returns_false(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="gw1"))
        assert reg.unregister_by_id("does-not-exist") is False
        # Original registration still intact
        assert reg.gateway_for_id("gw-1") is not None
```

- [ ] **Step 2: Run the test, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_registry.py -v -k "unregister_by_id"`
Expected: FAIL with `AttributeError: ... has no attribute 'unregister_by_id'`.

- [ ] **Step 3: Add the method**

In `backend/modules/tools/_mcp_registry.py`, inside `class SessionMcpRegistry`, add after the existing `gateway_for_id` method:

```python
    def unregister_by_id(self, gateway_id: str) -> bool:
        """Remove a gateway by its config id and prune its tool indices.

        Returns True if a gateway was removed, False if no gateway with
        the given id was registered. Idempotent — calling on an unknown
        id is a no-op.
        """
        handle = self.gateway_for_id(gateway_id)
        if handle is None:
            return False
        self._gateways.pop(handle.name, None)
        for td in handle.tool_definitions:
            self._tool_index.pop(td.name, None)
        for server_tools in handle.server_tools.values():
            for td in server_tools:
                self._tool_server_index.pop(td.name, None)
        return True
```

- [ ] **Step 4: Run the test, expect pass**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_registry.py -v`
Expected: ALL tests PASS (existing + the two new ones).

- [ ] **Step 5: Verify backend syntax**

Run: `uv run python -m py_compile backend/modules/tools/_mcp_registry.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_registry.py tests/test_mcp_registry.py
git commit -m "Add SessionMcpRegistry.unregister_by_id with index cleanup"
```

---

## Task 3: Backend — `mcp.tools.deregister` WS handler

**Files:**
- Modify: `backend/ws/router.py:325-353` (add new `elif` case after the existing `mcp.tools.register` block)
- Test: `tests/ws/test_router_mcp_deregister.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/ws/test_router_mcp_deregister.py`. Look at existing
`tests/ws/test_router.py` to see the WS-router test pattern. The test
sets up a registry, dispatches a fake `mcp.tools.deregister` message
through the router's message dispatch, and asserts the registry no
longer holds the gateway.

If `tests/ws/test_router.py` exists and uses a fixture-based pattern,
match it. If the WS-router tests use a higher-level test client, prefer
a unit-style test that calls the deregister branch directly:

```python
"""Tests for the mcp.tools.deregister WS handler branch."""

import pytest
from unittest.mock import patch

from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from backend.modules.tools import set_mcp_registry, get_mcp_registry, remove_mcp_registry
from shared.dtos.inference import ToolDefinition


def _make_handle(gw_id: str, name: str, tier: str = "local") -> GatewayHandle:
    return GatewayHandle(
        id=gw_id,
        name=name,
        url="",
        api_key=None,
        tier=tier,
        tool_definitions=[
            ToolDefinition(
                name=f"{name}__do_thing",
                description="d",
                parameters={},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_deregister_removes_local_gateway_from_registry():
    connection_id = "conn-deregister-1"
    registry = SessionMcpRegistry()
    registry.register(_make_handle("gw-keep", "keepme", tier="local"))
    registry.register(_make_handle("gw-drop", "dropme", tier="local"))
    set_mcp_registry(connection_id, registry)

    try:
        # Inline replay of the router's deregister branch logic — this
        # tests the *behaviour* required of the handler. The handler's
        # actual placement in router.py is verified by inspection.
        payload = {"gateway_id": "gw-drop"}
        gateway_id = payload.get("gateway_id")
        reg = get_mcp_registry(connection_id)
        assert reg is not None
        removed = reg.unregister_by_id(gateway_id)

        assert removed is True
        assert reg.gateway_for_id("gw-drop") is None
        assert reg.gateway_for_id("gw-keep") is not None
    finally:
        remove_mcp_registry(connection_id)


@pytest.mark.asyncio
async def test_deregister_unknown_gateway_is_no_op():
    connection_id = "conn-deregister-2"
    registry = SessionMcpRegistry()
    registry.register(_make_handle("gw-keep", "keepme", tier="local"))
    set_mcp_registry(connection_id, registry)

    try:
        removed = registry.unregister_by_id("does-not-exist")
        assert removed is False
        assert registry.gateway_for_id("gw-keep") is not None
    finally:
        remove_mcp_registry(connection_id)
```

This file exercises the registry-level behaviour the WS branch will
invoke. The structural assertion (the `elif` exists in router.py) is
covered by the spec-compliance review reading the diff.

- [ ] **Step 2: Run the test, expect pass**

Run: `PYTHONPATH=. uv run pytest tests/ws/test_router_mcp_deregister.py -v`
Expected: PASS — these tests rely on the `unregister_by_id` method
shipped in Task 2; they should pass before the router change because
they exercise the registry directly. The router-level `elif` is added
in step 3 below for the production code path.

- [ ] **Step 3: Add the WS handler branch in `backend/ws/router.py`**

Locate the `elif msg_type == "mcp.tools.register":` block at line 325. Add a new branch immediately after it (before the next `elif`):

```python
            elif msg_type == "mcp.tools.deregister":
                payload = data.get("payload", data)
                gateway_id = payload.get("gateway_id") if isinstance(payload, dict) else None
                if not isinstance(gateway_id, str) or not gateway_id:
                    _log.warning(
                        "malformed mcp.tools.deregister from user=%s connection=%s",
                        user_id, connection_id,
                    )
                else:
                    registry = get_mcp_registry(connection_id)
                    if registry is not None:
                        removed = registry.unregister_by_id(gateway_id)
                        _log.info(
                            "Deregistered local MCP gateway id=%s for user=%s (removed=%s)",
                            gateway_id, user_id, removed,
                        )
```

- [ ] **Step 4: Verify backend syntax**

Run: `uv run python -m py_compile backend/ws/router.py`
Expected: no output.

- [ ] **Step 5: Run the deregister + WS-router test suite**

Run: `PYTHONPATH=. uv run pytest tests/ws/test_router_mcp_deregister.py tests/ws/test_router.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/ws/router.py tests/ws/test_router_mcp_deregister.py
git commit -m "Add mcp.tools.deregister WS handler"
```

---

## Task 4: Backend — proactive `_refresh_user_mcp` and `_refresh_all_mcp`

Replace the lazy invalidation pattern with eager re-discovery so the
`MCP_TOOLS_REGISTERED` event fires immediately after a remote/admin
mutation.

**Files:**
- Modify: `backend/modules/user/_handlers.py:1281-1286` (replace `_invalidate_user_mcp` body or add a new helper alongside; update the four call sites)
- Modify: `backend/modules/user/_handlers.py` admin handlers around lines 1423, 1454, 1471
- Test: location matching existing user-handler tests; if none, create `tests/modules/user/test_mcp_refresh_helpers.py` (new)

- [ ] **Step 1: Identify existing user-handler test directory**

Run: `ls tests/modules/user/ 2>/dev/null`
- If a `tests/modules/user/` directory exists, place the new test there as `test_mcp_refresh_helpers.py`.
- Otherwise create the directory and an `__init__.py` first, then the test file.

- [ ] **Step 2: Write the failing test**

Create the file from step 1 with:

```python
"""Tests for proactive MCP registry refresh helpers."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from backend.modules.tools import set_mcp_registry, remove_mcp_registry
from shared.dtos.inference import ToolDefinition


def _make_handle(name: str, tier: str = "remote") -> GatewayHandle:
    return GatewayHandle(
        id=f"gw-{name}",
        name=name,
        url=f"http://{name}.example/mcp",
        api_key=None,
        tier=tier,
        tool_definitions=[
            ToolDefinition(name=f"{name}__ping", description="p", parameters={}),
        ],
    )


@pytest.mark.asyncio
async def test_refresh_user_mcp_invalidates_and_rediscovers():
    """After _refresh_user_mcp, registries for the user's connections are
    cleared and eager_discover_mcp is invoked once per connection."""
    from backend.modules.user import _handlers

    user_id = "user-refresh-1"
    cid_a = "conn-a"
    cid_b = "conn-b"

    registry_a = SessionMcpRegistry()
    registry_a.register(_make_handle("old_gw"))
    registry_a.backend_discovered = True
    set_mcp_registry(cid_a, registry_a)

    registry_b = SessionMcpRegistry()
    registry_b.register(_make_handle("other"))
    registry_b.backend_discovered = True
    set_mcp_registry(cid_b, registry_b)

    eager_calls: list[tuple[str, str]] = []

    class _FakeManager:
        def connection_ids_for_user(self, uid: str) -> list[str]:
            return [cid_a, cid_b] if uid == user_id else []

    async def _fake_eager(connection_id: str, uid: str) -> None:
        eager_calls.append((connection_id, uid))

    try:
        with patch.object(_handlers, "get_manager", return_value=_FakeManager()), \
             patch("backend.modules.tools.eager_discover_mcp", new=_fake_eager):
            await _handlers._refresh_user_mcp(user_id)

        assert sorted(eager_calls) == [(cid_a, user_id), (cid_b, user_id)]
    finally:
        remove_mcp_registry(cid_a)
        remove_mcp_registry(cid_b)


@pytest.mark.asyncio
async def test_refresh_user_mcp_no_active_connections_is_noop():
    from backend.modules.user import _handlers

    user_id = "user-refresh-empty"
    eager_calls: list = []

    class _EmptyManager:
        def connection_ids_for_user(self, uid: str) -> list[str]:
            return []

    async def _fake_eager(connection_id: str, uid: str) -> None:
        eager_calls.append((connection_id, uid))

    with patch.object(_handlers, "get_manager", return_value=_EmptyManager()), \
         patch("backend.modules.tools.eager_discover_mcp", new=_fake_eager):
        await _handlers._refresh_user_mcp(user_id)

    assert eager_calls == []
```

- [ ] **Step 3: Run the test, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/modules/user/test_mcp_refresh_helpers.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_refresh_user_mcp'`.

- [ ] **Step 4: Add the helpers in `backend/modules/user/_handlers.py`**

Locate `_invalidate_user_mcp` (around line 1281). Keep it as-is (other code may still call it indirectly), and add new helpers above it:

```python
async def _refresh_user_mcp(user_id: str) -> None:
    """Clear and immediately rediscover MCP registries for a user.

    Triggers MCP_TOOLS_REGISTERED emission for every active connection
    of the user, so persona-McpTab and the cockpit tools list reflect
    the change without waiting for the next inference.
    """
    from backend.ws.manager import get_manager
    from backend.modules.tools import (
        invalidate_mcp_registries,
        eager_discover_mcp,
    )
    cids = get_manager().connection_ids_for_user(user_id)
    if not cids:
        return
    invalidate_mcp_registries(cids)
    for cid in cids:
        await eager_discover_mcp(cid, user_id)


async def _refresh_all_mcp() -> None:
    """Admin gateway change: refresh registries for every active connection
    of every user. Sequential — admin changes are infrequent."""
    from backend.ws.manager import get_manager
    from backend.modules.tools import (
        invalidate_mcp_registries,
        eager_discover_mcp,
    )
    invalidate_mcp_registries()
    manager = get_manager()
    # Snapshot — connection map can mutate while we await
    user_ids = list(manager._connections.keys())
    for user_id in user_ids:
        for cid in manager.connection_ids_for_user(user_id):
            await eager_discover_mcp(cid, user_id)
```

- [ ] **Step 5: Run the test, expect pass**

Run: `PYTHONPATH=. uv run pytest tests/modules/user/test_mcp_refresh_helpers.py -v`
Expected: PASS — both tests green.

- [ ] **Step 6: Replace call sites in user remote-MCP handlers**

In `backend/modules/user/_handlers.py`, three call sites to `_invalidate_user_mcp(user["sub"])` exist in:
- `create_mcp_gateway` (line 1321)
- `update_mcp_gateway` (line 1350)
- `delete_mcp_gateway` (line 1368)

Each currently looks like:

```python
_invalidate_user_mcp(user["sub"])
```

Change each to:

```python
await _refresh_user_mcp(user["sub"])
```

(All three handlers are already `async def`, so no signature change is needed.)

- [ ] **Step 7: Replace call sites in admin-MCP handlers**

Three call sites to `invalidate_mcp_registries()` (no args, "all users") exist around lines 1423, 1454, 1471 in admin handlers. Each currently looks like:

```python
invalidate_mcp_registries()  # admin change affects all users
```

Change each to:

```python
await _refresh_all_mcp()
```

If a handler is not currently `async def`, make it so. Verify by searching for the surrounding `async def` headers.

- [ ] **Step 8: Verify backend syntax + run user-handler tests**

Run:
```bash
uv run python -m py_compile backend/modules/user/_handlers.py
PYTHONPATH=. uv run pytest tests/modules/user/ -v
```
Expected: compile clean, all user-handler tests pass (including the new helpers test).

- [ ] **Step 9: Commit**

```bash
git add backend/modules/user/_handlers.py tests/modules/user/test_mcp_refresh_helpers.py
git commit -m "Replace lazy MCP invalidation with proactive refresh + event emit"
```

If a `tests/modules/user/__init__.py` had to be created, include it in the commit.

---

## Task 5: Frontend — extract `syncLocalGatewayToBackend` helper

The existing `registerLocalGateways` function (`useMcpEvents.ts:35`) does
per-gateway work that we want to call from `mcpStore` mutators too. Lift
the per-gateway loop body into a reusable helper.

**Files:**
- Modify: `frontend/src/features/mcp/useMcpEvents.ts`

- [ ] **Step 1: Read current `registerLocalGateways` carefully**

Open `frontend/src/features/mcp/useMcpEvents.ts:35-82`. Note:
- It currently iterates `localGateways`, discovering each via `mcpToolsList`, sending `mcp.tools.register`, and accumulating local entries to merge into `sessionGateways` at the end.
- The merge uses `filter(tier !== "local")` to keep existing non-local entries.

- [ ] **Step 2: Refactor — extract per-gateway helper, keep `registerLocalGateways` as the orchestrator**

Replace the contents of `useMcpEvents.ts` (specifically the helper section before `useMcpEvents`) so that a per-gateway helper exists alongside the bulk path:

```typescript
import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { useNotificationStore } from "../../core/store/notificationStore"
import { useEventStore } from "../../core/store/eventStore"
import { useMcpStore } from "./mcpStore"
import { sendMessage } from "../../core/websocket/connection"
import { mcpToolsList } from "./mcpClient"
import type { BaseEvent } from "../../core/types/events"
import { Topics } from "../../core/types/events"
import type { McpGatewayConfig, McpSessionGateway } from "./types"

interface McpGatewayErrorPayload {
  gateway_name: string
  error: string
  recoverable: boolean
}

interface McpGatewayToolEntry {
  namespace: string
  tier: 'admin' | 'remote' | 'local'
  tools: Array<{ name: string; description: string; server_name: string }>
  collisions: string[]
}

interface McpToolsRegisteredPayload {
  session_id: string
  gateways: McpGatewayToolEntry[]
  total_tools: number
}

function namespaceFromName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

/**
 * Discover one local gateway and register its tools with the backend.
 * Returns the corresponding McpSessionGateway entry on success, or null
 * if the gateway was unreachable / yielded no tools.
 *
 * Called from registerLocalGateways (WS-connect bulk path) AND from
 * mcpStore mutators (per-mutation path).
 */
export async function syncLocalGatewayToBackend(
  gw: McpGatewayConfig,
): Promise<McpSessionGateway | null> {
  if (!gw.enabled) return null
  try {
    const { tools } = await mcpToolsList(gw.url, gw.api_key)
    if (tools.length === 0) return null

    sendMessage({
      type: "mcp.tools.register",
      payload: {
        gateway_id: gw.id,
        name: gw.name,
        tier: "local",
        tools: tools.map((t) => ({
          name: t.name,
          description: t.description,
          parameters: t.inputSchema ?? {},
        })),
      },
    })

    const ns = namespaceFromName(gw.name)
    return {
      namespace: ns,
      tier: "local" as const,
      tools: tools.map((t) => ({
        name: `${ns}__${t.name}`,
        description: t.description,
        server_name: t._gateway_server ?? gw.name,
      })),
      collisions: [],
    }
  } catch {
    return null
  }
}

/**
 * Discover tools from all enabled local gateways and register them with
 * the backend via WebSocket so they are available during inference.
 * Called once on WebSocket connect.
 */
async function registerLocalGateways(): Promise<void> {
  const gateways = useMcpStore.getState().localGateways
  const localEntries: McpSessionGateway[] = []

  for (const gw of gateways) {
    const entry = await syncLocalGatewayToBackend(gw)
    if (entry) localEntries.push(entry)
  }

  if (localEntries.length > 0) {
    const existing = useMcpStore.getState().sessionGateways.filter((e) => e.tier !== "local")
    useMcpStore.getState().setSessionGateways([...existing, ...localEntries])
  }
}
```

The rest of the file (the `useMcpEvents` hook and `MCP_TOOLS_REGISTERED` listener) stays unchanged.

- [ ] **Step 3: Verify TS type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Run useMcpEvents tests if any exist (regression)**

Run: `cd frontend && pnpm vitest run src/features/mcp/`
Expected: existing tests stay green. (Task 6 adds new mcpStore tests; Task 7's user-modal tests if they exercise this path should still pass.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/mcp/useMcpEvents.ts
git commit -m "Extract syncLocalGatewayToBackend helper for per-gateway sync"
```

---

## Task 6: Frontend — `mcpStore` mutators sync `sessionGateways` and notify backend

**Files:**
- Modify: `frontend/src/features/mcp/mcpStore.ts`
- Test: `frontend/src/features/mcp/__tests__/mcpStore.test.ts` (new)

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/mcp/__tests__/mcpStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useMcpStore } from '../mcpStore'
import type { McpGatewayConfig, McpSessionGateway } from '../types'

const sendMessageMock = vi.fn()
vi.mock('../../../core/websocket/connection', () => ({
  sendMessage: (...args: unknown[]) => sendMessageMock(...args),
}))

const syncLocalGatewayToBackendMock = vi.fn<(gw: McpGatewayConfig) => Promise<McpSessionGateway | null>>()
vi.mock('../useMcpEvents', () => ({
  syncLocalGatewayToBackend: (gw: McpGatewayConfig) => syncLocalGatewayToBackendMock(gw),
}))

function makeGateway(overrides: Partial<McpGatewayConfig> = {}): McpGatewayConfig {
  return {
    id: 'gw-test',
    name: 'Test Gateway',
    url: 'http://localhost:9999',
    api_key: null,
    enabled: true,
    disabled_tools: [],
    server_configs: {},
    tool_overrides: [],
    ...overrides,
  }
}

function makeSessionEntry(namespace: string): McpSessionGateway {
  return {
    namespace,
    tier: 'local' as const,
    tools: [
      { name: `${namespace}__do_thing`, description: '', server_name: 'srv' },
    ],
    collisions: [],
  }
}

describe('mcpStore mutators sync sessionGateways and notify backend', () => {
  beforeEach(() => {
    sendMessageMock.mockReset()
    syncLocalGatewayToBackendMock.mockReset()
    localStorage.clear()
    useMcpStore.setState({ localGateways: [], sessionGateways: [] })
  })

  afterEach(() => {
    useMcpStore.setState({ localGateways: [], sessionGateways: [] })
  })

  it('addLocalGateway: discovers, sends mcp.tools.register, appends to sessionGateways', async () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    syncLocalGatewayToBackendMock.mockResolvedValueOnce(makeSessionEntry('one'))

    await useMcpStore.getState().addLocalGateway(gw)

    expect(syncLocalGatewayToBackendMock).toHaveBeenCalledWith(gw)
    const session = useMcpStore.getState().sessionGateways
    expect(session).toHaveLength(1)
    expect(session[0]?.namespace).toBe('one')
  })

  it('addLocalGateway: gracefully handles unreachable gateway (no sessionGateways change)', async () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    syncLocalGatewayToBackendMock.mockResolvedValueOnce(null)

    await useMcpStore.getState().addLocalGateway(gw)

    expect(useMcpStore.getState().sessionGateways).toHaveLength(0)
  })

  it('deleteLocalGateway: sends mcp.tools.deregister and removes from sessionGateways', () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    useMcpStore.setState({
      localGateways: [gw],
      sessionGateways: [makeSessionEntry('one')],
    })

    useMcpStore.getState().deleteLocalGateway('gw-1')

    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: 'gw-1' },
    })
    expect(useMcpStore.getState().sessionGateways).toHaveLength(0)
    expect(useMcpStore.getState().localGateways).toHaveLength(0)
  })

  it('deleteLocalGateway: unknown id is a no-op (no message, no state change)', () => {
    const gw = makeGateway({ id: 'gw-1', name: 'one' })
    useMcpStore.setState({
      localGateways: [gw],
      sessionGateways: [makeSessionEntry('one')],
    })

    useMcpStore.getState().deleteLocalGateway('does-not-exist')

    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(useMcpStore.getState().sessionGateways).toHaveLength(1)
    expect(useMcpStore.getState().localGateways).toHaveLength(1)
  })

  it('updateLocalGateway: deregisters then re-registers and replaces session entry', async () => {
    const gw = makeGateway({ id: 'gw-1', name: 'old' })
    useMcpStore.setState({
      localGateways: [gw],
      sessionGateways: [makeSessionEntry('old')],
    })
    syncLocalGatewayToBackendMock.mockResolvedValueOnce(makeSessionEntry('new'))

    await useMcpStore.getState().updateLocalGateway('gw-1', { name: 'new', url: 'http://different' })

    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: 'gw-1' },
    })
    expect(syncLocalGatewayToBackendMock).toHaveBeenCalledOnce()
    const session = useMcpStore.getState().sessionGateways
    expect(session).toHaveLength(1)
    expect(session[0]?.namespace).toBe('new')
  })
})
```

- [ ] **Step 2: Run the tests, expect failure**

Run: `cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpStore.test.ts`
Expected: FAIL — current mutators don't touch sessionGateways or call sendMessage.

- [ ] **Step 3: Update the three mutators in `frontend/src/features/mcp/mcpStore.ts`**

Replace the file contents:

```typescript
import { create } from 'zustand'
import { sendMessage } from '../../core/websocket/connection'
import { syncLocalGatewayToBackend } from './useMcpEvents'
import type { McpGatewayConfig, McpSessionGateway } from './types'

const LOCAL_STORAGE_KEY = 'chatsune:mcp_local_gateways'

interface McpState {
  /** User's local gateways (localStorage, this device only) */
  localGateways: McpGatewayConfig[]
  /** All discovered MCP gateways for current session (set after discovery) */
  sessionGateways: McpSessionGateway[]

  loadLocalGateways: () => void
  addLocalGateway: (gw: McpGatewayConfig) => Promise<void>
  updateLocalGateway: (id: string, updates: Partial<McpGatewayConfig>) => Promise<void>
  deleteLocalGateway: (id: string) => void
  setSessionGateways: (gateways: McpSessionGateway[]) => void
  clearSessionGateways: () => void
}

function migrateGateway(gw: McpGatewayConfig): McpGatewayConfig {
  return {
    ...gw,
    server_configs: gw.server_configs ?? {},
    tool_overrides: gw.tool_overrides ?? [],
  }
}

function readLocalGateways(): McpGatewayConfig[] {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as McpGatewayConfig[]) : []
  } catch {
    return []
  }
}

function writeLocalGateways(gateways: McpGatewayConfig[]): void {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(gateways))
}

function namespaceFromName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

export const useMcpStore = create<McpState>((set, get) => ({
  localGateways: [],
  sessionGateways: [],

  loadLocalGateways: () => {
    set({ localGateways: readLocalGateways().map(migrateGateway) })
  },

  addLocalGateway: async (gw) => {
    const updated = [...get().localGateways, gw]
    writeLocalGateways(updated)
    set({ localGateways: updated })

    const entry = await syncLocalGatewayToBackend(gw)
    if (entry) {
      set((s) => ({
        sessionGateways: [
          ...s.sessionGateways.filter((e) => e.namespace !== entry.namespace),
          entry,
        ],
      }))
    }
  },

  updateLocalGateway: async (id, updates) => {
    const updated = get().localGateways.map((gw) =>
      gw.id === id ? { ...gw, ...updates } : gw,
    )
    writeLocalGateways(updated)
    set({ localGateways: updated })

    const next = updated.find((gw) => gw.id === id)
    if (!next) return

    // Deregister the old namespace (URL/name may have changed) and re-register fresh.
    sendMessage({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: id },
    })

    // Drop any old session entry under the previous namespace as well.
    set((s) => ({
      sessionGateways: s.sessionGateways.filter(
        (e) => !(e.tier === 'local' && e.namespace === namespaceFromName(next.name)),
      ),
    }))

    const entry = await syncLocalGatewayToBackend(next)
    if (entry) {
      set((s) => ({
        sessionGateways: [
          ...s.sessionGateways.filter((e) => e.namespace !== entry.namespace),
          entry,
        ],
      }))
    }
  },

  deleteLocalGateway: (id) => {
    const removed = get().localGateways.find((gw) => gw.id === id)
    if (!removed) return

    const updated = get().localGateways.filter((gw) => gw.id !== id)
    writeLocalGateways(updated)
    const ns = namespaceFromName(removed.name)
    set((s) => ({
      localGateways: updated,
      sessionGateways: s.sessionGateways.filter(
        (e) => !(e.tier === 'local' && e.namespace === ns),
      ),
    }))

    sendMessage({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: id },
    })
  },

  setSessionGateways: (gateways) => set({ sessionGateways: gateways }),
  clearSessionGateways: () => set({ sessionGateways: [] }),
}))
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `cd frontend && pnpm vitest run src/features/mcp/__tests__/mcpStore.test.ts`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Run TS type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: clean. (Callers of `addLocalGateway` / `updateLocalGateway` are now Promise-returning. The user-modal callers are updated in Task 7.)

If type-check surfaces compile errors at the caller sites, that's expected — they're fixed in Task 7. Note any errors in the commit message of Task 7.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/mcp/mcpStore.ts frontend/src/features/mcp/__tests__/mcpStore.test.ts
git commit -m "Sync sessionGateways inline + notify backend on local gateway mutations"
```

---

## Task 7: Frontend — update callers in `user-modal/McpTab.tsx`

`addLocalGateway` and `updateLocalGateway` are now `async`. Two call sites
in `frontend/src/app/components/user-modal/McpTab.tsx` need `await`.

**Files:**
- Modify: `frontend/src/app/components/user-modal/McpTab.tsx:235-250`

- [ ] **Step 1: Read the current call sites**

Open `frontend/src/app/components/user-modal/McpTab.tsx` around lines 235-250. Note `handleSaveLocal` and `handleDeleteLocal` and how they're invoked.

- [ ] **Step 2: Make `handleSaveLocal` async + add awaits**

Replace the function:

```typescript
  // ── save handlers for local gateways ──
  async function handleSaveLocal(data: McpGatewayConfig, original?: McpGatewayConfig) {
    if (original) {
      await useMcpStore.getState().updateLocalGateway(original.id, data)
    } else {
      await useMcpStore.getState().addLocalGateway({
        ...data,
        id: crypto.randomUUID(),
      })
    }
    setView({ kind: 'list' })
  }
```

`handleDeleteLocal` stays synchronous — `deleteLocalGateway` is still sync.

- [ ] **Step 3: Verify the caller is comfortable with `async` handler**

Look up where `handleSaveLocal` is passed as a prop (likely as `onSave={handleSaveLocal}` on a `GatewayEditDialog`). Confirm the dialog calls `onSave(...)` without expecting a return value (fire-and-forget) — no further changes needed.

If the dialog awaits the result, you'll see TypeScript happy with an
async handler returning `Promise<void>`. If the prop type insists on
`void`, leave a `void`-returning wrapper:

```typescript
const onSave = (data: McpGatewayConfig, original?: McpGatewayConfig) => {
  void handleSaveLocal(data, original)
}
```

But prefer the direct async handler if the dialog accepts `Promise<void>` already.

- [ ] **Step 4: Verify TS type-check + production build**

Run:
```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm run build
```
Expected: both clean.

- [ ] **Step 5: Run the full frontend test suite (regression)**

Run: `cd frontend && pnpm vitest run`
Expected: existing tests stay green; the new `mcpStore.test.ts` from Task 6 stays green.

If the existing user-modal McpTab test exists and exercises the save flow, it must still pass. If a small adjustment is needed (e.g., to await the handler in test setup), make it as part of this task — but only if the test clearly broke because of the async change, not for unrelated reasons.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/user-modal/McpTab.tsx
git commit -m "Await async local-gateway mutators in user-modal McpTab"
```

---

## Task 8: Final verification

Manual + automated, no commit.

- [ ] **Step 1: Frontend production build**

Run: `cd frontend && pnpm run build`
Expected: `✓ built` with no TS errors.

- [ ] **Step 2: Backend test suite (host-safe)**

The MongoDB-using test files must be excluded on host (per `db_tests_on_host` rule). Adjust the ignore list to whatever the project already uses. One shape that works:

```bash
PYTHONPATH=. uv run pytest \
    --ignore=tests/integration \
    --ignore=tests/modules/persona/test_repository.py \
    --ignore=tests/modules/user/test_repository.py \
    --ignore=tests/modules/chat/test_repository.py \
    -q
```
Expected: all green.

- [ ] **Step 3: Manual verification per spec §6**

Run the 8 scenarios from `devdocs/specs/2026-05-10-mcp-gateway-sync-design.md` §6 against the live dev stack:

1. Local add — live propagation
2. Local delete — live removal
3. Local update — re-discovery
4. Reload stability (Strg+F5 produces exactly 1 entry per gateway, repeated)
5. Remote add via REST UI — live propagation
6. Remote delete via REST UI — live removal
7. Admin gateway change with another user online
8. Backend log audit — no `tier: "local"` in `MCP_TOOLS_REGISTERED` event payload

- [ ] **Step 4: STOP**

Subagent does NOT merge to master, does NOT push, does NOT switch branches.
Report back with: list of commits on `fix/mcp-gateway-sync`, frontend build
result, backend test result, and verification status (or what could not be
verified on host vs needs real-stack manual run).
