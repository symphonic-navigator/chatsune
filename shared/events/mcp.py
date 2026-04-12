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
