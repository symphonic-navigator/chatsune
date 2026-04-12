# MCP Gateway Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate MCP gateway support into Chatsune — three tiers (admin, user-remote, user-local), with Tool Explorer, Chat toggle, and cache-prefix-stable tool lists.

**Architecture:** MCP tools are discovered once at session start and held in-memory per connection. Backend-executed gateways (admin + user-remote) use a new McpExecutor. Frontend-executed gateways (user-local) reuse the existing ClientToolDispatcher path. All MCP tool names are namespaced as `{gateway_name}__{tool_name}`.

**Tech Stack:** Python/FastAPI (backend), React/TSX/Tailwind (frontend), MCP JSON-RPC over HTTP, Pydantic v2 DTOs, Zustand stores.

**Design Spec:** `docs/superpowers/specs/2026-04-12-mcp-gateway-integration-design.md`
**Gateway Spec:** `GATEWAY-SPEC.md`

---

## File Map

### Create

| File | Responsibility |
|------|---------------|
| `shared/dtos/mcp.py` | MCP DTOs: gateway config, status, tool definitions, registration payload |
| `shared/events/mcp.py` | MCP events: tools registered, gateway error |
| `backend/modules/tools/_mcp_executor.py` | McpExecutor — HTTP MCP JSON-RPC client for backend-executed calls |
| `backend/modules/tools/_mcp_registry.py` | SessionMcpRegistry — per-connection MCP tool state + namespace resolution |
| `backend/modules/tools/_mcp_discovery.py` | Discovery logic — calls tools/list on gateways, builds registry |
| `backend/modules/tools/_namespace.py` | Namespace normalisation utility |
| `tests/test_mcp_registry.py` | Tests for SessionMcpRegistry |
| `tests/test_mcp_namespace.py` | Tests for namespace normalisation |
| `tests/test_mcp_executor.py` | Tests for McpExecutor |
| `frontend/src/features/mcp/mcpClient.ts` | MCP JSON-RPC HTTP client (tools/list, tools/call) |
| `frontend/src/features/mcp/mcpStore.ts` | Zustand store for local gateways + session MCP state |
| `frontend/src/features/mcp/mcpApi.ts` | REST API client for gateway CRUD |
| `frontend/src/features/mcp/types.ts` | TypeScript types for MCP (gateway config, tool definition) |
| `frontend/src/features/mcp/GatewayEditDialog.tsx` | Gateway add/edit inline form |
| `frontend/src/features/mcp/ToolExplorer.tsx` | Split-layout tool explorer with test UI |
| `frontend/src/app/components/user-modal/McpTab.tsx` | MCP settings tab in user modal |
| `frontend/src/features/chat/ToolPopover.tsx` | Tool overview popover for chat top bar |

### Modify

| File | Change |
|------|--------|
| `shared/topics.py` | Add MCP topic constants |
| `backend/modules/tools/__init__.py` | Extend execute_tool() with MCP routing, new timeout constants |
| `backend/modules/tools/_registry.py` | Add `mcp` ToolGroup |
| `backend/modules/user/_models.py` | Add mcp_gateways field to UserDocument |
| `backend/modules/user/_repository.py` | Add MCP gateway CRUD methods |
| `backend/modules/user/_handlers.py` | Add MCP gateway REST endpoints |
| `backend/modules/user/__init__.py` | Expose MCP gateway methods |
| `backend/modules/chat/_orchestrator.py` | Trigger MCP discovery, merge tools into CompletionRequest |
| `backend/ws/router.py` | Handle mcp.tools.register message |
| `backend/main.py` | Register admin MCP routes (if separate router) |
| `frontend/src/app/components/user-modal/UserModal.tsx` | Add MCP tab |
| `frontend/src/features/chat/ToolToggles.tsx` | Add MCP toggle with green accent |
| `frontend/src/features/chat/ChatView.tsx` | Add tool icon + popover in top bar |
| `frontend/src/features/code-execution/clientToolHandler.ts` | Route MCP tools to local gateway |
| `frontend/src/core/websocket/eventBus.ts` or equivalent | Handle mcp.tools.registered + mcp.gateway.error events |

---

## Task 1: Shared Contracts — DTOs, Events, Topics

**Files:**
- Create: `shared/dtos/mcp.py`
- Create: `shared/events/mcp.py`
- Modify: `shared/topics.py`

- [ ] **Step 1: Create MCP DTOs**

```python
# shared/dtos/mcp.py
"""MCP gateway DTOs — shared between backend and frontend contracts."""

from typing import Literal

from pydantic import BaseModel


class McpGatewayConfigDto(BaseModel):
    """Gateway configuration — used for CRUD and stored in DB / localStorage."""

    id: str
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True
    disabled_tools: list[str] = []


class McpGatewayStatusDto(BaseModel):
    """Gateway status after discovery — returned to frontend."""

    id: str
    name: str
    tier: Literal["admin", "remote", "local"]
    tool_count: int
    reachable: bool


class McpToolDefinitionDto(BaseModel):
    """Single tool discovered from a gateway."""

    name: str
    description: str
    parameters: dict  # JSON Schema


class McpToolRegistrationPayload(BaseModel):
    """Frontend -> Backend via WebSocket: registering local gateway tools."""

    gateway_id: str
    name: str
    tier: Literal["local"] = "local"
    tools: list[McpToolDefinitionDto]
```

- [ ] **Step 2: Create MCP events**

```python
# shared/events/mcp.py
"""MCP gateway events."""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.mcp import McpGatewayStatusDto


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
    recoverable: bool
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 3: Add MCP topics to shared/topics.py**

Add after the existing `CHAT_SESSION_PINNED_UPDATED` line (around line 52):

```python
    # MCP gateways
    MCP_TOOLS_REGISTER = "mcp.tools.register"
    MCP_TOOLS_REGISTERED = "mcp.tools.registered"
    MCP_GATEWAY_ERROR = "mcp.gateway.error"
```

- [ ] **Step 4: Verify imports work**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "from shared.dtos.mcp import McpGatewayConfigDto; from shared.events.mcp import McpToolsRegisteredEvent; from shared.topics import Topics; print(Topics.MCP_TOOLS_REGISTERED)"`

Expected: `mcp.tools.registered`

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/mcp.py shared/events/mcp.py shared/topics.py
git commit -m "Add shared MCP contracts: DTOs, events, and topics"
```

---

## Task 2: Namespace Normalisation Utility

**Files:**
- Create: `backend/modules/tools/_namespace.py`
- Create: `tests/test_mcp_namespace.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_namespace.py
"""Tests for MCP namespace normalisation."""

from backend.modules.tools._namespace import normalise_namespace, validate_namespace


class TestNormaliseNamespace:
    def test_lowercase(self):
        assert normalise_namespace("MyServer") == "myserver"

    def test_special_chars_to_underscore(self):
        assert normalise_namespace("my-server.v2") == "my_server_v2"

    def test_collapse_multiple_underscores(self):
        assert normalise_namespace("my--server") == "my_server"

    def test_strip_leading_trailing_underscores(self):
        assert normalise_namespace("_server_") == "server"

    def test_already_clean(self):
        assert normalise_namespace("homelab") == "homelab"

    def test_spaces(self):
        assert normalise_namespace("my server") == "my_server"


class TestValidateNamespace:
    def test_valid(self):
        assert validate_namespace("homelab", existing_namespaces=set()) is None

    def test_empty_name(self):
        err = validate_namespace("", existing_namespaces=set())
        assert err is not None

    def test_duplicate(self):
        err = validate_namespace("homelab", existing_namespaces={"homelab"})
        assert err is not None

    def test_collides_with_builtin(self):
        err = validate_namespace("web_search", existing_namespaces=set())
        assert err is not None

    def test_contains_double_underscore(self):
        err = validate_namespace("my__server", existing_namespaces=set())
        assert err is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_mcp_namespace.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement namespace normalisation**

