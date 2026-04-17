# MCP Tool Curation & Persona-Level MCP Configuration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable admins and users to curate MCP tools (hide, rename, add server prefixes) at the gateway level, and allow per-persona MCP tool exclusions with a new Persona MCP tab.

**Architecture:** Extend existing `McpGatewayConfigDto` with `server_configs` and `tool_overrides` (persisted in MongoDB / localStorage). Add `PersonaMcpConfig` to persona documents. Discovery pipeline reads `_gateway_server`, applies curation, detects collisions. New Persona MCP tab shows three-level grouped checkboxes.

**Tech Stack:** Python/FastAPI/Pydantic (backend), React/TSX/Tailwind/Zustand (frontend), MongoDB, localStorage

---

## File Map

### Shared (DTOs & Events)
| File | Action | Responsibility |
|------|--------|----------------|
| `shared/dtos/mcp.py` | Modify | Add `McpServerConfig`, `McpToolOverride`, extend `McpGatewayConfigDto`, add `PersonaMcpConfig` |
| `shared/dtos/persona.py` | Modify | Add `mcp_config` field to `PersonaDto`, `CreatePersonaDto`, `UpdatePersonaDto` |
| `shared/events/mcp.py` | Modify | Add `server_name` to tool entries, add `collisions` field |

### Backend
| File | Action | Responsibility |
|------|--------|----------------|
| `backend/modules/tools/_mcp_registry.py` | Modify | Add `server_tools` to `GatewayHandle`, add `_tool_server_index` to registry |
| `backend/modules/tools/_mcp_discovery.py` | Modify | Read `_gateway_server`, apply curation, detect collisions |
| `backend/modules/tools/__init__.py` | Modify | Add persona MCP filtering to `get_active_definitions()` |
| `backend/modules/tools/_namespace.py` | Modify | Add `normalise_prefix()` helper |
| `backend/modules/persona/_models.py` | Modify | Add `mcp_config` to `PersonaDocument` |
| `backend/modules/persona/_repository.py` | Modify | Add `update_mcp_config()`, extend `to_dto()` |
| `backend/modules/persona/_handlers.py` | Modify | Add `PATCH /{persona_id}/mcp` endpoint |
| `backend/modules/user/_handlers.py` | Modify | Accept `server_configs` and `tool_overrides` in gateway requests |
| `backend/modules/chat/_orchestrator.py` | Modify | Pass persona `mcp_config` to `get_active_definitions()` |

### Frontend
| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/features/mcp/types.ts` | Modify | Add TS interfaces for new models |
| `frontend/src/features/mcp/mcpStore.ts` | Modify | Extend local gateway store with new fields |
| `frontend/src/features/mcp/mcpApi.ts` | Modify | Add persona MCP endpoint |
| `frontend/src/features/mcp/ToolExplorer.tsx` | Modify | Server-grouped layout, per-server/per-tool controls |
| `frontend/src/app/components/user-modal/McpTab.tsx` | Modify | Pass new props to ToolExplorer |
| `frontend/src/app/components/admin-modal/AdminMcpTab.tsx` | Modify | Pass new props to ToolExplorer |
| `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` | Modify | Add MCP tab |
| `frontend/src/app/components/persona-overlay/McpTab.tsx` | Create | Three-level grouped checkboxes for persona MCP exclusions |
| `frontend/src/core/api/persona.ts` | Modify | Add `updatePersonaMcp()` API call |

---

## Task 1: Shared DTOs — New Models & Extended Gateway Config

**Files:**
- Modify: `shared/dtos/mcp.py` (currently 44 lines)
- Modify: `shared/dtos/persona.py` (currently 76 lines)

- [ ] **Step 1: Add McpServerConfig and McpToolOverride to shared/dtos/mcp.py**

Add these models before `McpGatewayConfigDto`:

```python
class McpServerConfig(BaseModel):
    """Per-server settings within a gateway."""
    server_name: str
    prefix_enabled: bool = False
    custom_prefix: str | None = None
    hidden: bool = False


class McpToolOverride(BaseModel):
    """Per-tool overrides within a gateway."""
    original_name: str
    server_name: str
    display_name: str | None = None
    hidden: bool = False
```

- [ ] **Step 2: Extend McpGatewayConfigDto with new fields**

Add two new fields to `McpGatewayConfigDto` (after `disabled_tools`):

```python
class McpGatewayConfigDto(BaseModel):
    """Gateway configuration — used for CRUD and stored in DB / localStorage."""
    id: str
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True
    disabled_tools: list[str] = []
    server_configs: dict[str, McpServerConfig] = {}
    tool_overrides: list[McpToolOverride] = []
```

- [ ] **Step 3: Add PersonaMcpConfig to shared/dtos/mcp.py**

Add at the bottom of the file:

```python
class PersonaMcpConfig(BaseModel):
    """Persona-level MCP tool exclusions. Default: everything enabled."""
    excluded_gateways: list[str] = []
    excluded_servers: list[str] = []
    excluded_tools: list[str] = []
```

- [ ] **Step 4: Add mcp_config to PersonaDto and UpdatePersonaDto**

In `shared/dtos/persona.py`, add import and field:

```python
from shared.dtos.mcp import PersonaMcpConfig
```

Add to `PersonaDto` (after `profile_crop`):

```python
    mcp_config: PersonaMcpConfig | None = None
```

Add to `UpdatePersonaDto` (after `profile_crop`):

```python
    mcp_config: PersonaMcpConfig | None = None
