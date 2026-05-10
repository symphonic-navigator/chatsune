# MCP Streamable HTTP — Session Lifecycle — Design

**Date:** 2026-05-10
**Status:** Draft
**Branch:** `feat/mcp-streamable-http-session-lifecycle`
**Insight:** [INS-044](../../INSIGHTS.md#ins-044--streamable-http-session-lifecycle-is-required-by-fastmcp-default-servers-2026-05-10)
**Predecessor spec:** [`2026-05-10-mcp-pills-result-and-streamable-http-design.md`](2026-05-10-mcp-pills-result-and-streamable-http-design.md)

---

## 1. Context & Problem

The 2026-05-10 polish package made Chatsune's MCP integration speak the
Streamable HTTP transport on the wire — `Accept: application/json,
text/event-stream` is sent on every request, and SSE responses are
parsed correctly. That fixed Mode A (stateless + JSON) and Mode B
(stateless + SSE).

It explicitly deferred the **session lifecycle** half of Streamable
HTTP. A FastMCP-default server (`stateless_http=False`) requires a
three-step handshake before any tool call:

1. Client `POST /mcp` with `method: "initialize"` and capability
   negotiation. Server responds with the `Mcp-Session-Id` header.
2. Client stores the session id and sends it as `Mcp-Session-Id` header
   on every subsequent request.
3. Client sends a `notifications/initialized` notification to confirm
   the handshake is complete.

Servers signal session expiry by returning `404 Session not found`. A
correct client must re-run the handshake and retry the request.

Without this lifecycle, vanilla FastMCP servers (the most common Python
MCP framework) return `400 Bad Request: Missing session ID` on the
first tools-related call. INS-044 specifies "implement when a user
asks for vanilla-FastMCP support" — this spec is that implementation.

The trigger event is the `simple_mcp` test fixture
(`/home/chris/projects/simple_mcp`), which has switches for all four
mode combinations and is the reference server for manual verification.

## 2. Goals & Non-Goals

**Goals**
- Backend `McpExecutor` runs the full three-step handshake when a
  gateway requires it, stashes the session id on `GatewayHandle`, and
  carries `Mcp-Session-Id` on every subsequent request from that
  handle.
- Backend retries once on `404` after re-initialising, transparently
  to the inference loop.
- Frontend `mcpClient.ts` runs the same lifecycle for `tier="local"`
  gateways called directly from the browser, with session state in the
  `mcpStore` Zustand store.
- Backend proxy routes (`/api/mcp/gateways/{id}/{tools|call}`,
  Tool-Explorer) run a one-shot lifecycle per HTTP request.
- All four server modes — stateless+JSON, stateless+SSE, stateful+JSON,
  stateful+SSE — work transparently to the user. Mode is auto-detected
  from `Mcp-Session-Id` header presence; no client-side configuration.
- Concurrent tool calls on the same gateway do not race the
  initialise step (init_lock per `GatewayHandle`).

**Non-goals**
- Server-initiated message channel via `GET /mcp`. Tool calls are
  unidirectional client-to-server; we do not need bidirectional
  messaging.
- `DELETE /mcp` on session end. Servers must implement TTL/GC for
  abandoned sessions; we do not waste a round-trip per disconnect on
  politeness. Can be added if a server signals it cannot cope.
- Cross-WebSocket session reuse. Each WebSocket session has its own
  `SessionMcpRegistry` with its own `GatewayHandle`s and therefore its
  own MCP session id, even when two WebSockets belong to the same user
  and the same admin gateway.
- Persistent session-id storage across browser reloads. The frontend
  `mcpStore` is in-memory; reload triggers fresh initialise on the
  next tool call. Marginal latency cost, no server-side stale-session
  build-up.
- Surfacing `notifications/progress` mid-stream as live UI events.
  Same scope decision as the polish package: out of scope, separate
  feature with its own pipeline.
- Capability features beyond tools/call: sampling, roots, elicitation.
  We send `capabilities: {}` in the initialise payload — correct for a
  pure tool-use client.

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Backend  GatewayHandle (per WebSocket-Session, per Gateway)     │
│   • session_id: str | None                                       │
│   • init_lock: asyncio.Lock                                      │
└──────────────────────────────────────────────────────────────────┘
              ▲                                ▲
              │ created by                      │ used by
              │                                 │
┌─────────────────────────────────┐  ┌─────────────────────────────┐
│ _mcp_discovery.py               │  │ tools/__init__.py inference │
│   1) initialise → session_id    │  │   call_tool(...)            │
│   2) notifications/initialized  │  │     → uses gw.session_id    │
│   3) tools/list                 │  │     → on 404: re-init+retry │
│   → builds GatewayHandle        │  │       (under gw.init_lock)  │
└─────────────────────────────────┘  └─────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ Backend  proxy routes /api/mcp/gateways/{id}/{tools|call}        │
│   • One-shot per HTTP request:                                   │
│     init → tools/list-or-call → return                           │
│   • No shared state with the inference path                      │
│   • Stateless from Chatsune's side (server gc's)                 │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│ Frontend  mcpClient.ts (tier="local", browser → gateway direct)  │
│   • Session-State in Zustand mcpStore                            │
│   • Keyed by canonicalised gateway URL                           │
│   • In-flight Promise dedup (browser equivalent of init_lock)    │
│   • call_tool: Mcp-Session-Id header; on 404 → clear+retry once  │
└──────────────────────────────────────────────────────────────────┘
```

| Lifecycle Context | State Holder | Lifetime | Re-Init Trigger |
|---|---|---|---|
| Backend Inference | `GatewayHandle.session_id` | WebSocket session | `404` on tools/call |
| Backend Proxy Route | local in function | one HTTP request | n/a (one-shot) |
| Frontend Local Tier | `mcpStore.sessions[url]` | browser tab | `404` on tools/call |

### 3.1 Stateless-Server Tolerance

`initialise` runs **always**, even against stateless servers
(`stateless_http=True`). Stateless-mode FastMCP accepts `initialize`
as a no-op and responds without an `Mcp-Session-Id` header. The
client treats absence-of-header as "this gateway is stateless" and
omits `Mcp-Session-Id` on subsequent calls. **Mode is auto-detected
on a per-gateway basis, no client-side flag.**

This means a gateway whose admin toggles `stateless_http` between
sessions is handled correctly without re-configuration: the next
`initialise` after reconnect picks up the new mode.

### 3.2 Concurrency Model

Within one WebSocket session, multiple tool calls can run concurrently
(the orchestrator may parallelise calls within a single inference
turn). They share one `GatewayHandle` per gateway.

- **Initial initialise** runs exactly once during discovery
  (`_mcp_discovery._discover_single_gateway`). No race possible at
  this point because discovery is sequential per gateway.
- **Re-initialise on 404** uses `gw.init_lock` to serialise. First
  parallel coroutine to see 404 acquires the lock, re-initialises,
  writes new session_id. Second coroutine acquires the lock, finds
  the session_id has been refreshed (we read `gw.session_id` again
  *after* lock acquisition), skips re-init, retries.

Practical simplification for the first implementation: we accept that
two coroutines that both see 404 simultaneously may both run
`initialise` in sequence (one re-init lands first, the second redoes
it). The cost is one extra round-trip per gateway in the rare
collision case. If profiling shows this hurts, the double-check
inside the lock can be added later. (YAGNI per Pareto.)

### 3.3 Cross-User Isolation

Session ids are scoped per-WebSocket, **not** per-user. For admin
gateways, two users' WebSocket sessions hit the same gateway URL
with the same shared API key but two independent `Mcp-Session-Id`s.
The server scopes its session state to each id; the API key
authorises both calls under the same admin identity.

**This is the designed behaviour of admin gateways**: shared
credential ⇒ shared resource access (same Gmail account, same search
quota, same file-system root). User-specific resource access belongs
in the remote or local tier. No cross-user data leak is possible via
the session-id mechanism; admin-tier identity sharing is a separate
property of the admin-gateway concept and is documented elsewhere.

The per-WebSocket scoping has a useful side-effect: parallel logins
of the same user (Tab 1 + phone) get separate MCP sessions, each with
its own negotiated state, and disconnecting one does not affect the
other.

### 3.4 Protocol Constants

```python
# backend/modules/tools/_mcp_executor.py
MCP_PROTOCOL_VERSION = "2025-06-18"
```

```typescript
// frontend/src/features/mcp/mcpClient.ts
const MCP_PROTOCOL_VERSION = "2025-06-18"
```

The two strings must stay in lock-step. They should be reviewed as a
pair when bumping. (No runtime drift check; review discipline.)

`clientInfo` is sourced from the project's own version metadata:

- **Backend**: `importlib.metadata.version("chatsune-backend")` with
  fallback to `"chatsune"` and finally `"unknown"`. This handles both
  Docker (`chatsune-backend` package) and host dev (`chatsune` package
  via `uv sync` in repo root).
- **Frontend**: Vite JSON-import of `package.json` `version` field.
  Currently `"0.0.0"` until proper versioning lands; will lift
  automatically once it does.

`clientInfo.name` is `"chatsune"` on both sides.

## 4. Backend Detail

### 4.1 `GatewayHandle` extension (`_mcp_registry.py`)

```python
import asyncio
from dataclasses import dataclass, field
from typing import Literal

