import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.database import get_redis
from backend.modules.chat import handle_chat_send, handle_chat_cancel, handle_chat_edit, handle_chat_regenerate, handle_incognito_send
from backend.modules.user import decode_access_token
from backend.ws.manager import get_manager

_log = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = Query(...),
    since: str | None = Query(default=None),
) -> None:
    try:
        payload = decode_access_token(token)
    except Exception:
        await ws.close(code=4001)
        return

    if payload.get("mcp"):
        await ws.close(code=4003)
        return

    user_id: str = payload["sub"]
    role: str = payload["role"]
    exp: int = payload["exp"]

    manager = get_manager()
    await ws.accept()
    await manager.connect(user_id, role, ws)

    expiry_task: asyncio.Task | None = None

    try:
        if since is not None:
            # Phase 1: replay from global scope only; future scopes (persona, session) extend this
            entries = await get_redis().xrange("events:global", min=f"({since}", max="+")
            for stream_id, data in entries:
                try:
                    envelope = json.loads(data["envelope"])
                    envelope["sequence"] = stream_id
                    await ws.send_json(envelope)
                except Exception:
                    pass

        async def _send_expiry_warning() -> None:
            now = datetime.now(timezone.utc).timestamp()
            delay = exp - 120 - now
            if delay > 0:
                await asyncio.sleep(delay)
                try:
                    await ws.send_json({"type": "token.expiring_soon"})
                except Exception:
                    pass

        expiry_task = asyncio.create_task(_send_expiry_warning())

        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "chat.send":
                task = asyncio.create_task(handle_chat_send(user_id, data))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.cancel":
                handle_chat_cancel(user_id, data)
            elif msg_type == "chat.edit":
                task = asyncio.create_task(handle_chat_edit(user_id, data))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.regenerate":
                task = asyncio.create_task(handle_chat_regenerate(user_id, data))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.incognito.send":
                task = asyncio.create_task(handle_incognito_send(user_id, data))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

            # token.refresh is handled via POST /api/auth/refresh (HTTP) — the httpOnly
            # refresh token cookie cannot be updated over WebSocket; the token.expiring_soon
            # event prompts the client to refresh via the REST endpoint

    except WebSocketDisconnect:
        pass
    except Exception as e:
        _log.error("Unexpected error in WebSocket handler for user %s: %s", user_id, e)
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
        await manager.disconnect(user_id, ws)
