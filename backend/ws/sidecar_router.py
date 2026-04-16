"""WebSocket endpoint for sidecar connections (CSP/1).

Authenticates the sidecar via a Host-Key bearer token, performs the CSP
handshake, and hands the socket off to a :class:`SidecarConnection` that
owns the frame loop for the duration of the connection. The connection is
registered in the process-local :class:`SidecarRegistry` so that the
community adapter (and other callers) can route RPCs to it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.database import get_db
from backend.modules.llm import (
    HOST_KEY_PREFIX,
    HandshakeAckFrame,
    HandshakeFrame,
    HomelabService,
    SidecarConnection,
    SidecarRegistry,
    get_sidecar_registry,
    negotiate_version,
)
from backend.ws.event_bus import get_event_bus

_log = logging.getLogger(__name__)

router = APIRouter()

BACKEND_CSP_VERSION = "1.0"


@router.websocket("/ws/sidecar")
async def sidecar_endpoint(ws: WebSocket) -> None:
    auth = ws.headers.get("authorization") or ws.query_params.get("access_token")
    if not auth or not auth.startswith("Bearer "):
        await ws.close(code=4401)
        return
    host_key = auth.removeprefix("Bearer ").strip()
    if not host_key.startswith(HOST_KEY_PREFIX):
        await ws.close(code=4401)
        return

    svc = HomelabService(get_db(), get_event_bus())
    homelab = await svc.resolve_homelab_by_host_key(host_key)
    if homelab is None or homelab.get("status") != "active":
        await ws.close(code=4401)
        return

    await ws.accept()

    # Read the handshake frame.
    try:
        raw = await ws.receive_text()
    except WebSocketDisconnect:
        return
    try:
        hs = HandshakeFrame.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "csp.bad_handshake homelab=%s err=%s",
            homelab["homelab_id"], exc,
        )
        try:
            await ws.close(code=1002)
        except Exception:  # noqa: BLE001
            pass
        return

    accepted, negotiated, notices = negotiate_version(
        hs.csp_version, BACKEND_CSP_VERSION,
    )
    if not accepted:
        ack = HandshakeAckFrame(
            csp_version=BACKEND_CSP_VERSION,
            accepted=False,
            notices=notices,
        )
        await ws.send_text(ack.model_dump_json(exclude_none=True))
        try:
            await ws.close(code=1002)
        except Exception:  # noqa: BLE001
            pass
        return

    ack = HandshakeAckFrame(
        csp_version=negotiated,
        homelab_id=homelab["homelab_id"],
        display_name=homelab["display_name"],
        accepted=True,
        notices=notices,
    )
    await ws.send_text(ack.model_dump_json(exclude_none=True))

    # Stamp the homelab with the latest sidecar metadata. Best-effort: a
    # failure here must not prevent the sidecar from connecting.
    try:
        await svc.touch_last_seen(
            homelab_id=homelab["homelab_id"],
            sidecar_version=hs.sidecar_version,
            engine_info={"type": hs.engine.type, "version": hs.engine.version},
        )
    except Exception:  # noqa: BLE001
        _log.warning(
            "csp.touch_last_seen_failed homelab=%s",
            homelab["homelab_id"], exc_info=True,
        )

    conn = SidecarConnection(
        ws=ws,
        homelab_id=homelab["homelab_id"],
        display_name=homelab["display_name"],
        max_concurrent=hs.max_concurrent_requests,
        capabilities=set(hs.capabilities),
        sidecar_version=hs.sidecar_version,
        engine_info={"type": hs.engine.type, "version": hs.engine.version},
    )

    registry: SidecarRegistry = get_sidecar_registry()
    await registry.register(user_id=homelab["user_id"], conn=conn)
    try:
        await conn.run()
    finally:
        # Only unregister if we still own the slot. A later connection for
        # the same homelab would have called ``register`` which supersedes
        # this one and pushed a SupersededFrame — it also updates the
        # registry slot to the new connection.
        current = registry.get(conn.homelab_id)
        if current is conn:
            await registry.unregister(conn.homelab_id)
        if ws.application_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
