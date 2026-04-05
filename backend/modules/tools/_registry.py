"""Tool group registry — defines which tools exist and how they are grouped."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from shared.dtos.inference import ToolDefinition


class ToolExecutor(Protocol):
    """Interface that server-side tool executors must satisfy."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return the result as a string."""
        ...


@dataclass(frozen=True)
class ToolGroup:
    id: str
    display_name: str
    description: str
    side: Literal["server", "client"]
    toggleable: bool
    tool_names: list[str]
    definitions: list[ToolDefinition] = field(default_factory=list)
    executor: ToolExecutor | None = None


def _build_groups() -> dict[str, ToolGroup]:
    """Build the tool group registry. Imported lazily to avoid circular imports."""
    from backend.modules.tools._executors import WebSearchExecutor
    from backend.modules.websearch import get_tool_definitions as ws_definitions

    ws_defs = ws_definitions()

    return {
        "web_search": ToolGroup(
            id="web_search",
            display_name="Web Search",
            description="Search the web and fetch page content",
            side="server",
            toggleable=True,
            tool_names=[d.name for d in ws_defs],
            definitions=ws_defs,
            executor=WebSearchExecutor(),
        ),
    }


# Lazily initialised on first access.
_groups: dict[str, ToolGroup] | None = None


def get_groups() -> dict[str, ToolGroup]:
    global _groups
    if _groups is None:
        _groups = _build_groups()
    return _groups
