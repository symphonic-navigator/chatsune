# Integrations System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a plugin-based integrations framework that lets users enable local service integrations (first: Lovense), with per-persona assignment, system prompt extension, response tag parsing, frontend-executed tools, and a chat-level control panel.

**Architecture:** New `backend/modules/integrations/` module owns config persistence and integration definitions. Frontend `features/integrations/` provides a plugin registry, Zustand store, streaming response tag processor, and chat UI panel. Integrations are decoupled from MCP — separate toggle path, separate tool injection. Frontend integrations execute API calls directly from the browser via the existing `ClientToolDispatcher` mechanism.

**Tech Stack:** Python/FastAPI (backend), React/TSX/Zustand/Tailwind (frontend), MongoDB (config storage), existing WebSocket event bus.

---

## File Structure

### Shared Contracts (new files)
- `shared/dtos/integrations.py` — DTOs for integration definitions, user configs, config field schemas
- `shared/events/integrations.py` — Events for config changes and integration actions

### Shared Contracts (modified)
- `shared/topics.py` — Add `INTEGRATION_*` topic constants
- `shared/dtos/persona.py` — Add `PersonaIntegrationConfig` DTO (if not existing, create)

### Backend Module (all new)
- `backend/modules/integrations/__init__.py` — Public API: `IntegrationService` facade
- `backend/modules/integrations/_registry.py` — Static integration definitions
- `backend/modules/integrations/_repository.py` — MongoDB CRUD for user integration configs
- `backend/modules/integrations/_handlers.py` — REST endpoints (`/api/integrations/*`)
- `backend/modules/integrations/_models.py` — Internal document models

### Backend Integration Points (modified)
- `backend/main.py` — Import and register integration router
- `backend/modules/chat/_prompt_assembler.py` — New layer for integration prompt extensions
- `backend/modules/chat/_orchestrator.py` — Merge integration tools into active tools
- `backend/modules/tools/__init__.py` — Add `get_active_definitions()` parameter for integration tools

### Frontend Framework (all new)
- `frontend/src/features/integrations/types.ts` — `IntegrationPlugin` interface and related types
- `frontend/src/features/integrations/registry.ts` — Plugin registry (register/lookup)
- `frontend/src/features/integrations/store.ts` — Zustand store for user integration state
- `frontend/src/features/integrations/api.ts` — REST API client for backend integration endpoints
- `frontend/src/features/integrations/responseTagProcessor.ts` — Streaming tag parser/executor

### Frontend UI (new + modified)
- `frontend/src/app/components/user-modal/IntegrationsTab.tsx` — New tab replacing LovenseTestTab
- `frontend/src/features/integrations/ChatIntegrationsPanel.tsx` — Chat toolbar panel
- `frontend/src/app/components/persona-overlay/IntegrationsTab.tsx` — Persona integration assignment

### Frontend UI (modified)
- `frontend/src/app/components/user-modal/UserModal.tsx` — Replace lovense-test tab with integrations
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — Add integrations tab
- `frontend/src/features/chat/ChatView.tsx` — Wire in ChatIntegrationsPanel
- `frontend/src/features/chat/useChatStream.ts` — Wire in response tag processor
- `frontend/src/core/types/events.ts` — Add `INTEGRATION_*` topic constants
- `frontend/src/core/types/persona.ts` — Add `integrations_config` field to `PersonaDto`

### Frontend Lovense Plugin (all new — built alongside framework to validate it)
- `frontend/src/features/integrations/plugins/lovense/index.ts` — Plugin definition
- `frontend/src/features/integrations/plugins/lovense/api.ts` — Lovense Game Mode API client
- `frontend/src/features/integrations/plugins/lovense/config.tsx` — Config UI component
- `frontend/src/features/integrations/plugins/lovense/tags.ts` — Response tag handlers
- `frontend/src/features/integrations/plugins/lovense/prompt.ts` — System prompt extension text

---

## Task 1: Shared Contracts — DTOs, Events, Topics

**Files:**
- Create: `shared/dtos/integrations.py`
- Modify: `shared/topics.py`
- Create: `shared/events/integrations.py`

- [ ] **Step 1: Create integration DTOs**

```python
# shared/dtos/integrations.py
from typing import Literal

from pydantic import BaseModel


class IntegrationConfigFieldDto(BaseModel):
    """Describes one user-configurable field for an integration."""
    key: str
    label: str
    field_type: Literal["text", "number", "boolean"]
    placeholder: str = ""
    required: bool = True
    description: str = ""


class IntegrationDefinitionDto(BaseModel):
    """Static definition of an available integration (from the registry)."""
    id: str
    display_name: str
    description: str
    icon: str                               # SVG path or emoji for UI
    execution_mode: Literal["frontend", "backend", "hybrid"]
    config_fields: list[IntegrationConfigFieldDto]
    has_tools: bool = False
    has_response_tags: bool = False
    has_prompt_extension: bool = False


class UserIntegrationConfigDto(BaseModel):
    """Per-user config for one integration (persisted in MongoDB)."""
    integration_id: str
    enabled: bool = False
    config: dict = {}                       # keys match config_fields[].key


class PersonaIntegrationConfigDto(BaseModel):
    """Which integrations a persona has enabled."""
    enabled_integration_ids: list[str] = []
```

- [ ] **Step 2: Add topics to shared/topics.py**

Add after the `MCP_GATEWAY_ERROR` line (line 56 of `shared/topics.py`):

```python
    # Integrations
    INTEGRATION_CONFIG_UPDATED = "integration.config.updated"
    INTEGRATION_TOOL_DISPATCH = "integration.tool.dispatch"
    INTEGRATION_TOOL_RESULT = "integration.tool.result"
    INTEGRATION_ACTION_EXECUTED = "integration.action.executed"
    INTEGRATION_EMERGENCY_STOP = "integration.emergency_stop"
```

- [ ] **Step 3: Create integration events**

```python
# shared/events/integrations.py
from datetime import datetime

from pydantic import BaseModel


class IntegrationConfigUpdatedEvent(BaseModel):
    type: str = "integration.config.updated"
    integration_id: str
    enabled: bool
    correlation_id: str
    timestamp: datetime


class IntegrationActionExecutedEvent(BaseModel):
    """Emitted when a response tag triggers an integration action."""
    type: str = "integration.action.executed"
    integration_id: str
    action: str
    success: bool
    display_text: str
    correlation_id: str
    timestamp: datetime


class IntegrationEmergencyStopEvent(BaseModel):
    type: str = "integration.emergency_stop"
    integration_id: str | None = None       # None = all integrations
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile shared/dtos/integrations.py && uv run python -m py_compile shared/events/integrations.py && echo OK`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/integrations.py shared/events/integrations.py shared/topics.py
git commit -m "Add shared contracts for integrations system"
```

---

## Task 2: Backend Module — Registry and Repository

**Files:**
- Create: `backend/modules/integrations/_models.py`
- Create: `backend/modules/integrations/_registry.py`
- Create: `backend/modules/integrations/_repository.py`

- [ ] **Step 1: Create internal models**

```python
# backend/modules/integrations/_models.py
"""Internal document models for the integrations module."""

from dataclasses import dataclass, field
from typing import Literal

from shared.dtos.inference import ToolDefinition


@dataclass(frozen=True)
class IntegrationDefinition:
    """Static definition of an available integration."""
    id: str
    display_name: str
    description: str
    icon: str
    execution_mode: Literal["frontend", "backend", "hybrid"]
    config_fields: list[dict]               # serialised IntegrationConfigFieldDto dicts
    system_prompt_template: str = ""        # injected when integration active for a persona
    response_tag_prefix: str = ""           # e.g. "lovense" for <lovense ...> tags
    tool_definitions: list[ToolDefinition] = field(default_factory=list)
    tool_side: Literal["server", "client"] = "client"