```

- [ ] **Step 5: Verify syntax**

Run: `uv run python -c "from shared.dtos.mcp import McpServerConfig, McpToolOverride, PersonaMcpConfig, McpGatewayConfigDto; print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/mcp.py shared/dtos/persona.py
git commit -m "Add MCP curation DTOs and persona MCP config"
```

---

## Task 2: Shared Events — Server Name & Collisions

**Files:**
- Modify: `shared/events/mcp.py` (currently 35 lines)

- [ ] **Step 1: Extend McpGatewayToolEntry with server_name and collisions**

Replace the `McpGatewayToolEntry` class:

```python
class McpGatewayToolEntry(BaseModel):
    """One gateway with its discovered tool definitions — sent to the frontend."""
    namespace: str
    tier: str
    tools: list[dict]  # [{name, description, server_name}] — lightweight, no full JSON schema
    collisions: list[str] = []  # namespaced names that had duplicates
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from shared.events.mcp import McpGatewayToolEntry; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add shared/events/mcp.py
git commit -m "Add server_name and collisions to MCP gateway events"
```

---

## Task 3: Backend Registry — Server Grouping

**Files:**
- Modify: `backend/modules/tools/_mcp_registry.py` (currently 70 lines)

- [ ] **Step 1: Extend GatewayHandle with server_tools and collisions**

Replace the `GatewayHandle` dataclass:

```python
@dataclass
class GatewayHandle:
    """One connected MCP gateway with its discovered tools."""

    id: str
    name: str  # = namespace
    url: str
    api_key: str | None
    tier: Literal["admin", "remote", "local"]
    tool_definitions: list[ToolDefinition]
    server_tools: dict[str, list[ToolDefinition]] = field(default_factory=dict)
    collisions: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Add _tool_server_index to SessionMcpRegistry**

In `__init__`, add:

```python
    def __init__(self) -> None:
        self._gateways: dict[str, GatewayHandle] = {}
        self._tool_index: dict[str, str] = {}
        self._tool_server_index: dict[str, str] = {}  # namespaced_name -> server_name
        self.backend_discovered: bool = False
```

Update `register()` to populate the server index:

```python
    def register(self, handle: GatewayHandle) -> None:
        """Register a gateway and index its tools."""
        if handle.name in self._gateways:
            raise ValueError(f"Namespace '{handle.name}' is already registered.")
        self._gateways[handle.name] = handle
        for td in handle.tool_definitions:
            self._tool_index[td.name] = handle.name
        for server_name, tools in handle.server_tools.items():
            for td in tools:
                self._tool_server_index[td.name] = server_name
```

- [ ] **Step 3: Add server_name_for_tool() method**

Add after `is_mcp_tool()`:

```python
    def server_name_for_tool(self, tool_name: str) -> str | None:
        """Return the MCP server name for a namespaced tool, or None."""
        return self._tool_server_index.get(tool_name)

    def gateway_for_id(self, gateway_id: str) -> GatewayHandle | None:
        """Look up a gateway by its config ID."""
        for gw in self._gateways.values():
            if gw.id == gateway_id:
                return gw
        return None
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -c "from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_mcp_registry.py
git commit -m "Add server grouping and collision tracking to MCP registry"
```

---

## Task 4: Backend Namespace — Prefix Helper

**Files:**
- Modify: `backend/modules/tools/_namespace.py` (currently 44 lines)

- [ ] **Step 1: Add normalise_prefix() function**

Add after `normalise_namespace()`:

```python
def normalise_prefix(value: str) -> str:
    """Normalise a server name or custom prefix for use as a tool name prefix.

    Same rules as namespace normalisation — lowercase, alphanumeric + underscore.
    """
    result = value.lower().strip()
    result = re.sub(r"[^a-z0-9]", "_", result)
    result = re.sub(r"_+", "_", result)
    result = result.strip("_")
    return result
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from backend.modules.tools._namespace import normalise_prefix; print(normalise_prefix('Quote Wise'))"`

Expected: `quote_wise`

- [ ] **Step 3: Commit**

```bash
git add backend/modules/tools/_namespace.py
git commit -m "Add normalise_prefix helper for MCP server prefixes"
```

---

## Task 5: Backend Discovery — Read _gateway_server, Apply Curation, Detect Collisions

**Files:**
- Modify: `backend/modules/tools/_mcp_discovery.py` (currently 180 lines)

This is the core logic change. The `_raw_tools_to_definitions()` function gets completely rewritten.

- [ ] **Step 1: Update imports**

Add at the top of the file:

```python
from shared.dtos.mcp import McpGatewayConfigDto, McpGatewayStatusDto, McpToolDefinitionDto, McpServerConfig, McpToolOverride
from backend.modules.tools._namespace import normalise_namespace, normalise_prefix
```

Remove the now-redundant `normalise_namespace` import if it was imported from `_namespace` directly.

- [ ] **Step 2: Replace _raw_tools_to_definitions()**

Replace the function (lines 23-40) with:

```python
def _find_tool_override(
    overrides: list[McpToolOverride],
    original_name: str,
    server_name: str,
) -> McpToolOverride | None:
    """Find matching override for a tool."""
    for ov in overrides:
        if ov.original_name == original_name and ov.server_name == server_name:
            return ov
    return None


def _raw_tools_to_definitions(
    namespace: str,
    raw_tools: list[dict],
    disabled_tools: list[str],
    server_configs: dict[str, McpServerConfig],
    tool_overrides: list[McpToolOverride],
) -> tuple[list[ToolDefinition], dict[str, list[ToolDefinition]], list[str]]:
    """Convert raw MCP tools/list response to namespaced ToolDefinitions.

    Returns:
        (flat tool list, server_tools grouping, collision names)
    """
    defs: list[ToolDefinition] = []
    server_tools: dict[str, list[ToolDefinition]] = {}
    seen_names: dict[str, str] = {}  # namespaced_name -> server_name (first-wins)
    collisions: list[str] = []

    for tool in raw_tools:
        original_name = tool.get("name", "")
        server_name = tool.get("_gateway_server", "_unknown")

        # Legacy disabled_tools check
        if original_name in disabled_tools:
            continue

        # Server-level hiding
        server_cfg = server_configs.get(server_name)
        if server_cfg and server_cfg.hidden:
            continue

        # Tool-level hiding via override
        override = _find_tool_override(tool_overrides, original_name, server_name)
        if override and override.hidden:
            continue

        # Determine effective tool name (after rename)
        effective_name = original_name
        if override and override.display_name:
            effective_name = override.display_name

        # Apply server prefix if enabled
        if server_cfg and server_cfg.prefix_enabled:
            prefix = normalise_prefix(server_cfg.custom_prefix or server_name)
            if prefix:
                effective_name = f"{prefix}_{effective_name}"

        namespaced = f"{namespace}__{effective_name}"

        # Collision detection (within this gateway)
        if namespaced in seen_names:
            if namespaced not in collisions:
                collisions.append(namespaced)
            _log.warning(
                "Tool name collision in gateway %s: %s (servers: %s, %s)",
                namespace, namespaced, seen_names[namespaced], server_name,
            )
            continue  # skip duplicate — first-wins
        seen_names[namespaced] = server_name

        td = ToolDefinition(
            name=namespaced,
            description=tool.get("description", ""),
            parameters=tool.get("inputSchema", {}),
        )
        defs.append(td)

        if server_name not in server_tools:
            server_tools[server_name] = []
        server_tools[server_name].append(td)

    return defs, server_tools, collisions
```

