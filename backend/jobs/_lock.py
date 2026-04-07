import asyncio
import weakref

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


def get_job_lock(user_id: str) -> asyncio.Lock:
    """Per-user lock for background jobs only.

    Serialises background jobs for the same user (so two memory-extraction
    runs do not race against each other) but does NOT block on foreground
    chat inference.
    """
    lock = _job_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _job_locks[user_id] = lock
    return lock