```

- [ ] **Step 2: Create the integration registry**

```python
# backend/modules/integrations/_registry.py
"""Static registry of all known integrations.

Each integration is defined here with its metadata, config schema, tools,
and system prompt template. Plugins are registered at import time.
"""

import logging
from backend.modules.integrations._models import IntegrationDefinition
from shared.dtos.inference import ToolDefinition

_log = logging.getLogger(__name__)

_registry: dict[str, IntegrationDefinition] = {}


def register(definition: IntegrationDefinition) -> None:
    """Register an integration definition."""
    if definition.id in _registry:
        raise ValueError(f"Integration '{definition.id}' already registered")
    _registry[definition.id] = definition
    _log.info("Registered integration: %s", definition.id)


def get(integration_id: str) -> IntegrationDefinition | None:
    """Look up an integration by ID."""
    return _registry.get(integration_id)


def get_all() -> dict[str, IntegrationDefinition]:
    """Return all registered integrations."""
    return dict(_registry)


def _register_builtins() -> None:
    """Register built-in integrations. Called once at import time."""

    register(IntegrationDefinition(
        id="lovense",
        display_name="Lovense",
        description="Control Lovense toys via the Game Mode API on your local network.",
        icon="lovense",
        execution_mode="frontend",
        config_fields=[
            {
                "key": "ip",
                "label": "Phone IP Address",
                "field_type": "text",
                "placeholder": "192.168.0.92",
                "required": True,
                "description": "IP address of the phone running Lovense Remote.",
            },
        ],
        system_prompt_template=(
            '<integrations name="lovense">\n'
            "You have access to Lovense toy control. The user's Lovense Remote app "
            "is connected and you can control their toys.\n\n"
            "To send a command, write a tag in your response:\n"
            "  <lovense command toy strength duration>\n\n"
            "Available commands:\n"
            "  <lovense vibrate TOYNAME STRENGTH SECONDS> — vibrate (strength 1-20)\n"
            "  <lovense rotate TOYNAME STRENGTH SECONDS> — rotate (strength 1-20)\n"
            "  <lovense stop TOYNAME> — stop a specific toy\n"
            "  <lovense stopall> — stop all toys immediately\n\n"
            "TOYNAME is the toy's nickname from GetToys. STRENGTH is 1-20. "
            "SECONDS is duration (0 = indefinite until stopped).\n\n"
            "You can also use the lovense_get_toys tool to query connected toys.\n"
            "Be creative and responsive. Integrate toy control naturally into "
            "conversation — never make it feel mechanical.\n"
            "</integrations>"
        ),
        response_tag_prefix="lovense",
        tool_definitions=[
            ToolDefinition(
                name="lovense_get_toys",
                description="Query connected Lovense toys. Returns toy names, types, and status.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ],
        tool_side="client",
    ))


_register_builtins()
```

- [ ] **Step 3: Create the repository**

```python
# backend/modules/integrations/_repository.py
"""MongoDB persistence for per-user integration configurations."""

import logging
from motor.motor_asyncio import AsyncIOMotorDatabase

_log = logging.getLogger(__name__)

COLLECTION = "user_integration_configs"


class IntegrationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    async def init_indexes(self) -> None:
        await self._col.create_index(
            [("user_id", 1), ("integration_id", 1)],
            unique=True,
        )

    async def get_user_configs(self, user_id: str) -> list[dict]:
        """Return all integration configs for a user."""
        cursor = self._col.find({"user_id": user_id}, {"_id": 0})
        return await cursor.to_list(length=100)

    async def get_user_config(self, user_id: str, integration_id: str) -> dict | None:
        """Return a single integration config."""
        return await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"_id": 0},
        )

    async def upsert_config(
        self,
        user_id: str,
        integration_id: str,
        enabled: bool,
        config: dict,
    ) -> dict:
        """Create or update a user's integration config."""
        doc = {
            "user_id": user_id,
            "integration_id": integration_id,
            "enabled": enabled,
            "config": config,
        }
        await self._col.update_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": doc},
            upsert=True,
        )
        _log.info(
            "Upserted integration config: user=%s integration=%s enabled=%s",
            user_id, integration_id, enabled,
        )
        return doc
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/integrations/_models.py && uv run python -m py_compile backend/modules/integrations/_registry.py && uv run python -m py_compile backend/modules/integrations/_repository.py && echo OK`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_models.py backend/modules/integrations/_registry.py backend/modules/integrations/_repository.py
git commit -m "Add integrations module: registry, repository, and models"
```

---

## Task 3: Backend Module — Handlers and Public API

**Files:**
- Create: `backend/modules/integrations/_handlers.py`
- Create: `backend/modules/integrations/__init__.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create REST handlers**

```python
# backend/modules/integrations/_handlers.py
"""REST endpoints for the integrations module."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.modules.user import require_active_session
from backend.modules.integrations._registry import get_all, get as get_definition
from backend.modules.integrations._repository import IntegrationRepository
from backend.database import get_db
from backend.ws.event_bus import get_event_bus
from shared.dtos.integrations import IntegrationDefinitionDto, IntegrationConfigFieldDto, UserIntegrationConfigDto
from shared.events.integrations import IntegrationConfigUpdatedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _repo() -> IntegrationRepository:
    return IntegrationRepository(get_db())


@router.get("/definitions")
async def list_definitions(
    _user: dict = Depends(require_active_session),
) -> list[IntegrationDefinitionDto]:
    """Return all available integration definitions."""
    defs = get_all()
    return [
        IntegrationDefinitionDto(
            id=d.id,
            display_name=d.display_name,
            description=d.description,
            icon=d.icon,
            execution_mode=d.execution_mode,
            config_fields=[IntegrationConfigFieldDto(**f) for f in d.config_fields],
            has_tools=len(d.tool_definitions) > 0,
            has_response_tags=bool(d.response_tag_prefix),
            has_prompt_extension=bool(d.system_prompt_template),
        )
        for d in defs.values()
    ]


@router.get("/configs")
async def list_user_configs(
    user: dict = Depends(require_active_session),
) -> list[UserIntegrationConfigDto]:
    """Return all integration configs for the current user."""
    repo = _repo()
    docs = await repo.get_user_configs(user["_id"])
    return [UserIntegrationConfigDto(**d) for d in docs]


class _UpsertBody(BaseModel):
    enabled: bool
    config: dict = {}


@router.put("/configs/{integration_id}")
async def upsert_config(
    integration_id: str,
    body: _UpsertBody,
    user: dict = Depends(require_active_session),
) -> UserIntegrationConfigDto:
    """Create or update a user's integration config."""
    definition = get_definition(integration_id)
    if definition is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration_id}")

    repo = _repo()
    doc = await repo.upsert_config(user["_id"], integration_id, body.enabled, body.config)

    # Publish event so frontend can react
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.INTEGRATION_CONFIG_UPDATED,
        IntegrationConfigUpdatedEvent(
            integration_id=integration_id,
            enabled=body.enabled,
            correlation_id=f"int-config-{integration_id}",
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['_id']}",
        target_user_ids=[user["_id"]],
        correlation_id=f"int-config-{integration_id}",
    )

    return UserIntegrationConfigDto(**doc)
```

- [ ] **Step 2: Create the public API (__init__.py)**

```python
# backend/modules/integrations/__init__.py
"""Integrations module — plugin-based local service integrations.

Public API: import only from this file.
"""

