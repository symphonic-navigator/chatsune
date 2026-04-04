import asyncio

_user_locks: dict[str, asyncio.Lock] = {}


def get_user_lock(user_id: str) -> asyncio.Lock:
    """Return a per-user asyncio.Lock, creating one if it does not exist.

    This lock is shared between chat inference and background jobs
    to ensure at most one concurrent LLM request per user.
    """
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]
