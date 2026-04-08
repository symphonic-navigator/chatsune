"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._consumer import consumer_loop, ensure_consumer_group
from backend.jobs._inspect import (
    get_lock_snapshot,
    get_pending_jobs,
    get_stream_queue_snapshot,
)
from backend.jobs._lock import get_job_lock, get_user_lock
from backend.jobs._models import JobType
from backend.jobs._submit import submit

__all__ = [
    "consumer_loop",
    "ensure_consumer_group",
    "get_user_lock",
    "get_job_lock",
    "submit",
    "JobType",
    "get_lock_snapshot",
    "get_pending_jobs",
    "get_stream_queue_snapshot",
]
