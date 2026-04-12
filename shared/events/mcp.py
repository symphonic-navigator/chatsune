"""MCP gateway events."""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.mcp import McpGatewayStatusDto


class McpGatewayToolEntry(BaseModel):
    """One gateway with its discovered tool definitions — sent to the frontend."""

    namespace: str
    tier: str
    tools: list[dict]  # [{name, description, server_name}] — lightweight, no full JSON schema
    collisions: list[str] = []  # namespaced names that had duplicates


class McpToolsRegisteredEvent(BaseModel):
    type: str = "mcp.tools.registered"
    session_id: str
    gateways: list[McpGatewayToolEntry]
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