- [ ] **Step 3: Update _discover_single_gateway() to use new signature**

Replace lines 43-72. The function passes the gateway config's curation fields through:

```python
async def _discover_single_gateway(
    config: McpGatewayConfigDto,
    tier: str,
) -> tuple[GatewayHandle | None, McpGatewayStatusDto]:
    """Discover tools from one gateway. Returns (handle_or_None, status)."""
    namespace = normalise_namespace(config.name)
    mcp_url = config.url.rstrip("/") + "/mcp"

    raw_tools = await _executor.discover_tools(url=mcp_url, api_key=config.api_key)
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
    )
    status = McpGatewayStatusDto(
        id=config.id, name=namespace, tier=tier, tool_count=len(tool_defs), reachable=True,
    )
    return handle, status
```

- [ ] **Step 4: Update register_local_tools() to accept server info**

Replace `register_local_tools()` (lines 155-179):

```python
def register_local_tools(
    registry: SessionMcpRegistry,
    gateway_id: str,
    namespace: str,
    url: str,
    tools: list[McpToolDefinitionDto],
    server_configs: dict[str, McpServerConfig] | None = None,
    tool_overrides: list[McpToolOverride] | None = None,
) -> list[str]:
    """Register locally-discovered tools from a frontend gateway into the registry.

    Returns list of collision names (if any).
    """
    # Convert McpToolDefinitionDto list to raw dicts for _raw_tools_to_definitions
    raw_tools = [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.parameters,
            "_gateway_server": t.server_name if hasattr(t, "server_name") else "_unknown",
        }
        for t in tools
    ]
    tool_defs, server_tools_map, collisions = _raw_tools_to_definitions(
        namespace, raw_tools, [],
        server_configs or {}, tool_overrides or [],
    )

    handle = GatewayHandle(
        id=gateway_id,
        name=namespace,
        url=url,
        api_key=None,
        tier="local",
        tool_definitions=tool_defs,
        server_tools=server_tools_map,
        collisions=collisions,
    )
    registry.register(handle)
    return collisions
```

- [ ] **Step 5: Update McpToolDefinitionDto to include server_name**

In `shared/dtos/mcp.py`, update `McpToolDefinitionDto`:

```python
class McpToolDefinitionDto(BaseModel):
    """Single tool discovered from a gateway."""
    name: str
    description: str
    parameters: dict  # JSON Schema
    server_name: str = "_unknown"
```

- [ ] **Step 6: Verify syntax**

Run: `uv run python -c "from backend.modules.tools._mcp_discovery import discover_backend_gateways, register_local_tools; print('OK')"`

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/modules/tools/_mcp_discovery.py shared/dtos/mcp.py
git commit -m "Apply MCP curation (hide, rename, prefix) during discovery"
```

---

## Task 6: Backend Tool Service — Persona MCP Filtering

**Files:**
- Modify: `backend/modules/tools/__init__.py` (lines 98-116)

- [ ] **Step 1: Extend get_active_definitions() signature**

Replace `get_active_definitions()` (lines 98-116):

```python
def get_active_definitions(
    disabled_groups: list[str] | None = None,
    mcp_registry: SessionMcpRegistry | None = None,
    persona_mcp_config: "PersonaMcpConfig | None" = None,
) -> list[ToolDefinition]:
    """Return tool definitions for all enabled groups, plus MCP tools if registry provided.

    If persona_mcp_config is provided, excluded gateways/servers/tools are filtered out.
    """
    from shared.dtos.mcp import PersonaMcpConfig  # avoid circular import at module level

    disabled = set(disabled_groups or [])
    definitions: list[ToolDefinition] = []
    for group in get_groups().values():
        if group.id in disabled and group.toggleable:
            continue
        if group.id == "mcp":
            continue
        definitions.extend(group.definitions)

    # Append MCP tools with persona filtering
    if mcp_registry and "mcp" not in disabled:
        excluded_gw_ids = set()
        excluded_servers = set()
        excluded_tools = set()
        if persona_mcp_config:
            excluded_gw_ids = set(persona_mcp_config.excluded_gateways)
            excluded_servers = set(persona_mcp_config.excluded_servers)
            excluded_tools = set(persona_mcp_config.excluded_tools)

        for gw in mcp_registry.gateways.values():
            if gw.id in excluded_gw_ids:
                continue
            for td in gw.tool_definitions:
                if td.name in excluded_tools:
                    continue
                server = mcp_registry.server_name_for_tool(td.name)
                if server and f"{gw.id}:{server}" in excluded_servers:
                    continue
                definitions.append(td)

    return definitions
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -c "from backend.modules.tools import get_active_definitions; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/modules/tools/__init__.py
git commit -m "Add persona MCP exclusion filtering to get_active_definitions"
```

---

## Task 7: Backend Orchestrator — Pass Persona MCP Config

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py` (line 540)

- [ ] **Step 1: Extract persona mcp_config and pass to get_active_definitions**

At line 540, the current call is:

```python
    active_tools = get_active_definitions(disabled_tool_groups, mcp_registry=mcp_registry) or None
```

Replace with:

