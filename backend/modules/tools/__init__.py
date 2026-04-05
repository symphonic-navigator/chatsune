"""Tools module — pluggable tool registry with group-based toggling.

Public API: import only from this file.
"""

import json
import logging
from datetime import datetime, timezone

from backend.modules.tools._registry import ToolGroup, get_groups
from shared.dtos.inference import ToolDefinition
from shared.dtos.tools import ToolGroupDto

_log = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 5


class ToolNotFoundError(Exception):
    """No registered executor can handle this tool name."""


def get_all_groups() -> list[ToolGroupDto]:
    """Return DTOs for all registered tool groups (for the frontend)."""
    return [
        ToolGroupDto(
            id=g.id,
            display_name=g.display_name,
            description=g.description,
            side=g.side,
            toggleable=g.toggleable,
        )
        for g in get_groups().values()
    ]


def get_active_definitions(
    disabled_groups: list[str] | None = None,
) -> list[ToolDefinition]:
    """Return tool definitions for all enabled groups.

    Groups not in ``disabled_groups`` are considered active.
    Non-toggleable groups are always included regardless.
    """
    disabled = set(disabled_groups or [])
    definitions: list[ToolDefinition] = []
    for group in get_groups().values():
        if group.id in disabled and group.toggleable:
            continue
        definitions.extend(group.definitions)
    return definitions


async def execute_tool(user_id: str, tool_name: str, arguments_json: str) -> str:
    """Dispatch a tool call to the appropriate executor.

    Returns the tool result as a string (JSON).
    Raises ToolNotFoundError if no executor handles this tool name.
    """
    arguments = json.loads(arguments_json)

    for group in get_groups().values():
        if tool_name in group.tool_names and group.executor is not None:
            return await group.executor.execute(user_id, tool_name, arguments)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")


def get_max_tool_iterations() -> int:
    """Return the maximum number of tool loop iterations."""
    return _MAX_TOOL_ITERATIONS


__all__ = [
    "get_all_groups",
    "get_active_definitions",
    "execute_tool",
    "get_max_tool_iterations",
    "ToolNotFoundError",
]