```python
# backend/modules/tools/_namespace.py
"""MCP gateway namespace normalisation and validation."""

from __future__ import annotations

import re

# Built-in tool names that must never be used as namespaces.
_BUILTIN_TOOL_NAMES = frozenset({
    "web_search", "web_fetch", "knowledge_search",
    "create_artefact", "update_artefact", "read_artefact", "list_artefacts",
    "calculate_js", "write_journal_entry",
})


def normalise_namespace(name: str) -> str:
    """Normalise a gateway name into a valid namespace prefix.

    Lowercase, replace non-alphanumeric with underscore, collapse runs,
    strip leading/trailing underscores.
    """
    result = name.lower().strip()
    result = re.sub(r"[^a-z0-9]", "_", result)
    result = re.sub(r"_+", "_", result)
    result = result.strip("_")
    return result


def validate_namespace(
    name: str,
    existing_namespaces: set[str],
) -> str | None:
    """Return an error message if the namespace is invalid, or None if OK."""
    normalised = normalise_namespace(name) if name else ""
    if not normalised:
        return "Gateway name must not be empty."
    if "__" in normalised:
        return "Gateway name must not contain double underscores."
    if normalised in existing_namespaces:
        return f"Namespace '{normalised}' is already in use."
    if normalised in _BUILTIN_TOOL_NAMES:
        return f"'{normalised}' conflicts with a built-in tool name."
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_mcp_namespace.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_namespace.py tests/test_mcp_namespace.py
git commit -m "Add MCP namespace normalisation and validation"
```

---

## Task 3: Session MCP Registry

**Files:**
- Create: `backend/modules/tools/_mcp_registry.py`
- Create: `tests/test_mcp_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_registry.py
"""Tests for SessionMcpRegistry."""

import pytest

from backend.modules.tools._mcp_registry import SessionMcpRegistry, GatewayHandle
from shared.dtos.inference import ToolDefinition


def _make_handle(
    name: str = "test",
    tier: str = "remote",
    tools: list[ToolDefinition] | None = None,
) -> GatewayHandle:
    return GatewayHandle(
        id="gw-1",
        name=name,
        url="http://localhost:9100",
        api_key=None,
        tier=tier,
        tool_definitions=tools or [
            ToolDefinition(
                name=f"{name}__read_file",
                description="Read a file",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
        ],
    )


class TestSessionMcpRegistry:
    def test_register_and_resolve(self):
        reg = SessionMcpRegistry()
        handle = _make_handle(name="homelab")
        reg.register(handle)
        gw, original = reg.resolve("homelab__read_file")
        assert gw.name == "homelab"
        assert original == "read_file"

    def test_resolve_unknown_raises(self):
        reg = SessionMcpRegistry()
        with pytest.raises(KeyError):
            reg.resolve("unknown__tool")

    def test_is_mcp_tool(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="homelab"))
        assert reg.is_mcp_tool("homelab__read_file") is True
        assert reg.is_mcp_tool("web_search") is False
        assert reg.is_mcp_tool("unknown__tool") is False

    def test_all_definitions_sorted(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="zeta", tools=[
            ToolDefinition(name="zeta__z_tool", description="Z", parameters={}),
        ]))
        reg.register(_make_handle(name="alpha", tools=[
            ToolDefinition(name="alpha__a_tool", description="A", parameters={}),
        ]))
        defs = reg.all_definitions()
        assert [d.name for d in defs] == ["alpha__a_tool", "zeta__z_tool"]

    def test_duplicate_namespace_raises(self):
        reg = SessionMcpRegistry()
        reg.register(_make_handle(name="homelab"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_make_handle(name="homelab"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_mcp_registry.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Implement SessionMcpRegistry**

```python
# backend/modules/tools/_mcp_registry.py
"""Per-connection MCP tool registry — holds discovered gateway tools for one session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shared.dtos.inference import ToolDefinition


@dataclass
class GatewayHandle:
    """One connected MCP gateway with its discovered tools."""

    id: str
    name: str  # = namespace
    url: str
    api_key: str | None
    tier: Literal["admin", "remote", "local"]
    tool_definitions: list[ToolDefinition]


class SessionMcpRegistry:
    """Holds MCP tool state for one WebSocket connection.

    Created at session start, destroyed on disconnect.
    """

    def __init__(self) -> None:
        self._gateways: dict[str, GatewayHandle] = {}  # namespace -> handle
        self._tool_index: dict[str, str] = {}  # namespaced_name -> namespace

    def register(self, handle: GatewayHandle) -> None:
        """Register a gateway and index its tools."""
        if handle.name in self._gateways:
            raise ValueError(f"Namespace '{handle.name}' is already registered.")
        self._gateways[handle.name] = handle
        for td in handle.tool_definitions:
            self._tool_index[td.name] = handle.name

    def resolve(self, tool_name: str) -> tuple[GatewayHandle, str]:
        """Resolve a namespaced tool name to (gateway, original_tool_name).

        Raises KeyError if the tool is not in the index.
        """
        namespace = self._tool_index.get(tool_name)
        if namespace is None:
            raise KeyError(f"MCP tool '{tool_name}' not found in registry.")
        gw = self._gateways[namespace]
        # Strip namespace prefix: "homelab__read_file" -> "read_file"
        original_name = tool_name[len(namespace) + 2:]
        return gw, original_name

    def all_definitions(self) -> list[ToolDefinition]:
        """All MCP tool definitions, sorted alphabetically by name."""
        defs: list[ToolDefinition] = []
        for gw in self._gateways.values():
            defs.extend(gw.tool_definitions)
        defs.sort(key=lambda d: d.name)
        return defs

    def is_mcp_tool(self, tool_name: str) -> bool:
        """True if the tool name is a registered MCP tool."""
        return tool_name in self._tool_index

    @property
    def gateways(self) -> dict[str, GatewayHandle]:
        return self._gateways
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_mcp_registry.py -v`

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_mcp_registry.py tests/test_mcp_registry.py
git commit -m "Add SessionMcpRegistry for per-connection MCP tool state"
```

---

## Task 4: MCP Executor (Backend HTTP Client)

**Files:**
- Create: `backend/modules/tools/_mcp_executor.py`
- Create: `tests/test_mcp_executor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_executor.py
"""Tests for McpExecutor — backend-side MCP JSON-RPC client."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.tools._mcp_executor import McpExecutor


@pytest.fixture
def executor():
    return McpExecutor()


