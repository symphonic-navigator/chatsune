"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._consumer import consumer_loop, ensure_consumer_group
from backend.jobs._dedup import (
    memory_extraction_slot_key,
    release_inflight_slot,
    try_acquire_inflight_slot,
)
from backend.jobs._errors import UnrecoverableJobError
from backend.jobs._inspect import (
    get_lock_snapshot,
    get_pending_jobs,
    get_stream_queue_snapshot,
)
from backend.jobs._lock import get_job_lock, get_user_lock
from backend.jobs._http import router as jobs_http_router
from backend.jobs._log import append_job_log_entry, read_job_log_entries
from backend.jobs._models import JobType
from backend.jobs._submit import submit

__all__ = [
    "consumer_loop",
    "ensure_consumer_group",
    "get_user_lock",
    "get_job_lock",
    "submit",
    "JobType",
    "UnrecoverableJobError",
    "try_acquire_inflight_slot",
    "release_inflight_slot",
    "memory_extraction_slot_key",
    "get_lock_snapshot",
    "get_pending_jobs",
    "get_stream_queue_snapshot",
    "append_job_log_entry",
    "read_job_log_entries",
    "jobs_http_router",
]
