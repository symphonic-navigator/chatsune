from typing import Literal

from pydantic import BaseModel


class ToolGroupDto(BaseModel):
    id: str
    display_name: str
    description: str
    side: Literal["server", "client"]
    toggleable: bool


class ClientToolResultPayloadDto(BaseModel):
    """The shape of the `result` field in a chat.client_tool.result WS message."""
    stdout: str
    error: str | None


class ClientToolResultDto(BaseModel):
    """Validates inbound chat.client_tool.result WebSocket messages."""
    tool_call_id: str
    result: ClientToolResultPayloadDto
