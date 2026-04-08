"""Inference concurrency control.

Adapters declare a ``ConcurrencyPolicy`` as a class attribute; the
:class:`InferenceLockRegistry` hands out the matching asyncio lock (or
``None`` for fully parallel providers) at inference time.

``ollama_local`` uses ``GLOBAL`` because the local engine cannot sensibly
serve two generations at once — a second request would need its own KV
cache and prefill, which the hardware can't provide. ``ollama_cloud``
and other remote providers leave it at the default ``NONE``.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Protocol


class ConcurrencyPolicy(str, Enum):
    NONE = "none"          # fully parallel (default)
    GLOBAL = "global"      # one inference at a time, process-wide
    PER_USER = "per_user"  # one inference at a time, per user


class _AdapterLike(Protocol):
    provider_id: str
    concurrency_policy: ConcurrencyPolicy


class InferenceLockRegistry:
    """Process-local registry of asyncio locks keyed by adapter policy."""

    def __init__(self) -> None:
        self._global: dict[str, asyncio.Lock] = {}
        self._per_user: dict[tuple[str, str], asyncio.Lock] = {}

    def lock_for(
        self, adapter_cls: type[_AdapterLike], user_id: str,
    ) -> asyncio.Lock | None:
        policy = adapter_cls.concurrency_policy
        if policy is ConcurrencyPolicy.NONE:
            return None
        if policy is ConcurrencyPolicy.GLOBAL:
            return self._global.setdefault(adapter_cls.provider_id, asyncio.Lock())
        if policy is ConcurrencyPolicy.PER_USER:
            key = (adapter_cls.provider_id, user_id)
            return self._per_user.setdefault(key, asyncio.Lock())
        raise ValueError(f"Unknown concurrency policy: {policy!r}")


# Single process-wide registry used by LlmService.
_registry = InferenceLockRegistry()


def get_lock_registry() -> InferenceLockRegistry:
    return _registry