```python
    # Extract persona MCP config for tool filtering
    persona_mcp_config = None
    if persona and persona.get("mcp_config"):
        from shared.dtos.mcp import PersonaMcpConfig
        persona_mcp_config = PersonaMcpConfig(**persona["mcp_config"])

    active_tools = get_active_definitions(
        disabled_tool_groups,
        mcp_registry=mcp_registry,
        persona_mcp_config=persona_mcp_config,
    ) or None
```

- [ ] **Step 2: Update event emission to include server_name and collisions**

At lines 514-524, update the `McpGatewayToolEntry` construction to include server_name per tool and collisions:

```python
            gateway_entries = [
                McpGatewayToolEntry(
                    namespace=gw.name,
                    tier=gw.tier,
                    tools=[
                        {
                            "name": td.name,
                            "description": td.description,
                            "server_name": gw.server_tools
                                and next(
                                    (sn for sn, tds in gw.server_tools.items() if td in tds),
                                    "_unknown",
                                )
                                or "_unknown",
                        }
                        for td in gw.tool_definitions
                    ],
                    collisions=gw.collisions,
                )
                for gw in mcp_registry.gateways.values()
            ]
```

Wait — that nested lookup is ugly. Better to use the registry's server index:

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

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py`

Expected: no output (success)

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Pass persona MCP config to tool filtering and include server info in events"
```

---

## Task 8: Backend Persona — MCP Config Persistence & Endpoint

**Files:**
- Modify: `backend/modules/persona/_models.py` (currently 30 lines)
- Modify: `backend/modules/persona/_repository.py` (currently 153 lines)
- Modify: `backend/modules/persona/_handlers.py` (currently 536 lines)

- [ ] **Step 1: Add mcp_config to PersonaDocument**

In `_models.py`, add field after `profile_crop`:

```python
    mcp_config: dict | None = None
```

- [ ] **Step 2: Update repository to_dto()**

In `_repository.py`, update `to_dto()` (line 131-152). Add import at top:

```python
from shared.dtos.mcp import PersonaMcpConfig
```

Add after the `profile_crop` line in `to_dto()`:

```python
            mcp_config=PersonaMcpConfig(**doc["mcp_config"]) if doc.get("mcp_config") else None,
```

- [ ] **Step 3: Add update_mcp_config() to repository**

Add method to `PersonaRepository` (after `update_profile_crop()`):

```python
    async def update_mcp_config(
        self, persona_id: str, user_id: str, mcp_config: dict | None,
    ) -> bool:
        result = await self._collection.update_one(
            {"_id": persona_id, "user_id": user_id},
            {"$set": {"mcp_config": mcp_config, "updated_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count > 0
```

Add missing import at top of `_repository.py` if not present:

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Add PATCH endpoint in _handlers.py**

Add import at the top of `_handlers.py`:

```python
from shared.dtos.mcp import PersonaMcpConfig
```

Add the endpoint (after the existing `PATCH /{persona_id}` handler, around line 282):

```python
@router.patch("/{persona_id}/mcp")
async def update_persona_mcp(
    persona_id: str,
    body: PersonaMcpConfig,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    existing = await repo.find_by_id(persona_id, user["sub"])
    if not existing:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Store as dict for MongoDB
    config_dict = body.model_dump()
    # If all lists are empty, store None (= all tools enabled)
    is_empty = not config_dict["excluded_gateways"] and not config_dict["excluded_servers"] and not config_dict["excluded_tools"]
    await repo.update_mcp_config(persona_id, user["sub"], None if is_empty else config_dict)

    updated = await repo.find_by_id(persona_id, user["sub"])
    return repo.to_dto(updated)
```

- [ ] **Step 5: Verify syntax**

Run: `uv run python -m py_compile backend/modules/persona/_handlers.py && uv run python -m py_compile backend/modules/persona/_repository.py && echo OK`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/modules/persona/_models.py backend/modules/persona/_repository.py backend/modules/persona/_handlers.py
git commit -m "Add persona MCP config persistence and PATCH endpoint"
```

---

## Task 9: Backend User Handlers — Accept New Gateway Fields

**Files:**
- Modify: `backend/modules/user/_handlers.py` (lines 657-669, 701-708, 814-842)

- [ ] **Step 1: Update request models**

Update `CreateMcpGatewayRequest` (line 657):

```python
class CreateMcpGatewayRequest(_BaseModel):
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True
    server_configs: dict[str, dict] = {}
    tool_overrides: list[dict] = []
```

Update `UpdateMcpGatewayRequest` (line 664):

```python
class UpdateMcpGatewayRequest(_BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    disabled_tools: list[str] | None = None
    server_configs: dict[str, dict] | None = None
    tool_overrides: list[dict] | None = None
```

- [ ] **Step 2: Update create_mcp_gateway() to include new fields**

In the gateway dict construction (line 701-708), add the new fields:

```python
    gateway = {
        "id": str(uuid4()),
        "name": body.name,
        "url": body.url,
        "api_key": body.api_key,
        "enabled": body.enabled,
        "disabled_tools": [],
        "server_configs": body.server_configs,
        "tool_overrides": body.tool_overrides,
    }
```

Do the same for `create_admin_gateway()` (similar block around line 800).

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/user/_handlers.py && echo OK`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/modules/user/_handlers.py
git commit -m "Accept server_configs and tool_overrides in gateway CRUD endpoints"
```

---

## Task 10: Frontend Types — New Interfaces

**Files:**
- Modify: `frontend/src/features/mcp/types.ts` (currently 33 lines)

- [ ] **Step 1: Add new TypeScript interfaces**

Add after existing interfaces:

```typescript
export interface McpServerConfig {
  server_name: string
  prefix_enabled: boolean
  custom_prefix: string | null
  hidden: boolean
}

export interface McpToolOverride {
  original_name: string
  server_name: string
  display_name: string | null
  hidden: boolean
}

export interface PersonaMcpConfig {
  excluded_gateways: string[]
  excluded_servers: string[]
  excluded_tools: string[]
}
```

Update `McpGatewayConfig` to include new fields:

```typescript
export interface McpGatewayConfig {
  id: string
  name: string
  url: string
  api_key: string | null
  enabled: boolean
  disabled_tools: string[]
  server_configs: Record<string, McpServerConfig>
  tool_overrides: McpToolOverride[]
}
```

Update `McpToolDefinition` to include `server_name`:

```typescript
export interface McpToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  server_name?: string
}
```

Add session tool entry with server info:

```typescript
export interface McpSessionToolEntry {
  name: string
  description: string
  server_name: string
}

