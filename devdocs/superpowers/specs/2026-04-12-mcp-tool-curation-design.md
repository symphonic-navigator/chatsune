# MCP Tool Curation & Persona-Level MCP Configuration

**Date:** 2026-04-12
**Status:** Draft

---

## Summary

Extend MCP gateway management so admins and users can curate discovered tools
(hide, rename, add server-name prefixes) and give each persona its own MCP tool
selection. The gateway already exposes a `_gateway_server` field per tool — this
feature makes that data visible and actionable throughout the stack.

---

## Goals

1. **Tool hiding** — remove irrelevant tools from context to save tokens and
   reduce noise (gateway-level, persistent).
2. **Tool renaming** — give tools clearer names for the LLM (gateway-level,
   persistent).
3. **Optional server prefix** — disambiguate tools from different servers behind
   the same gateway. Per-server setting; prefix is the server name by default but
   can be overridden (gateway-level, persistent).
4. **Server-grouped display** — UI groups tools by their originating MCP server
   within each gateway, both in gateway management and persona configuration.
5. **Persona-level MCP exclusions** — per persona, exclude entire gateways,
   entire servers, or individual tools. Default: everything enabled.
6. **Name collision detection** — warn when two tools within the same gateway
   resolve to the same namespaced name; only the first is sent to the LLM.

---

## Non-Goals

- Changing how the MCP gateway itself works (no changes in chatsune-mcp-gateway).
- Cross-gateway collision detection (gateway namespaces already isolate).
- Automatic prefix enforcement (user resolves collisions manually).

---

## Data Model

### 1. Gateway-Level: Server & Tool Configuration

New Pydantic models in `shared/dtos/mcp.py`:

```python
class McpServerConfig(BaseModel):
    """Per-server settings within a gateway."""
    server_name: str               # original _gateway_server value
    prefix_enabled: bool = False   # prepend prefix to tool names?
    custom_prefix: str | None = None  # overrides server_name as prefix
    hidden: bool = False           # hide all tools from this server

class McpToolOverride(BaseModel):
    """Per-tool overrides within a gateway."""
    original_name: str             # original tool name from MCP server
    server_name: str               # which server this tool belongs to
    display_name: str | None = None  # rename (None = keep original)
    hidden: bool = False           # hide this specific tool
```

**McpGatewayConfigDto** gains two new fields:

```python
class McpGatewayConfigDto(BaseModel):
    id: str
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True
    disabled_tools: list[str] = []           # DEPRECATED — kept for migration
    server_configs: dict[str, McpServerConfig] = {}  # key = server_name
    tool_overrides: list[McpToolOverride] = []
```

`disabled_tools` is superseded by `tool_overrides[].hidden`. A one-time migration
converts existing `disabled_tools` entries into `McpToolOverride(hidden=True)` records.
After migration, `disabled_tools` is ignored.

**Storage locations (unchanged pattern):**

| Tier   | Storage                                           |
|--------|---------------------------------------------------|
| Admin  | MongoDB `admin_settings` doc (`_id: "mcp"`)       |
| Remote | MongoDB `users` doc (`mcp_gateways[]`)            |
| Local  | Browser `localStorage` (`chatsune:mcp_local_gateways`) |

All three tiers store the same shape — `server_configs` and `tool_overrides`
are part of the gateway config regardless of tier.

### 2. Persona-Level: MCP Exclusions

New model in `shared/dtos/mcp.py`:

```python
class PersonaMcpConfig(BaseModel):
    """Persona-level MCP tool exclusions. Default: everything enabled."""
    excluded_gateways: list[str] = []      # gateway IDs
    excluded_servers: list[str] = []       # "gateway_id:server_name" pairs
    excluded_tools: list[str] = []         # fully namespaced tool names
```

New field on `PersonaDto` and `PersonaDocument`:

```python
mcp_config: PersonaMcpConfig | None = None  # None = all tools enabled
```

### 3. Tool Definition Extension

`GatewayHandle` in `_mcp_registry.py` gains server grouping:

```python
@dataclass
class GatewayHandle:
    id: str
    name: str          # namespace
    url: str
    api_key: str | None
    tier: str
    tool_definitions: list[ToolDefinition]
    server_tools: dict[str, list[ToolDefinition]]  # server_name -> tools
```

`ToolDefinition` itself stays unchanged — the server association is tracked
in `GatewayHandle.server_tools` and in a new `_tool_server_index` on
`SessionMcpRegistry`:

```python
_tool_server_index: dict[str, str]  # namespaced_tool_name -> server_name
```

---

## Backend Logic

### Discovery Pipeline (modified)