from shared.dtos.inference import ToolDefinition


@dataclass
class GatewayHandle:
    id: str
    name: str  # = namespace
    url: str
    api_key: str | None
    tier: Literal["admin", "remote", "local"]
    tool_definitions: list[ToolDefinition]
    server_tools: dict[str, list[ToolDefinition]] = field(default_factory=dict)
    collisions: list[str] = field(default_factory=list)
    # NEW: Streamable HTTP session lifecycle state
    session_id: str | None = None
    init_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

For `tier="local"` both new fields stay default. The frontend manages
the local-tier session itself; the backend handle is a placeholder
for routing only.

### 4.2 `McpExecutor` API additions (`_mcp_executor.py`)

Three new entry points, plus extended existing entry points:

```python
class McpExecutor:
    async def initialise(
        self, *, url: str, api_key: str | None, timeout: float = 10.0,
    ) -> str | None:
        """Run the MCP three-step handshake.

        Returns the Mcp-Session-Id from the server, or None for stateless
        servers that do not issue one. Always sends the
        notifications/initialized confirmation. Returns None on protocol
        failure (caller should treat as gateway-unreachable).
        """

    async def call_tool(
        self, *, url: str, api_key: str | None,
        tool_name: str, arguments: dict,
        session_id: str | None = None,                                       # NEW
        on_session_refresh: Callable[[str], Awaitable[None]] | None = None,  # NEW
        _retry: bool = True,                                                  # internal
    ) -> str: ...

    async def discover_tools(
        self, *, url: str, api_key: str | None, timeout: float = 10.0,
        session_id: str | None = None,                                        # NEW
    ) -> list[dict]: ...

    async def call_tool_oneshot(
        self, *, url: str, api_key: str | None,
        tool_name: str, arguments: dict,
    ) -> str:
        """Initialise → call → return. For proxy routes."""

    async def discover_tools_oneshot(
        self, *, url: str, api_key: str | None, timeout: float = 10.0,
    ) -> list[dict]:
        """Initialise → tools/list → return. For proxy routes."""
```