export interface McpSessionGateway {
  namespace: string
  tier: 'admin' | 'remote' | 'local'
  tools: McpSessionToolEntry[]
  collisions: string[]
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | head -20`

Expected: no errors (or only pre-existing ones unrelated to MCP types)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/mcp/types.ts
git commit -m "Add TypeScript interfaces for MCP curation and persona config"
```

---

## Task 11: Frontend MCP Store — Extend Local Gateway Persistence

**Files:**
- Modify: `frontend/src/features/mcp/mcpStore.ts` (currently 70 lines)

- [ ] **Step 1: Update local gateway storage to include new fields**

The store already persists `McpGatewayConfig` to localStorage. Since we updated the interface in Task 10, the store automatically handles the new fields via `McpGatewayConfig`. No structural changes needed — but we need a migration for existing localStorage data.

Add a migration helper at the top (after imports):

```typescript
function migrateGateway(gw: McpGatewayConfig): McpGatewayConfig {
  return {
    ...gw,
    server_configs: gw.server_configs ?? {},
    tool_overrides: gw.tool_overrides ?? [],
  }
}
```

In `loadLocalGateways()`, apply migration when reading:

```typescript
loadLocalGateways: () => {
  const raw = readLocalGateways()
  set({ localGateways: raw.map(migrateGateway) })
},
```

- [ ] **Step 2: Update session tools type**

Update the `SessionToolEntry` interface to use the new `McpSessionGateway` type:

```typescript
import type { McpGatewayConfig, McpSessionGateway } from './types'
```

Replace `SessionToolEntry` and the `sessionTools` state:

```typescript
interface McpState {
  localGateways: McpGatewayConfig[]
  sessionGateways: McpSessionGateway[]
  // ... actions
  setSessionGateways: (gateways: McpSessionGateway[]) => void
  clearSessionGateways: () => void
}
```

Update the corresponding actions in the store to use `sessionGateways` instead of `sessionTools`.

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | head -20`

Fix any type errors from consumers of the old `sessionTools` shape.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/mcp/mcpStore.ts
git commit -m "Extend MCP store with curation fields and localStorage migration"
```

---

## Task 12: Frontend MCP API — Persona MCP Endpoint

**Files:**
- Modify: `frontend/src/features/mcp/mcpApi.ts` (currently 31 lines)
- Modify: `frontend/src/core/api/persona.ts` (if it exists, otherwise mcpApi.ts)

- [ ] **Step 1: Add persona MCP API call**

Add to `mcpApi` in `mcpApi.ts`:

```typescript
  // Persona MCP config
  updatePersonaMcp: (personaId: string, config: PersonaMcpConfig) =>
    api.patch<unknown>(`/api/personas/${personaId}/mcp`, config),
```

Add the import:

```typescript
import type { McpGatewayConfig, PersonaMcpConfig } from './types'
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | head -20`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/mcp/mcpApi.ts
git commit -m "Add persona MCP config API endpoint"
```

---

## Task 13: Frontend ToolExplorer — Server-Grouped Layout with Curation Controls

**Files:**
- Modify: `frontend/src/features/mcp/ToolExplorer.tsx` (currently 528 lines)

This is the largest frontend change. The ToolExplorer transforms from a flat list to a server-grouped layout with per-server and per-tool controls.

- [ ] **Step 1: Update props interface**

Replace `ToolExplorerProps` (lines 5-10):

```typescript
interface ToolExplorerProps {
  gateway: McpGatewayConfig
  tier: 'admin' | 'remote' | 'local'
  onToggleTool: (toolName: string, hidden: boolean) => void
  onRenameTool: (originalName: string, serverName: string, displayName: string | null) => void
  onUpdateServerConfig: (serverName: string, config: Partial<McpServerConfig>) => void
  readOnly?: boolean
}
```

Add imports:

```typescript
import type { McpGatewayConfig, McpToolDefinition, McpServerConfig, McpToolOverride } from './types'
```

- [ ] **Step 2: Group tools by _gateway_server**

After loading tools, group them by `_gateway_server` (or the `server_name` field from the tool list response):

```typescript
const toolsByServer = useMemo(() => {
  const grouped: Record<string, McpToolDefinition[]> = {}
  for (const tool of tools) {
    const server = (tool as any)._gateway_server ?? tool.server_name ?? '_unknown'
    if (!grouped[server]) grouped[server] = []
    grouped[server].push(tool)
  }
  return grouped
}, [tools])
```

- [ ] **Step 3: Render server sections**

Replace the flat tool list with collapsible server sections. Each section has:
- Server name header with tool count
- Per-server controls: hide toggle, prefix toggle, custom prefix input
- Tool list with per-tool hide toggle and rename field

The left panel becomes:

```tsx
{Object.entries(toolsByServer).map(([serverName, serverTools]) => {
  const serverCfg = gateway.server_configs[serverName]
  const isServerHidden = serverCfg?.hidden ?? false
  const filteredTools = serverTools.filter(t => {
    const tokens = search.toLowerCase().split(/\s+/).filter(Boolean)
    const hay = `${t.name} ${t.description}`.toLowerCase()
    return tokens.every(tok => hay.includes(tok))
  })
  if (filteredTools.length === 0 && search) return null

  return (
    <div key={serverName} style={{ marginBottom: 16 }}>
      {/* Server header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 8px', borderRadius: 6,
        background: 'rgba(255,255,255,0.04)',
      }}>
        <span style={{ fontWeight: 600, fontSize: 13, flex: 1, opacity: isServerHidden ? 0.4 : 1 }}>
          {serverName}
        </span>
        <span style={{ fontSize: 11, opacity: 0.5 }}>
          {serverTools.length} tools
        </span>
        {!readOnly && (
          <button
            onClick={() => onUpdateServerConfig(serverName, { hidden: !isServerHidden, server_name: serverName })}
            style={{ fontSize: 11, opacity: 0.6, cursor: 'pointer', background: 'none', border: 'none', color: 'inherit' }}
          >
            {isServerHidden ? 'Show' : 'Hide'}
          </button>
        )}
      </div>

      {/* Server prefix controls */}
      {!readOnly && !isServerHidden && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', fontSize: 12 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={serverCfg?.prefix_enabled ?? false}
              onChange={e => onUpdateServerConfig(serverName, {
                server_name: serverName,
                prefix_enabled: e.target.checked,
              })}
            />
            Prefix
          </label>
          {serverCfg?.prefix_enabled && (
            <input
              type="text"
              placeholder={normaliseNamespace(serverName)}
              value={serverCfg?.custom_prefix ?? ''}
              onChange={e => onUpdateServerConfig(serverName, {
                server_name: serverName,
                custom_prefix: e.target.value || null,
              })}
              style={{
                background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 4, padding: '2px 6px', color: 'inherit', fontSize: 12, width: 120,
              }}
            />
          )}
        </div>
      )}

      {/* Tool list */}
      {!isServerHidden && filteredTools.map(tool => {
        const override = gateway.tool_overrides.find(
          o => o.original_name === tool.name && o.server_name === serverName
        )
        const isHidden = override?.hidden ?? false
        return (
          <div
            key={`${serverName}:${tool.name}`}
            onClick={() => setSelectedToolName(tool.name)}
            style={{
              padding: '6px 12px', cursor: 'pointer', fontSize: 13,
              opacity: isHidden ? 0.35 : 1,
              background: selectedToolName === tool.name ? 'rgba(255,255,255,0.08)' : 'transparent',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontWeight: 500 }}>
                {override?.display_name ?? tool.name}
              </span>
              {!readOnly && (
                <button
                  onClick={e => { e.stopPropagation(); onToggleTool(tool.name, !isHidden) }}
                  style={{ fontSize: 10, opacity: 0.5, cursor: 'pointer', background: 'none', border: 'none', color: 'inherit' }}
                >
                  {isHidden ? 'show' : 'hide'}
                </button>
              )}
            </div>
            <div style={{ fontSize: 11, opacity: 0.5, marginTop: 2 }}>
              {tool.description?.slice(0, 80)}
            </div>
          </div>
        )
      })}
    </div>
  )
})}
```

- [ ] **Step 4: Add collision warning banner**

At the top of the tool list area, if the gateway has tools with `_gateway_server` collisions (passed via props or detected locally), show:

```tsx
{collisions.length > 0 && (
  <div style={{
    padding: '8px 12px', margin: '0 0 8px', borderRadius: 6,
    background: 'rgba(245,169,127,0.15)', border: '1px solid rgba(245,169,127,0.3)',
    fontSize: 12,
  }}>
    <strong>Name collisions detected:</strong>{' '}
    {collisions.join(', ')} — only the first tool per name is active.
    Enable server prefixes or rename tools to resolve.
  </div>
)}
```

- [ ] **Step 5: Add rename UI to tool detail panel**

In the right-side detail panel (when a tool is selected), add a rename field:

```tsx
{!readOnly && selectedTool && (
  <div style={{ marginTop: 12 }}>
    <label style={{ fontSize: 12, opacity: 0.6 }}>Display name override</label>
    <input
      type="text"
      placeholder={selectedTool.name}
      value={currentOverride?.display_name ?? ''}
      onChange={e => onRenameTool(
        selectedTool.name,
        (selectedTool as any)._gateway_server ?? '_unknown',
        e.target.value || null,
      )}
      style={{
        display: 'block', width: '100%', marginTop: 4,
        background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: 4, padding: '4px 8px', color: 'inherit', fontSize: 13,
      }}
    />
  </div>
)}
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | head -30`

Fix any type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/mcp/ToolExplorer.tsx
git commit -m "Restructure ToolExplorer with server grouping and curation controls"
```