`_mcp_discovery.py` — `_raw_tools_to_definitions()` changes:

1. **Read `_gateway_server`** from each raw tool dict.
2. **Apply server-level hiding**: skip tools whose server has `hidden=True` in
   `server_configs`.
3. **Apply tool-level hiding**: skip tools with a matching `McpToolOverride`
   where `hidden=True`.
4. **Apply rename**: if `McpToolOverride.display_name` is set, use it as the
   tool name (the part after the namespace prefix).
5. **Apply server prefix**: if the server's `prefix_enabled` is true, prepend
   `{prefix}_` before the tool name. Prefix is `custom_prefix` if set,
   otherwise `normalise_namespace(server_name)`.
6. **Build namespaced name**: `{gateway_namespace}__{maybe_prefix_}{tool_name}`.
7. **Collision detection**: after processing all tools for a gateway, check for
   duplicate namespaced names. Log a warning. Include collision info in the
   resulting `GatewayHandle`. Only the first tool per name is kept.

Return type changes to include `server_tools` grouping and a list of collisions.

### Collision Reporting

New field on `McpGatewayToolEntry` (the per-gateway payload inside
`McpToolsRegisteredEvent`):

```python
collisions: list[str] = []  # namespaced names that had duplicates
```

Frontend uses this to render warnings in the gateway management UI.

### Persona Filtering

In `backend/modules/tools/__init__.py` — `get_active_definitions()`:

1. Existing flow: filter by `disabled_tool_groups` and collect MCP tools from
   registry.
2. **New step**: if `persona_mcp_config` is provided, remove:
   - All tools from excluded gateways (match on `gateway_id`).
   - All tools from excluded servers (match on `gateway_id:server_name`).
   - Individual excluded tools (match on namespaced name).
3. Return filtered list.

The persona's `mcp_config` is passed down from the orchestrator, which already
has access to the persona document.

### Migration

On backend startup (or first access), if a gateway config has `disabled_tools`
entries but no corresponding `tool_overrides`, generate `McpToolOverride` records
with `hidden=True` for each entry. Clear `disabled_tools` afterwards.

For local gateways the migration runs in the frontend on first load.

---

## Frontend — Gateway Management UI

### Tool Explorer Restructure

Both `AdminMcpTab` and `McpTab` (user settings) use the `ToolExplorer`
component. It changes from a flat tool list to a **server-grouped** layout:

```
Gateway: "homelab"
├─ Server: quotewise (3 tools visible, 15 hidden)
│  ├─ [x] quotes_about       "Get quotes about a topic"
│  ├─ [x] random_quote        "Get a random quote"
│  └─ [ ] admin_reset         (hidden)
│  Server settings: [ ] Add prefix  [quotewise___]
│
├─ Server: filesystem (5 tools visible)
│  ├─ [x] read_file           "Read file contents"
│  ...
```

**Per-server controls:**
- Toggle: hide entire server
- Toggle: enable server prefix (shows normalised server name as default)
- Text input: override prefix (only visible when prefix enabled)

**Per-tool controls:**
- Toggle: hide/show
- Inline rename field (click tool name to edit, or small edit icon)

**Collision warnings:**
- If collisions exist, show a warning banner at the top of the gateway's tool
  list: "2 tools named `write_data` — only the first is active. Add a server
  prefix or rename to resolve."
- Affected tools get a visual indicator (warning icon).

### Local Gateway Parity

Local gateway settings (`localStorage`) get the same `server_configs` and
`tool_overrides` shape. The `mcpStore.ts` Zustand store is extended to persist
these fields. The UI is identical to remote/admin gateways.

---

## Frontend — Persona MCP Tab

New 6th tab in `PersonaOverlay`: **"MCP"** (or "Tools" — naming TBD, but MCP
is clearer given the existing "tool groups" toggles in chat).

**Layout:** Three-level grouped checkboxes.

```
Gateway: homelab (admin)                    [x]
├─ Server: quotewise                        [x]
│  ├─ [x] quotes_about
│  ├─ [x] random_quote
│  └─ [x] search_quotes
├─ Server: filesystem                       [ ]  (excluded)
│  ├─ [ ] read_file
│  └─ [ ] write_file

Gateway: my-remote (remote)                 [x]
├─ Server: weather                          [x]
│  ├─ [x] get_forecast
│  └─ [x] get_current
```

