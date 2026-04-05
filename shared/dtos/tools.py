from typing import Literal

from pydantic import BaseModel


class ToolGroupDto(BaseModel):
    id: str
    display_name: str
    description: str
    side: Literal["server", "client"]
    toggleable: bool
