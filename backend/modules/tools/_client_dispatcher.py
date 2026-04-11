"""Client-side tool call dispatcher.

Forwards tool calls whose ``ToolGroup.side == "client"`` to the originating
browser connection and waits for the result. Every failure path returns a
``{"stdout": "...", "error": "..."}`` JSON string — no exceptions escape.
"""

import asyncio
import json
import logging

from backend.ws.event_bus import get_event_bus
from shared.events.chat import ChatClientToolDispatchEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


class ClientToolDispatcher:
    """Awaits ``chat.client_tool.result`` messages and resolves pending futures."""

    def __init__(self) -> None:
        # tool_call_id -> (user_id, asyncio.Future[str])
        self._pending: dict[str, tuple[str, asyncio.Future[str]]] = {}

    async def dispatch(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        server_timeout_ms: int,
        client_timeout_ms: int,
        target_connection_id: str,
    ) -> str:
        """Publish the dispatch event and await the client's response.

        Returns a JSON string of shape ``{"stdout": "...", "error": null|str}``.
        Never raises.

        The server-side timeout (``server_timeout_ms``) is used for the
        ``asyncio.wait_for`` call and should be larger than
        ``client_timeout_ms`` (which is sent to the browser in the event
        payload so the Worker knows its own hard budget). The difference
        absorbs network latency and scheduler jitter.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[tool_call_id] = (user_id, future)

        try:
            await get_event_bus().publish(
                Topics.CHAT_CLIENT_TOOL_DISPATCH,
                ChatClientToolDispatchEvent(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    timeout_ms=client_timeout_ms,
                    target_connection_id=target_connection_id,
                ),
                scope=f"user:{user_id}",
                target_user_ids=[user_id],
                target_connection_id=target_connection_id,
                correlation_id=tool_call_id,
            )
            return await asyncio.wait_for(future, timeout=server_timeout_ms / 1000)
        except asyncio.TimeoutError:
            return json.dumps({
                "stdout": "",
                "error": f"Tool execution timed out after {server_timeout_ms}ms",
            })
        finally:
            self._pending.pop(tool_call_id, None)

    def resolve(
        self,
        *,
        tool_call_id: str,
        received_from_user_id: str,
        result_json: str,
    ) -> None:
        """Resolve a pending future with the given result JSON.

        Silent no-op (with warning) if the id is unknown or the user does
        not match. Double-resolve is silently ignored by the
        ``if not future.done()`` check.
        """
        pending = self._pending.get(tool_call_id)
        if pending is None:
            _log.warning(
                "client_tool_result for unknown tool_call_id=%s from user=%s",
                tool_call_id, received_from_user_id,
            )
            return

        expected_user_id, future = pending
        if expected_user_id != received_from_user_id:
            _log.warning(
                "client_tool_result user mismatch: tool_call_id=%s "
                "expected=%s received=%s (dropped)",
                tool_call_id, expected_user_id, received_from_user_id,
            )
            return

        if not future.done():
            future.set_result(result_json)

    def cancel_for_user(self, user_id: str) -> None:
        """Fail every pending future that belongs to this user.

        Called by the WS disconnect path when the user's last connection
        drops. Produces synthetic disconnect errors so the inference loop
        can complete cleanly.
        """
        for call_id, (uid, future) in list(self._pending.items()):
            if uid == user_id and not future.done():
                future.set_result(json.dumps({
                    "stdout": "",
                    "error": "Client disconnected before tool completed",
                }))