Existing call sites that pass `session_id=None` keep working (no
header, stateless behaviour) — strictly additive.

### 4.3 `initialise` implementation sketch

```python
async def initialise(self, *, url, api_key, timeout=10.0) -> str | None:
    headers = {
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
            "clientInfo": {"name": "chatsune", "version": _client_version()},
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=init_payload, headers=headers) as resp:
            if resp.status_code != 200:
                _log.warning("MCP initialise failed: HTTP %d from %s", resp.status_code, url)
                return None
            session_id = resp.headers.get("mcp-session-id")
            # Drain the body — may be JSON or SSE; we don't need the result content,
            # but we MUST consume it before issuing the notification.
            ctype = _content_type(resp)
            if ctype == "application/json":
                await resp.aread()
            elif ctype == "text/event-stream":
                # Read until first matching reply; subsequent messages on this stream
                # are not relevant to the handshake.
                await _read_sse_response(resp, expected_id=init_id)

        # Step 3: notifications/initialized — fire-and-forget, no id, no expected reply.
        notif_headers = {**headers}
        if session_id:
            notif_headers["Mcp-Session-Id"] = session_id
        await client.post(url, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, headers=notif_headers)

    return session_id  # may be None for stateless servers
```

`_client_version()` is a module-level helper that resolves
`chatsune-backend` / `chatsune` / `"unknown"` once at import time.

### 4.4 Discovery integration (`_mcp_discovery.py`)

`_discover_single_gateway` becomes:

```python
async def _discover_single_gateway(config, tier):
    namespace = normalise_namespace(config.name)
    mcp_url = config.url.rstrip("/") + "/mcp"

    session_id = await _executor.initialise(url=mcp_url, api_key=config.api_key)
    # session_id is None either for stateless servers OR for failed init.
    # We can't distinguish from the return alone; we attempt tools/list either way
    # and treat empty result as "unreachable" same as today.

    raw_tools = await _executor.discover_tools(
        url=mcp_url, api_key=config.api_key, session_id=session_id,
    )
    reachable = isinstance(raw_tools, list) and len(raw_tools) > 0

    # ... existing tool_defs / server_tools / collisions logic ...

    handle = GatewayHandle(
        id=config.id, name=namespace, url=mcp_url, api_key=config.api_key,
        tier=tier, tool_definitions=tool_defs, server_tools=server_tools,
        collisions=collisions,
        session_id=session_id,
        init_lock=asyncio.Lock(),
    )
    # ... return (handle, status)
```

If `initialise` returns `None` because of a real protocol failure
(server returned 5xx, network error, etc.), the subsequent
`discover_tools` will also fail — the existing
`McpGatewayErrorEvent` path handles it.

### 4.5 Inference call_tool wiring (`tools/__init__.py:227`)

```python
async def _refresh(new_id: str) -> None:
    gw.session_id = new_id  # under the executor's init_lock acquisition

return await _mcp_executor.call_tool(
    url=gw.url, api_key=gw.api_key,
    tool_name=original_name, arguments=arguments,
    session_id=gw.session_id,
    on_session_refresh=_refresh,
)
```

### 4.6 `call_tool` retry-on-404 sketch

```python
async def call_tool(self, *, url, api_key, tool_name, arguments,
                    session_id=None, on_session_refresh=None,
                    init_lock: asyncio.Lock | None = None,
                    _retry: bool = True) -> str:
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if api_key: headers["Authorization"] = f"Bearer {api_key}"
    if session_id: headers["Mcp-Session-Id"] = session_id
    request_id = _next_request_id()
    payload = {"jsonrpc": "2.0", "id": request_id,
               "method": "tools/call",
               "params": {"name": tool_name, "arguments": arguments}}

    try:
        async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code == 404 and session_id and _retry:
                    # Session expired → re-init + retry once.
                    async with (init_lock or _NULL_LOCK):
                        new_id = await self.initialise(url=url, api_key=api_key)
                        if new_id is None:
                            return _error_json("MCP session expired; re-initialise failed")
                        if on_session_refresh:
                            await on_session_refresh(new_id)
                    return await self.call_tool(
                        url=url, api_key=api_key,
                        tool_name=tool_name, arguments=arguments,
                        session_id=new_id, on_session_refresh=on_session_refresh,
                        init_lock=init_lock, _retry=False,
                    )

                # ... existing JSON / SSE dispatch + result parsing ...
```

`_NULL_LOCK` is a module-level no-op async context manager so the
proxy routes (which pass no lock) can use the same code path:

```python
class _NullAsyncLock:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return None
_NULL_LOCK = _NullAsyncLock()
```

### 4.7 Proxy route helpers (`_handlers.py:1533/1548`)

```python
@router.get("/mcp/gateways/{gateway_id}/tools")
async def proxy_mcp_tools_list(...):
    gw = await _resolve_gateway(gateway_id, user)
    executor = McpExecutor()
    mcp_url = gw.url.rstrip("/") + "/mcp"
    tools = await executor.discover_tools_oneshot(url=mcp_url, api_key=gw.api_key)
    return {"tools": tools}


@router.post("/mcp/gateways/{gateway_id}/call")
async def proxy_mcp_tool_call(...):
    gw = await _resolve_gateway(gateway_id, user)
    executor = McpExecutor()
    mcp_url = gw.url.rstrip("/") + "/mcp"
    result_json = await executor.call_tool_oneshot(
        url=mcp_url, api_key=gw.api_key,
        tool_name=body.tool_name, arguments=body.arguments,
    )
    return _json.loads(result_json)
```

Each helper internally runs `await self.initialise(...)` then the
data call. No 404 retry on proxy paths — fresh session per request,
no expiry possible within one HTTP call.

## 5. Frontend Detail

### 5.1 `mcpStore` extension

New slice independent of `localGateways`:

