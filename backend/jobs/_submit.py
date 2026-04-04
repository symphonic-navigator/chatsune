from datetime import datetime, timezone
from uuid import uuid4

from backend.database import get_redis
from backend.jobs._models import JobEntry, JobType


async def submit(
    job_type: JobType,
    user_id: str,
    model_unique_id: str,
    payload: dict,
    correlation_id: str | None = None,
) -> str:
    """Enqueue a background job into the Redis Stream.

    Returns the job ID (UUID).
    """
    job_id = str(uuid4())
    entry = JobEntry(
        id=job_id,
        job_type=job_type,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload,
        correlation_id=correlation_id or str(uuid4()),
        created_at=datetime.now(timezone.utc),
    )

    redis = get_redis()
    await redis.xadd("jobs:pending", {"data": entry.model_dump_json()})
    return job_id