class TestMcpExecutor:
    @pytest.mark.asyncio
    async def test_successful_call(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "file contents here"}],
            },
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://localhost:9100/mcp",
                api_key=None,
                tool_name="read_file",
                arguments={"path": "/tmp/test.txt"},
            )

        parsed = json.loads(result)
        assert parsed["stdout"] == "file contents here"
        assert parsed["error"] is None

    @pytest.mark.asyncio
    async def test_call_with_auth(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await executor.call_tool(
                url="http://example.com/mcp",
                api_key="sk-test-key",
                tool_name="search",
                arguments={"q": "test"},
            )

            call_kwargs = mock_client.post.call_args
            assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer sk-test-key"

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, executor):
        import httpx
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timed out")
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://localhost:9100/mcp",
                api_key=None,
                tool_name="slow_tool",
                arguments={},
            )

        parsed = json.loads(result)
        assert parsed["error"] is not None
        assert "timed out" in parsed["error"].lower() or "timeout" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_jsonrpc_error_returns_error(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32601, "message": "Tool not found"},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://localhost:9100/mcp",
                api_key=None,
                tool_name="missing",
                arguments={},
            )

        parsed = json.loads(result)
        assert parsed["error"] is not None
        assert "not found" in parsed["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_mcp_executor.py -v`

Expected: FAIL — module not found.

- [ ] **Step 3: Add httpx dependency**

Check if httpx is already in the project. If not:

Run: `cd /home/chris/workspace/chatsune && grep httpx pyproject.toml backend/pyproject.toml`

If missing, add to both `pyproject.toml` and `backend/pyproject.toml`. httpx is likely already present since the project uses external HTTP calls.

- [ ] **Step 4: Implement McpExecutor**

```python
# backend/modules/tools/_mcp_executor.py
"""MCP JSON-RPC client for backend-executed tool calls (admin + user-remote gateways)."""

from __future__ import annotations

import json
import logging

import httpx

_log = logging.getLogger(__name__)

_MCP_HTTP_TIMEOUT_S = 30
_REQUEST_ID_COUNTER = 0


def _next_request_id() -> int:
    global _REQUEST_ID_COUNTER
    _REQUEST_ID_COUNTER += 1
    return _REQUEST_ID_COUNTER


class McpExecutor:
    """Calls MCP gateway tools via HTTP JSON-RPC.

    Stateless — one instance can be shared across connections.
    """

    async def call_tool(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """Call a tool on a gateway and return JSON string ``{"stdout": ..., "error": ...}``.

        Never raises. All failure modes produce an error in the returned JSON.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "jsonrpc": "2.0",
            "id": _next_request_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
                resp = await client.post(url, json=payload, headers=headers)

            body = resp.json()

            # JSON-RPC error
            if "error" in body:
                err = body["error"]
                msg = err.get("message", str(err))
                _log.warning("MCP JSON-RPC error from %s: %s", url, msg)
                return json.dumps({"stdout": "", "error": f"MCP error: {msg}"})

            # Successful result — extract text content
            result = body.get("result", {})
            if result.get("isError"):
                content_parts = result.get("content", [])
                text = "\n".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
                return json.dumps({"stdout": "", "error": text or "Tool returned an error"})

            content_parts = result.get("content", [])
            text = "\n".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
            return json.dumps({"stdout": text, "error": None})

        except httpx.TimeoutException:
            _log.warning("MCP call timed out: %s tool=%s", url, tool_name)
            return json.dumps({"stdout": "", "error": f"MCP gateway timed out after {_MCP_HTTP_TIMEOUT_S}s"})
        except Exception as exc:
            _log.warning("MCP call failed: %s tool=%s error=%s", url, tool_name, exc)
            return json.dumps({"stdout": "", "error": f"MCP gateway unreachable: {exc}"})

    async def discover_tools(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
    ) -> list[dict]:
        """Call tools/list on a gateway. Returns list of tool dicts or empty on failure.

        Does NOT raise — returns empty list on any error.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "jsonrpc": "2.0",
            "id": _next_request_id(),
            "method": "tools/list",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)

            body = resp.json()
            if "error" in body:
                _log.warning("MCP tools/list error from %s: %s", url, body["error"])
                return []

            return body.get("result", {}).get("tools", [])

        except Exception as exc:
            _log.warning("MCP tools/list failed for %s: %s", url, exc)
            return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_mcp_executor.py -v`

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py tests/test_mcp_executor.py
git commit -m "Add McpExecutor for backend-side MCP JSON-RPC calls"
```

---

## Task 5: MCP Discovery Logic

**Files:**
- Create: `backend/modules/tools/_mcp_discovery.py`

- [ ] **Step 1: Implement discovery module**

```python
# backend/modules/tools/_mcp_discovery.py
"""MCP gateway discovery — called once at session start to build the SessionMcpRegistry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.tools._mcp_executor import McpExecutor
from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from backend.modules.tools._namespace import normalise_namespace
from backend.ws.event_bus import get_event_bus
from shared.dtos.inference import ToolDefinition
from shared.dtos.mcp import McpGatewayConfigDto, McpGatewayStatusDto, McpToolDefinitionDto
from shared.events.mcp import McpGatewayErrorEvent, McpToolsRegisteredEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)
_executor = McpExecutor()


def _raw_tools_to_definitions(
    namespace: str,
    raw_tools: list[dict],
    disabled_tools: list[str],
) -> list[ToolDefinition]:
    """Convert raw MCP tools/list response to namespaced ToolDefinitions."""
    defs: list[ToolDefinition] = []
    for tool in raw_tools:
        original_name = tool.get("name", "")
        if original_name in disabled_tools:
            continue
        namespaced = f"{namespace}__{original_name}"
        defs.append(ToolDefinition(
            name=namespaced,
            description=tool.get("description", ""),
            parameters=tool.get("inputSchema", {}),
        ))
    return defs


async def _discover_single_gateway(
    config: McpGatewayConfigDto,
    tier: str,
) -> tuple[GatewayHandle | None, McpGatewayStatusDto]:
    """Discover tools from one gateway. Returns (handle_or_None, status)."""
    namespace = normalise_namespace(config.name)
    mcp_url = config.url.rstrip("/") + "/mcp"

    raw_tools = await _executor.discover_tools(url=mcp_url, api_key=config.api_key)

    if not raw_tools and raw_tools is not None:
        # Empty tool list is valid (gateway reachable, no servers configured)
        pass

    reachable = raw_tools is not None and isinstance(raw_tools, list)
    # discover_tools returns [] on failure, so check if we got actual tools or an empty list
    # We treat empty list as reachable (gateway works, just no tools)
    # To distinguish: discover_tools returns [] on both success-empty and failure
    # We'll treat any list response as reachable for simplicity

    tool_defs = _raw_tools_to_definitions(namespace, raw_tools, config.disabled_tools)

    status = McpGatewayStatusDto(
        id=config.id,
        name=namespace,
        tier=tier,
        tool_count=len(tool_defs),
        reachable=len(raw_tools) > 0 or True,  # If discover_tools returned [], gateway might still be reachable
    )

    if not tool_defs and not raw_tools:
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
    )
    return handle, status


async def discover_backend_gateways(
    admin_gateways: list[McpGatewayConfigDto],
    user_remote_gateways: list[McpGatewayConfigDto],
    session_id: str,
    user_id: str,
    correlation_id: str,
) -> SessionMcpRegistry:
    """Discover tools from all backend-reachable gateways (admin + user-remote).

    Emits McpGatewayErrorEvent for unreachable gateways.
    Returns a populated SessionMcpRegistry (may be empty if all fail).
    """
    registry = SessionMcpRegistry()
    statuses: list[McpGatewayStatusDto] = []

    # Build tasks: (config, tier) pairs
    tasks: list[tuple[McpGatewayConfigDto, str]] = []
    for gw in admin_gateways:
        if gw.enabled:
            tasks.append((gw, "admin"))
    for gw in user_remote_gateways:
        if gw.enabled:
            tasks.append((gw, "remote"))

    if not tasks:
        return registry

    # Discover in parallel
    results = await asyncio.gather(
        *[_discover_single_gateway(cfg, tier) for cfg, tier in tasks],
        return_exceptions=True,
    )

    event_bus = get_event_bus()
    for (cfg, tier), result in zip(tasks, results):
        if isinstance(result, Exception):
            _log.warning("MCP discovery failed for %s: %s", cfg.name, result)
            await event_bus.publish(
                Topics.MCP_GATEWAY_ERROR,
                McpGatewayErrorEvent(
                    gateway_id=cfg.id,
                    gateway_name=cfg.name,
                    error=str(result),
                    recoverable=True,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"user:{user_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )
            continue

        handle, status = result
        statuses.append(status)
        if handle:
            try:
                registry.register(handle)
            except ValueError as exc:
                _log.warning("MCP registry conflict: %s", exc)

        if not status.reachable:
            await event_bus.publish(
                Topics.MCP_GATEWAY_ERROR,
                McpGatewayErrorEvent(
                    gateway_id=cfg.id,
                    gateway_name=cfg.name,
                    error="Gateway unreachable or returned no tools",
                    recoverable=True,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"user:{user_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    return registry


def register_local_tools(
    registry: SessionMcpRegistry,
    gateway_id: str,
    namespace: str,
    url: str,
    tools: list[McpToolDefinitionDto],
) -> None:
    """Register locally-discovered tools from a frontend gateway into the registry."""
    tool_defs = [
        ToolDefinition(
            name=f"{namespace}__{t.name}",
            description=t.description,
            parameters=t.parameters,
        )
        for t in tools
    ]
    handle = GatewayHandle(
        id=gateway_id,
        name=namespace,
        url=url,
        api_key=None,  # local gateways: auth handled by frontend
        tier="local",
        tool_definitions=tool_defs,
    )
    registry.register(handle)
```

- [ ] **Step 2: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/tools/_mcp_discovery.py`

Expected: No output (success).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/tools/_mcp_discovery.py
git commit -m "Add MCP discovery logic for backend gateways"
```

---

## Task 6: Extend Tool Module — MCP Routing in execute_tool()

**Files:**
- Modify: `backend/modules/tools/__init__.py`
- Modify: `backend/modules/tools/_registry.py`

- [ ] **Step 1: Add `mcp` ToolGroup to registry**

In `backend/modules/tools/_registry.py`, add to the dict returned by `_build_groups()`, after the `"journal"` entry:

```python
        "mcp": ToolGroup(
            id="mcp",
            display_name="MCP",
            description="Tools from connected MCP gateways",
            side="client",  # side varies, but group toggle uses this; actual routing is in execute_tool
            toggleable=True,
            tool_names=[],  # dynamic — populated per-session, not used for routing
            definitions=[],  # dynamic — populated per-session
            executor=None,
        ),
```

- [ ] **Step 2: Extend execute_tool() with MCP routing**

In `backend/modules/tools/__init__.py`, add imports at the top:

```python
from backend.modules.tools._mcp_executor import McpExecutor
from backend.modules.tools._mcp_registry import SessionMcpRegistry
```

Add new timeout constants after the existing ones (around line 26):

```python
_MCP_SERVER_TIMEOUT_MS = 35_000
_MCP_CLIENT_TIMEOUT_MS = 30_000
```

Add module-level MCP executor singleton:

```python
_mcp_executor = McpExecutor()
```

Add a dict to hold per-connection registries:

```python
# connection_id -> SessionMcpRegistry
_mcp_registries: dict[str, SessionMcpRegistry] = {}


def set_mcp_registry(connection_id: str, registry: SessionMcpRegistry) -> None:
    """Store the MCP registry for a connection (called at session start)."""
    _mcp_registries[connection_id] = registry


def get_mcp_registry(connection_id: str) -> SessionMcpRegistry | None:
    """Retrieve the MCP registry for a connection."""
    return _mcp_registries.get(connection_id)


def remove_mcp_registry(connection_id: str) -> None:
    """Remove the MCP registry when a connection closes."""
    _mcp_registries.pop(connection_id, None)
```

Modify `get_active_definitions()` to accept an optional registry:

```python
def get_active_definitions(
    disabled_groups: list[str] | None = None,
    mcp_registry: SessionMcpRegistry | None = None,
) -> list[ToolDefinition]:
    """Return tool definitions for all enabled groups, plus MCP tools if registry provided."""
    disabled = set(disabled_groups or [])
    definitions: list[ToolDefinition] = []
    for group in get_groups().values():
        if group.id in disabled and group.toggleable:
            continue
        if group.id == "mcp":
            continue  # MCP tools come from registry, not from static group
        definitions.extend(group.definitions)

    # Append MCP tools (already sorted alphabetically by registry)
    if mcp_registry and "mcp" not in disabled:
        definitions.extend(mcp_registry.all_definitions())

    return definitions
```

Modify `execute_tool()` — add MCP routing before the static group loop. Insert before the `for group in get_groups().values():` line:

```python
    # MCP tool routing: any tool containing __ may be an MCP tool
    if "__" in tool_name:
        registry = _mcp_registries.get(originating_connection_id)
        if registry and registry.is_mcp_tool(tool_name):
            try:
                gw, original_name = registry.resolve(tool_name)
                if gw.tier == "local":
                    # Frontend-executed: use ClientToolDispatcher
                    return await _dispatcher_singleton.dispatch(
                        user_id=user_id,
                        session_id=session_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        server_timeout_ms=_MCP_SERVER_TIMEOUT_MS,
                        client_timeout_ms=_MCP_CLIENT_TIMEOUT_MS,
                        target_connection_id=originating_connection_id,
                    )
                else:
                    # Backend-executed: use McpExecutor
                    return await _mcp_executor.call_tool(
                        url=gw.url,
                        api_key=gw.api_key,
                        tool_name=original_name,
                        arguments=arguments,
                    )
            finally:
                duration = _time.monotonic() - t_start
                tool_calls_total.labels(model=model, tool_name=tool_name).inc()
                tool_call_duration_seconds.labels(model=model, tool_name=tool_name).observe(duration)
```

Update `__all__` to include new exports:

```python
__all__ = [
    "get_all_groups",
    "get_active_definitions",
    "execute_tool",
    "get_max_tool_iterations",
    "get_client_dispatcher",
    "set_mcp_registry",
    "get_mcp_registry",
    "remove_mcp_registry",
    "ToolNotFoundError",
]
```

- [ ] **Step 3: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/tools/__init__.py && uv run python -m py_compile backend/modules/tools/_registry.py`

Expected: No output (success).

- [ ] **Step 4: Run existing tests to check for regressions**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/ -v --timeout=30`

Expected: All existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/__init__.py backend/modules/tools/_registry.py
git commit -m "Extend tool module with MCP routing and per-connection registry"
```

---

## Task 7: User MCP Gateway CRUD (Backend)

**Files:**
- Modify: `backend/modules/user/_models.py`
- Modify: `backend/modules/user/_repository.py`
- Modify: `backend/modules/user/_handlers.py`
- Modify: `backend/modules/user/__init__.py`

- [ ] **Step 1: Add mcp_gateways to UserDocument**

In `backend/modules/user/_models.py`, the `UserDocument` class currently has no mcp_gateways field. The field is stored in MongoDB but not on the Pydantic model (it uses `model_config = {"populate_by_name": True}`). Since the repository works with raw dicts, we only need to ensure the repository methods handle the field. No model change needed — MongoDB is schemaless.

- [ ] **Step 2: Add repository methods**

In `backend/modules/user/_repository.py`, add these methods to the `UserRepository` class:

```python
    async def get_mcp_gateways(self, user_id: str) -> list[dict]:
        """Return the user's remote MCP gateway configurations."""
        doc = await self._users.find_one({"_id": user_id}, {"mcp_gateways": 1})
        if not doc:
            return []
        return doc.get("mcp_gateways", [])

    async def set_mcp_gateways(self, user_id: str, gateways: list[dict]) -> None:
        """Replace the user's MCP gateway configurations."""
        await self._users.update_one(
            {"_id": user_id},
            {"$set": {"mcp_gateways": gateways, "updated_at": datetime.now(timezone.utc)}},
        )

    async def add_mcp_gateway(self, user_id: str, gateway: dict) -> None:
        """Append a gateway to the user's MCP gateway list."""
        await self._users.update_one(
            {"_id": user_id},
            {
                "$push": {"mcp_gateways": gateway},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    async def update_mcp_gateway(self, user_id: str, gateway_id: str, updates: dict) -> bool:
        """Update a specific gateway by ID. Returns True if found and updated."""
        result = await self._users.update_one(
            {"_id": user_id, "mcp_gateways.id": gateway_id},
            {
                "$set": {
                    **{f"mcp_gateways.$.{k}": v for k, v in updates.items()},
                    "updated_at": datetime.now(timezone.utc),
                },
            },
        )
        return result.modified_count > 0

    async def delete_mcp_gateway(self, user_id: str, gateway_id: str) -> bool:
        """Remove a gateway by ID. Returns True if found and removed."""
        result = await self._users.update_one(
            {"_id": user_id},
            {
                "$pull": {"mcp_gateways": {"id": gateway_id}},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )
        return result.modified_count > 0
```

- [ ] **Step 3: Add REST endpoints**

In `backend/modules/user/_handlers.py`, add the MCP gateway endpoints. Add the import at the top:

```python
from shared.dtos.mcp import McpGatewayConfigDto
from backend.modules.tools._namespace import normalise_namespace, validate_namespace
```

Add endpoints after the existing user endpoints:

```python
# ── MCP Gateways ─────────────────────────────────────────────────────


class CreateMcpGatewayRequest(BaseModel):
    name: str
    url: str
    api_key: str | None = None
    enabled: bool = True


class UpdateMcpGatewayRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    disabled_tools: list[str] | None = None


@router.get("/api/user/mcp/gateways")
async def list_mcp_gateways(user: dict = Depends(require_active_session)):
    repo = _user_repo()
    gateways = await repo.get_mcp_gateways(user["sub"])
    return [McpGatewayConfigDto(**gw) for gw in gateways]


@router.post("/api/user/mcp/gateways", status_code=201)
async def create_mcp_gateway(
    body: CreateMcpGatewayRequest,
    user: dict = Depends(require_active_session),
):
    repo = _user_repo()
    existing = await repo.get_mcp_gateways(user["sub"])
    existing_namespaces = {normalise_namespace(gw["name"]) for gw in existing}

    err = validate_namespace(body.name, existing_namespaces)
    if err:
        raise HTTPException(status_code=422, detail=err)

    from uuid import uuid4
    gateway = {
        "id": str(uuid4()),
        "name": body.name,
        "url": body.url,
        "api_key": body.api_key,
        "enabled": body.enabled,
        "disabled_tools": [],
    }
    await repo.add_mcp_gateway(user["sub"], gateway)
    return McpGatewayConfigDto(**gateway)


@router.patch("/api/user/mcp/gateways/{gateway_id}")
async def update_mcp_gateway(
    gateway_id: str,
    body: UpdateMcpGatewayRequest,
    user: dict = Depends(require_active_session),
):
    repo = _user_repo()
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    if "name" in updates:
        existing = await repo.get_mcp_gateways(user["sub"])
        existing_namespaces = {
            normalise_namespace(gw["name"])
            for gw in existing
            if gw["id"] != gateway_id
        }
        err = validate_namespace(updates["name"], existing_namespaces)
        if err:
            raise HTTPException(status_code=422, detail=err)

    success = await repo.update_mcp_gateway(user["sub"], gateway_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="Gateway not found")

    gateways = await repo.get_mcp_gateways(user["sub"])
    gw = next((g for g in gateways if g["id"] == gateway_id), None)
    if not gw:
        raise HTTPException(status_code=404, detail="Gateway not found")
    return McpGatewayConfigDto(**gw)


@router.delete("/api/user/mcp/gateways/{gateway_id}", status_code=204)
async def delete_mcp_gateway(
    gateway_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _user_repo()
    success = await repo.delete_mcp_gateway(user["sub"], gateway_id)
    if not success:
        raise HTTPException(status_code=404, detail="Gateway not found")
```

- [ ] **Step 4: Expose in module public API**

In `backend/modules/user/__init__.py`, add a function to retrieve gateways for the orchestrator:

```python
async def get_user_mcp_gateways(user_id: str) -> list[dict]:
    """Return the user's remote MCP gateway configurations."""
    repo = UserRepository(get_db())
    return await repo.get_mcp_gateways(user_id)
```

Add `"get_user_mcp_gateways"` to `__all__`.

- [ ] **Step 5: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/user/_handlers.py && uv run python -m py_compile backend/modules/user/_repository.py && uv run python -m py_compile backend/modules/user/__init__.py`

Expected: No output (success).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/user/_repository.py backend/modules/user/_handlers.py backend/modules/user/__init__.py
git commit -m "Add user MCP gateway CRUD endpoints"
```

---

## Task 8: Admin MCP Gateway CRUD (Backend)

**Files:**
- Modify: `backend/modules/user/_handlers.py` (admin endpoints share the same router prefix)

- [ ] **Step 1: Add admin MCP endpoints**

These go in the same handlers file, using `require_admin` dependency. Check the existing admin endpoints pattern in the file and follow it. Add after the user MCP endpoints:

```python
# ── Admin MCP Gateways ───────────────────────────────────────────────


async def _get_admin_mcp_settings(db) -> dict:
    """Read the admin MCP settings document."""
    doc = await db["admin_settings"].find_one({"_id": "mcp"})
    return doc or {"_id": "mcp", "gateways": []}


async def _save_admin_mcp_settings(db, gateways: list[dict]) -> None:
    """Upsert the admin MCP settings document."""
    await db["admin_settings"].update_one(
        {"_id": "mcp"},
        {"$set": {"gateways": gateways}},
        upsert=True,
    )


@router.get("/api/admin/mcp/gateways")
async def list_admin_mcp_gateways(user: dict = Depends(require_admin)):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    return [McpGatewayConfigDto(**gw) for gw in settings.get("gateways", [])]


@router.post("/api/admin/mcp/gateways", status_code=201)
async def create_admin_mcp_gateway(
    body: CreateMcpGatewayRequest,
    user: dict = Depends(require_admin),
):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    existing = settings.get("gateways", [])
    existing_namespaces = {normalise_namespace(gw["name"]) for gw in existing}

    err = validate_namespace(body.name, existing_namespaces)
    if err:
        raise HTTPException(status_code=422, detail=err)

    from uuid import uuid4
    gateway = {
        "id": str(uuid4()),
        "name": body.name,
        "url": body.url,
        "api_key": body.api_key,
        "enabled": body.enabled,
        "disabled_tools": [],
    }
    existing.append(gateway)
    await _save_admin_mcp_settings(db, existing)
    return McpGatewayConfigDto(**gateway)


@router.patch("/api/admin/mcp/gateways/{gateway_id}")
async def update_admin_mcp_gateway(
    gateway_id: str,
    body: UpdateMcpGatewayRequest,
    user: dict = Depends(require_admin),
):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    gateways = settings.get("gateways", [])

    target = next((gw for gw in gateways if gw["id"] == gateway_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Gateway not found")

    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        existing_namespaces = {
            normalise_namespace(gw["name"])
            for gw in gateways
            if gw["id"] != gateway_id
        }
        err = validate_namespace(updates["name"], existing_namespaces)
        if err:
            raise HTTPException(status_code=422, detail=err)

    target.update(updates)
    await _save_admin_mcp_settings(db, gateways)
    return McpGatewayConfigDto(**target)


@router.delete("/api/admin/mcp/gateways/{gateway_id}", status_code=204)
async def delete_admin_mcp_gateway(
    gateway_id: str,
    user: dict = Depends(require_admin),
):
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    gateways = settings.get("gateways", [])
    original_len = len(gateways)
    gateways = [gw for gw in gateways if gw["id"] != gateway_id]
    if len(gateways) == original_len:
        raise HTTPException(status_code=404, detail="Gateway not found")
    await _save_admin_mcp_settings(db, gateways)
```

Also add a public function for the orchestrator to read admin gateways:

```python
async def get_admin_mcp_gateways() -> list[dict]:
    """Return admin-configured MCP gateways. Used by the chat orchestrator."""
    db = get_db()
    settings = await _get_admin_mcp_settings(db)
    return settings.get("gateways", [])
```

Expose `get_admin_mcp_gateways` in the module `__init__.py` and `__all__`.

- [ ] **Step 2: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/user/_handlers.py`

Expected: No output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/__init__.py
git commit -m "Add admin MCP gateway CRUD endpoints"
```

---

## Task 9: WebSocket Router — Handle mcp.tools.register

**Files:**
- Modify: `backend/ws/router.py`

- [ ] **Step 1: Add mcp.tools.register handler**

Add imports at the top of `router.py`:

```python
from shared.dtos.mcp import McpToolRegistrationPayload
from backend.modules.tools import get_mcp_registry
from backend.modules.tools._mcp_discovery import register_local_tools
from backend.modules.tools._namespace import normalise_namespace
```

In the message dispatch `while True` loop (around line 187, after the `chat.client_tool.result` handler), add:

```python
        elif msg_type == "mcp.tools.register":
            try:
                payload = McpToolRegistrationPayload.model_validate(data.get("payload", data))
            except ValidationError as e:
                _log.warning(
                    "malformed mcp.tools.register from user=%s connection=%s: %s",
                    user_id, connection_id, e,
                )
            else:
                registry = get_mcp_registry(connection_id)
                if registry is not None:
                    namespace = normalise_namespace(payload.name)
                    try:
                        register_local_tools(
                            registry=registry,
                            gateway_id=payload.gateway_id,
                            namespace=namespace,
                            url="",  # local gateways: URL not needed server-side
                            tools=payload.tools,
                        )
                        _log.info(
                            "Registered %d local MCP tools from gateway '%s' for user=%s",
                            len(payload.tools), namespace, user_id,
                        )
                    except ValueError as exc:
                        _log.warning("MCP registration failed: %s", exc)
```

- [ ] **Step 2: Clean up registry on disconnect**

In the disconnect/cleanup section of the router (where `cancel_for_user` is called), add:

```python
from backend.modules.tools import remove_mcp_registry

# In the disconnect handler:
remove_mcp_registry(connection_id)
```

- [ ] **Step 3: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/ws/router.py`

Expected: No output.

- [ ] **Step 4: Commit**

```bash
git add backend/ws/router.py
git commit -m "Handle mcp.tools.register in WebSocket router"
```

---

## Task 10: Orchestrator Integration — Trigger MCP Discovery

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Import MCP modules**

Add at the top of `_orchestrator.py`:

```python
from backend.modules.tools import set_mcp_registry, get_mcp_registry
from backend.modules.tools._mcp_discovery import discover_backend_gateways
from backend.modules.user import get_user_mcp_gateways, get_admin_mcp_gateways
from shared.dtos.mcp import McpGatewayConfigDto
```

- [ ] **Step 2: Add MCP discovery to run_inference**

In `run_inference()`, after the existing tool resolution (around line 471-473), replace:

```python
    # Resolve active tool definitions based on session toggle state
    disabled_tool_groups = session.get("disabled_tool_groups", [])
    active_tools = get_active_definitions(disabled_tool_groups) or None
```

With:

```python
    # Resolve active tool definitions based on session toggle state
    disabled_tool_groups = session.get("disabled_tool_groups", [])

    # MCP discovery: build or retrieve per-connection registry
    mcp_registry = get_mcp_registry(connection_id) if connection_id else None
    if mcp_registry is None and connection_id and "mcp" not in set(disabled_tool_groups):
        # First inference on this connection: discover backend MCP gateways
        admin_gw_raw = await get_admin_mcp_gateways()
        user_gw_raw = await get_user_mcp_gateways(user_id)
        admin_gateways = [McpGatewayConfigDto(**gw) for gw in admin_gw_raw]
        user_gateways = [McpGatewayConfigDto(**gw) for gw in user_gw_raw]

        mcp_registry = await discover_backend_gateways(
            admin_gateways=admin_gateways,
            user_remote_gateways=user_gateways,
            session_id=session_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )
        set_mcp_registry(connection_id, mcp_registry)

    active_tools = get_active_definitions(disabled_tool_groups, mcp_registry=mcp_registry) or None
```

- [ ] **Step 3: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/chat/_orchestrator.py`

Expected: No output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Trigger MCP gateway discovery on first inference per connection"
```

---

## Task 11: Frontend — TypeScript Types and MCP JSON-RPC Client

**Files:**
- Create: `frontend/src/features/mcp/types.ts`
- Create: `frontend/src/features/mcp/mcpClient.ts`

- [ ] **Step 1: Create TypeScript types**

```typescript
// frontend/src/features/mcp/types.ts

export interface McpGatewayConfig {
  id: string
  name: string
  url: string
  api_key: string | null
  enabled: boolean
  disabled_tools: string[]
}

export interface McpToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

export interface McpGatewayStatus {
  id: string
  name: string
  tier: 'admin' | 'remote' | 'local'
  tool_count: number
  reachable: boolean
}

export interface McpToolsListResponse {
  tools: McpToolDefinition[]
  _errors?: Array<{ server: string; error: string }>
}

export interface McpToolCallResult {
  content: Array<{ type: string; text?: string }>
  isError?: boolean
}
```

- [ ] **Step 2: Create MCP JSON-RPC client**

```typescript
// frontend/src/features/mcp/mcpClient.ts
/**
 * MCP JSON-RPC client — used by the Tool Explorer for direct gateway calls
 * and by the clientToolHandler for local gateway tool execution.
 */

import type { McpToolDefinition, McpToolCallResult } from './types'

let requestId = 0

function nextId(): number {
  return ++requestId
}

export async function mcpToolsList(
  gatewayUrl: string,
  apiKey: string | null,
  timeoutMs: number = 10_000,
): Promise<{ tools: McpToolDefinition[]; errors: Array<{ server: string; error: string }> }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', id: nextId(), method: 'tools/list' }),
      signal: controller.signal,
    })
    const body = await resp.json()
    if (body.error) {
      throw new Error(body.error.message || JSON.stringify(body.error))
    }
    const result = body.result || {}
    return {
      tools: result.tools || [],
      errors: result._errors || [],
    }
  } finally {
    clearTimeout(timer)
  }
}

export async function mcpToolsCall(
  gatewayUrl: string,
  apiKey: string | null,
  toolName: string,
  args: Record<string, unknown>,
  timeoutMs: number = 30_000,
): Promise<{ stdout: string; error: string | null }> {
  const url = gatewayUrl.replace(/\/+$/, '') + '/mcp'
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['Authorization'] = `Bearer ${apiKey}`

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: nextId(),
        method: 'tools/call',
        params: { name: toolName, arguments: args },
      }),
      signal: controller.signal,
    })
    const body = await resp.json()

    if (body.error) {
      return { stdout: '', error: `MCP error: ${body.error.message || JSON.stringify(body.error)}` }
    }

    const result: McpToolCallResult = body.result || {}
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
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      return { stdout: '', error: `MCP gateway timed out after ${timeoutMs}ms` }
    }
    return { stdout: '', error: `MCP gateway unreachable: ${e instanceof Error ? e.message : String(e)}` }
  } finally {
    clearTimeout(timer)
  }
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/mcp/types.ts frontend/src/features/mcp/mcpClient.ts
git commit -m "Add frontend MCP types and JSON-RPC client"
```

---

## Task 12: Frontend — MCP Store and REST API Client

**Files:**
- Create: `frontend/src/features/mcp/mcpStore.ts`
- Create: `frontend/src/features/mcp/mcpApi.ts`

- [ ] **Step 1: Create REST API client**

```typescript
// frontend/src/features/mcp/mcpApi.ts

import { api } from '../../core/api/client'
import type { McpGatewayConfig } from './types'

export const mcpApi = {
  // User remote gateways
  listGateways: () => api.get<McpGatewayConfig[]>('/api/user/mcp/gateways'),
  createGateway: (data: { name: string; url: string; api_key?: string | null; enabled?: boolean }) =>
    api.post<McpGatewayConfig>('/api/user/mcp/gateways', data),
  updateGateway: (id: string, data: Partial<McpGatewayConfig>) =>
    api.patch<McpGatewayConfig>(`/api/user/mcp/gateways/${id}`, data),
  deleteGateway: (id: string) => api.delete(`/api/user/mcp/gateways/${id}`),

  // Admin gateways
  listAdminGateways: () => api.get<McpGatewayConfig[]>('/api/admin/mcp/gateways'),
  createAdminGateway: (data: { name: string; url: string; api_key?: string | null; enabled?: boolean }) =>
    api.post<McpGatewayConfig>('/api/admin/mcp/gateways', data),
  updateAdminGateway: (id: string, data: Partial<McpGatewayConfig>) =>
    api.patch<McpGatewayConfig>(`/api/admin/mcp/gateways/${id}`, data),
  deleteAdminGateway: (id: string) => api.delete(`/api/admin/mcp/gateways/${id}`),
}
```

- [ ] **Step 2: Create Zustand store**

```typescript
// frontend/src/features/mcp/mcpStore.ts

import { create } from 'zustand'
import type { McpGatewayConfig, McpToolDefinition } from './types'

const LOCAL_STORAGE_KEY = 'chatsune:mcp_local_gateways'

interface McpState {
  /** User's local gateways (localStorage, this device only) */
  localGateways: McpGatewayConfig[]
  /** All discovered MCP tools for current session (set after discovery) */
  sessionTools: Array<{ namespace: string; tier: string; tools: McpToolDefinition[] }>

  loadLocalGateways: () => void
  addLocalGateway: (gw: McpGatewayConfig) => void
  updateLocalGateway: (id: string, updates: Partial<McpGatewayConfig>) => void
  deleteLocalGateway: (id: string) => void
  setSessionTools: (tools: McpState['sessionTools']) => void
  clearSessionTools: () => void
}

function readLocalGateways(): McpGatewayConfig[] {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function writeLocalGateways(gateways: McpGatewayConfig[]): void {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(gateways))
}

export const useMcpStore = create<McpState>((set, get) => ({
  localGateways: [],
  sessionTools: [],

  loadLocalGateways: () => {
    set({ localGateways: readLocalGateways() })
  },

  addLocalGateway: (gw) => {
    const updated = [...get().localGateways, gw]
    writeLocalGateways(updated)
    set({ localGateways: updated })
  },

  updateLocalGateway: (id, updates) => {
    const updated = get().localGateways.map((gw) =>
      gw.id === id ? { ...gw, ...updates } : gw,
    )
    writeLocalGateways(updated)
    set({ localGateways: updated })
  },

  deleteLocalGateway: (id) => {
    const updated = get().localGateways.filter((gw) => gw.id !== id)
    writeLocalGateways(updated)
    set({ localGateways: updated })
  },

  setSessionTools: (tools) => set({ sessionTools: tools }),
  clearSessionTools: () => set({ sessionTools: [] }),
}))
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/mcp/mcpStore.ts frontend/src/features/mcp/mcpApi.ts
git commit -m "Add MCP Zustand store and REST API client"
```

---

## Task 13: Frontend — Extend clientToolHandler for MCP

**Files:**
- Modify: `frontend/src/features/code-execution/clientToolHandler.ts`

- [ ] **Step 1: Add MCP tool routing**

Replace the `handleDispatch` function in `clientToolHandler.ts`:

```typescript
import { mcpToolsCall } from '../mcp/mcpClient'
import { useMcpStore } from '../mcp/mcpStore'

async function handleDispatch(ev: DispatchPayload): Promise<void> {
  // Check if this is an MCP tool (contains __ separator)
  if (ev.tool_name.includes('__')) {
    await handleMcpDispatch(ev)
    return
  }

  if (ev.tool_name !== 'calculate_js') {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Unknown client tool: ${ev.tool_name}`,
    })
    return
  }

  const code = typeof ev.arguments?.code === 'string' ? ev.arguments.code : ''
  if (!code) {
    sendResult(ev.tool_call_id, { stdout: '', error: 'No code provided' })
    return
  }

  try {
    const result = await runSandbox(code, ev.timeout_ms, MAX_OUTPUT_BYTES)
    sendResult(ev.tool_call_id, result)
  } catch (e) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Sandbox host crashed: ${e instanceof Error ? e.message : String(e)}`,
    })
  }
}

async function handleMcpDispatch(ev: DispatchPayload): Promise<void> {
  const separatorIdx = ev.tool_name.indexOf('__')
  const namespace = ev.tool_name.substring(0, separatorIdx)
  const originalToolName = ev.tool_name.substring(separatorIdx + 2)

  // Find the local gateway for this namespace
  const localGateways = useMcpStore.getState().localGateways
  const gateway = localGateways.find(
    (gw) => gw.name.toLowerCase().replace(/[^a-z0-9]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '') === namespace,
  )

  if (!gateway) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `No local MCP gateway found for namespace '${namespace}'`,
    })
    return
  }

  try {
    const result = await mcpToolsCall(
      gateway.url,
      gateway.api_key,
      originalToolName,
      ev.arguments as Record<string, unknown>,
      ev.timeout_ms,
    )
    sendResult(ev.tool_call_id, result)
  } catch (e) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `MCP call failed: ${e instanceof Error ? e.message : String(e)}`,
    })
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/code-execution/clientToolHandler.ts
git commit -m "Extend clientToolHandler to route MCP tools to local gateways"
```

---

## Task 14: Frontend — MCP Settings Tab (User Modal)

**Files:**
- Create: `frontend/src/app/components/user-modal/McpTab.tsx`
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`

- [ ] **Step 1: Create McpTab component**

This is a large UI component. Create `frontend/src/app/components/user-modal/McpTab.tsx` with:

- Three sections: Remote Gateways, Local Gateways, Global Gateways (admin, read-only)
- Gateway cards showing: status dot, name, URL, tool count, Explore/Edit buttons
- Disabled gateways shown faded
- "Add Gateway" buttons per section (not for global)
- When "Explore" is clicked, switches to ToolExplorer view (pass gateway config as props)
- When "Edit" is clicked, opens GatewayEditDialog inline

The component should follow the existing Catppuccin admin style used in other tabs (SettingsTab, ApiKeysTab). Match the existing patterns — use the same colour values, font sizes, spacing, and component structure.

Full implementation code is required — the engineer implementing this task should read the existing `SettingsTab.tsx` and `ApiKeysTab.tsx` (or similar tabs) for style reference, then build McpTab following the mockups from the design spec. The three sections are:

1. **Remote Gateways** (user-owned, green accent `rgba(166,218,149,*)`)
2. **Local Gateways** (device-specific, orange accent `rgba(245,194,131,*)`)
3. **Global Gateways** (admin, purple accent `rgba(140,118,215,*)`, read-only)

Each gateway card renders: status dot (coloured by tier), name, monospace URL, tool count badge, action buttons.

State management: remote gateways via `mcpApi`, local gateways via `useMcpStore`, admin gateways via `mcpApi.listAdminGateways()`.

- [ ] **Step 2: Add MCP tab to UserModal**

In `frontend/src/app/components/user-modal/UserModal.tsx`:

Add `'mcp'` to the `UserModalTab` type union (after `'api-keys'`):

```typescript
export type UserModalTab =
  | 'about-me'
  // ... existing tabs ...
  | 'api-keys'
  | 'mcp'
```

Add to the `TABS` array (after the api-keys entry):

```typescript
  { id: 'mcp', label: 'MCP' },
```

Add the import and render case in the tab content switch:

```typescript
import { McpTab } from './McpTab'

// In the render:
case 'mcp':
  return <McpTab />
```

- [ ] **Step 3: Verify TypeScript compiles and frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit && pnpm run build`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/McpTab.tsx frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Add MCP settings tab to user modal"
```

---

## Task 15: Frontend — Gateway Edit Dialog

**Files:**
- Create: `frontend/src/features/mcp/GatewayEditDialog.tsx`

- [ ] **Step 1: Create GatewayEditDialog component**

Inline dialog (not a modal) with fields:
- **Name** — text input, with helper text showing namespace preview ("Tools will appear as name__tool_name")
- **URL** — text input
- **API Key** — password input, optional, with placeholder "No authentication"
- **Enabled** — toggle switch
- **Delete** button (red, with confirmation) — only for edit mode, not create
- **Cancel** / **Save** buttons

Props: `mode: 'create' | 'edit'`, `gateway?: McpGatewayConfig`, `tier: 'remote' | 'local'`, `onSave`, `onDelete`, `onCancel`.

For `tier='remote'`: onSave calls `mcpApi.createGateway()` or `mcpApi.updateGateway()`.
For `tier='local'`: onSave calls `useMcpStore.getState().addLocalGateway()` or `updateLocalGateway()`.

Validation: name must not be empty, URL must start with `http://` or `https://`.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/mcp/GatewayEditDialog.tsx
git commit -m "Add gateway edit dialog component"
```

---

## Task 16: Frontend — Tool Explorer

**Files:**
- Create: `frontend/src/features/mcp/ToolExplorer.tsx`

- [ ] **Step 1: Create ToolExplorer component**

Split-layout component (replaces McpTab content when active):

**Left panel (220px):**
- Back button (returns to gateway list)
- Gateway info header (name, URL, status dot)
- Refresh button
- Search input (case-insensitive token search, space = AND)
- Scrollable tool list: each item shows tool name (monospace) + truncated description
- Disabled tools shown faded with "off" badge
- Selected tool highlighted with blue background

**Right panel:**
- Tool name (large, monospace) + namespaced name below (small, muted)
- Description (full text)
- Enable/disable toggle per tool
- **Parameters section:** rendered from JSON Schema `inputSchema`
  - Each parameter: name (monospace, blue), type badge, required badge (orange), description
  - Input field per parameter (text input, respecting type for placeholder)
- **Execute button:** calls `mcpToolsCall()` directly with entered parameters
- **Response area:** pre-formatted JSON output, green text on dark background

Props: `gateway: McpGatewayConfig`, `tier: 'admin' | 'remote' | 'local'`, `onBack: () => void`, `onToggleTool: (toolName: string, disabled: boolean) => void`.

Discovery: on mount, calls `mcpToolsList(gateway.url, gateway.api_key)` to load tools.

Execute: calls `mcpToolsCall()` directly from browser to gateway URL (not through backend).

- [ ] **Step 2: Verify TypeScript compiles and frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit && pnpm run build`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/mcp/ToolExplorer.tsx
git commit -m "Add MCP Tool Explorer with parameter testing UI"
```

---

## Task 17: Frontend — MCP Toggle in Chat ToolToggles

**Files:**
- Modify: `frontend/src/features/chat/ToolToggles.tsx`

- [ ] **Step 1: Add MCP toggle**

In `ToolToggles.tsx`, after the existing tool group buttons (line 99, before `</div>`), add the MCP toggle. The MCP toggle should:

- Only render if the user has at least one enabled MCP gateway (check `useMcpStore` for local + fetch remote count)
- Use green accent colour (`rgba(166,218,149,*)`) instead of blue
- Show active MCP tool count next to label
- Be separated from built-in toggles with a vertical divider
- Toggle `mcp` in `disabledToolGroups` (same mechanism as other toggles)

Add before the closing `</div>` of the flex container, after the existing group buttons and before the reasoning toggle:

```typescript
{/* MCP toggle — only if gateways configured */}
{hasMcpGateways && (
  <>
    <div className="mx-0.5 h-3.5 w-px" style={{ backgroundColor: 'rgba(255,255,255,0.08)' }} />
    <button
      type="button"
      onClick={() => handleToggle('mcp')}
      disabled={disabled || !modelSupportsTools}
      className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        color: mcpEnabled ? 'rgba(166,218,149,0.9)' : 'rgba(255,255,255,0.2)',
        fontFamily: "'Courier New', monospace",
      }}
      title="MCP tools from connected gateways"
    >
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: mcpEnabled ? 'rgba(166,218,149,0.9)' : 'rgba(255,255,255,0.15)' }}
      />
      MCP
      {mcpEnabled && mcpToolCount > 0 && (
        <span style={{ color: 'rgba(166,218,149,0.5)', fontSize: '9px', marginLeft: '2px' }}>
          {mcpToolCount}
        </span>
      )}
    </button>
  </>
)}
```

Where `hasMcpGateways` and `mcpToolCount` are derived from the MCP store state, and `mcpEnabled` checks that `'mcp'` is not in `disabledToolGroups`.

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/ToolToggles.tsx
git commit -m "Add MCP toggle to chat tool bar"
```

