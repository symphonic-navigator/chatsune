"""Admin debug DTOs.

These DTOs power the admin debug overlay. They are diagnostic snapshots —
not authoritative state. Treat fields as best-effort: a job may transition
between snapshot and render, a lock may be released between read and use.

Visibility: every DTO here may carry user-identifying information and is
therefore restricted to admin / master_admin roles by the routes that
return them.
"""

from datetime import datetime

from pydantic import BaseModel


class ActiveInferenceDto(BaseModel):
    """A single in-flight LLM inference inside the backend process."""

    inference_id: str
    user_id: str
    username: str | None
    provider_id: str
    model_slug: str
    model_unique_id: str
    source: str  # "chat" | "job:<job_type>" | "vision_fallback" | other
    started_at: datetime
    duration_seconds: float


class JobSnapshotDto(BaseModel):
    """A queued, running, or retry-pending background job."""

    job_id: str
    job_type: str
    user_id: str
    username: str | None
    model_unique_id: str
    correlation_id: str
    created_at: datetime
    age_seconds: float
    attempt: int
    status: str  # "queued" | "running" | "retry_pending"
    next_retry_at: datetime | None = None
    max_retries: int | None = None


class LockSnapshotDto(BaseModel):
    """A single in-process lock that is currently held."""

    kind: str  # "user" | "job"
    user_id: str
    username: str | None


class StreamQueueDto(BaseModel):
    """Redis Stream queue depth + consumer group state."""

    name: str
    stream_length: int
    pending_count: int  # XPENDING summary count
    oldest_pending_age_seconds: float | None
    consumer_group: str | None


class EmbeddingQueueDto(BaseModel):
    """Local embedding worker queue depths."""

    model_loaded: bool
    model_name: str
    query_queue_size: int
    embed_queue_size: int


class DebugSnapshotDto(BaseModel):
    """Full diagnostic snapshot of background work + LLM inference."""

    generated_at: datetime
    active_inferences: list[ActiveInferenceDto]
    jobs: list[JobSnapshotDto]
    locks: list[LockSnapshotDto]
    stream_queues: list[StreamQueueDto]
    embedding_queue: EmbeddingQueueDto


class DebugInferenceStartedPayload(BaseModel):
    """Live event payload — emitted when an LLM inference begins."""

    inference_id: str
    user_id: str
    username: str | None
    provider_id: str
    model_slug: str
    model_unique_id: str
    source: str
    started_at: datetime


class DebugInferenceFinishedPayload(BaseModel):
    """Live event payload — emitted when an LLM inference ends."""

    inference_id: str
    duration_seconds: float