---

## Task 14: Frontend McpTab & AdminMcpTab — Wire Up Curation Callbacks

**Files:**
- Modify: `frontend/src/app/components/user-modal/McpTab.tsx` (currently 380 lines)
- Modify: `frontend/src/app/components/admin-modal/AdminMcpTab.tsx` (currently 210 lines)

- [ ] **Step 1: Add curation handlers to McpTab**

In `McpTab`, add handlers that update `server_configs` and `tool_overrides` on the gateway and persist:

```typescript
const handleUpdateServerConfig = useCallback(async (
  gateway: McpGatewayConfig, tier: string,
  serverName: string, updates: Partial<McpServerConfig>,
) => {
  const newConfigs = { ...gateway.server_configs }
  const existing = newConfigs[serverName] ?? { server_name: serverName, prefix_enabled: false, custom_prefix: null, hidden: false }
  newConfigs[serverName] = { ...existing, ...updates }

  if (tier === 'local') {
    useMcpStore.getState().updateLocalGateway(gateway.id, { server_configs: newConfigs })
  } else if (tier === 'remote') {
    await mcpApi.updateGateway(gateway.id, { server_configs: newConfigs })
  }
  // Refresh
  fetchGateways()
}, [fetchGateways])

const handleRenameTool = useCallback(async (
  gateway: McpGatewayConfig, tier: string,
  originalName: string, serverName: string, displayName: string | null,
) => {
  const overrides = [...gateway.tool_overrides]
  const idx = overrides.findIndex(o => o.original_name === originalName && o.server_name === serverName)
  if (idx >= 0) {
    overrides[idx] = { ...overrides[idx], display_name: displayName }
  } else {
    overrides.push({ original_name: originalName, server_name: serverName, display_name: displayName, hidden: false })
  }

  if (tier === 'local') {
    useMcpStore.getState().updateLocalGateway(gateway.id, { tool_overrides: overrides })
  } else if (tier === 'remote') {
    await mcpApi.updateGateway(gateway.id, { tool_overrides: overrides })
  }
  fetchGateways()
}, [fetchGateways])

const handleToggleTool = useCallback(async (
  gateway: McpGatewayConfig, tier: string,
  toolName: string, hidden: boolean,
) => {
  // Update tool_overrides (replacing the old disabled_tools approach)
  const overrides = [...gateway.tool_overrides]
  // We need to find the server for this tool — for now use _unknown, or pass it from ToolExplorer
  const idx = overrides.findIndex(o => o.original_name === toolName)
  if (idx >= 0) {
    overrides[idx] = { ...overrides[idx], hidden }
  } else {
    overrides.push({ original_name: toolName, server_name: '_unknown', display_name: null, hidden })
  }

  if (tier === 'local') {
    useMcpStore.getState().updateLocalGateway(gateway.id, { tool_overrides: overrides })
  } else if (tier === 'remote') {
    await mcpApi.updateGateway(gateway.id, { tool_overrides: overrides })
  }
  fetchGateways()
}, [fetchGateways])
```

