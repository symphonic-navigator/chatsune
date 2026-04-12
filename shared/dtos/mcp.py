"""MCP gateway DTOs — shared between backend and frontend contracts."""

from typing import Literal

from pydantic import BaseModel


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
    server_name: str = "_unknown"


class McpToolRegistrationPayload(BaseModel):
    """Frontend -> Backend via WebSocket: registering local gateway tools."""

    gateway_id: str
    name: str
    tier: Literal["local"] = "local"
    tools: list[McpToolDefinitionDto]


class PersonaMcpConfig(BaseModel):
    """Persona-level MCP tool exclusions. Default: everything enabled."""

    excluded_gateways: list[str] = []
    excluded_servers: list[str] = []
    excluded_tools: list[str] = []
