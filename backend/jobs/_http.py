"""HTTP routes for the job log (per-user diagnostic view)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from backend.database import get_redis
from backend.dependencies import require_active_session
from backend.jobs._log import JOB_LOG_MAX, read_job_log_entries
from shared.dtos.jobs import JobLogDto

_log = logging.getLogger("chatsune.jobs.http")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/log", response_model=JobLogDto)
async def get_job_log(
    user: dict = Depends(require_active_session),
    limit: int = Query(JOB_LOG_MAX, ge=1, le=JOB_LOG_MAX),
) -> JobLogDto:
    redis = get_redis()
    user_id = user["sub"]
    entries = await read_job_log_entries(redis, user_id=user_id, limit=limit)
    _log.debug("jobs.log.served user_id=%s count=%d", user_id, len(entries))
    return JobLogDto(entries=entries)
