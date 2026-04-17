"""Process-local semaphore registries for homelab-wide and api-key concurrency."""
from __future__ import annotations

import asyncio


class _KeyedSemRegistry:
    def __init__(self) -> None:
        self._map: dict[str, tuple[int, asyncio.Semaphore]] = {}

    def get(self, key: str, size: int) -> asyncio.Semaphore:
        size = max(1, int(size))
        existing = self._map.get(key)
        if existing is None or existing[0] != size:
            sem = asyncio.Semaphore(size)
            self._map[key] = (size, sem)
            return sem
        return existing[1]

    def evict(self, key: str) -> None:
        self._map.pop(key, None)


_homelab_sem: _KeyedSemRegistry | None = None
_api_key_sem: _KeyedSemRegistry | None = None


def get_homelab_semaphore_registry() -> _KeyedSemRegistry:
    global _homelab_sem
    if _homelab_sem is None:
        _homelab_sem = _KeyedSemRegistry()
    return _homelab_sem


def get_api_key_semaphore_registry() -> _KeyedSemRegistry:
    global _api_key_sem
    if _api_key_sem is None:
        _api_key_sem = _KeyedSemRegistry()
    return _api_key_sem