---

## Task 18: Frontend — Tool Popover in Chat Top Bar

**Files:**
- Create: `frontend/src/features/chat/ToolPopover.tsx`
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Create ToolPopover component**

Floating popover that opens on click of the wrench icon:

- **Search field** at top (case-insensitive token search, AND logic)
- **Built-in tools** grouped by category (blue headers: Web Search, Knowledge, Artefacts, Code Execution, Journal)
- **Separator line** between built-in and MCP
- **MCP tools** grouped by gateway namespace (green headers), each with tier badge (local/remote/global)
- **Footer:** "N tools active — configure in Settings > MCP"
- Read-only — no editing
- Closes on click outside or Escape

Props: `disabledToolGroups: string[]`, `mcpSessionTools: McpState['sessionTools']`.

The component fetches built-in tool groups from `chatApi.listToolGroups()` and renders them alongside MCP tools from the store.

- [ ] **Step 2: Add wrench icon to ChatView top bar**

In `ChatView.tsx`, in the top bar section (around line 545-570), add a wrench icon with badge next to the mortarboard. The badge shows total active tool count. Click toggles the ToolPopover.

Add state: `const [toolPopoverOpen, setToolPopoverOpen] = useState(false)`

Add the icon + popover next to the existing knowledge dropdown button:

```typescript
<div className="relative">
  <button
    type="button"
    onClick={() => setToolPopoverOpen((v) => !v)}
    className="relative rounded px-1.5 py-0.5 text-sm transition-colors hover:bg-white/5"
    title="Active tools"
  >
    🔧
    {totalToolCount > 0 && (
      <span className="absolute -right-1.5 -top-1 rounded-full px-1 text-[8px] font-bold"
        style={{ backgroundColor: 'rgba(166,218,149,0.8)', color: '#0f0d16' }}>
        {totalToolCount}
      </span>
    )}
  </button>
  {toolPopoverOpen && (
    <ToolPopover
      disabledToolGroups={disabledToolGroups}
      mcpSessionTools={useMcpStore.getState().sessionTools}
      onClose={() => setToolPopoverOpen(false)}
    />
  )}
</div>
```

