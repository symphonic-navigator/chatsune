# MCP Gateway Sync — Bug Fix Design

**Date:** 2026-05-10
**Status:** Draft
**Branch:** `fix/mcp-gateway-sync`

---

## 1. Context — two bugs, one architectural wound

Tester scenario surfaced two related defects in the MCP gateway / persona /
chat-tools synchronisation pipeline:

### Bug #1 — Stale UI after gateway mutation (all three tiers)

When a user adds, deletes, or updates an MCP gateway, the persona-McpTab
and the chat cockpit "tools" mouseover continue to show the pre-mutation
state until a hard reload (Strg+F5).

Code trace:

- `mcpStore.{add,delete,update}LocalGateway` mutate `localGateways` and
  localStorage immediately, but **do not** touch `sessionGateways`. Yet
  `sessionGateways` is what `frontend/src/app/components/persona-overlay/McpTab.tsx:22`
  and `frontend/src/features/chat/ChatView.tsx:431` read.
- `sessionGateways` is only populated on (a) `useMcpEvents.ts:101` at
  WebSocket-connect, and (b) inbound `MCP_TOOLS_REGISTERED` events.
- For admin and remote gateways the REST handlers (`backend/modules/user/_handlers.py:1281,1321,1350,1368,1423,1454,1471`)
  already call `invalidate_mcp_registries(...)`. But the `MCP_TOOLS_REGISTERED`
  re-emission only happens **lazily**, inside `_orchestrator.py:925-931`,
  on the next inference. Until then the frontend sees stale data.
- For local gateways the backend has no awareness of the mutation at all —
  no `mcp.tools.deregister` flow exists.

### Bug #2 — Local gateway duplicates after Strg+F5

After a hard reload the local gateway "test" appears twice in the persona
and the cockpit; another reload produces three; another reload produces two
again. The count drifts because of a Redis-Streams replay race interacting
with the live event emission.

Code trace:

- At WS-connect, `ws/router.py:186` schedules `eager_discover_mcp` as a
  background task and `useMcpEvents.ts:98` runs `registerLocalGateways`.
  Both write to the backend `SessionMcpRegistry` and the frontend
  `sessionGateways` store on overlapping timelines.
- `eager_discover_mcp` (`tools/__init__.py:357-371`) emits
  `MCP_TOOLS_REGISTERED` with `gateway_entries` that iterates **all**
  registered gateways — including any local ones already deposited by the
  earlier `mcp.tools.register` WS message.
- The frontend handler (`useMcpEvents.ts:116-131`) merges these `entries`
  with `locals = sessionGateways.filter(tier === "local")`. If the event
  payload already contains a local entry, it is now in both `entries` and
  `locals` → duplicated.
- Redis-Streams replay (the `since` parameter on reconnect) can re-deliver
  an older `MCP_TOOLS_REGISTERED` event in addition to the freshly emitted
  one, accounting for the variable count (2× / 3× / 2×) across reloads.

### The shared root cause

The synchronisation layer does not respect tier ownership:

- **Local** gateways are conceptually frontend-owned (per-device, in
  localStorage). The backend mirrors them only as long as the WS
  connection lives, for inference dispatch.
- **Remote** gateways are user-owned, persisted in the user document.
- **Admin** gateways are global, persisted in `admin_settings`.

Today both bugs follow from event paths that mix the tiers: the
`MCP_TOOLS_REGISTERED` event echoes back local gateways the frontend
already knows, and frontend mutators don't update the projection
`sessionGateways` that the persona-McpTab and cockpit read.

## 2. Goals & Non-Goals

**Goals**
- Mutations on any of the three tiers reflect in the persona-McpTab and
  cockpit-tools mouseover **without a reload**.
- Strg+F5 produces exactly one entry per gateway, regardless of how many
  reloads in succession or how often Redis replays a missed event.
- Tier ownership is encoded in the event payload contract:
  `MCP_TOOLS_REGISTERED` carries only backend-owned tiers (admin + remote);
  local gateways are entirely frontend-managed.
- Same UX across tiers — no "remote takes effect on next chat, local takes
  effect after F5".

**Non-goals**
- Fixing the post-reconnect registry leak in `_delayed_disconnect_cleanup`
  (`ws/router.py:67-83`). Old `connection_id`-keyed registries linger in
  `_mcp_registries` after a reconnect because the cleanup early-returns on
  `has_reconnect`. No user-visible impact (the leaked registry is keyed by
  a connection_id that no longer routes anywhere). Park as future work.
- Multi-tab consistency: a user with two browser tabs may add a local
  gateway in one tab and not see it in the other. localStorage is
  per-origin shared but `sessionGateways` is per-tab Zustand store.
  Defer; the same-tab fix already addresses the tester complaint.
- Admin runs gateway-discovery autonomously / push-style. The fix here is
  reactive: refresh on mutation, not on a schedule.
- New tool subscription / progress notification surface (out of scope; see
  INSIGHTS INS-044 for related Streamable-HTTP session lifecycle work).

