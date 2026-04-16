"""Process-local registry of live sidecar connections.

Keys: ``homelab_id``. Values: :class:`SidecarConnection`. No persistence.
Emits ``llm.homelab.status_changed`` on register/unregister transitions so
the host UI updates the online indicator in real time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from backend.modules.llm._csp._connection import SidecarConnection
from backend.modules.llm._csp._frames import AuthRevokedFrame, SupersededFrame
from shared.events.llm import HomelabStatusChangedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


def _monotonic() -> float:
    return time.monotonic()


def _now() -> datetime:
    return datetime.now(UTC)


class SidecarRegistry:
    def __init__(self, event_bus) -> None:
        self._by_homelab: dict[str, SidecarConnection] = {}
        self._user_by_homelab: dict[str, str] = {}
        self._degraded: set[str] = set()
        self._lock = asyncio.Lock()
        self._bus = event_bus

    def get(self, homelab_id: str) -> SidecarConnection | None:
        return self._by_homelab.get(homelab_id)

    def online_homelab_ids(self) -> set[str]:
        return set(self._by_homelab.keys())

    async def register(
        self, user_id: str, conn: SidecarConnection
    ) -> None:
        hid = conn.homelab_id
        async with self._lock:
            old = self._by_homelab.get(hid)
            self._by_homelab[hid] = conn
            self._user_by_homelab[hid] = user_id
            self._degraded.discard(hid)
        if old is not None:
            _log.info("csp.supersede homelab=%s", hid)
            try:
                await old.send(SupersededFrame())
            except Exception:  # noqa: BLE001
                pass
            await old.close()
        else:
            await self._publish_status(hid, user_id, is_online=True)

    async def unregister(self, homelab_id: str) -> None:
        async with self._lock:
            conn = self._by_homelab.pop(homelab_id, None)
            user_id = self._user_by_homelab.pop(homelab_id, None)
            self._degraded.discard(homelab_id)
        if conn is not None and user_id is not None:
            await self._publish_status(homelab_id, user_id, is_online=False)

    async def revoke(self, homelab_id: str) -> None:
        async with self._lock:
            conn = self._by_homelab.pop(homelab_id, None)
            user_id = self._user_by_homelab.pop(homelab_id, None)
            self._degraded.discard(homelab_id)
        if conn is None:
            return
        try:
            await conn.send(AuthRevokedFrame())
        except Exception:  # noqa: BLE001
            pass
        await conn.close()
        if user_id is not None:
            await self._publish_status(homelab_id, user_id, is_online=False)

    async def _publish_status(
        self, homelab_id: str, user_id: str, is_online: bool
    ) -> None:
        event = HomelabStatusChangedEvent(
            homelab_id=homelab_id,
            is_online=is_online,
            timestamp=_now(),
        )
        await self._bus.publish(
            Topics.LLM_HOMELAB_STATUS_CHANGED,
            event,
            target_user_ids=[user_id],
        )

    async def tick_health(self) -> None:
        """Called periodically (~15 s). Emits degraded/offline transitions.

        - > 90 s of silence → emit status (degraded) once, keep connection.
        - > 300 s of silence → drop the connection and emit offline.
        """

        now = _monotonic()
        to_remove: list[tuple[str, str]] = []
        degraded_transitions: list[tuple[str, str]] = []
        for hid, conn in list(self._by_homelab.items()):
            silence = now - getattr(conn, "last_traffic_at", now)
            user_id = self._user_by_homelab.get(hid)
            if user_id is None:
                continue
            if silence > 300:
                to_remove.append((hid, user_id))
            elif silence > 90 and hid not in self._degraded:
                degraded_transitions.append((hid, user_id))

        for hid, user_id in degraded_transitions:
            self._degraded.add(hid)
            # Emit an is_online=False signal once; the frontend treats the
            # combination of is_online=False + a still-present connection
            # as "degraded" (see design spec §5.10).
            await self._publish_status(hid, user_id, is_online=False)

        for hid, user_id in to_remove:
            async with self._lock:
                self._by_homelab.pop(hid, None)
                self._user_by_homelab.pop(hid, None)
                self._degraded.discard(hid)
            await self._publish_status(hid, user_id, is_online=False)


_singleton: SidecarRegistry | None = None


def set_sidecar_registry(reg: SidecarRegistry) -> None:
    global _singleton
    _singleton = reg


def get_sidecar_registry() -> SidecarRegistry:
    if _singleton is None:
        raise RuntimeError("SidecarRegistry not initialised")
    return _singleton