**Behaviour:**
- All checkboxes **checked by default** (everything enabled).
- Unchecking a gateway excludes all its tools → adds to `excluded_gateways`.
- Unchecking a server excludes all its tools → adds to `excluded_servers`.
- Unchecking a tool excludes just that one → adds to `excluded_tools`.
- Parent checkboxes show indeterminate state when children are mixed.
- Only tools that passed gateway-level curation (not hidden) appear here.
- Shown tool names reflect any renames and prefixes applied at gateway level.

**Data flow:**
- On open: fetch current persona's `mcp_config` + current session's registered
  tools (grouped by gateway and server).
- On save: PATCH persona with updated `mcp_config`.
- Changes take effect on next chat message (tool list is rebuilt per inference
  call from persona config).

**Tab theming:** Follows the existing chakra colour system. Suggested: anja
(third eye / indigo) — fits the "configuration/perception" metaphor.

---

## API Changes

### Existing Endpoints (shape change only)

- `PATCH /api/user/mcp/gateways/{id}` — body now accepts `server_configs` and
  `tool_overrides` alongside existing fields.
- `PATCH /api/admin/mcp/gateways/{id}` — same.
- `GET /api/user/mcp/gateways` / `GET /api/admin/mcp/gateways` — response
  includes new fields.

### New Endpoint

- `PATCH /api/personas/{id}/mcp` — update persona MCP config.
  Body: `PersonaMcpConfig`.
  Response: updated `PersonaDto`.

### Event Changes

- `McpToolsRegisteredEvent.gateways[].tools` — each tool entry gains a
  `server_name: str` field.
- `McpToolsRegisteredEvent.gateways[].collisions` — new `list[str]` field
  for collision warnings.

---

## Filter Precedence

Filters are applied in this order during tool assembly:

1. **Gateway enabled** — `McpGatewayConfigDto.enabled` (master switch)
2. **Server hidden** — `McpServerConfig.hidden`
3. **Tool hidden** — `McpToolOverride.hidden` (or legacy `disabled_tools`)
4. **Tool rename & prefix** — applied to surviving tools
5. **Collision dedup** — first-wins within a gateway
6. **Session tool groups** — `disabled_tool_groups` (the existing chat-level
   MCP toggle)
7. **Persona exclusions** — `PersonaMcpConfig` (gateway, server, tool level)
8. **Result** — final `list[ToolDefinition]` sent to LLM

---

## Edge Cases

- **Server not in `server_configs`**: use defaults (no prefix, not hidden).
- **Tool not in `tool_overrides`**: use defaults (original name, not hidden).
- **`_gateway_server` missing from tool**: group under a synthetic server name
  `"_unknown"`. This shouldn't happen with the current gateway but handles
  edge cases gracefully.
- **Gateway returns zero tools after filtering**: treat as reachable but empty;
  no error event.
- **Persona references a gateway/server/tool that no longer exists**: silently
  ignore stale exclusions (no error, no cleanup needed — they're just no-ops).
- **Local gateway curation + browser storage**: same data shape as server-side,
  stored in localStorage via mcpStore. Migration of old `disabled_tools` runs
  on first load.

---

## Files to Create or Modify

### Shared
- `shared/dtos/mcp.py` — add `McpServerConfig`, `McpToolOverride`, extend
  `McpGatewayConfigDto`, add `PersonaMcpConfig`
- `shared/dtos/persona.py` — add `mcp_config` field
- `shared/events/mcp.py` — add `server_name` to tool entries, add `collisions`

### Backend
- `backend/modules/tools/_mcp_discovery.py` — read `_gateway_server`, apply
  server/tool overrides, detect collisions
- `backend/modules/tools/_mcp_registry.py` — extend `GatewayHandle` with
  `server_tools`, add `_tool_server_index`
- `backend/modules/tools/__init__.py` — persona filtering in
  `get_active_definitions()`
- `backend/modules/persona/_handlers.py` — new `PATCH /{id}/mcp` endpoint
- `backend/modules/persona/_repository.py` — persist `mcp_config`
- `backend/modules/user/_handlers.py` — accept new fields in gateway PATCH

### Frontend
- `frontend/src/features/mcp/types.ts` — add TS types for new models
- `frontend/src/features/mcp/ToolExplorer.tsx` — server-grouped layout,
  per-server/per-tool controls
- `frontend/src/features/mcp/mcpStore.ts` — extend local gateway persistence
- `frontend/src/features/mcp/mcpApi.ts` — add persona MCP endpoint
- `frontend/src/app/components/user-modal/McpTab.tsx` — use updated explorer
- `frontend/src/app/components/admin-modal/AdminMcpTab.tsx` — use updated
  explorer
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — add MCP tab
- `frontend/src/app/components/persona-overlay/McpTab.tsx` — **new file**,
  three-level grouped checkboxes
