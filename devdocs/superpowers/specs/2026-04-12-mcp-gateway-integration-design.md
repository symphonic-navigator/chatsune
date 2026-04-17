# MCP Gateway Integration — Design Specification

**Date:** 2026-04-12
**Status:** Approved
**Scope:** Client-side MCP gateway calls integrated into Chatsune's tool system

---

## Overview

Integrate MCP (Model Context Protocol) gateway support into Chatsune, allowing
users and admins to connect external tool servers. MCP tools appear alongside
built-in tools in the chat, are discoverable via a Tool Explorer, and maintain
stable cache prefixes within sessions.

The MCP gateway itself is a separate project (`chatsune-mcp-gateway`), specified
in `GATEWAY-SPEC.md`. This document covers Chatsune-side integration only.

---

## Three-Tier Gateway Model

### Tier 1: Admin MCP Gateways

- Configured by the master admin in the Admin Modal
- Stored in `admin_settings` collection
- Backend calls the gateway directly (server-to-server)
- Available to all users automatically
- API key set by admin
- Users cannot edit or disable admin gateways (but can disable individual tools)

### Tier 2: User Remote MCP Gateways

- Configured by the user in User Modal > MCP tab
- Stored in the user document (MongoDB, `mcp_gateways` field)
- Backend calls the gateway directly (server-to-server)
- Available on all the user's devices
- API key set by user (optional — no key means no auth header)

### Tier 3: User Local MCP Gateways

- Configured by the user in User Modal > MCP tab
- Stored in `localStorage` (browser-only, device-specific)
- Frontend calls the gateway directly (browser HTTP fetch)
- Only available on the device where configured
- API key set by user (optional)

---

## Gateway Configuration Schema

Shared across all tiers. Identical structure in MongoDB and localStorage.

```python
class McpGatewayConfig(BaseModel):
    id: str                          # UUID
    name: str                        # display name + namespace prefix
    url: str                         # gateway endpoint URL
    api_key: str | None = None       # optional Bearer token
    enabled: bool = True             # master switch
    disabled_tools: list[str] = []   # tool names turned off by user
```

### Namespace Rules

- Gateway `name` is used as namespace prefix for all tools from that gateway
- Normalised on save: lowercase, special characters replaced with underscore,
  no double underscores (to preserve `__` separator)
- Tool name format: `{namespace}__{original_tool_name}` (e.g. `homelab__read_file`)
- Static (built-in) tools have no prefix — no collision possible
- Duplicate namespace names rejected at save time with validation error

---

## Storage Locations

### Admin Gateways

New field in `admin_settings` collection:

```python
# admin_settings document
{
  "_id": "mcp",
  "gateways": [McpGatewayConfig, ...]
}
```

### User Remote Gateways

New field on the user document:

```python
# users collection — existing document gains:
{
  ...,
  "mcp_gateways": [McpGatewayConfig, ...]
}
```

### User Local Gateways

localStorage key: `chatsune:mcp_local_gateways`

```json
[
  { "id": "...", "name": "homelab", "url": "http://localhost:9100", "api_key": null, "enabled": true, "disabled_tools": [] }
]
```

---

## Discovery and Registration Flow

Triggered once at session start. No mid-session changes.

### Sequence

1. Frontend sends `chat.send` (first message) or session start
2. **Backend** reads admin gateways from `admin_settings` and user remote gateways
   from the user document
3. **Backend** calls `POST /mcp` with `tools/list` on each admin + user-remote
   gateway (parallel, with 10s timeout per gateway)
4. **Frontend** calls `POST /mcp` with `tools/list` on each local gateway
   (parallel, same timeout)
5. **Frontend** sends discovered local tools via WebSocket:
   `mcp.tools.register` message containing gateway info and tool definitions
6. **Backend** merges all tools into the `SessionMcpRegistry` (in-memory,
   connection-scoped)
7. **Backend** emits `McpToolsRegisteredEvent` to confirm registration
8. If any gateway is unreachable: `McpGatewayErrorEvent` emitted, Toast shown
   in frontend. Session starts without that gateway's tools.

### Tool Sorting (cache-prefix critical)

The merged tool list is sorted deterministically:

1. **Static tools first** — fixed order matching the registry definition order:
   web_search, web_fetch, knowledge_search, create_artefact, update_artefact,
   read_artefact, list_artefacts, calculate_js, write_journal_entry
2. **MCP tools second** — alphabetically sorted by `namespace__tool_name`

This order is stable within a session (no mid-session changes) and deterministic
across sessions with identical tool sets.

---

## Session MCP Registry

New in-memory structure, one per WebSocket connection.

