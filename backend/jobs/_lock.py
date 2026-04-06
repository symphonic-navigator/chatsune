import asyncio
import weakref

_user_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def get_user_lock(user_id: str) -> asyncio.Lock:
    """Return a per-user asyncio.Lock, creating one if it does not exist.

    This lock is shared between chat inference and background jobs
    to ensure at most one concurrent LLM request per user.
    """
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock
