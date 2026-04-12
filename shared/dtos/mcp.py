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
