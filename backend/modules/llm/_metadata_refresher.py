"""Per-user background refresher for the LLM model metadata cache.

One `asyncio.Task` runs for every online user. It refreshes every
Connection and Premium Provider model list owned by the user on a fixed
cadence and replaces the Redis entry atomically on success. Failures are
logged and leave the prior cached value intact.

Lifecycle is driven by WebSocket presence: the ConnectionManager fires
`ensure_user_task` on the first-connect edge and `release_user_task` on
the last-disconnect edge. Both are idempotent and refcounted so multiple
tabs do not create multiple tasks.
"""

import asyncio
import logging
import random

_log = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 30 * 60
REFRESH_JITTER_SECONDS = 60
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


class ModelCacheRefresher:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._refcounts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def has_active_task(self, user_id: str) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

    async def ensure_user_task(self, user_id: str) -> None:
        async with self._lock:
            self._refcounts[user_id] = self._refcounts.get(user_id, 0) + 1
            if user_id in self._tasks and not self._tasks[user_id].done():
                return
            self._tasks[user_id] = asyncio.create_task(
                self._user_loop(user_id),
                name=f"model-cache-refresher:{user_id}",
            )

    async def release_user_task(self, user_id: str) -> None:
        async with self._lock:
            current = self._refcounts.get(user_id, 0)
            if current <= 1:
                self._refcounts.pop(user_id, None)
                task = self._tasks.pop(user_id, None)
            else:
                self._refcounts[user_id] = current - 1
                task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception(
                "refresher task for user=%s raised on cancel", user_id,
            )

    async def _user_loop(self, user_id: str) -> None:
        """Background loop body — runs until cancelled."""
        while True:
            try:
                await self._run_user_iteration(user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception(
                    "refresher iteration crashed for user=%s — continuing",
                    user_id,
                )
            jitter = random.uniform(-REFRESH_JITTER_SECONDS, REFRESH_JITTER_SECONDS)
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS + jitter)

    async def _run_user_iteration(self, user_id: str) -> None:
        """One full refresh pass. Filled in by Task 3."""
        raise NotImplementedError


_refresher: ModelCacheRefresher | None = None


def get_model_cache_refresher() -> ModelCacheRefresher:
    global _refresher
    if _refresher is None:
        _refresher = ModelCacheRefresher()
    return _refresher


def reset_for_tests() -> None:
    """Test-only hook to reinitialise the singleton."""
    global _refresher
    _refresher = None