```python
@dataclass
class GatewayHandle:
    id: str
    name: str                          # = namespace
    url: str
    api_key: str | None
    tier: Literal["admin", "remote", "local"]
    tool_definitions: list[ToolDefinition]

class SessionMcpRegistry:
    gateways: dict[str, GatewayHandle]    # namespace -> handle
    tool_index: dict[str, str]            # namespaced_tool_name -> namespace

    def resolve(self, tool_name: str) -> tuple[GatewayHandle, str]:
        """Returns (gateway, original_tool_name) or raises."""

    def all_definitions(self) -> list[ToolDefinition]:
        """All MCP tool definitions, sorted alphabetically by name."""

    def is_mcp_tool(self, tool_name: str) -> bool:
        """True if tool_name contains __ and is in the index."""
```

Lifetime: created at session start, destroyed when the WebSocket connection closes.
Not persisted to Redis or MongoDB.

---

## Execution Paths

### Path A: Backend-Executed (Admin + User Remote)

```
LLM emits tool_call: company__search_docs(query="...")
  -> execute_tool() sees __ separator
  -> SessionMcpRegistry.resolve("company__search_docs")
     returns (gateway=company, original_name="search_docs")
  -> McpExecutor sends POST to gateway.url/mcp:
     { jsonrpc: "2.0", method: "tools/call",
       params: { name: "search_docs", arguments: {query: "..."} } }
  -> Gateway returns result
  -> Result fed back to LLM as tool message
```

**New component:** `McpExecutor` in `backend/modules/tools/`
- Implements the `ToolExecutor` interface
- Speaks MCP JSON-RPC over HTTP (via httpx)
- Strips namespace prefix before sending to gateway
- Adds `Authorization: Bearer <key>` header if api_key is set
- HTTP timeout: 30 seconds

### Path B: Frontend-Executed (User Local)

```
LLM emits tool_call: homelab__read_file(path="...")
  -> execute_tool() sees __ separator
  -> SessionMcpRegistry.resolve("homelab__read_file")
     returns (gateway=homelab, tier="local")
  -> ClientToolDispatcher.dispatch() (existing mechanism)
  -> Frontend clientToolHandler receives dispatch event
  -> Recognises MCP tool, strips namespace
  -> fetch("http://localhost:9100/mcp", {
       method: "POST",
       body: { jsonrpc: "2.0", method: "tools/call",
               params: { name: "read_file", arguments: {path: "..."} } }
     })
  -> Gateway returns result
  -> Frontend sends chat.client_tool.result back via WebSocket
  -> ClientToolDispatcher.resolve() completes the Future
```

Reuses existing `ClientToolDispatcher` path. Only change in `clientToolHandler`:
routing MCP tools to the correct local gateway via HTTP instead of the sandbox.

### Routing Decision (in execute_tool)

```
1. Does tool_name contain __ ?
   No  -> existing static tool group path (unchanged)
   Yes -> extract namespace, look up in SessionMcpRegistry
          2. Is tier = admin or remote?
             Yes -> McpExecutor (backend HTTP call)
          3. Is tier = local?
             Yes -> ClientToolDispatcher (browser roundtrip)
```

---

## Timeout Configuration

| Path | Timeout | Rationale |
|------|---------|-----------|
| Backend -> Gateway (admin/remote) | 30s | MCP tools may perform real work (DB, files, APIs) |
| ClientToolDispatcher server timeout | 35s | 30s client + 5s jitter absorption |
| ClientToolDispatcher client timeout | 30s | Actual HTTP call to local gateway |
| Discovery (tools/list) per gateway | 10s | Discovery should be fast; slow = unreachable |

Compare with existing code_execution timeouts (10s server / 5s client) which are
lower because sandbox JS execution is inherently fast.

---

## Shared Contracts

### New File: `shared/dtos/mcp.py`

```python
class McpGatewayConfigDto(BaseModel):
    id: str
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True
    disabled_tools: list[str] = []

class McpGatewayStatusDto(BaseModel):
    id: str
    name: str
    tier: Literal["admin", "remote", "local"]
    tool_count: int
    reachable: bool

class McpToolDefinitionDto(BaseModel):
    name: str                    # original name (without namespace)
    description: str
    parameters: dict             # JSON Schema

class McpToolRegistrationPayload(BaseModel):
    """Frontend -> Backend via WebSocket: registering local gateway tools."""
    gateway_id: str
    name: str                    # gateway name = namespace
    tier: Literal["local"]       # always local when coming from frontend
    tools: list[McpToolDefinitionDto]
```

### New File: `shared/events/mcp.py`