```typescript
interface McpSessionState {
  // sessionId: string  → server is stateful, send header
  // sessionId: null    → server is stateless, omit header
  // sessionId: undefined → not yet initialised (in-flight only)
  sessionId: string | null | undefined
  initialising: Promise<string | null> | null
}

interface McpStore {
  // existing fields untouched
  sessions: Record<string, McpSessionState>  // key: canonical gateway URL (rstrip("/") + "/mcp")
  setSession: (url: string, sessionId: string | null) => void
  clearSession: (url: string) => void
  getSession: (url: string) => McpSessionState | undefined
}
```

**Mutation hooks** in existing `localGateways`-mutator paths:
- Adding gateway: nothing — session is created lazily on first call.
- Editing URL: `clearSession(oldUrl)` after the edit lands.
- Deleting gateway: `clearSession(url)` in the delete path.

### 5.2 `ensureSession` (private to `mcpClient.ts`)

```typescript
async function ensureSession(gatewayUrl: string, apiKey: string | null): Promise<string | null> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const store = useMcpStore.getState()
  const existing = store.getSession(url)

  if (existing && existing.sessionId !== undefined) return existing.sessionId
  if (existing?.initialising) return existing.initialising

  const initPromise = doInitialise(url, apiKey)
  useMcpStore.setState((s) => ({
    sessions: { ...s.sessions, [url]: { sessionId: undefined, initialising: initPromise } },
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

async function doInitialise(url: string, apiKey: string | null): Promise<string | null> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
  }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  // Step 1: initialize
  const initId = nextId()
  const initResp = await fetch(url, {
    method: 'POST', headers,
    body: JSON.stringify({
      jsonrpc: '2.0', id: initId,
      method: 'initialize',
      params: {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: 'chatsune', version: APP_VERSION },
      },
    }),
  })
  if (!initResp.ok) throw new Error(`MCP initialise failed: HTTP ${initResp.status}`)
  await readJsonRpcResponse(initResp, initId)
  const sessionId = initResp.headers.get('mcp-session-id')  // null for stateless servers

  // Step 2: notifications/initialized (fire-and-forget; no JSON-RPC id, no reply)
  const notifHeaders = { ...headers }
  if (sessionId) notifHeaders['Mcp-Session-Id'] = sessionId
  await fetch(url, {
    method: 'POST', headers: notifHeaders,
    body: JSON.stringify({
      jsonrpc: '2.0',
      method: 'notifications/initialized',
    }),
  })

  return sessionId
}
```

### 5.3 SSE-aware response reader

```typescript
async function readJsonRpcResponse(resp: Response, expectedId?: number): Promise<JsonRpcReply> {
  const ctype = (resp.headers.get('content-type') || '').split(';')[0].trim().toLowerCase()

  if (ctype === 'application/json') {
    return await resp.json()
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
          const obj = JSON.parse(data)
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

`pipeThrough(new TextDecoderStream())` is supported in all browsers
Chatsune already targets (Chrome ≥ 71, Firefox ≥ 105, Safari ≥ 14.1).

### 5.4 `mcpToolsCall` and `mcpToolsList` rewrap

```typescript
export async function mcpToolsCall(
  gatewayUrl: string, apiKey: string | null,
  toolName: string, args: Record<string, unknown>,
  timeoutMs = 30_000,
): Promise<{ stdout: string; error: string | null }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'

  let sessionId: string | null
  try {
    sessionId = await ensureSession(gatewayUrl, apiKey)
  } catch (e) {
    return { stdout: '', error: `MCP initialise failed: ${stringifyError(e)}` }
  }

  const doCall = async (sid: string | null): Promise<Response> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
    }
    if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`
    if (sid) headers['Mcp-Session-Id'] = sid
    return fetch(url, {
      method: 'POST', headers,
      body: JSON.stringify({
        jsonrpc: '2.0', id: nextId(),
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
      sessionId = await ensureSession(gatewayUrl, apiKey)
      resp = await doCall(sessionId)
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      return { stdout: '', error: `MCP gateway timed out after ${timeoutMs}ms` }
    }
    return { stdout: '', error: `MCP gateway unreachable: ${stringifyError(e)}` }
  }

  const body = await readJsonRpcResponse(resp)
  // ... existing error / isError / content extraction logic ...
}
```

`mcpToolsList` follows the same pattern with `method: 'tools/list'`.

## 6. Error Handling

