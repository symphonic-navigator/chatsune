import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.modules.user._auth import decode_access_token
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager

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

    if since is not None:
        redis = get_event_bus()._redis
        entries = await redis.xrange("events:global", min=f"({since}", max="+")
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

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "token.refresh":
                refresh_token = ws.cookies.get("refresh_token")
                if not refresh_token:
                    await ws.send_json({"type": "error", "detail": "No refresh token cookie"})
                    continue
                from backend.modules.user import perform_token_refresh
                result = await perform_token_refresh(refresh_token, get_event_bus()._redis)
                if result is None:
                    await ws.send_json({"type": "error", "detail": "Invalid refresh token"})
                    continue
                await ws.send_json({
                    "type": "token.refreshed",
                    "access_token": result["access_token"],
                    "expires_in": result["expires_in"],
                })

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        expiry_task.cancel()
        await manager.disconnect(user_id, ws)
