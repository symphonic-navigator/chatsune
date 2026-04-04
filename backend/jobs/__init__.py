"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._consumer import consumer_loop, ensure_consumer_group
from backend.jobs._lock import get_user_lock
from backend.jobs._models import JobType
from backend.jobs._submit import submit

__all__ = [
    "consumer_loop",
    "ensure_consumer_group",
    "get_user_lock",
    "submit",
    "JobType",
]
