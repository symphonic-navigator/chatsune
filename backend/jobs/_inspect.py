"""Diagnostic snapshot helpers for the background job subsystem.

These helpers expose otherwise-private state (per-user locks, the
``jobs:pending`` Redis Stream, retry hashes) to the admin debug overlay.
They are read-only and best-effort — every value reflects the moment of
the call, not authoritative state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from backend.jobs._lock import _job_locks, _user_locks
from backend.jobs._models import JobEntry
from backend.jobs._retry import get_retry

_log = logging.getLogger("chatsune.debug.jobs_inspect")

_STREAM = "jobs:pending"
_GROUP = "workers"


def get_lock_snapshot() -> list[dict]:
    """Return every lock currently held in this process.

    Each item: ``{"kind": "user"|"job", "user_id": str}``. The lock objects
    themselves live in ``WeakValueDictionary`` so dead entries auto-expire.
    """
    out: list[dict] = []
    # WeakValueDictionary iteration is safe; copy keys to avoid mutation races.
    for user_id in list(_user_locks.keys()):
        lock = _user_locks.get(user_id)
        if lock is not None and lock.locked():
            out.append({"kind": "user", "user_id": user_id})
    for user_id in list(_job_locks.keys()):
        lock = _job_locks.get(user_id)
        if lock is not None and lock.locked():
            out.append({"kind": "job", "user_id": user_id})
    return out


async def get_pending_jobs(redis: Redis, limit: int = 100) -> list[dict]:
    """Return every job currently sitting in the ``jobs:pending`` stream.

    Each item: ``{"job": JobEntry, "stream_id": str, "retry": dict | None,
    "status": "queued"|"running"|"retry_pending"}``. The ``status`` is a
    best-effort heuristic derived from retry state and lock state — it
    cannot distinguish "running" from "queued and not yet picked up" with
    100% accuracy because Redis Streams do not expose worker state for
    individual messages without XPENDING.
    """
    try:
        # XRANGE returns *all* entries currently in the stream regardless of
        # ack state. This is what we want — both queued (not yet read) and
        # in-flight (read but not yet acked) entries are visible to the
        # admin debug overlay.
        raw = await redis.xrange(_STREAM, min="-", max="+", count=limit)
    except Exception:
        _log.warning("XRANGE on %s failed", _STREAM, exc_info=True)
        return []

    pending_ids = await _xpending_ids(redis)

    out: list[dict] = []
    for stream_id, fields in raw:
        try:
            job = JobEntry.model_validate_json(fields["data"])
        except Exception:
            _log.warning("Failed to parse job entry %s", stream_id, exc_info=True)
            continue

        retry_state = await get_retry(redis, job.id)
        if retry_state and retry_state["next_retry_at"] > datetime.now(timezone.utc):
            status = "retry_pending"
        elif stream_id in pending_ids:
            # Read by a consumer but not yet acked — almost always means
            # the worker is currently executing this entry. Background
            # job execution is serialised per user (see _job_locks) so
            # this is the closest we can get to "running".
            status = "running"
        else:
            status = "queued"

        out.append({
            "job": job,
            "stream_id": stream_id,
            "retry": retry_state,
            "status": status,
        })
    return out


async def _xpending_ids(redis: Redis) -> set[str]:
    """Return the set of stream IDs that have been read but not yet acked."""
    try:
        # XPENDING with start/end "-" "+" returns up to ``count`` pending
        # entries. The default group is _GROUP. We only need the IDs.
        rows = await redis.xpending_range(
            name=_STREAM,
            groupname=_GROUP,
            min="-",
            max="+",
            count=100,
        )
    except Exception:
        # The consumer group may not exist yet during very early startup.
        return set()
    return {r["message_id"] for r in rows}


async def get_stream_queue_snapshot(redis: Redis) -> dict:
    """Return queue depth + oldest age for the ``jobs:pending`` stream."""
    try:
        length = await redis.xlen(_STREAM)
    except Exception:
        length = 0

    pending_count = 0
    oldest_age_seconds: float | None = None
    try:
        summary = await redis.xpending(_STREAM, _GROUP)
        # redis-py returns: {"pending": int, "min": str|None, "max": str|None, "consumers": [...]}
        pending_count = int(summary.get("pending", 0))
        min_id = summary.get("min")
        if min_id:
            # Stream IDs have the form "<ms>-<seq>" — parse the ms.
            try:
                ms = int(str(min_id).split("-", 1)[0])
                oldest_age_seconds = (
                    datetime.now(timezone.utc).timestamp() * 1000 - ms
                ) / 1000.0
            except (ValueError, IndexError):
                oldest_age_seconds = None
    except Exception:
        pass

    return {
        "name": _STREAM,
        "stream_length": int(length),
        "pending_count": pending_count,
        "oldest_pending_age_seconds": oldest_age_seconds,
        "consumer_group": _GROUP,
    }
