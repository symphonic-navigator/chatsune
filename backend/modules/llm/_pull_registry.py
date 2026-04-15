"""In-memory registry of running Ollama pull tasks.

Scope key is a string: "connection:{id}" or "admin-local".
No persistence — registry is lost on backend restart; Ollama aborts
the pull because the HTTP client is gone. Users must retry manually.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Awaitable, Callable


@dataclass
class PullHandle:
    pull_id: str
    scope: str
    slug: str
    task: asyncio.Task
    last_status: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PullTaskRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, PullHandle] = {}

    def register(
        self,
        *,
        scope: str,
        slug: str,
        coro_factory: Callable[[str], Awaitable[None]],
    ) -> PullHandle:
        pull_id = uuid.uuid4().hex
        task = asyncio.create_task(coro_factory(pull_id))
        handle = PullHandle(pull_id=pull_id, scope=scope, slug=slug, task=task)
        self._by_id[pull_id] = handle
        task.add_done_callback(lambda _t, pid=pull_id: self._on_done(pid))
        return handle

    def list(self, scope: str) -> list[PullHandle]:
        return [h for h in self._by_id.values() if h.scope == scope]

    def get(self, pull_id: str) -> PullHandle | None:
        return self._by_id.get(pull_id)

    def cancel(self, scope: str, pull_id: str) -> bool:
        h = self._by_id.get(pull_id)
        if h is None or h.scope != scope:
            return False
        h.task.cancel()
        return True

    def update_status(self, pull_id: str, status: str) -> None:
        h = self._by_id.get(pull_id)
        if h is not None:
            h.last_status = status

    def _on_done(self, pull_id: str) -> None:
        self._by_id.pop(pull_id, None)


_SINGLETON: PullTaskRegistry | None = None


def get_pull_registry() -> PullTaskRegistry:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = PullTaskRegistry()
    return _SINGLETON