from backend.modules.integrations._handlers import router
from backend.modules.integrations._registry import (
    get as get_integration,
    get_all as get_all_integrations,
)
from backend.modules.integrations._repository import IntegrationRepository
from shared.dtos.inference import ToolDefinition


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the integrations module."""
    repo = IntegrationRepository(db)
    await repo.init_indexes()


async def get_enabled_integration_ids(user_id: str, persona_id: str | None = None) -> list[str]:
    """Return integration IDs that are enabled for a user (and optionally filtered by persona)."""
    from backend.database import get_db
    repo = IntegrationRepository(get_db())
    configs = await repo.get_user_configs(user_id)
    enabled = [c["integration_id"] for c in configs if c.get("enabled")]

    if persona_id is not None:
        from backend.modules.persona import get_persona
        persona = await get_persona(persona_id, user_id)
        if persona:
            persona_integrations = (persona.get("integrations_config") or {}).get(
                "enabled_integration_ids", []
            )
            if persona_integrations:
                enabled = [eid for eid in enabled if eid in persona_integrations]
            else:
                # No persona integrations configured = none active
                enabled = []

    return enabled


async def get_integration_tools(
    user_id: str,
    persona_id: str | None = None,
) -> list[ToolDefinition]:
    """Return tool definitions for all integrations enabled for this user+persona."""
    enabled_ids = await get_enabled_integration_ids(user_id, persona_id)
    tools: list[ToolDefinition] = []
    for iid in enabled_ids:
        defn = get_integration(iid)
        if defn and defn.tool_definitions:
            tools.extend(defn.tool_definitions)
    return tools


async def get_integration_prompt_extensions(
    user_id: str,
    persona_id: str | None = None,
) -> str | None:
    """Return combined system prompt extension for all active integrations."""
    enabled_ids = await get_enabled_integration_ids(user_id, persona_id)
    parts: list[str] = []
    for iid in enabled_ids:
        defn = get_integration(iid)
        if defn and defn.system_prompt_template:
            parts.append(defn.system_prompt_template)
    return "\n\n".join(parts) if parts else None


__all__ = [
    "router",
    "init_indexes",
    "get_integration",
    "get_all_integrations",
    "get_enabled_integration_ids",
    "get_integration_tools",
    "get_integration_prompt_extensions",
]
```

- [ ] **Step 3: Register in main.py**

Add import at line 49 (after the `debug_router` import) of `backend/main.py`:

```python
from backend.modules.integrations import router as integrations_router, init_indexes as integrations_init_indexes
```

Add `await integrations_init_indexes(db)` in the startup section alongside other `init_indexes` calls.

Add `app.include_router(integrations_router)` after line 567 (after `debug_router`).

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/integrations/__init__.py && uv run python -m py_compile backend/modules/integrations/_handlers.py && echo OK`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/__init__.py backend/modules/integrations/_handlers.py backend/main.py
git commit -m "Add integrations REST API and register in main.py"
```

---

## Task 4: Backend Integration — Prompt Assembly and Tool Injection

**Files:**
- Modify: `backend/modules/chat/_prompt_assembler.py`
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Add integration layer to prompt assembler**

In `backend/modules/chat/_prompt_assembler.py`, add a new layer between the memory layer (line 108) and the user about_me layer (line 111). The integration prompt sits after memory so the persona voice and memories are established first:

After line 108 (`parts.append(memory_xml)`), add:

```python
    # Layer: Integration prompt extensions (active integrations for this persona)
    from backend.modules.integrations import get_integration_prompt_extensions
    integration_prompt = await get_integration_prompt_extensions(user_id, persona_id)
    if integration_prompt:
        parts.append(integration_prompt)
```

- [ ] **Step 2: Merge integration tools in the orchestrator**

In `backend/modules/chat/_orchestrator.py`, after the `active_tools` assignment (line 493-497), add integration tools. Find the block:

```python
    active_tools = get_active_definitions(
        disabled_tool_groups,
        mcp_registry=mcp_registry,
        persona_mcp_config=persona_mcp_config,
    ) or None
```

After this block, add:

```python
    # Merge integration tools (independent of MCP/tool group toggles)
    from backend.modules.integrations import get_integration_tools
    integration_tools = await get_integration_tools(user_id, persona_id)
    if integration_tools:
        if active_tools is None:
            active_tools = integration_tools
        else:
            active_tools = list(active_tools) + integration_tools
```

Where `persona_id` is available — find it from the `persona` dict. It is available as `persona.get("_id", "")` in the orchestrator context (the `persona` variable is already in scope at that point).

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_prompt_assembler.py && uv run python -m py_compile backend/modules/chat/_orchestrator.py && echo OK`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_prompt_assembler.py backend/modules/chat/_orchestrator.py
git commit -m "Inject integration prompts and tools into chat inference"
```

---

## Task 5: Frontend Framework — Types and Registry

**Files:**
- Create: `frontend/src/features/integrations/types.ts`
- Create: `frontend/src/features/integrations/registry.ts`

- [ ] **Step 1: Define TypeScript interfaces**

```typescript
// frontend/src/features/integrations/types.ts

/** Mirrors IntegrationConfigFieldDto from the backend. */
export interface IntegrationConfigField {
  key: string
  label: string
  field_type: 'text' | 'number' | 'boolean'
  placeholder: string
  required: boolean
  description: string
}

/** Mirrors IntegrationDefinitionDto from the backend. */
export interface IntegrationDefinition {
  id: string
  display_name: string
  description: string
  icon: string
  execution_mode: 'frontend' | 'backend' | 'hybrid'
  config_fields: IntegrationConfigField[]
  has_tools: boolean
  has_response_tags: boolean
  has_prompt_extension: boolean
}

/** Mirrors UserIntegrationConfigDto from the backend. */
export interface UserIntegrationConfig {
  integration_id: string
  enabled: boolean
  config: Record<string, unknown>
}

/** Result of a response tag execution. */
export interface TagExecutionResult {
  success: boolean
  displayText: string
}

/** Health status reported by a plugin's healthCheck. */
export type HealthStatus = 'connected' | 'reachable' | 'unreachable' | 'unknown'

/**
 * Frontend plugin interface. Each integration registers one of these.
 * Only frontend/hybrid integrations need most of these — backend-only
 * integrations use just metadata + config UI.
 */
export interface IntegrationPlugin {
  id: string

  /** Execute a response tag found in the LLM output. */
  executeTag?: (command: string, args: string[], config: Record<string, unknown>) => Promise<TagExecutionResult>

  /** Execute a tool call dispatched from the backend. */
  executeTool?: (toolName: string, args: Record<string, unknown>, config: Record<string, unknown>) => Promise<string>

  /** Check whether the integration is reachable. */
  healthCheck?: (config: Record<string, unknown>) => Promise<HealthStatus>

  /** Emergency stop — halt all activity immediately. */
  emergencyStop?: (config: Record<string, unknown>) => Promise<void>

  /** Custom config UI component (rendered in IntegrationsTab). */
  ConfigComponent?: React.ComponentType<{ config: Record<string, unknown>; onChange: (config: Record<string, unknown>) => void }>
}
```

- [ ] **Step 2: Create the plugin registry**

```typescript
// frontend/src/features/integrations/registry.ts

import type { IntegrationPlugin } from './types'

const plugins = new Map<string, IntegrationPlugin>()

export function registerPlugin(plugin: IntegrationPlugin): void {
  if (plugins.has(plugin.id)) {
    console.warn(`Integration plugin '${plugin.id}' already registered`)
    return
  }
  plugins.set(plugin.id, plugin)
}

export function getPlugin(id: string): IntegrationPlugin | undefined {
  return plugins.get(id)
}

export function getAllPlugins(): Map<string, IntegrationPlugin> {
  return plugins
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/integrations/types.ts frontend/src/features/integrations/registry.ts
git commit -m "Add frontend integration types and plugin registry"
```

---

## Task 6: Frontend Framework — API Client and Store

**Files:**
- Create: `frontend/src/features/integrations/api.ts`
- Create: `frontend/src/features/integrations/store.ts`

- [ ] **Step 1: Create the API client**

```typescript
// frontend/src/features/integrations/api.ts

import { api } from '../../core/api/client'
import type { IntegrationDefinition, UserIntegrationConfig } from './types'

export const integrationsApi = {
  listDefinitions: () =>
    api.get<IntegrationDefinition[]>('/api/integrations/definitions'),

  listConfigs: () =>
    api.get<UserIntegrationConfig[]>('/api/integrations/configs'),

  upsertConfig: (integrationId: string, enabled: boolean, config: Record<string, unknown>) =>
    api.put<UserIntegrationConfig>(`/api/integrations/configs/${integrationId}`, {
      enabled,
      config,
    }),
}
```

- [ ] **Step 2: Create the Zustand store**

```typescript
// frontend/src/features/integrations/store.ts

import { create } from 'zustand'
import type { IntegrationDefinition, UserIntegrationConfig, HealthStatus } from './types'
import { integrationsApi } from './api'

interface IntegrationsState {
  definitions: IntegrationDefinition[]
  configs: Map<string, UserIntegrationConfig>
  healthStatus: Map<string, HealthStatus>
  loaded: boolean
  loading: boolean

  /** Fetch definitions + configs from backend. Called once on app boot. */
  load: () => Promise<void>

  /** Update a single integration config (persists to backend). */
  upsertConfig: (integrationId: string, enabled: boolean, config: Record<string, unknown>) => Promise<void>

  /** Update health status for an integration (frontend-only state). */
  setHealth: (integrationId: string, status: HealthStatus) => void

  /** Get config for a specific integration. */
  getConfig: (integrationId: string) => UserIntegrationConfig | undefined

  /** Get list of enabled integration IDs. */
  getEnabledIds: () => string[]
}

export const useIntegrationsStore = create<IntegrationsState>((set, get) => ({
  definitions: [],
  configs: new Map(),
  healthStatus: new Map(),
  loaded: false,
  loading: false,

  load: async () => {
    if (get().loading) return
    set({ loading: true })
    try {
      const [definitions, configs] = await Promise.all([
        integrationsApi.listDefinitions(),
        integrationsApi.listConfigs(),
      ])
      const configMap = new Map<string, UserIntegrationConfig>()
      for (const c of configs) {
        configMap.set(c.integration_id, c)
      }
      set({ definitions, configs: configMap, loaded: true })
    } finally {
      set({ loading: false })
    }
  },

  upsertConfig: async (integrationId, enabled, config) => {
    const result = await integrationsApi.upsertConfig(integrationId, enabled, config)
    set((s) => {
      const next = new Map(s.configs)
      next.set(integrationId, result)
      return { configs: next }
    })
  },

  setHealth: (integrationId, status) =>
    set((s) => {
      const next = new Map(s.healthStatus)
      next.set(integrationId, status)
      return { healthStatus: next }
    }),

  getConfig: (integrationId) => get().configs.get(integrationId),

  getEnabledIds: () => {
    const ids: string[] = []
    for (const [id, c] of get().configs) {
      if (c.enabled) ids.push(id)
    }
    return ids
  },
}))
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/integrations/api.ts frontend/src/features/integrations/store.ts
git commit -m "Add integrations API client and Zustand store"
```

---

## Task 7: Frontend — Lovense Plugin

**Files:**
- Create: `frontend/src/features/integrations/plugins/lovense/api.ts`
- Create: `frontend/src/features/integrations/plugins/lovense/tags.ts`
- Create: `frontend/src/features/integrations/plugins/lovense/prompt.ts`
- Create: `frontend/src/features/integrations/plugins/lovense/config.tsx`
- Create: `frontend/src/features/integrations/plugins/lovense/index.ts`

- [ ] **Step 1: Create Lovense API client**

```typescript
// frontend/src/features/integrations/plugins/lovense/api.ts

function buildUrl(ip: string): string {
  const dashed = ip.trim().replace(/\./g, '-')
  return `https://${dashed}.lovense.club:30010/command`
}

export async function sendCommand(ip: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const url = buildUrl(ip)
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return await res.json()
}

export async function getToys(ip: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'GetToys' })
}

export async function vibrate(ip: string, toy: string, strength: number, seconds: number): Promise<Record<string, unknown>> {
  return sendCommand(ip, {
    command: 'Function',
    action: `Vibrate:${strength}`,
    timeSec: seconds,
    toy,
  })
}

export async function rotate(ip: string, toy: string, strength: number, seconds: number): Promise<Record<string, unknown>> {
  return sendCommand(ip, {
    command: 'Function',
    action: `Rotate:${strength}`,
    timeSec: seconds,
    toy,
  })
}

export async function stopToy(ip: string, toy: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'Function', action: 'Stop', toy })
}

export async function stopAll(ip: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'Function', action: 'Stop' })
}
```

- [ ] **Step 2: Create tag handlers**

```typescript
// frontend/src/features/integrations/plugins/lovense/tags.ts

import type { TagExecutionResult } from '../../types'
import * as api from './api'

/**
 * Parse and execute a Lovense response tag.
 * Tag format: <lovense command [args...]>
 * Examples:
 *   <lovense vibrate nova 5 3>
 *   <lovense stop nova>
 *   <lovense stopall>
 */
export async function executeTag(
  command: string,
  args: string[],
  config: Record<string, unknown>,
): Promise<TagExecutionResult> {
  const ip = config.ip as string | undefined
  if (!ip) {
    return { success: false, displayText: '_[Lovense: no IP configured]_' }
  }

  try {
    switch (command.toLowerCase()) {
      case 'vibrate': {
        const [toy, strengthStr, secondsStr] = args
        const strength = parseInt(strengthStr, 10) || 5
        const seconds = parseInt(secondsStr, 10) || 0
        await api.vibrate(ip, toy, strength, seconds)
        return {
          success: true,
          displayText: seconds > 0
            ? `_vibrate ${toy} at strength ${strength} for ${seconds}s_`
            : `_vibrate ${toy} at strength ${strength}_`,
        }
      }
      case 'rotate': {
        const [toy, strengthStr, secondsStr] = args
        const strength = parseInt(strengthStr, 10) || 5
        const seconds = parseInt(secondsStr, 10) || 0
        await api.rotate(ip, toy, strength, seconds)
        return {
          success: true,
          displayText: seconds > 0
            ? `_rotate ${toy} at strength ${strength} for ${seconds}s_`
            : `_rotate ${toy} at strength ${strength}_`,
        }
      }
      case 'stop': {
        const [toy] = args
        await api.stopToy(ip, toy)
        return { success: true, displayText: `_stop ${toy}_` }
      }
      case 'stopall': {
        await api.stopAll(ip)
        return { success: true, displayText: '_stop all toys_' }
      }
      default:
        return { success: false, displayText: `_[Lovense: unknown command "${command}"]_` }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { success: false, displayText: `_[Lovense error: ${msg}]_` }
  }
}
```

- [ ] **Step 3: Create prompt template export**

```typescript
// frontend/src/features/integrations/plugins/lovense/prompt.ts

/** System prompt extension for Lovense integration. Matches the backend registry. */
export const LOVENSE_PROMPT = `You have access to Lovense toy control. The user's Lovense Remote app is connected and you can control their toys.

To send a command, write a tag in your response:
  <lovense command toy strength duration>

Available commands:
  <lovense vibrate TOYNAME STRENGTH SECONDS> — vibrate (strength 1-20)
  <lovense rotate TOYNAME STRENGTH SECONDS> — rotate (strength 1-20)
  <lovense stop TOYNAME> — stop a specific toy
  <lovense stopall> — stop all toys immediately

TOYNAME is the toy's nickname from GetToys. STRENGTH is 1-20. SECONDS is duration (0 = indefinite until stopped).

Be creative and responsive. Integrate toy control naturally into conversation — never make it feel mechanical.`
```

- [ ] **Step 4: Create config UI component**

```tsx
// frontend/src/features/integrations/plugins/lovense/config.tsx

import { useState, useCallback } from 'react'
import * as api from './api'

const INPUT = "w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"

interface Props {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function LovenseConfig({ config, onChange }: Props) {
  const [testStatus, setTestStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [testResponse, setTestResponse] = useState<string | null>(null)

  const ip = (config.ip as string) ?? ''

  const handleTest = useCallback(async () => {
    if (!ip.trim()) return
    setTestStatus('loading')
    setTestResponse(null)
    try {
      const result = await api.getToys(ip)
      setTestResponse(JSON.stringify(result, null, 2))
      setTestStatus('success')
    } catch (err) {
      setTestResponse(err instanceof Error ? err.message : String(err))
      setTestStatus('error')
    }
  }, [ip])

  return (
    <div className="flex flex-col gap-4">
      <div>
        <input
          type="text"
          value={ip}
          onChange={(e) => onChange({ ...config, ip: e.target.value })}
          placeholder="192.168.0.92"
          className={INPUT}
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleTest}
          disabled={!ip.trim() || testStatus === 'loading'}
          className={[
            'px-4 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-wider transition-all border',
            ip.trim() && testStatus !== 'loading'
              ? 'border-white/20 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/85 cursor-pointer'
              : 'border-white/8 bg-transparent text-white/25 cursor-not-allowed',
          ].join(' ')}
        >
          {testStatus === 'loading' ? 'Testing...' : 'Test Connection'}
        </button>

        {testStatus === 'success' && (
          <span className="text-[11px] text-green-400/80 font-mono">Connected</span>
        )}
        {testStatus === 'error' && (
          <span className="text-[11px] text-red-400/80 font-mono">Failed</span>
        )}
      </div>

      {testResponse && (
        <pre className={[
          'rounded-lg border px-3 py-2 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-32 overflow-y-auto',
          testStatus === 'success'
            ? 'border-green-500/20 bg-green-500/[0.04] text-green-400/80'
            : 'border-red-500/20 bg-red-500/[0.04] text-red-400/80',
        ].join(' ')}>
          {testResponse}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Create the plugin entry point and register**

```typescript
// frontend/src/features/integrations/plugins/lovense/index.ts

import type { IntegrationPlugin } from '../../types'
import { registerPlugin } from '../../registry'
import { executeTag } from './tags'
import * as api from './api'
import { LovenseConfig } from './config'

const lovensePlugin: IntegrationPlugin = {
  id: 'lovense',

  executeTag,

  executeTool: async (toolName, _args, config) => {
    const ip = config.ip as string | undefined
    if (!ip) return JSON.stringify({ error: 'No IP configured' })

    if (toolName === 'lovense_get_toys') {
      try {
        const result = await api.getToys(ip)
        return JSON.stringify(result)
      } catch (err) {
        return JSON.stringify({ error: err instanceof Error ? err.message : String(err) })
      }
    }

    return JSON.stringify({ error: `Unknown tool: ${toolName}` })
  },

  healthCheck: async (config) => {
    const ip = config.ip as string | undefined
    if (!ip) return 'unknown'
    try {
      const result = await api.getToys(ip)
      if (typeof result === 'object' && result !== null) {
        const data = result.data as Record<string, unknown> | undefined
        if (data && Object.keys(data).length > 0) return 'connected'
        return 'reachable'
      }
      return 'reachable'
    } catch {
      return 'unreachable'
    }
  },

  emergencyStop: async (config) => {
    const ip = config.ip as string | undefined
    if (ip) {
      await api.stopAll(ip)
    }
  },

  ConfigComponent: LovenseConfig,
}

registerPlugin(lovensePlugin)

export default lovensePlugin
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/integrations/plugins/lovense/
git commit -m "Add Lovense integration plugin"
```

---

## Task 8: Frontend — Response Tag Processor

**Files:**
- Create: `frontend/src/features/integrations/responseTagProcessor.ts`

- [ ] **Step 1: Create the streaming tag processor**

```typescript
// frontend/src/features/integrations/responseTagProcessor.ts

import { getPlugin, getAllPlugins } from './registry'
import { useIntegrationsStore } from './store'
import type { TagExecutionResult } from './types'

/**
 * Collects known integration IDs that have response tag support.
 * Used to quickly check if a `<` could be the start of an integration tag.
 */
function getTagPrefixes(): Set<string> {
  const prefixes = new Set<string>()
  const defs = useIntegrationsStore.getState().definitions
  for (const d of defs) {
    if (d.has_response_tags) {
      prefixes.add(d.id)
    }
  }
  return prefixes
}

/**
 * Streaming tag buffer. Accumulates characters when a potential integration
 * tag is being received, then either executes it or flushes as plain text.
 *
 * Tag format: <integration_id command arg1 arg2 ...>
 *
 * Usage: create one instance per streaming session (correlation).
 * Call `process(delta)` for each content delta. It returns the text that
 * should be appended to the visible content — tags are replaced with
 * their execution result.
 */
export class ResponseTagBuffer {
  private buffer = ''
  private insideTag = false
  private tagPrefixes: Set<string>
  private pendingExecutions: Promise<void>[] = []

  /** Callback to replace a tag placeholder with execution result. */
  private onTagResolved: (placeholder: string, replacement: string) => void

  constructor(onTagResolved: (placeholder: string, replacement: string) => void) {
    this.tagPrefixes = getTagPrefixes()
    this.onTagResolved = onTagResolved
  }

  /**
   * Process an incoming content delta. Returns the text to append to
   * visible output. Tags in progress are buffered (returned as '').
   * Completed tags are replaced with a placeholder that gets swapped
   * asynchronously once the tag executes.
   */
  process(delta: string): string {
    if (this.tagPrefixes.size === 0) return delta

    let output = ''

    for (const ch of delta) {
      if (this.insideTag) {
        this.buffer += ch
        if (ch === '>') {
          // Tag complete — parse and execute
          const tagContent = this.buffer.slice(1, -1).trim() // strip < and >
          const parts = tagContent.split(/\s+/)
          const integrationId = parts[0]

          if (this.tagPrefixes.has(integrationId)) {
            const command = parts[1] || ''
            const args = parts.slice(2)
            const placeholder = `\u200B[${integrationId}:${command}]\u200B`
            output += placeholder

            // Fire-and-forget execution, resolve asynchronously
            const execution = this.executeTag(integrationId, command, args, placeholder)
            this.pendingExecutions.push(execution)
          } else {
            // Not a known integration — emit as literal text
            output += this.buffer
          }

          this.buffer = ''
          this.insideTag = false
        }
      } else if (ch === '<') {
        this.insideTag = true
        this.buffer = '<'
      } else {
        output += ch
      }
    }

    return output
  }

  /**
   * Flush any remaining buffer (called at end of stream).
   * Returns buffered text as-is if a tag was never completed.
   */
  flush(): string {
    const remainder = this.buffer
    this.buffer = ''
    this.insideTag = false
    return remainder
  }

  /** Wait for all pending tag executions to complete. */
  async awaitPending(): Promise<void> {
    await Promise.allSettled(this.pendingExecutions)
    this.pendingExecutions = []
  }

  private async executeTag(
    integrationId: string,
    command: string,
    args: string[],
    placeholder: string,
  ): Promise<void> {
    const plugin = getPlugin(integrationId)
    if (!plugin?.executeTag) {
      this.onTagResolved(placeholder, `_[${integrationId}: no tag handler]_`)
      return
    }

    const config = useIntegrationsStore.getState().getConfig(integrationId)
    const userConfig = config?.config ?? {}

    try {
      const result: TagExecutionResult = await plugin.executeTag(command, args, userConfig)
      this.onTagResolved(placeholder, result.displayText)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      this.onTagResolved(placeholder, `_[${integrationId} error: ${msg}]_`)
    }
  }
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/integrations/responseTagProcessor.ts
git commit -m "Add streaming response tag processor for integrations"
```

---

## Task 9: Frontend — IntegrationsTab in User Modal

**Files:**
- Create: `frontend/src/app/components/user-modal/IntegrationsTab.tsx`
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
- Delete content from: `frontend/src/app/components/user-modal/LovenseTestTab.tsx` (replaced)

- [ ] **Step 1: Create the IntegrationsTab**

```tsx
// frontend/src/app/components/user-modal/IntegrationsTab.tsx

import { useEffect, useState, useCallback } from 'react'
import { useIntegrationsStore } from '../../../features/integrations/store'
import { getPlugin } from '../../../features/integrations/registry'
import type { IntegrationDefinition, UserIntegrationConfig, HealthStatus } from '../../../features/integrations/types'

// Ensure plugins are registered
import '../../../features/integrations/plugins/lovense'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

function IntegrationCard({ definition }: { definition: IntegrationDefinition }) {
  const { configs, upsertConfig, healthStatus, setHealth } = useIntegrationsStore()
  const config = configs.get(definition.id)
  const enabled = config?.enabled ?? false
  const userConfig = config?.config ?? {}
  const health = healthStatus.get(definition.id) ?? 'unknown'

  const [localConfig, setLocalConfig] = useState<Record<string, unknown>>(userConfig)
  const [saving, setSaving] = useState(false)

  // Sync local config when store changes
  useEffect(() => {
    setLocalConfig(config?.config ?? {})
  }, [config])

  const handleToggle = useCallback(async () => {
    setSaving(true)
    try {
      await upsertConfig(definition.id, !enabled, localConfig)
    } finally {
      setSaving(false)
    }
  }, [definition.id, enabled, localConfig, upsertConfig])

  const handleSaveConfig = useCallback(async () => {
    setSaving(true)
    try {
      await upsertConfig(definition.id, enabled, localConfig)
    } finally {
      setSaving(false)
    }
  }, [definition.id, enabled, localConfig, upsertConfig])

  // Health check when enabled
  useEffect(() => {
    if (!enabled) {
      setHealth(definition.id, 'unknown')
      return
    }
    const plugin = getPlugin(definition.id)
    if (!plugin?.healthCheck) return

    let cancelled = false
    plugin.healthCheck(localConfig).then((status) => {
      if (!cancelled) setHealth(definition.id, status)
    })
    return () => { cancelled = true }
  }, [enabled, definition.id, localConfig, setHealth])

  const plugin = getPlugin(definition.id)
  const ConfigUI = plugin?.ConfigComponent

  const configDirty = JSON.stringify(localConfig) !== JSON.stringify(userConfig)

  const healthDot = (() => {
    if (!enabled) return null
    switch (health) {
      case 'connected': return <span className="inline-block w-2 h-2 rounded-full bg-green-400" title="Connected" />
      case 'reachable': return <span className="inline-block w-2 h-2 rounded-full bg-yellow-400" title="Reachable (no toys)" />
      case 'unreachable': return <span className="inline-block w-2 h-2 rounded-full bg-red-400" title="Unreachable" />
      default: return <span className="inline-block w-2 h-2 rounded-full bg-white/20" title="Unknown" />
    }
  })()

  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.02] p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold text-white/80">{definition.display_name}</span>
          {healthDot}
        </div>
        <button
          type="button"
          onClick={handleToggle}
          disabled={saving}
          className={[
            'px-3 py-1 rounded-full text-[10px] font-mono uppercase tracking-wider transition-all border',
            enabled
              ? 'border-green-500/40 bg-green-500/15 text-green-400'
              : 'border-white/15 bg-white/5 text-white/40 hover:text-white/60',
          ].join(' ')}
        >
          {enabled ? 'On' : 'Off'}
        </button>
      </div>

      <p className="text-[11px] text-white/40 font-mono leading-relaxed mb-3">{definition.description}</p>

      {/* Config UI (only when enabled) */}
      {enabled && ConfigUI && (
        <div className="mt-3 pt-3 border-t border-white/6">
          <label className={LABEL}>Configuration</label>
          <ConfigUI config={localConfig} onChange={setLocalConfig} />
          {configDirty && (
            <button
              type="button"
              onClick={handleSaveConfig}
              disabled={saving}
              className="mt-3 px-4 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-wider border border-gold/60 bg-gold/12 text-gold hover:bg-gold/20 transition-all"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          )}
        </div>
      )}

      {/* Feature badges */}
      <div className="flex gap-2 mt-3">
        {definition.has_response_tags && (
          <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">Tags</span>
        )}
        {definition.has_tools && (
          <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">Tools</span>
        )}
        {definition.has_prompt_extension && (
          <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">Prompt</span>
        )}
        <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">{definition.execution_mode}</span>
      </div>
    </div>
  )
}


export function IntegrationsTab() {
  const { definitions, loaded, load } = useIntegrationsStore()

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  if (!loaded) {
    return (
      <div className="p-6">
        <p className="text-[11px] text-white/40 font-mono">Loading integrations...</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6 max-w-xl overflow-y-auto">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Enable integrations to let your personas interact with local services
        and devices. Each integration must also be assigned to a persona to
        become active in chat.
      </p>

      {definitions.length === 0 ? (
        <p className="text-[11px] text-white/30 font-mono">No integrations available.</p>
      ) : (
        definitions.map((d) => <IntegrationCard key={d.id} definition={d} />)
      )}
    </div>
  )
}
```

- [ ] **Step 2: Update UserModal.tsx**

In `frontend/src/app/components/user-modal/UserModal.tsx`:

Replace the `LovenseTestTab` import with `IntegrationsTab`:

```typescript
// Remove this line:
import { LovenseTestTab } from './LovenseTestTab'
// Add this line:
import { IntegrationsTab } from './IntegrationsTab'
```

In the `UserModalTab` type, replace `'lovense-test'` with `'integrations'`.

In the `TABS` array, replace `{ id: 'lovense-test', label: 'Lovense' }` with `{ id: 'integrations', label: 'Integrations' }`.

In the render section, replace `{activeTab === 'lovense-test' && <LovenseTestTab />}` with `{activeTab === 'integrations' && <IntegrationsTab />}`.

- [ ] **Step 3: Delete LovenseTestTab.tsx**

Remove `frontend/src/app/components/user-modal/LovenseTestTab.tsx` — its functionality is now in the Lovense plugin's config component.

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git rm frontend/src/app/components/user-modal/LovenseTestTab.tsx
git add frontend/src/app/components/user-modal/IntegrationsTab.tsx frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Add Integrations tab to user modal, replacing Lovense test"
```

---

## Task 10: Frontend — Wire Response Tags into Chat Stream

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`
- Modify: `frontend/src/core/store/chatStore.ts`

- [ ] **Step 1: Add tag replacement support to chatStore**

In `frontend/src/core/store/chatStore.ts`, add a new action after `appendStreamingContent` (line 122):

```typescript
  replaceInStreamingContent: (search: string, replacement: string) =>
    set((s) => ({
      streamingContent: s.streamingContent.replace(search, replacement),
    })),
```

- [ ] **Step 2: Wire ResponseTagBuffer into useChatStream**

In `frontend/src/features/chat/useChatStream.ts`, at the top of the file add imports:

```typescript
import { ResponseTagBuffer } from '../integrations/responseTagProcessor'
import { useIntegrationsStore } from '../integrations/store'
```

The `handleChatEvent` function needs to use a `ResponseTagBuffer` instance per streaming session. Since `handleChatEvent` is a module-level function (not a hook), manage the buffer as module-level state:

At the top of the file (after imports), add:

```typescript
let activeTagBuffer: ResponseTagBuffer | null = null
```

In the `CHAT_STREAM_STARTED` case (around line 21-24), after `getStore().startStreaming(event.correlation_id)`, add:

```typescript
      // Create a new tag buffer for this streaming session
      const enabledIds = useIntegrationsStore.getState().getEnabledIds()
      if (enabledIds.length > 0) {
        activeTagBuffer = new ResponseTagBuffer((placeholder, replacement) => {
          getStore().replaceInStreamingContent(placeholder, replacement)
        })
      } else {
        activeTagBuffer = null
      }
```

In the `CHAT_CONTENT_DELTA` case (line 26-29), change:

```typescript
    case Topics.CHAT_CONTENT_DELTA: {
      if (event.correlation_id !== getStore().correlationId) return
      const rawDelta = p.delta as string
      const visibleDelta = activeTagBuffer ? activeTagBuffer.process(rawDelta) : rawDelta
      getStore().appendStreamingContent(visibleDelta)
      break
    }
```

In the `CHAT_STREAM_ENDED` case, before `getStore().finishStreaming(...)`, add:

```typescript
      // Flush any incomplete tag buffer
      if (activeTagBuffer) {
        const remainder = activeTagBuffer.flush()
        if (remainder) getStore().appendStreamingContent(remainder)
        activeTagBuffer = null
      }
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts frontend/src/core/store/chatStore.ts
git commit -m "Wire response tag processor into chat streaming"
```

---

## Task 11: Frontend — Chat Integrations Panel

**Files:**
- Create: `frontend/src/features/integrations/ChatIntegrationsPanel.tsx`
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Create the chat integrations panel**

```tsx
// frontend/src/features/integrations/ChatIntegrationsPanel.tsx

import { useIntegrationsStore } from './store'
import { getPlugin } from './registry'

// Ensure plugins are registered
import './plugins/lovense'

/**
 * Compact integration status & controls shown in the chat toolbar.
 * Displays enabled integrations with health dots and an emergency stop button.
 */
export function ChatIntegrationsPanel() {
  const { definitions, configs, healthStatus } = useIntegrationsStore()

  const enabledDefs = definitions.filter((d) => configs.get(d.id)?.enabled)

  if (enabledDefs.length === 0) return null

  const handleEmergencyStop = async () => {
    for (const d of enabledDefs) {
      const plugin = getPlugin(d.id)
      const config = configs.get(d.id)?.config ?? {}
      if (plugin?.emergencyStop) {
        try {
          await plugin.emergencyStop(config)
        } catch {
          // Best-effort stop
        }
      }
    }
  }

  return (
    <div className="flex items-center gap-2">
      {/* Integration pills */}
      {enabledDefs.map((d) => {
        const health = healthStatus.get(d.id) ?? 'unknown'
        const dotColour = health === 'connected' ? 'bg-green-400'
          : health === 'reachable' ? 'bg-yellow-400'
          : health === 'unreachable' ? 'bg-red-400'
          : 'bg-white/20'

        return (
          <span
            key={d.id}
            className="flex items-center gap-1.5 px-2 py-1 rounded border border-white/10 bg-white/[0.03] text-[10px] font-mono text-white/50"
            title={`${d.display_name}: ${health}`}
          >
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotColour}`} />
            {d.display_name}
          </span>
        )
      })}

      {/* Emergency stop button */}
      <button
        type="button"
        onClick={handleEmergencyStop}
        className="flex h-6 w-6 items-center justify-center rounded border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
        title="Emergency stop all integrations"
        aria-label="Emergency stop"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
          <rect x="1" y="1" width="8" height="8" rx="1" />
        </svg>
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Wire into ChatView**

In `frontend/src/features/chat/ChatView.tsx`, add import:

```typescript
import { ChatIntegrationsPanel } from '../integrations/ChatIntegrationsPanel'
```

In the desktop toolbar section (around line 826-839), add the integrations panel after the ToolToggles div. Find:

```tsx
                <div className="hidden lg:block">
                  <ToolToggles
                    ...
                  />
                </div>
```

After this `</div>`, add:

```tsx
                <div className="hidden lg:block">
                  <ChatIntegrationsPanel />
                </div>
```

In the mobile section, add the integrations panel inside the mobile tray. Find the mobile `<div className="lg:hidden">` section. After the icon buttons row but before the collapsible ToolToggles, add:

```tsx
                  <ChatIntegrationsPanel />
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/integrations/ChatIntegrationsPanel.tsx frontend/src/features/chat/ChatView.tsx
git commit -m "Add integrations panel to chat toolbar with emergency stop"
```

---

## Task 12: Frontend — Persona Integration Assignment

**Files:**
- Create: `frontend/src/app/components/persona-overlay/IntegrationsTab.tsx` (persona overlay version)
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`
- Modify: `frontend/src/core/types/persona.ts`
- Modify: `frontend/src/core/api/personas.ts` (if it exists, or wherever persona API calls live)

- [ ] **Step 1: Add integrations_config to PersonaDto**

In `frontend/src/core/types/persona.ts`, add to the `PersonaDto` interface (after `mcp_config`):

```typescript
  integrations_config: {
    enabled_integration_ids: string[]
  } | null;
```

- [ ] **Step 2: Create the persona IntegrationsTab**

```tsx
// frontend/src/app/components/persona-overlay/IntegrationsTab.tsx

import { useState, useEffect, useCallback } from 'react'
import { useIntegrationsStore } from '../../../features/integrations/store'
import type { PersonaDto } from '../../../core/types/persona'

// Ensure plugins registered
import '../../../features/integrations/plugins/lovense'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

interface Props {
  persona: PersonaDto
  onSave: (personaId: string, data: Record<string, unknown>) => Promise<void>
}

export function IntegrationsTab({ persona, onSave }: Props) {
  const { definitions, configs, loaded, load } = useIntegrationsStore()
  const [enabledIds, setEnabledIds] = useState<string[]>(
    persona.integrations_config?.enabled_integration_ids ?? []
  )
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  // Only show integrations that the user has enabled globally
  const availableDefs = definitions.filter((d) => configs.get(d.id)?.enabled)

  const isDirty = JSON.stringify(enabledIds.sort()) !==
    JSON.stringify((persona.integrations_config?.enabled_integration_ids ?? []).sort())

  const handleToggle = useCallback((id: string) => {
    setEnabledIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }, [])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await onSave(persona.id, {
        integrations_config: { enabled_integration_ids: enabledIds },
      })
    } finally {
      setSaving(false)
    }
  }, [persona.id, enabledIds, onSave])

  if (!loaded) {
    return <div className="p-6"><p className="text-[11px] text-white/40 font-mono">Loading...</p></div>
  }

  return (
    <div className="flex flex-col gap-4 p-6 max-w-xl overflow-y-auto">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Choose which integrations this persona can use during chat.
        Only integrations that are enabled in your user settings appear here.
      </p>

      {availableDefs.length === 0 ? (
        <p className="text-[11px] text-white/30 font-mono">
          No integrations enabled. Enable them in your user settings first.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <label className={LABEL}>Available Integrations</label>
          {availableDefs.map((d) => {
            const active = enabledIds.includes(d.id)
            return (
              <button
                key={d.id}
                type="button"
                onClick={() => handleToggle(d.id)}
                className={[
                  'flex items-center gap-3 px-4 py-2.5 rounded-lg border text-left transition-all',
                  active
                    ? 'border-gold/40 bg-gold/8 text-gold'
                    : 'border-white/8 bg-white/[0.02] text-white/50 hover:text-white/70 hover:border-white/15',
                ].join(' ')}
              >
                <span className={[
                  'w-3 h-3 rounded-sm border flex items-center justify-center transition-all',
                  active ? 'border-gold/60 bg-gold/20' : 'border-white/20',
                ].join(' ')}>
                  {active && (
                    <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                      <path d="M1.5 4L3 5.5L6.5 2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
                <div>
                  <span className="text-[12px] font-mono">{d.display_name}</span>
                  <span className="text-[10px] text-white/30 ml-2">{d.description}</span>
                </div>
              </button>
            )
          })}
        </div>
      )}

      {isDirty && (
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="self-start px-5 py-2 rounded-lg font-mono text-[11px] uppercase tracking-wider border border-gold/60 bg-gold/12 text-gold hover:bg-gold/20 transition-all"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Add Integrations tab to PersonaOverlay**

In `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`:

Add `'integrations'` to the `PersonaOverlayTab` type.

Add `{ id: 'integrations', label: 'Integrations' }` to the `TABS` array (after MCP).

Import the IntegrationsTab:
```typescript
import { IntegrationsTab as PersonaIntegrationsTab } from './IntegrationsTab'
```

In the tab content rendering section, add:
```tsx
{activeTab === 'integrations' && persona && (
  <PersonaIntegrationsTab persona={persona} onSave={handleSavePersona} />
)}
```

Where `handleSavePersona` is the same save handler used by other tabs. Check the existing PersonaOverlay code for the exact prop name and adapt accordingly (it may be `onSave` or passed differently — match the existing MCP tab pattern).

- [ ] **Step 4: Backend — Accept integrations_config on persona update**

In the persona module's update handler (likely `backend/modules/persona/_handlers.py`), ensure the `integrations_config` field is accepted and stored. Since the persona module stores arbitrary fields from the update body, this may already work. Verify by checking how `mcp_config` is handled — if it is simply passed through to MongoDB, `integrations_config` will work the same way with no changes.

- [ ] **Step 5: Verify build**

Run: `cd frontend && pnpm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/persona-overlay/IntegrationsTab.tsx frontend/src/app/components/persona-overlay/PersonaOverlay.tsx frontend/src/core/types/persona.ts
git commit -m "Add persona integration assignment tab"
```

---

## Task 13: Frontend — Integration Tool Execution via ClientToolDispatcher

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts` (or wherever client tool dispatch is handled)

- [ ] **Step 1: Find where client tool dispatch is handled**

Look for the `CHAT_CLIENT_TOOL_DISPATCH` topic handler in the frontend. This is where the backend sends a "please execute this tool" event. It should be in `useChatStream.ts` or a dedicated client tool handler.

- [ ] **Step 2: Add integration tool routing**

In the client tool dispatch handler, before the existing tool execution logic, add a check for integration tools:

```typescript
// Check if this is an integration tool
import { getPlugin } from '../integrations/registry'
import { useIntegrationsStore } from '../integrations/store'

// Inside the CHAT_CLIENT_TOOL_DISPATCH handler:
const toolName = p.tool_name as string
const integrationToolPrefix = toolName.split('_')[0] // e.g. "lovense" from "lovense_get_toys"

// Check all registered plugins for a matching tool
const allPlugins = getAllPlugins()
for (const [pluginId, plugin] of allPlugins) {
  if (toolName.startsWith(pluginId + '_') && plugin.executeTool) {
    const config = useIntegrationsStore.getState().getConfig(pluginId)?.config ?? {}
    const result = await plugin.executeTool(toolName, p.arguments as Record<string, unknown>, config)
    // Send result back to backend
    sendMessageFn({
      type: 'chat.client_tool.result',
      payload: {
        tool_call_id: p.tool_call_id,
        result: { stdout: result, error: null },
      },
    })
    return
  }
}
```

The exact wiring depends on how the existing client tool dispatch works. The key pattern: check if the tool name matches an integration plugin, execute via plugin, return result via WebSocket.

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Route integration tool calls through plugin executors"
```

---

## Task 14: Shared — Add Topics to Frontend Events

**Files:**
- Modify: `frontend/src/core/types/events.ts`

- [ ] **Step 1: Add integration topics to the frontend Topics object**

In `frontend/src/core/types/events.ts`, add after the `MCP_TOOLS_REGISTERED` line (line 111):

```typescript
  // Integrations
  INTEGRATION_CONFIG_UPDATED: "integration.config.updated",
  INTEGRATION_ACTION_EXECUTED: "integration.action.executed",
  INTEGRATION_EMERGENCY_STOP: "integration.emergency_stop",
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/types/events.ts
git commit -m "Add integration topic constants to frontend"
```

---

## Task 15: Integration — Load Integrations Store on App Boot

**Files:**
- Modify: The app bootstrap hook (likely `frontend/src/core/hooks/useBootstrap.ts` or `frontend/src/App.tsx`)

- [ ] **Step 1: Find where initial data is loaded**

Search for where the chat store, MCP store, or other stores are initialised on app startup. There should be a bootstrap hook or effect that runs on mount.

- [ ] **Step 2: Add integrations store loading**

After the existing store initialisation, add:

```typescript
import { useIntegrationsStore } from '../features/integrations/store'

// Inside the bootstrap effect:
useIntegrationsStore.getState().load()
```

This should be fire-and-forget (not awaited) — the IntegrationsTab shows a loading state if data hasn't arrived yet.

- [ ] **Step 3: Ensure Lovense plugin is imported**

Add a side-effect import somewhere that runs early (e.g. in the bootstrap file or App.tsx):

```typescript
import './features/integrations/plugins/lovense'
```

This ensures the plugin's `registerPlugin()` call executes before any code tries to look up plugins.

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm run build 2>&1 | tail -5`

Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/hooks/useBootstrap.ts  # or wherever the change was made
git commit -m "Load integrations store on app bootstrap"
```

---

## Task 16: Final Verification and Cleanup

- [ ] **Step 1: Full backend syntax check**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "from backend.modules.integrations import router, init_indexes, get_integration_tools, get_integration_prompt_extensions; print('OK')"` 

Expected: `OK`

- [ ] **Step 2: Full frontend build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build 2>&1 | tail -10`

Expected: Build succeeds with no TS errors

- [ ] **Step 3: Verify Docker build (both pyproject.toml files)**

Check that `shared/dtos/integrations.py` and `shared/events/integrations.py` don't require any new dependencies. They use only `pydantic` which is already in both `pyproject.toml` files. No new dependencies needed.

- [ ] **Step 4: Final commit (if any loose changes)**

```bash
git add -A
git status
# If there are changes:
git commit -m "Final cleanup for integrations system"
```

---