- [ ] **Step 3: Verify TypeScript compiles and frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit && pnpm run build`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/ToolPopover.tsx frontend/src/features/chat/ChatView.tsx
git commit -m "Add tool overview popover to chat top bar"
```

---

## Task 19: Frontend — Toast for MCP Gateway Errors

**Files:**
- Modify: `frontend/src/core/websocket/eventBus.ts` or the event handling registration in `App.tsx`

- [ ] **Step 1: Register event handler for mcp.gateway.error**

In the appropriate event registration location (where other event handlers are registered at app startup), add a listener:

```typescript
eventBus.on('mcp.gateway.error', (event: BaseEvent) => {
  const payload = event.payload as {
    gateway_name: string
    error: string
    recoverable: boolean
  }
  const variant = payload.recoverable ? 'warning' : 'error'
  // Use the existing toast/notification system
  showToast({
    variant,
    title: `MCP Gateway: ${payload.gateway_name}`,
    message: payload.error,
  })
})
```

Adapt `showToast` to whatever toast system the project uses (check existing toast/notification patterns in the codebase).

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/
git commit -m "Add toast notifications for MCP gateway errors"
```

---

## Task 20: Integration Verification

- [ ] **Step 1: Full backend syntax check**

Run: `cd /home/chris/workspace/chatsune && find backend -name '*.py' | head -50 | xargs -I{} uv run python -m py_compile {}`

Expected: All files compile.

- [ ] **Step 2: Full frontend build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`

Expected: Clean build, no errors.

- [ ] **Step 3: Run all tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/ -v --timeout=60`

Expected: All tests pass, including new MCP tests.

- [ ] **Step 4: Docker build verification**

Run: `cd /home/chris/workspace/chatsune && docker compose build`

Expected: Builds successfully. Check that `httpx` is in `backend/pyproject.toml` if it wasn't already.

- [ ] **Step 5: Final commit and merge to master**

```bash
git add -A
git status  # review what's staged
git commit -m "Complete MCP gateway integration: three-tier gateways, tool explorer, chat UI"
```

Then merge the feature branch to master as per project conventions.