### 6.1 Backend

| Scenario | Behaviour |
|---|---|
| `initialise` returns 5xx / network error | `discover_tools` fails empty → existing `McpGatewayErrorEvent` path. Gateway shown as unreachable. |
| `initialise` returns 200 without `Mcp-Session-Id` header | Treated as stateless server. `session_id=None` stored. All subsequent calls omit header. |
| `tools/call` returns 404 with valid session_id | Re-initialise (under `init_lock`), retry once. If re-init fails, return `MCP session expired; re-initialise failed` error JSON. |
| `tools/call` returns 404 with no session_id | No retry — server is rejecting for some other reason. Return existing error JSON. |
| `tools/call` returns SSE stream that closes without matching id | Existing `RuntimeError` path → JSON error string. |
| Concurrent re-init race | First coroutine acquires `init_lock`, runs initialise. Second waits, then runs another (best-effort). Acceptable extra round-trip. |

### 6.2 Frontend

| Scenario | Behaviour |
|---|---|
| `initialise` throws (network, non-200) | `clearSession(url)` so next call retries. Tool call returns user-visible "MCP initialise failed" error. |
| `initialise` returns no `mcp-session-id` header | Cached as `null` — server is stateless. Subsequent calls send no header. |
| `tools/call` returns 404 with stored session_id | `clearSession(url)`, `ensureSession` again, single retry. |
| Parallel `ensureSession` calls during init | Second caller awaits the first via the `initialising` Promise — single `initialize` round-trip. |
| Page reload | Store cleared by browser → next call lazy-initialises. |
| Gateway URL edit | Mutator calls `clearSession(oldUrl)` → next call uses new URL with fresh session. |

## 7. Testing

### 7.1 Backend pytest

Under `backend/modules/tools/__tests__/`:

- `test_mcp_executor_initialise_three_step_handshake` — initialize → notifications/initialized order.
- `test_mcp_executor_initialise_returns_session_id` — parses `mcp-session-id` header.
- `test_mcp_executor_initialise_handles_stateless_server` — returns `None` when header missing, no crash.
- `test_mcp_executor_initialise_returns_none_on_5xx` — graceful failure.
- `test_mcp_executor_call_tool_sends_session_id_header` — when `session_id` parameter is set.
- `test_mcp_executor_call_tool_no_header_when_session_id_none` — backwards compat.
- `test_mcp_executor_call_tool_404_triggers_reinit_and_retry` — full happy retry flow with `on_session_refresh` invoked.
- `test_mcp_executor_call_tool_404_with_failed_reinit_returns_error_json` — graceful degradation.
- `test_mcp_executor_call_tool_no_retry_on_second_404` — `_retry=False` honoured.
- `test_mcp_executor_call_tool_oneshot_runs_full_lifecycle` — proxy helper end-to-end.
- `test_mcp_executor_discover_tools_oneshot_runs_full_lifecycle` — proxy helper for tools/list.
- `test_mcp_discovery_initialises_gateway_and_stashes_session_id` — discovery wires session id onto handle.
- `test_mcp_discovery_marks_gateway_unreachable_on_init_failure_then_empty_tools` — error event flow preserved.
- `test_gateway_handle_init_lock_serialises_concurrent_reinit` — `asyncio.Lock` invariant under simulated 404 race.

### 7.2 Frontend Vitest

Under `frontend/src/features/mcp/__tests__/mcpClient.test.ts`:

- `ensureSession sends initialize then notifications/initialized in that order`
- `ensureSession parses Mcp-Session-Id from response headers`
- `ensureSession returns null when server omits Mcp-Session-Id`
- `ensureSession dedupes parallel calls into one initialise` (race test with two concurrent `ensureSession` calls)
- `mcpToolsCall sends Mcp-Session-Id header when session is present`
- `mcpToolsCall omits Mcp-Session-Id header for stateless server`
- `mcpToolsCall handles SSE response stream with notifications interleaved`
- `mcpToolsCall on 404 clears session, re-initialises, retries once`
- `mcpToolsCall on second 404 (post re-init) returns error without further retry`
- `mcpToolsList parallel ensureSession dedup` (sanity)
- `mcpStore.clearSession removes entry`
- `mcpStore.setSession overwrites existing entry` (URL-edit scenario)

### 7.3 Build verification

