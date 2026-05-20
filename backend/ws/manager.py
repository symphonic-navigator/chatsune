import asyncio
import logging
from typing import Awaitable, Callable
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

_log = logging.getLogger(__name__)

_manager: "ConnectionManager | None" = None


class ConnectionManager:
    def __init__(self) -> None:
        # user_id -> connection_id -> WebSocket
        self._connections: dict[str, dict[str, WebSocket]] = {}
        self._user_roles: dict[str, str] = {}
        self._on_first_user_connect: list[Callable[[str], Awaitable[None]]] = []
        self._on_last_user_disconnect: list[Callable[[str], Awaitable[None]]] = []

    def register_on_first_connect(
        self, cb: Callable[[str], Awaitable[None]],
    ) -> None:
        self._on_first_user_connect.append(cb)

    def register_on_last_disconnect(
        self, cb: Callable[[str], Awaitable[None]],
    ) -> None:
        self._on_last_user_disconnect.append(cb)

    async def _fire_hooks(
        self,
        hooks: list[Callable[[str], Awaitable[None]]],
        user_id: str,
    ) -> None:
        for hook in hooks:
            try:
                await hook(user_id)
            except Exception:
                _log.exception(
                    "lifecycle hook %r failed for user=%s",
                    getattr(hook, "__name__", repr(hook)), user_id,
                )

    async def connect(self, user_id: str, role: str, ws: WebSocket) -> str:
        """Register a new WebSocket and return its assigned connection id."""
        connection_id = str(uuid4())
        is_first = user_id not in self._connections
        if is_first:
            self._connections[user_id] = {}
        self._connections[user_id][connection_id] = ws
        self._user_roles[user_id] = role
        if is_first:
            await self._fire_hooks(self._on_first_user_connect, user_id)
        return connection_id

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(user_id)
        if not conns:
            return
        dead_ids = [cid for cid, w in conns.items() if w is ws]
        for cid in dead_ids:
            del conns[cid]
        became_empty = not conns
        if became_empty:
            del self._connections[user_id]
            del self._user_roles[user_id]
            await self._fire_hooks(self._on_last_user_disconnect, user_id)

    def _iter_sockets(self, user_id: str) -> list[WebSocket]:
        return list(self._connections.get(user_id, {}).values())

    async def _send_ws_safe(self, user_id: str, ws: WebSocket, event: dict) -> None:
        try:
            await ws.send_json(event)
        except WebSocketDisconnect:
            await self.disconnect(user_id, ws)
        except Exception:
            await self.disconnect(user_id, ws)

    async def send_to_user(self, user_id: str, event: dict) -> None:
        sockets = self._iter_sockets(user_id)
        if not sockets:
            return
        await asyncio.gather(
            *(self._send_ws_safe(user_id, ws, event) for ws in sockets),
            return_exceptions=True,
        )

    async def send_to_users(self, user_ids: list[str], event: dict) -> None:
        for user_id in user_ids:
            await self.send_to_user(user_id, event)

    async def send_to_connection(
        self, user_id: str, connection_id: str, event: dict,
    ) -> None:
        """Deliver an event to exactly one WebSocket, identified by connection id.

        Best-effort: silent no-op if the connection is unknown (already
        disconnected, wrong user, or never existed).
        """
        ws = self._connections.get(user_id, {}).get(connection_id)
        if ws is None:
            return
        await self._send_ws_safe(user_id, ws, event)

    async def broadcast_to_roles(self, roles: list[str], event: dict) -> None:
        for user_id, role in list(self._user_roles.items()):
            if role in roles:
                await self.send_to_user(user_id, event)

    def user_ids_by_role(self, role: str) -> list[str]:
        return [uid for uid, r in self._user_roles.items() if r == role]

    def has_connections(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))

    def connection_ids_for_user(self, user_id: str) -> list[str]:
        """Return the list of connection ids currently held for the user."""
        return list(self._connections.get(user_id, {}).keys())

    def user_ids(self) -> list[str]:
        """Return the list of user_ids with at least one active connection."""
        return list(self._connections.keys())

    def update_role(self, user_id: str, role: str) -> None:
        if user_id in self._connections:
            self._user_roles[user_id] = role

    async def broadcast_to_all(self, event: dict) -> None:
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, event)


def set_manager(manager: ConnectionManager) -> None:
    global _manager
    _manager = manager


def get_manager() -> ConnectionManager:
    if _manager is None:
        raise RuntimeError("ConnectionManager not initialised")
    return _manager
