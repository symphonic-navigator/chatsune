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
        # Drop this specific socket from the manager. The delayed-cancel
        # task below checks whether the user still has any live sockets,
        # so this must happen first.
        await manager.disconnect(user_id, ws)

        # Give the user a short grace period to reconnect before cancelling
        # in-flight inferences. Without this grace period, a flaky network
        # (or a chat that is waiting on the ollama_local concurrency lock,
        # which may take >30 s behind a background job) causes a momentary
        # WS drop to kill the chat — even though the user never went away.
        async def _delayed_disconnect_cleanup() -> None:
            try:
                await asyncio.sleep(10)
                if manager.has_connections(user_id):
                    # User reconnected in time — keep the inference alive.
                    return
                cancelled = await cancel_all_for_user(user_id)
                if cancelled > 0:
                    _log.info(
                        "Cancelled %d in-flight inferences after disconnect grace period for user %s",
                        cancelled, user_id,
                    )
                try:
                    await trigger_disconnect_extraction(user_id)
                except Exception:
                    # H-003: do NOT swallow silently. The retry/buffer logic
                    # inside ``trigger_disconnect_extraction`` is the safety
                    # net; log loudly here so we notice if it breaks.
                    _log.error(
                        "disconnect_extraction_failed user=%s", user_id, exc_info=True,
                    )
            except Exception as exc:
                _log.error(
                    "Error in delayed disconnect cleanup for user %s: %s",
                    user_id, exc,
                )

        cleanup_task = asyncio.create_task(_delayed_disconnect_cleanup())
        _background_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(_background_tasks.discard)
