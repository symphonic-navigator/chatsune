import asyncio

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

_manager: "ConnectionManager | None" = None


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._user_roles: dict[str, str] = {}

    async def connect(self, user_id: str, role: str, ws: WebSocket) -> None:
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(ws)
        self._user_roles[user_id] = role

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        if user_id not in self._connections:
            return
        self._connections[user_id].discard(ws)
        if not self._connections[user_id]:
            del self._connections[user_id]
            del self._user_roles[user_id]

    async def send_to_user(self, user_id: str, event: dict) -> None:
        sockets = list(self._connections.get(user_id, set()))
        if not sockets:
            return

        async def _send(ws: WebSocket) -> None:
            try:
                await ws.send_json(event)
            except WebSocketDisconnect:
                await self.disconnect(user_id, ws)
            except Exception:
                # Treat any send error as a dead socket — drop it.
                await self.disconnect(user_id, ws)

        await asyncio.gather(*(_send(ws) for ws in sockets), return_exceptions=True)

    async def send_to_users(self, user_ids: list[str], event: dict) -> None:
        for user_id in user_ids:
            await self.send_to_user(user_id, event)

    async def broadcast_to_roles(self, roles: list[str], event: dict) -> None:
        for user_id, role in list(self._user_roles.items()):
            if role in roles:
                await self.send_to_user(user_id, event)

    def user_ids_by_role(self, role: str) -> list[str]:
        return [uid for uid, r in self._user_roles.items() if r == role]

    def has_connections(self, user_id: str) -> bool:
        """Return True if at least one live WebSocket exists for this user."""
        return bool(self._connections.get(user_id))

    def update_role(self, user_id: str, role: str) -> None:
        """Update the cached role for a connected user (no-op if not connected)."""
        if user_id in self._connections:
            self._user_roles[user_id] = role

    async def broadcast_to_all(self, event: dict) -> None:
        """Send an event to every connected user."""
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, event)


def set_manager(manager: ConnectionManager) -> None:
    global _manager
    _manager = manager


def get_manager() -> ConnectionManager:
    if _manager is None:
        raise RuntimeError("ConnectionManager not initialised")
    return _manager
