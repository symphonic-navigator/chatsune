"""Tools module — pluggable tool registry with group-based toggling.

Public API: import only from this file.
"""

import json
import logging
import time as _time
from datetime import datetime, timezone

from backend.modules.metrics import tool_calls_total, tool_call_duration_seconds

from backend.modules.tools._client_dispatcher import ClientToolDispatcher
from backend.modules.tools._registry import ToolGroup, get_groups
from shared.dtos.inference import ToolDefinition
from shared.dtos.tools import ToolGroupDto

_log = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 5

# Client-tool timeouts: the server-side wait budget is intentionally ~5s
# larger than the client-side Worker budget to absorb network and
# scheduler jitter. See docs/superpowers/specs/2026-04-11-calculate-js-
# client-tool-design.md §4.
_CLIENT_TOOL_SERVER_TIMEOUT_MS = 10_000
_CLIENT_TOOL_CLIENT_TIMEOUT_MS = 5_000

_dispatcher_singleton = ClientToolDispatcher()


def get_client_dispatcher() -> ClientToolDispatcher:
    """Return the singleton client-tool dispatcher (for WS router and disconnect hooks)."""
    return _dispatcher_singleton


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


async def execute_tool(
    user_id: str,
    tool_name: str,
    arguments_json: str,
    *,
    tool_call_id: str,
    session_id: str,
    originating_connection_id: str,
    model: str = "",
) -> str:
    """Dispatch a tool call to the appropriate executor.

    For server-side tools (``side == "server"``) the registered executor is
    invoked directly. For client-side tools (``side == "client"``) the call
    is forwarded to the originating browser connection via the
    ``ClientToolDispatcher`` and this coroutine awaits the result.

    Always returns a string (JSON-encoded result or error). Raises
    ``ToolNotFoundError`` only if the tool name is unknown.
    """
    arguments = json.loads(arguments_json)
    t_start = _time.monotonic()

    for group in get_groups().values():
        if tool_name not in group.tool_names:
            continue

        try:
            if group.side == "client":
                return await _dispatcher_singleton.dispatch(
                    user_id=user_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    server_timeout_ms=_CLIENT_TOOL_SERVER_TIMEOUT_MS,
                    client_timeout_ms=_CLIENT_TOOL_CLIENT_TIMEOUT_MS,
                    target_connection_id=originating_connection_id,
                )

            if group.executor is not None:
                return await group.executor.execute(user_id, tool_name, arguments)
        finally:
            duration = _time.monotonic() - t_start
            tool_calls_total.labels(model=model, tool_name=tool_name).inc()
            tool_call_duration_seconds.labels(model=model, tool_name=tool_name).observe(duration)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")


def get_max_tool_iterations() -> int:
    """Return the maximum number of tool loop iterations."""
    return _MAX_TOOL_ITERATIONS


__all__ = [
    "get_all_groups",
    "get_active_definitions",
    "execute_tool",
    "get_max_tool_iterations",
    "get_client_dispatcher",
    "ToolNotFoundError",
]
