# backend/modules/tools/_mcp_discovery.py
"""MCP gateway discovery — called once at session start to build the SessionMcpRegistry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from backend.modules.tools._mcp_executor import McpExecutor
from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from backend.modules.tools._namespace import normalise_namespace, normalise_prefix
from backend.ws.event_bus import get_event_bus
from shared.dtos.inference import ToolDefinition
from shared.dtos.mcp import (
    McpGatewayConfigDto,
    McpGatewayStatusDto,
    McpServerConfig,
    McpToolDefinitionDto,
    McpToolOverride,
)
from shared.events.mcp import McpGatewayErrorEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)
_executor = McpExecutor()


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
        if isinstance(result, BaseException):
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
            continue

        if handle:
            try:
                registry.register(handle)
            except ValueError as exc:
                _log.warning("MCP registry conflict: %s", exc)

    return registry


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
    raw_tools = [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.parameters,
            "_gateway_server": t.server_name,
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
