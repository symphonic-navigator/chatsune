from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobLogStatus = Literal["started", "completed", "failed", "retry"]


class JobLogEntryDto(BaseModel):
    """One transition of a background job, as shown in the Job Log tab."""

    entry_id: str = Field(..., description="Stable id for client-side dedupe")
    job_id: str
    job_type: str
    persona_id: str | None = None
    status: JobLogStatus
    attempt: int = 0
    silent: bool = False
    ts: datetime
    duration_ms: int | None = None
    error_message: str | None = None


class JobLogDto(BaseModel):
    entries: list[JobLogEntryDto]