```python
class McpToolsRegisteredEvent(BaseModel):
    type: str = "mcp.tools.registered"
    session_id: str
    gateways: list[McpGatewayStatusDto]
    total_tools: int
    correlation_id: str
    timestamp: datetime

class McpGatewayErrorEvent(BaseModel):
    type: str = "mcp.gateway.error"
    gateway_id: str
    gateway_name: str
    error: str
    recoverable: bool           # true = warning toast, false = error toast
    correlation_id: str
    timestamp: datetime
```

### New Topics in `shared/topics.py`

```python
MCP_TOOLS_REGISTER    = "mcp.tools.register"      # Frontend -> Backend (WS)
MCP_TOOLS_REGISTERED  = "mcp.tools.registered"     # Backend -> Frontend (confirmation)
MCP_GATEWAY_ERROR     = "mcp.gateway.error"        # Backend -> Frontend (toast trigger)
```

### New WS Message Type

```
mcp.tools.register    — Frontend sends local gateway tool definitions to Backend
```

All gateway CRUD (admin and user-remote) uses REST endpoints, not WebSocket.

---

## UI Components

### User Modal: MCP Tab (new, tab 13)

Location: `frontend/src/app/components/user-modal/McpTab.tsx`

Three sections:

1. **Remote Gateways** — user's remote gateways (green accent)
   - Add / Edit / Delete / Explore buttons
   - Status dot: green = reachable, grey = disabled, red = unreachable
   - Tool count badge

2. **Local Gateways** — user's local gateways (orange accent)
   - Same UI as remote, but stored in localStorage
   - Subtitle: "This device only — stored in browser"

3. **Global Gateways** — admin gateways (purple accent, read-only)
   - Explore button only (no edit/delete)
   - Subtitle: "Managed by admin — available to all users"

### Gateway Edit Dialog

Inline dialog (not a separate modal) with fields:
- Name (= namespace prefix, with preview: "Tools will appear as name__tool_name")
- URL
- API Key (password field, optional)
- Enabled toggle
- Delete button (with confirmation)

### Tool Explorer

Location: `frontend/src/features/mcp/ToolExplorer.tsx`

Opened via "Explore" button on any gateway card. Replaces MCP tab content
(with back button to return).

Split layout:
- **Left panel (220px):** Tool list with search, disabled tools shown faded with
  "off" badge
- **Right panel:** Selected tool detail — description, namespaced name, enable/disable
  toggle, parameters rendered from JSON Schema, Execute button, response area

**Execute:** Direct HTTP call from browser to gateway (not through LLM or backend).
For remote/admin gateways, the frontend calls the gateway directly for testing purposes.
Response shown as formatted JSON.

**Search:** Case-insensitive token search (space-separated AND). Matches against
tool name, description, and namespaced name.

### Chat: MCP Toggle

Location: Extends existing `ToolToggles.tsx`

- New "MCP" toggle with green accent colour (`rgba(166,218,149,*)`)
- Vertical separator between built-in toggles and MCP
- Shows total active MCP tool count next to label
- Only rendered if user has at least one enabled MCP gateway
- Toggles `mcp` in `disabled_tool_groups` (one group ID for all MCP tools)

### Chat: Tool Overview Popover

Location: `frontend/src/features/chat/ToolPopover.tsx`

- Wrench icon in the chat top bar (next to mortarboard), with badge showing
  total active tool count
- Click opens popover with:
  - Search field (same token search as Explorer)
  - Built-in tools grouped by category (blue headers)
  - Separator line
  - MCP tools grouped by gateway (green headers), each with tier badge
    (local / remote / global)
  - Footer: total count + link to Settings > MCP
- Read-only — no editing capability
- Closes on click outside or Escape

---

## Admin Configuration

### Admin Modal: MCP Tab (new)

Same gateway card UI as user modal, but with full CRUD:
- Add / Edit / Delete gateways
- Set name, URL, API key
- No per-tool toggles (users manage their own tool preferences)

### REST Endpoints

```
GET    /api/admin/mcp/gateways          — list admin gateways
POST   /api/admin/mcp/gateways          — create admin gateway
PATCH  /api/admin/mcp/gateways/{id}     — update admin gateway
DELETE /api/admin/mcp/gateways/{id}     — delete admin gateway
```

### User REST Endpoints

```
GET    /api/user/mcp/gateways           — list user's remote gateways
POST   /api/user/mcp/gateways           — create remote gateway
PATCH  /api/user/mcp/gateways/{id}      — update remote gateway
DELETE /api/user/mcp/gateways/{id}      — delete remote gateway
```

Local gateways have no REST endpoints (localStorage only).

---

## Cache Prefix Strategy

**Hard requirement:** Tool list must be identical across all turns within a session.

### Guarantees

1. **Session-stable tool list** — discovery happens once at session start.
   No mid-session additions, removals, or reordering.
2. **Deterministic sort** — static tools in fixed registry order, then MCP tools
   alphabetically by namespaced name.
