from datetime import datetime

from pydantic import BaseModel


class JobStartedEvent(BaseModel):
    type: str = "job.started"
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime
    notify: bool = True
    persona_id: str | None = None


class JobCompletedEvent(BaseModel):
    type: str = "job.completed"
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime


class JobFailedEvent(BaseModel):
    type: str = "job.failed"
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    max_retries: int
    error_message: str
    recoverable: bool
    timestamp: datetime


class JobRetryEvent(BaseModel):
    type: str = "job.retry"
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    next_retry_at: datetime
    timestamp: datetime
    notify: bool = True


class JobExpiredEvent(BaseModel):
    type: str = "job.expired"
    job_id: str
    job_type: str
    correlation_id: str
    waited_seconds: float
    timestamp: datetime
