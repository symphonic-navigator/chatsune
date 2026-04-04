"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._lock import get_user_lock

__all__ = [
    "get_user_lock",
]