- [ ] **Step 2: Pass new props to ToolExplorer**

Where `ToolExplorer` is rendered in the explore view, pass the new callbacks:

```tsx
<ToolExplorer
  gateway={exploreGateway}
  tier={exploreTier}
  onToggleTool={(name, hidden) => handleToggleTool(exploreGateway, exploreTier, name, hidden)}
  onRenameTool={(orig, server, display) => handleRenameTool(exploreGateway, exploreTier, orig, server, display)}
  onUpdateServerConfig={(server, cfg) => handleUpdateServerConfig(exploreGateway, exploreTier, server, cfg)}
  readOnly={exploreTier === 'admin'}
/>
```

- [ ] **Step 3: Apply same pattern to AdminMcpTab**

In `AdminMcpTab`, add the same handlers but using `mcpApi.updateAdminGateway()` instead:

```typescript
const handleUpdateServerConfig = useCallback(async (serverName: string, updates: Partial<McpServerConfig>) => {
  if (!exploreGateway) return
  const newConfigs = { ...exploreGateway.server_configs }
  const existing = newConfigs[serverName] ?? { server_name: serverName, prefix_enabled: false, custom_prefix: null, hidden: false }
  newConfigs[serverName] = { ...existing, ...updates }
  await mcpApi.updateAdminGateway(exploreGateway.id, { server_configs: newConfigs })
  fetchGateways()
}, [exploreGateway, fetchGateways])
```

And similar for `handleRenameTool` and `handleToggleTool`.

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | head -30`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/McpTab.tsx frontend/src/app/components/admin-modal/AdminMcpTab.tsx
git commit -m "Wire up MCP curation callbacks in user and admin gateway tabs"
```

---

## Task 15: Frontend Persona MCP Tab — Three-Level Grouped Checkboxes

**Files:**
- Create: `frontend/src/app/components/persona-overlay/McpTab.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Create McpTab component**

Create `frontend/src/app/components/persona-overlay/McpTab.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react'
import { mcpApi } from '../../../features/mcp/mcpApi'
import { useMcpStore } from '../../../features/mcp/mcpStore'
import type { McpSessionGateway, PersonaMcpConfig } from '../../../features/mcp/types'

interface McpTabProps {
  personaId: string
  mcpConfig: PersonaMcpConfig | null
  onSaved: () => void
}

