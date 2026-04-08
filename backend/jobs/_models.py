from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class JobType(StrEnum):
    TITLE_GENERATION = "title_generation"
    MEMORY_EXTRACTION = "memory_extraction"
    MEMORY_CONSOLIDATION = "memory_consolidation"


@dataclass(frozen=True)
class JobConfig:
    handler: Callable[..., Awaitable[None]]
    max_retries: int = 3
    retry_delay_seconds: float = 15.0
    queue_timeout_seconds: float = 3600.0
    execution_timeout_seconds: float = 300.0
    reasoning_enabled: bool = False
    notify: bool = False
    notify_error: bool = False


class JobEntry(BaseModel):
    id: str
    job_type: JobType
    user_id: str
    model_unique_id: str
    payload: dict
    correlation_id: str
    created_at: datetime
    attempt: int = 0
    # Unique per submission; used as a one-shot idempotency key so a
    # re-delivered stream message does not run its handler twice.
    execution_token: str = Field(default_factory=lambda: uuid4().hex)
