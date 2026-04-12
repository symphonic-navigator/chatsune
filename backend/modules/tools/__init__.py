"""Tools module — pluggable tool registry with group-based toggling.

Public API: import only from this file.
"""

import json
import logging
import time as _time
from datetime import datetime, timezone

from backend.modules.metrics import tool_calls_total, tool_call_duration_seconds

from backend.modules.tools._client_dispatcher import ClientToolDispatcher
from backend.modules.tools._mcp_executor import McpExecutor
from backend.modules.tools._mcp_registry import SessionMcpRegistry
from backend.modules.tools._registry import ToolGroup, get_groups
from shared.dtos.inference import ToolDefinition
from shared.dtos.tools import ToolGroupDto

_log = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 5

# Client-tool timeouts: the server-side wait budget is intentionally ~5s
# larger than the client-side Worker budget to absorb network and
# scheduler jitter. See docs/superpowers/specs/2026-04-11-calculate-js-
# client-tool-design.md §4.
_CLIENT_TOOL_SERVER_TIMEOUT_MS = 10_000
_CLIENT_TOOL_CLIENT_TIMEOUT_MS = 5_000

_MCP_SERVER_TIMEOUT_MS = 35_000
_MCP_CLIENT_TIMEOUT_MS = 30_000

_dispatcher_singleton = ClientToolDispatcher()
_mcp_executor = McpExecutor()


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


def invalidate_mcp_registries(connection_ids: list[str] | None = None) -> int:
    """Clear cached MCP registries so the next inference re-discovers tools.

    If *connection_ids* is ``None``, ALL registries are cleared (admin gateway
    change). Otherwise only the listed connections are invalidated (user
    gateway change).  Returns the number of registries removed.
    """
    if connection_ids is None:
        count = len(_mcp_registries)
        _mcp_registries.clear()
        return count
    count = 0
    for cid in connection_ids:
        if _mcp_registries.pop(cid, None) is not None:
            count += 1
    return count


def get_client_dispatcher() -> ClientToolDispatcher:
    """Return the singleton client-tool dispatcher (for WS router and disconnect hooks)."""
    return _dispatcher_singleton


class ToolNotFoundError(Exception):
    """No registered executor can handle this tool name."""


def get_all_groups() -> list[ToolGroupDto]:
    """Return DTOs for all registered tool groups (for the frontend)."""
    return [
        ToolGroupDto(
            id=g.id,
            display_name=g.display_name,
            description=g.description,
            side=g.side,
            toggleable=g.toggleable,
        )
        for g in get_groups().values()
    ]


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


async def execute_tool(
    user_id: str,
    tool_name: str,
    arguments_json: str,
    *,
    tool_call_id: str,
    session_id: str,
    originating_connection_id: str,
    model: str = "",
) -> str:
    """Dispatch a tool call to the appropriate executor.

    For server-side tools (``side == "server"``) the registered executor is
    invoked directly. For client-side tools (``side == "client"``) the call
    is forwarded to the originating browser connection via the
    ``ClientToolDispatcher`` and this coroutine awaits the result.

    Always returns a string (JSON-encoded result or error). Raises
    ``ToolNotFoundError`` only if the tool name is unknown.
    """
    arguments = json.loads(arguments_json)
    t_start = _time.monotonic()

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

    for group in get_groups().values():
        if tool_name not in group.tool_names:
            continue

        try:
            if group.side == "client":
                return await _dispatcher_singleton.dispatch(
                    user_id=user_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    server_timeout_ms=_CLIENT_TOOL_SERVER_TIMEOUT_MS,
                    client_timeout_ms=_CLIENT_TOOL_CLIENT_TIMEOUT_MS,
                    target_connection_id=originating_connection_id,
                )

            if group.executor is not None:
                return await group.executor.execute(user_id, tool_name, arguments)
        finally:
            duration = _time.monotonic() - t_start
            tool_calls_total.labels(model=model, tool_name=tool_name).inc()
            tool_call_duration_seconds.labels(model=model, tool_name=tool_name).observe(duration)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")


def get_max_tool_iterations() -> int:
    """Return the maximum number of tool loop iterations."""
    return _MAX_TOOL_ITERATIONS


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
