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
            if gw.name in excluded_gw_ids:
                continue
            for td in gw.tool_definitions:
                if td.name in excluded_tools:
                    continue
                server = mcp_registry.server_name_for_tool(td.name)
                if server and f"{gw.name}:{server}" in excluded_servers:
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
        if not registry:
            _log.warning(
                "MCP tool '%s' requested but no registry for connection=%s (known: %s)",
                tool_name, originating_connection_id[:8] if originating_connection_id else "none",
                list(_mcp_registries.keys())[:5],
            )
        elif not registry.is_mcp_tool(tool_name):
            _log.warning(
                "MCP tool '%s' not in registry for connection=%s (registered: %s)",
                tool_name, originating_connection_id[:8],
                [td.name for td in registry.all_definitions()][:10],
            )
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

    # Integration tool routing: frontend-executed tools from the integrations module
    from backend.modules.integrations import get_all_integrations
    for defn in get_all_integrations().values():
        if any(td.name == tool_name for td in defn.tool_definitions):
            try:
                if defn.tool_side == "client":
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
                # Backend-side integration tools would go here in the future
            finally:
                duration = _time.monotonic() - t_start
                tool_calls_total.labels(model=model, tool_name=tool_name).inc()
                tool_call_duration_seconds.labels(model=model, tool_name=tool_name).observe(duration)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")


async def eager_discover_mcp(
    connection_id: str,
    user_id: str,
) -> None:
    """Eagerly discover MCP tools for a connection (called on WebSocket connect).

    Populates the per-connection registry so tools are available before the
    first chat message. Emits McpToolsRegisteredEvent to the frontend.
    """
    from backend.modules.user import get_user_mcp_gateways, get_admin_mcp_gateways
    from backend.modules.tools._mcp_discovery import discover_backend_gateways
    from shared.dtos.mcp import McpGatewayConfigDto
    from shared.events.mcp import McpGatewayToolEntry, McpToolsRegisteredEvent
    from shared.topics import Topics
    from backend.ws.event_bus import get_event_bus

    # Skip if already discovered (e.g. rapid reconnect)
    existing = get_mcp_registry(connection_id)
    if existing and existing.backend_discovered:
        return

    admin_gw_raw = await get_admin_mcp_gateways()
    user_gw_raw = await get_user_mcp_gateways(user_id)
    admin_gateways = [McpGatewayConfigDto(**gw) for gw in admin_gw_raw]
    user_gateways = [McpGatewayConfigDto(**gw) for gw in user_gw_raw]

    if not any(gw.enabled for gw in admin_gateways) and not any(gw.enabled for gw in user_gateways):
        return  # no gateways configured — nothing to discover

    correlation_id = f"mcp-eager-{connection_id[:8]}"

    backend_registry = await discover_backend_gateways(
        admin_gateways=admin_gateways,
        user_remote_gateways=user_gateways,
        session_id="",  # no session yet — discovery is connection-scoped
        user_id=user_id,
        correlation_id=correlation_id,
    )

    # Merge into existing registry (may already contain local tools)
    mcp_registry = get_mcp_registry(connection_id)
    if mcp_registry is None:
        mcp_registry = backend_registry
    else:
        for gw in backend_registry.gateways.values():
            try:
                mcp_registry.register(gw)
            except ValueError:
                pass  # namespace conflict with existing local gateway
    mcp_registry.backend_discovered = True
    set_mcp_registry(connection_id, mcp_registry)

    # Notify frontend about discovered tools
    if mcp_registry.gateways:
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
        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.MCP_TOOLS_REGISTERED,
            McpToolsRegisteredEvent(
                session_id="",
                gateways=gateway_entries,
                total_tools=len(mcp_registry.all_definitions()),
                correlation_id=correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"user:{user_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    _log.info(
        "Eager MCP discovery for connection=%s user=%s: %d gateways, %d tools",
        connection_id[:8], user_id,
        len(mcp_registry.gateways), len(mcp_registry.all_definitions()),
    )


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
    "eager_discover_mcp",
    "ToolNotFoundError",
]