## 3. Architecture — tier responsibilities

The shape that the fix locks in:

| Tier | Source of truth | Mutation triggers | Backend registry update | Frontend `sessionGateways` update |
|---|---|---|---|---|
| **local** | localStorage (this device) | `mcpStore.{add,delete,update}LocalGateway` | WS `mcp.tools.register` (existing) / `mcp.tools.deregister` (new) | inline in store mutators |
| **remote** | user document (DB) | REST `/user/mcp/gateways/...` | proactive `eager_discover_mcp` after `_invalidate_user_mcp` | via `MCP_TOOLS_REGISTERED` |
| **admin** | `admin_settings` doc | REST admin endpoints | proactive `eager_discover_mcp` for every active connection of every user | via `MCP_TOOLS_REGISTERED` |

`MCP_TOOLS_REGISTERED` event carries **only `tier ∈ {admin, remote}`** entries.
Local entries never appear in this event — they are entirely the frontend's
domain via the local-gateway store mutators.

## 4. Detailed Design

### 4.1 Backend: filter `tier="local"` out of `MCP_TOOLS_REGISTERED`

In `backend/modules/tools/__init__.py:357-371`, the `gateway_entries`
comprehension currently iterates `mcp_registry.gateways.values()`
unconditionally. Add a tier guard:

```python
gateway_entries = [
    McpGatewayToolEntry(
        namespace=gw.name,
        tier=gw.tier,
        tools=[...],
        collisions=gw.collisions,
    )
    for gw in mcp_registry.gateways.values()
    if gw.tier != "local"   # NEW: locals are frontend-owned
]
```

Same condition on the same comprehension wherever else
`McpToolsRegisteredEvent` is constructed (currently only this one site —
verify during implementation). This single line fixes Bug #2.

`McpToolsRegisteredEvent.gateways` payload type stays the same — we are
constraining what we put in, not the schema.

### 4.2 Backend: `SessionMcpRegistry.unregister(...)`

Add a method to `_mcp_registry.py` for removing a gateway by `gateway_id`:

```python
def unregister_by_id(self, gateway_id: str) -> bool:
    """Remove a gateway by its config id. Returns True if removed."""
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

Indexed by `gateway_id` rather than namespace because the WS message
payload from frontend is keyed by `gateway_id` (uuid), and the rename
case (which would change namespace) is handled by deregister-then-register
on the frontend side.

### 4.3 Backend: `mcp.tools.deregister` WS handler (new)

In `backend/ws/router.py`, add a new case mirroring `mcp.tools.register`
(`router.py:325-353`):

```python
elif msg_type == "mcp.tools.deregister":
    payload = data.get("payload", data)
    gateway_id = payload.get("gateway_id")
    if not gateway_id or not isinstance(gateway_id, str):
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

No event emission — local mutations are frontend-driven; the frontend
already updates its own `sessionGateways` synchronously.

### 4.4 Backend: proactive event emit for admin/remote mutations

Today `_invalidate_user_mcp(user_id)` (`backend/modules/user/_handlers.py:1281`)
clears registries; rediscovery happens lazily on the next inference. Add a
helper alongside it:

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
```

The four user-MCP CRUD handlers (`_handlers.py:1321,1350,1368` and the
patch path) replace `_invalidate_user_mcp(user_id)` with `await
_refresh_user_mcp(user_id)`.

For admin handlers (`_handlers.py:1423,1454,1471`) — they currently call
`invalidate_mcp_registries()` (None → all). Replace with:

```python
async def _refresh_all_mcp() -> None:
    """Admin gateway change: refresh registries for every active connection."""
    from backend.ws.manager import get_manager
    from backend.modules.tools import (
        invalidate_mcp_registries,
        eager_discover_mcp,
    )
    invalidate_mcp_registries()
    manager = get_manager()
    # Snapshot user list — the connection map can mutate while we await.
    user_ids = list(manager._connections.keys())
    for user_id in user_ids:
        for cid in manager.connection_ids_for_user(user_id):
            await eager_discover_mcp(cid, user_id)
```

Sequential (not gathered) — admin changes are infrequent and the
event-bus publish is the dominant cost; keeping it serial avoids
over-paralleling discovery against the same gateways.

### 4.5 Frontend: `mcpStore` mutators update `sessionGateways` and notify backend

In `frontend/src/features/mcp/mcpStore.ts`, the three local-gateway
mutators currently update only `localGateways` and `localStorage`. Extend
them to also keep `sessionGateways` in sync and signal the backend:

```typescript
addLocalGateway: async (gw) => {
  const updated = [...get().localGateways, gw]
  writeLocalGateways(updated)
  set({ localGateways: updated })

  // Discover tools, then both update local state + notify backend
  await syncLocalGatewayToBackend(gw, "register")
},

