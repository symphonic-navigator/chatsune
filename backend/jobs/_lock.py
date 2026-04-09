import asyncio
import weakref
import structlog

_log = structlog.get_logger("chatsune.jobs.lock")

_user_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_job_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def get_user_lock(user_id: str) -> asyncio.Lock:
    """Per-user lock for foreground chat inference.

    Held by the WS chat handler while a user's chat stream is in flight.
    Background jobs MUST NOT take this lock — they have their own lock
    namespace via :func:`get_job_lock`. Upstream providers (Ollama Cloud
    etc.) tolerate concurrent calls per user, so chat and background jobs
    are allowed to run in parallel.
    """
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


class _InstrumentedJobLock:
    """Thin wrapper around asyncio.Lock that emits structured log events on
    acquire, contention, and release."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id
        self._lock = asyncio.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    async def __aenter__(self):
        lock_key = f"job_lock:{self._user_id}"
        if self._lock.locked():
            _log.info("job.lock.contended", lock_key=lock_key, holder=self._user_id)
        await self._lock.acquire()
        _log.info("job.lock.acquired", lock_key=lock_key, holder=self._user_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        lock_key = f"job_lock:{self._user_id}"
        if not self._lock.locked():
            # Lock was already released — should not happen under normal operation
            _log.warning("job.lock.expired", lock_key=lock_key)
            return
        self._lock.release()
        _log.info("job.lock.released", lock_key=lock_key, holder=self._user_id)


_instrumented_job_locks: weakref.WeakValueDictionary[str, _InstrumentedJobLock] = (
    weakref.WeakValueDictionary()
)


def get_job_lock(user_id: str) -> _InstrumentedJobLock:
    """Per-user lock for background jobs only.

    Serialises background jobs for the same user (so two memory-extraction
    runs do not race against each other) but does NOT block on foreground
    chat inference.
    """
    lock = _instrumented_job_locks.get(user_id)
    if lock is None:
        lock = _InstrumentedJobLock(user_id)
        _instrumented_job_locks[user_id] = lock
    return lock
