# backend/modules/tools/_mcp_discovery.py
"""MCP gateway discovery — called once at session start to build the SessionMcpRegistry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from backend.modules.tools._mcp_executor import McpExecutor
from backend.modules.tools._mcp_registry import GatewayHandle, SessionMcpRegistry
from backend.modules.tools._namespace import normalise_namespace
from backend.ws.event_bus import get_event_bus
from shared.dtos.inference import ToolDefinition
from shared.dtos.mcp import McpGatewayConfigDto, McpGatewayStatusDto, McpToolDefinitionDto
from shared.events.mcp import McpGatewayErrorEvent
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
    reachable = isinstance(raw_tools, list) and len(raw_tools) > 0

    tool_defs = _raw_tools_to_definitions(namespace, raw_tools, config.disabled_tools)

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
