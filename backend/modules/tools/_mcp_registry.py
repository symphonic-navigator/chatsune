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
    server_tools: dict[str, list[ToolDefinition]] = field(default_factory=dict)
    collisions: list[str] = field(default_factory=list)


class SessionMcpRegistry:
    """Holds MCP tool state for one WebSocket connection.

    Created at session start, destroyed on disconnect.
    """

    def __init__(self) -> None:
        self._gateways: dict[str, GatewayHandle] = {}  # namespace -> handle
        self._tool_index: dict[str, str] = {}  # namespaced_name -> namespace
        self._tool_server_index: dict[str, str] = {}  # namespaced_name -> server_name
        self.backend_discovered: bool = False

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

    def server_name_for_tool(self, tool_name: str) -> str | None:
        """Return the MCP server name for a namespaced tool, or None."""
        return self._tool_server_index.get(tool_name)

    def gateway_for_id(self, gateway_id: str) -> GatewayHandle | None:
        """Look up a gateway by its config ID."""
        for gw in self._gateways.values():
            if gw.id == gateway_id:
                return gw
        return None

    @property
    def gateways(self) -> dict[str, GatewayHandle]:
        return self._gateways
