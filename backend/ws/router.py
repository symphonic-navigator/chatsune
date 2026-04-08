import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

_STREAM_ID_RE = re.compile(r"^\d+-\d+$")

from backend.database import get_redis
from backend.modules.chat import (
    cancel_all_for_user,
    handle_chat_cancel,
    handle_chat_edit,
    handle_chat_inference_alive,
    handle_chat_regenerate,
    handle_chat_send,
    handle_incognito_send,
    trigger_disconnect_extraction,
)
from backend.modules.user import decode_access_token
from backend.ws.manager import get_manager

_log = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def get_background_tasks() -> set[asyncio.Task]:
    """Return the set of in-flight WebSocket background tasks."""
    return _background_tasks


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

    user_id = payload.get("sub")
    role = payload.get("role")
    exp = payload.get("exp")
    if not user_id or not role or exp is None:
        _log.warning("WebSocket token missing required claims (sub/role/exp)")
        await ws.close(code=4001)
        return

    manager = get_manager()
    await ws.accept()
    await manager.connect(user_id, role, ws)

    expiry_task: asyncio.Task | None = None

    try:
        if since is not None:
            # Phase 1: replay from global scope only; future scopes (persona, session) extend this
            if not _STREAM_ID_RE.match(since):
                _log.warning("Ignoring invalid 'since' stream id from client: %r", since)
            else:
                try:
                    entries = await get_redis().xrange(
                        "events:global", min=f"({since}", max="+",
                    )
                except Exception:
                    _log.exception("Failed to xrange replay stream for user %s", user_id)
                    entries = []
                for stream_id, data in entries:
                    try:
                        envelope = json.loads(data["envelope"])
                        envelope["sequence"] = stream_id
                        await ws.send_json(envelope)
                    except Exception:
                        _log.exception("Failed to replay stream entry %s", stream_id)

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
            elif msg_type == "chat.inference.alive":
                await handle_chat_inference_alive(user_id, data)
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
        # Cancel any in-flight inferences for this user — they will never be
        # observed now that the socket is gone, so the tokens would be wasted.
        try:
            cancelled = await cancel_all_for_user(user_id)
            if cancelled > 0:
                _log.info(
                    "Cancelled %d in-flight inferences due to WS disconnect for user %s",
                    cancelled, user_id,
                )
        except Exception as e:
            _log.error("Error cancelling in-flight inferences for user %s: %s", user_id, e)
        # Trigger memory extraction for any sessions with pending messages
        try:
            await trigger_disconnect_extraction(user_id)
        except Exception as e:
            _log.error("Error triggering disconnect extraction for user %s: %s", user_id, e)
        await manager.disconnect(user_id, ws)
