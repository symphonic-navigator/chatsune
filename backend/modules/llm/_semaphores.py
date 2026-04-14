"""Per-connection asyncio semaphore registry."""

from __future__ import annotations

import asyncio


class ConnectionSemaphoreRegistry:
    """Process-local registry. Semaphore size == connection.config.max_parallel."""

    def __init__(self) -> None:
        self._map: dict[str, tuple[int, asyncio.Semaphore]] = {}

    def get(self, connection_id: str, max_parallel: int) -> asyncio.Semaphore:
        max_parallel = max(1, int(max_parallel))
        existing = self._map.get(connection_id)
        if existing is None or existing[0] != max_parallel:
            sem = asyncio.Semaphore(max_parallel)
            self._map[connection_id] = (max_parallel, sem)
            return sem
        return existing[1]

    def evict(self, connection_id: str) -> None:
        self._map.pop(connection_id, None)


_registry: ConnectionSemaphoreRegistry | None = None


def get_semaphore_registry() -> ConnectionSemaphoreRegistry:
    global _registry
    if _registry is None:
        _registry = ConnectionSemaphoreRegistry()
    return _registry
