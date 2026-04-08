import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from backend.database import get_redis
from backend.jobs._models import JobEntry, JobType
from backend.modules.safeguards import (
    EmergencyStoppedError,
    SafeguardConfig,
    enforce_queue_cap,
    is_emergency_stopped,
)

_log = logging.getLogger(__name__)

_STREAM_KEY = "jobs:pending"


async def submit(
    job_type: JobType,
    user_id: str,
    model_unique_id: str,
    payload: dict,
    correlation_id: str | None = None,
) -> str:
    """Enqueue a background job into the Redis Stream.

    Returns the job ID (UUID).

    Safeguards applied here:
    - Global kill-switch: if engaged, raises ``EmergencyStoppedError`` before
      touching the stream.
    - Per-user queue cap: after the entry is appended, any overflow older
      messages are evicted from the stream. Evictions are logged at WARNING.
    """
    # Re-read config on every call so the kill-switch can be flipped without
    # a restart — do not cache.
    sg_config = SafeguardConfig.from_env()
    if is_emergency_stopped(sg_config):
        raise EmergencyStoppedError()

    job_id = str(uuid4())
    corr_id = correlation_id or str(uuid4())
    entry = JobEntry(
        id=job_id,
        job_type=job_type,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload,
        correlation_id=corr_id,
        created_at=datetime.now(timezone.utc),
        execution_token=uuid4().hex,
    )

    redis = get_redis()
    msg_id = await redis.xadd(_STREAM_KEY, {"data": entry.model_dump_json()})
    msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id

    now_ms = int(time.time() * 1000)
    evicted = await enforce_queue_cap(
        redis,
        sg_config,
        user_id=user_id,
        stream_key=_STREAM_KEY,
        new_message_id=msg_id_str,
        now_ms=now_ms,
    )
    if evicted:
        _log.warning(
            "job.queue_cap.evicted user=%s count=%d ids=%s",
            user_id, len(evicted), evicted,
        )

    _log.info(
        "Submitted job %s (type=%s, model=%s, user=%s, correlation=%s)",
        job_id, job_type.value, model_unique_id, user_id, corr_id,
    )
    return job_id