- `pnpm run build` (full `tsc -b && vite build`, **not** `tsc --noEmit`) — required by CLAUDE.md and memory `frontend_build_check`.
- Backend: `uv run python -m py_compile <changed files>` for syntax sanity.
- Backend pytest run on host excludes the four DB-dependent files (memory `db_tests_on_host`); the new tests are pure unit-tests against mocked `httpx`, safe on host.

## 8. Manual Verification

The `simple_mcp` server has switches:

```bash
# Stateless + JSON (Mode A) — already works after polish package
MCP_STATELESS_HTTP=true  MCP_JSON_RESPONSE=true  uv run python server.py

# Stateless + SSE (Mode B) — already works after polish package
MCP_STATELESS_HTTP=true  MCP_JSON_RESPONSE=false uv run python server.py

# Stateful + JSON (Mode C) — NEW, must work after this package
MCP_STATELESS_HTTP=false MCP_JSON_RESPONSE=true  uv run python server.py

# Stateful + SSE (Mode D) — NEW, must work after this package
MCP_STATELESS_HTTP=false MCP_JSON_RESPONSE=false uv run python server.py
```

Run each scenario on a real machine with backend + frontend up:

1. **Local-tier × Mode C** — `simple_mcp` in stateful+JSON. In Chatsune
   add a local gateway pointing at `http://127.0.0.1:3333/`. Open a chat
   and ask the model to call `get_datetime`. Pill should appear,
   expand, show the ISO timestamp.
   - Network tab: three requests in order — `initialize`,
     `notifications/initialized`, `tools/call`. Last two carry
     `Mcp-Session-Id`.

2. **Local-tier × Mode D** — same as 1 with `MCP_JSON_RESPONSE=false`.
   Pill should still show timestamp; SSE response is parsed
   transparently.

3. **Remote-tier × Mode C** — configure `simple_mcp` as a user-remote
   gateway (URL must be reachable from the backend container; in dev
   that means `host.docker.internal:3333` or running `simple_mcp` on
   the host network). Run a tool call. Backend log:
   `MCP initialise … session_id=…` then `tools/call …`.

4. **Remote-tier × Mode D** — same as 3 with SSE response.

5. **Admin-tier × Mode C/D** — register `simple_mcp` as an admin
   gateway. Tool-Explorer modal lists the tool. Direct call from
   Tool-Explorer (proxy route) works. Tool call from chat works.

6. **Re-init trigger** — with stateful+JSON server, run a tool call,
   restart `simple_mcp` (kills all sessions), run another tool call.
   Expected: 404 in backend log, `MCP re-initialise … session_id=…`,
   `tools/call` succeeds. Pill shows result without user-visible error.

7. **Concurrent calls** — start a chat where the model is likely to
   call multiple tools in one turn. Backend log: exactly one
   `initialise` at discovery, then multiple `tools/call`s, all with the
   same session id, no extra initialise.

8. **Page reload (frontend)** — local-tier gateway, after a successful
   call reload the browser. First subsequent call: Network-tab shows
   fresh `initialize` then call. (Confirms in-memory store dropped
   correctly.)

9. **Tool-Explorer (proxy route)** — admin-tier or remote-tier
   `simple_mcp`. Open Tool-Explorer modal. Network-tab to backend
   shows one HTTP call to `/api/mcp/gateways/{id}/tools`. Backend log
   shows two HTTP calls outbound to the gateway: `initialize` and
   `tools/list`.

10. **Backwards-compat** — re-run any pre-existing manual scenario
    against a known stateless+JSON gateway (existing Chatsune-internal
    server, if any). No regression.

## 9. Rollout

- Single feature branch `feat/mcp-streamable-http-session-lifecycle`.
- Subagent-driven implementation per Chatsune defaults.
- Manual verification matrix completed before merge.
- Merge to master after green verification per Chatsune defaults.
- INS-044 should be appended with a "Resolved" note pointing at this
  spec on the merge commit, per repo convention.

No flag, no staged rollout: the change improves baseline behaviour
across all servers (stateless paths remain unchanged because
`session_id=None` is the no-op default), is reversible by revert, and
the test surface is well-bounded.

## 10. Open questions

None at this stage. Frontend storage (in-memory only), DELETE policy
(skip), proxy lifecycle (per-request), concurrency model (init_lock
without double-check), and stateless-server tolerance (auto-detect via
header presence) are all resolved above.
