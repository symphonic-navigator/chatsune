"""One-per-sidecar state machine. Decouples callers from the WS."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from backend.modules.llm._csp._errors import CSPConnectionClosed
from backend.modules.llm._csp._frames import (
    CancelFrame,
    ErrFrame,
    PingFrame,
    PongFrame,
    ReqFrame,
    ResFrame,
    StreamEndFrame,
    StreamFrame,
    parse_frame,
)

_log = logging.getLogger(__name__)


def _monotonic() -> float:
    return time.monotonic()


class _PendingRequest:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[BaseModel | None] = asyncio.Queue()
        self.done = asyncio.Event()


class SidecarConnection:
    """Wraps a WS connection plus all per-connection dispatch state."""

    def __init__(
        self,
        ws,
        homelab_id: str,
        display_name: str,
        max_concurrent: int,
        capabilities: set[str],
        sidecar_version: str,
        engine_info: dict,
    ) -> None:
        self.ws = ws
        self.homelab_id = homelab_id
        self.display_name = display_name
        self.max_concurrent = max_concurrent
        self.capabilities = capabilities
        self.sidecar_version = sidecar_version
        self.engine_info = engine_info
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, _PendingRequest] = {}
        self._closed = asyncio.Event()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self.last_traffic_at: float = _monotonic()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    async def send(self, frame: BaseModel) -> None:
        if self.closed:
            raise CSPConnectionClosed()
        async with self._send_lock:
            await self.ws.send_text(frame.model_dump_json(exclude_none=True))

    async def run(self) -> None:
        """Drive the frame loop until the socket closes. Blocking."""

        try:
            while not self.closed:
                raw = await self.ws.receive_text()
                try:
                    frame = parse_frame(raw)
                except Exception as exc:
                    _log.warning(
                        "csp.parse_error homelab=%s err=%s",
                        self.homelab_id, exc,
                    )
                    continue
                await self._dispatch(frame)
        except CSPConnectionClosed:
            pass
        except Exception as exc:  # noqa: BLE001
            _log.info(
                "csp.connection_closed homelab=%s cause=%s",
                self.homelab_id, exc,
            )
        finally:
            self._closed.set()
            for pr in self._pending.values():
                await pr.queue.put(None)
                pr.done.set()

    async def _dispatch(self, frame: BaseModel) -> None:
        self.last_traffic_at = _monotonic()
        if isinstance(frame, PingFrame):
            await self.send(PongFrame())
            return
        if isinstance(frame, PongFrame):
            return
        if isinstance(frame, ResFrame):
            pr = self._pending.get(frame.id)
            if pr is None:
                _log.warning("csp.res_no_pending id=%s", frame.id)
                return
            await pr.queue.put(frame)
            await pr.queue.put(None)  # sentinel
            pr.done.set()
            return
        if isinstance(frame, StreamFrame):
            pr = self._pending.get(frame.id)
            if pr is None:
                return
            await pr.queue.put(frame)
            return
        if isinstance(frame, StreamEndFrame):
            pr = self._pending.get(frame.id)
            if pr is None:
                return
            await pr.queue.put(frame)
            await pr.queue.put(None)
            pr.done.set()
            return
        if isinstance(frame, ErrFrame):
            pr = self._pending.get(frame.id) if frame.id else None
            if pr is None:
                _log.warning(
                    "csp.orphan_err code=%s msg=%s",
                    frame.code, frame.message,
                )
                return
            await pr.queue.put(frame)
            return
        # Unknown → ignored (forward-compat).

    async def close(self) -> None:
        if self.closed:
            return
        self._closed.set()
        try:
            await self.ws.close(code=1000)
        except Exception:  # noqa: BLE001
            pass

    # --- Public RPCs ---

    async def rpc_list_models(self) -> list[dict[str, Any]]:
        if self.closed:
            raise CSPConnectionClosed()
        rid = str(uuid4())
        pr = _PendingRequest()
        self._pending[rid] = pr
        try:
            async with self._semaphore:
                await self.send(ReqFrame(id=rid, op="list_models"))
                frame = await pr.queue.get()
                if frame is None:
                    raise CSPConnectionClosed()
                if isinstance(frame, ErrFrame):
                    # drain sentinel
                    await pr.queue.get()
                    raise RuntimeError(f"{frame.code}: {frame.message}")
                assert isinstance(frame, ResFrame)
                return frame.body.get("models", []) if frame.body else []
        finally:
            self._pending.pop(rid, None)

    async def rpc_generate_chat(
        self, body: dict[str, Any]
    ) -> AsyncIterator[BaseModel]:
        """Stream frames for a ``generate_chat`` request.

        The caller iterates with ``async for``. Closing the generator
        (via ``aclose``/``GeneratorExit``) sends a ``cancel`` frame and
        briefly awaits the sidecar's final ``stream_end(cancelled)``.
        """
        if self.closed:
            raise CSPConnectionClosed()
        rid = str(uuid4())
        pr = _PendingRequest()
        self._pending[rid] = pr
        completed_normally = False
        try:
            async with self._semaphore:
                await self.send(
                    ReqFrame(id=rid, op="generate_chat", body=body)
                )
                while True:
                    frame = await pr.queue.get()
                    if frame is None:
                        completed_normally = True
                        return
                    yield frame
                    if isinstance(frame, StreamEndFrame):
                        completed_normally = True
                        return
        finally:
            # If we're here via GeneratorExit (caller closed early) and the
            # stream did not complete, try to send a cancel frame and wait
            # briefly for the sidecar's cancelled stream_end.
            if not completed_normally and not self.closed:
                try:
                    await self.send(CancelFrame(id=rid))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await asyncio.wait_for(pr.done.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            self._pending.pop(rid, None)