deleteLocalGateway: (id) => {
  const removed = get().localGateways.find((g) => g.id === id)
  const updated = get().localGateways.filter((gw) => gw.id !== id)
  writeLocalGateways(updated)
  set({ localGateways: updated })

  // Drop from sessionGateways immediately
  if (removed) {
    const ns = normaliseNamespace(removed.name)
    set((s) => ({
      sessionGateways: s.sessionGateways.filter((sg) => sg.namespace !== ns),
    }))
    // Tell backend
    sendMessage({ type: "mcp.tools.deregister", payload: { gateway_id: id } })
  }
},

updateLocalGateway: async (id, updates) => {
  const updated = get().localGateways.map((gw) =>
    gw.id === id ? { ...gw, ...updates } : gw,
  )
  writeLocalGateways(updated)
  set({ localGateways: updated })

  const next = updated.find((g) => g.id === id)
  if (next) {
    // Treat update as deregister + register so the namespace, URL, and
    // tool list are all refreshed cleanly.
    sendMessage({ type: "mcp.tools.deregister", payload: { gateway_id: id } })
    await syncLocalGatewayToBackend(next, "register")
  }
},
```

Where `syncLocalGatewayToBackend` is a small private helper extracted
from the existing `registerLocalGateways` body in `useMcpEvents.ts:35-82`
— discover tools via `mcpToolsList`, send `mcp.tools.register`, and merge
the new entry into `sessionGateways`. Lifting it into a shared helper
removes duplication between the WS-connect path and the per-mutation
paths.

`registerLocalGateways` (the WS-connect path) keeps its current shape; it
becomes one caller of `syncLocalGatewayToBackend` per gateway.

The `addLocalGateway` mutator becomes async to await discovery before
returning. The two callers (`user-modal/McpTab.tsx:239,237`) will need
`await` (see plan).

### 4.6 Frontend: nothing else changes for the event handler

Once §4.1 lands, the `MCP_TOOLS_REGISTERED` event payload carries only
admin/remote tiers, so the existing handler logic in `useMcpEvents.ts:116-131`
already does the right thing — `entries` (admin/remote) plus `locals`
(from store) without overlap. **No frontend handler change needed for
Bug #2** beyond §4.1. We confirm this with a test (§5.1).

## 5. Tests

### 5.1 Backend

- **`test_mcp_tools_registered_event_excludes_local`** — register a
  mixed registry (admin + remote + local) and assert the
  `McpToolsRegisteredEvent.gateways` payload contains only admin/remote.
  Direct regression for Bug #2.
- **`test_session_mcp_registry_unregister_by_id`** — exercise add → list
  → unregister → list cycle on a `SessionMcpRegistry`. Confirm tool
  indices are also pruned.
- **`test_mcp_tools_deregister_handler`** — drive the WS router with a
  fake message, assert the registry no longer holds the gateway after
  the call.
- **`test_refresh_user_mcp_emits_event`** — set up a fake registry,
  call `_refresh_user_mcp`, assert exactly one `MCP_TOOLS_REGISTERED`
  per active connection.

### 5.2 Frontend

- **`mcpStore.test.ts` — add/delete/update mutators update sessionGateways**
  (currently no test file for mcpStore — create one).
- **`useMcpEvents.test.ts` regression for #2** — fire two
  `MCP_TOOLS_REGISTERED` events in sequence, the second one redundantly
  containing the same admin/remote entries; assert `sessionGateways`
  remains stable (no duplicates) and that any pre-existing local entry
  is preserved without doubling.

### 5.3 Build verification
- `pnpm run build` clean
- `PYTHONPATH=. uv run pytest tests/...` clean (host-safe subset, per
  `db_tests_on_host` rule)

## 6. Manual verification

Tester-style scenarios on the running stack:

1. **Local add — live propagation.** Persona-McpTab open, add a local
   MCP gateway → without reload, the gateway and its tools appear in the
   tab. The cockpit "tools" mouseover shows it too.
2. **Local delete — live removal.** Same setup, delete the gateway →
   without reload, it's gone from both UIs.
3. **Local update — re-discovery.** Change the URL of a local gateway →
   tool list updates without reload.
4. **Reload stability.** Hard-reload (Strg+F5) with one local + one
   remote gateway present → exactly one entry per gateway in both UIs,
   first reload, second reload, third reload.
5. **Remote add via REST UI — live propagation.** No reload between add
   and observation.
6. **Remote delete via REST UI — live removal.** No reload.
7. **Admin gateway change with another user online.** A second browser
   profile with a different user sees the change without reload.
8. **Backend log audit.** Check that no `MCP_TOOLS_REGISTERED` event
   payload contains an entry with `tier === "local"` (per §4.1).

## 7. Rollout

- Single fix branch `fix/mcp-gateway-sync`.
- One subagent-driven implementation pass (Chatsune defaults).
- Merge to master after manual verification.
- No flag, no staged rollout — this is a bug fix that improves baseline
  behaviour.

## 8. Open questions

None at this stage. The local-mutation-while-disconnected scenario (user
adds a gateway while the WS is down) is implicitly handled — the next WS
connect runs `registerLocalGateways` over `localGateways`, which now
includes the new entry. No special path needed.