3. **Namespace normalisation** — gateway names normalised on save (lowercase,
   special chars to underscore, no double underscores). Same name always produces
   same prefix.
4. **System prompt independence** — MCP information flows only through the `tools`
   parameter, never injected into the system prompt. System prompt stability is
   unaffected.
5. **Cross-session stability** — users with identical gateway configs and identical
   tool sets get identical tool lists, enabling cross-session cache hits.

### What Invalidates the Prefix

- Adding/removing a gateway (requires new session)
- A gateway exposing different tools than last time (requires new session)
- Enabling/disabling a tool in settings (requires new session for tools list change)
- Toggling MCP on/off in chat (changes disabled_tool_groups, different tools list)

All of these are user-initiated actions that naturally start a new context.

---

## Error Handling

### Discovery Errors (session start)

- Gateway unreachable: `McpGatewayErrorEvent` with `recoverable=true`, warning
  toast (yellow). Session starts without that gateway's tools.
- Gateway reachable but `tools/list` fails: same handling, toast includes error detail.
- No gateway blocks session start — graceful degradation.

### Tool Call Errors (during inference)

- Backend path: HTTP timeout (30s) or error -> tool result with error field,
  LLM sees error and can react. `ChatToolCallCompletedEvent` with `success=false`.
- Frontend path: ClientToolDispatcher timeout (35s) or error -> synthetic error
  result via existing mechanism.
- Gateway returns MCP error (JSON-RPC error) -> translated to error field in
  tool result.

### Configuration Errors

- Duplicate namespace name: validation error on save, UI shows inline error
- Invalid URL format: validation error on save
- Namespace collides with built-in tool name: validation error, rejected

### Toast Behaviour

- `McpGatewayErrorEvent` with `recoverable=true` -> yellow warning toast
- `McpGatewayErrorEvent` with `recoverable=false` -> red error toast
- Toast includes gateway name and brief error message

---

## Files to Create

### Backend

| File | Purpose |
|------|---------|
| `shared/dtos/mcp.py` | MCP DTOs |
| `shared/events/mcp.py` | MCP events |
| `backend/modules/tools/_mcp_executor.py` | McpExecutor — HTTP MCP client for backend-executed calls |
| `backend/modules/tools/_mcp_registry.py` | SessionMcpRegistry — per-connection MCP tool state |
| `backend/modules/tools/_mcp_discovery.py` | Discovery logic — calls tools/list on gateways |

### Backend (modify)

| File | Change |
|------|--------|
| `shared/topics.py` | Add MCP_TOOLS_REGISTER, MCP_TOOLS_REGISTERED, MCP_GATEWAY_ERROR |
| `backend/modules/tools/__init__.py` | Extend execute_tool() with MCP routing |
| `backend/modules/tools/_registry.py` | Add "mcp" tool group (toggleable, side varies) |
| `backend/modules/chat/_orchestrator.py` | Trigger MCP discovery at session start, merge tools |
| `backend/modules/user/_models.py` | Add mcp_gateways field to user document |
| `backend/modules/user/_handlers.py` | Add user MCP gateway CRUD endpoints |
| `backend/modules/user/__init__.py` | Expose MCP gateway methods |
| `backend/ws/router.py` | Handle mcp.tools.register message |
| `backend/main.py` | Register admin MCP routes |

### Frontend (create)

| File | Purpose |
|------|---------|
| `frontend/src/app/components/user-modal/McpTab.tsx` | MCP settings tab |
| `frontend/src/features/mcp/ToolExplorer.tsx` | Tool explorer with test UI |
| `frontend/src/features/mcp/GatewayEditDialog.tsx` | Gateway add/edit form |
| `frontend/src/features/mcp/mcpStore.ts` | Zustand store for local gateways + MCP state |
| `frontend/src/features/mcp/mcpApi.ts` | REST API client for gateway CRUD |
| `frontend/src/features/mcp/mcpClient.ts` | MCP JSON-RPC HTTP client (for discovery + explorer) |
| `frontend/src/features/chat/ToolPopover.tsx` | Tool overview popover |

### Frontend (modify)

| File | Change |
|------|--------|
| `frontend/src/app/components/user-modal/UserModal.tsx` | Add MCP tab |
| `frontend/src/features/chat/ToolToggles.tsx` | Add MCP toggle |
| `frontend/src/features/chat/ChatView.tsx` | Add tool icon + popover in top bar |
| `frontend/src/features/code-execution/clientToolHandler.ts` | Route MCP tools to local gateway |
| `frontend/src/core/store/chatStore.ts` | MCP tools state for active session |
| `frontend/src/core/websocket/connection.ts` | Handle mcp.tools.registered + mcp.gateway.error events |