export default function McpTab({ personaId, mcpConfig, onSaved }: McpTabProps) {
  const sessionGateways = useMcpStore(s => s.sessionGateways)
  const [config, setConfig] = useState<PersonaMcpConfig>(
    mcpConfig ?? { excluded_gateways: [], excluded_servers: [], excluded_tools: [] },
  )
  const [saving, setSaving] = useState(false)

  // Sync from props when persona changes
  useEffect(() => {
    setConfig(mcpConfig ?? { excluded_gateways: [], excluded_servers: [], excluded_tools: [] })
  }, [mcpConfig])

  const isGatewayExcluded = useCallback(
    (gwId: string) => config.excluded_gateways.includes(gwId),
    [config.excluded_gateways],
  )

  const isServerExcluded = useCallback(
    (gwId: string, server: string) =>
      config.excluded_gateways.includes(gwId) || config.excluded_servers.includes(`${gwId}:${server}`),
    [config.excluded_gateways, config.excluded_servers],
  )

  const isToolExcluded = useCallback(
    (gwId: string, server: string, toolName: string) =>
      isGatewayExcluded(gwId) || isServerExcluded(gwId, server) || config.excluded_tools.includes(toolName),
    [isGatewayExcluded, isServerExcluded, config.excluded_tools],
  )

  const toggleGateway = useCallback((gwId: string) => {
    setConfig(prev => {
      const excluded = new Set(prev.excluded_gateways)
      if (excluded.has(gwId)) {
        excluded.delete(gwId)
      } else {
        excluded.add(gwId)
      }
      return { ...prev, excluded_gateways: [...excluded] }
    })
  }, [])

  const toggleServer = useCallback((gwId: string, server: string) => {
    const key = `${gwId}:${server}`
    setConfig(prev => {
      const excluded = new Set(prev.excluded_servers)
      if (excluded.has(key)) {
        excluded.delete(key)
      } else {
        excluded.add(key)
      }
      return { ...prev, excluded_servers: [...excluded] }
    })
  }, [])

  const toggleTool = useCallback((toolName: string) => {
    setConfig(prev => {
      const excluded = new Set(prev.excluded_tools)
      if (excluded.has(toolName)) {
        excluded.delete(toolName)
      } else {
        excluded.add(toolName)
      }
      return { ...prev, excluded_tools: [...excluded] }
    })
  }, [])

  // Group tools by server within each gateway
  const gatewayServers = useMemo(() => {
    return sessionGateways.map(gw => {
      const byServer: Record<string, typeof gw.tools> = {}
      for (const tool of gw.tools) {
        const sn = tool.server_name ?? '_unknown'
        if (!byServer[sn]) byServer[sn] = []
        byServer[sn].push(tool)
      }
      return { ...gw, servers: byServer }
    })
  }, [sessionGateways])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await mcpApi.updatePersonaMcp(personaId, config)
      onSaved()
    } finally {
      setSaving(false)
    }
  }, [personaId, config, onSaved])

  if (sessionGateways.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: 'center', opacity: 0.5, fontSize: 14 }}>
        No MCP gateways discovered in this session.
        Start a chat to discover available tools.
      </div>
    )
  }

  return (
    <div style={{ padding: '12px 16px' }}>
      <p style={{ fontSize: 12, opacity: 0.5, marginBottom: 16 }}>
        Uncheck gateways, servers, or individual tools to exclude them from this persona.
        All tools are enabled by default.
      </p>

      {gatewayServers.map(gw => {
        const gwExcluded = isGatewayExcluded(gw.namespace)
        return (
          <div key={gw.namespace} style={{ marginBottom: 16 }}>
            {/* Gateway header */}
            <label style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '6px 8px', borderRadius: 6,
              background: 'rgba(255,255,255,0.06)', cursor: 'pointer',
              fontWeight: 600, fontSize: 14,
            }}>
              <input
                type="checkbox"
                checked={!gwExcluded}
                onChange={() => toggleGateway(gw.namespace)}
              />
              {gw.namespace}
              <span style={{ fontSize: 11, opacity: 0.5, fontWeight: 400 }}>
                ({gw.tier})
              </span>
            </label>

            {/* Servers within gateway */}
            {!gwExcluded && Object.entries(gw.servers).map(([serverName, serverTools]) => {
              const serverExcluded = isServerExcluded(gw.namespace, serverName)
              return (
                <div key={serverName} style={{ marginLeft: 20, marginTop: 6 }}>
                  <label style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '4px 6px', cursor: 'pointer',
                    fontWeight: 500, fontSize: 13,
                  }}>
                    <input
                      type="checkbox"
                      checked={!serverExcluded}
                      onChange={() => toggleServer(gw.namespace, serverName)}
                    />
                    {serverName}
                    <span style={{ fontSize: 11, opacity: 0.4 }}>
                      {serverTools.length} tools
                    </span>
                  </label>

                  {/* Tools within server */}
                  {!serverExcluded && serverTools.map(tool => {
                    const toolExcluded = config.excluded_tools.includes(tool.name)
                    return (
                      <label
                        key={tool.name}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 6,
                          marginLeft: 20, padding: '2px 4px', cursor: 'pointer',
                          fontSize: 12, opacity: toolExcluded ? 0.4 : 1,
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={!toolExcluded}
                          onChange={() => toggleTool(tool.name)}
                        />
                        <span>{tool.name}</span>
                        <span style={{ opacity: 0.4 }}>
                          {tool.description?.slice(0, 60)}
                        </span>
                      </label>
                    )
                  })}
                </div>
              )
            })}
          </div>
        )
      })}

      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          marginTop: 12, padding: '8px 24px', borderRadius: 6,
          background: 'rgba(140,118,215,0.8)', color: '#fff',
          border: 'none', cursor: saving ? 'wait' : 'pointer',
          fontSize: 13, fontWeight: 500,
        }}
      >
        {saving ? 'Saving...' : 'Save'}
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Add MCP tab to PersonaOverlay**

In `PersonaOverlay.tsx`, update the tab type and TABS array:

```typescript
export type PersonaOverlayTab = 'overview' | 'edit' | 'knowledge' | 'memories' | 'history' | 'mcp'

const TABS: { id: PersonaOverlayTab; label: string; subtitle?: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'edit', label: 'Edit' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'memories', label: 'Memories' },
  { id: 'history', label: 'History' },
  { id: 'mcp', label: 'MCP' },
]
```

Add the import:

```typescript
import McpTab from './McpTab'
```

In the tab content switch/render section, add the MCP case:

```tsx
{activeTab === 'mcp' && persona && (
  <McpTab
    personaId={persona.id}
    mcpConfig={persona.mcp_config ?? null}
    onSaved={() => { /* refetch persona */ }}
  />
)}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | head -30`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-overlay/McpTab.tsx frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Add persona MCP tab with three-level grouped tool exclusions"
```

---

## Task 16: Frontend Build Verification & Integration Test

- [ ] **Step 1: Full frontend build**

Run: `cd frontend && pnpm run build`

Expected: Build succeeds with no errors.

- [ ] **Step 2: Backend syntax check on all modified files**

Run:

```bash
uv run python -m py_compile shared/dtos/mcp.py && \
uv run python -m py_compile shared/dtos/persona.py && \
uv run python -m py_compile shared/events/mcp.py && \
uv run python -m py_compile backend/modules/tools/_mcp_registry.py && \
uv run python -m py_compile backend/modules/tools/_mcp_discovery.py && \
uv run python -m py_compile backend/modules/tools/__init__.py && \
uv run python -m py_compile backend/modules/tools/_namespace.py && \
uv run python -m py_compile backend/modules/persona/_models.py && \
uv run python -m py_compile backend/modules/persona/_repository.py && \
uv run python -m py_compile backend/modules/persona/_handlers.py && \
uv run python -m py_compile backend/modules/user/_handlers.py && \
uv run python -m py_compile backend/modules/chat/_orchestrator.py && \
echo "All OK"
```

Expected: `All OK`

- [ ] **Step 3: Start backend and verify startup**

Run: `cd /home/chris/workspace/chatsune && docker compose up -d`

Check logs for startup errors.

- [ ] **Step 4: Manual smoke test**

1. Open the app, go to User Settings → MCP tab
2. Explore a gateway — tools should be grouped by server
3. Toggle a server's prefix on/off, hide/show a tool, rename a tool
4. Open a persona, check the new MCP tab — verify three-level checkboxes
5. Uncheck a tool, save, start a chat — verify the tool is not in the LLM's tool list

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "Fix integration issues from MCP curation implementation"
```
