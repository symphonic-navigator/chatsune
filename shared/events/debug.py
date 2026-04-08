"""Admin debug events.

These events are broadcast to admin-role users only and are NOT persisted
in Redis Streams (high frequency, ephemeral diagnostics — see
``_SKIP_PERSISTENCE`` in ``backend/ws/event_bus.py``).
"""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.debug import DebugSnapshotDto


class DebugInferenceStartedEvent(BaseModel):
    type: str = "debug.inference.started"
    inference_id: str
    user_id: str
    username: str | None
    provider_id: str
    model_slug: str
    model_unique_id: str
    source: str
    started_at: datetime
    correlation_id: str
    timestamp: datetime


class DebugInferenceFinishedEvent(BaseModel):
    type: str = "debug.inference.finished"
    inference_id: str
    user_id: str
    duration_seconds: float
    correlation_id: str
    timestamp: datetime


class DebugSnapshotEvent(BaseModel):
    type: str = "debug.snapshot"
    snapshot: DebugSnapshotDto
    correlation_id: str
    timestamp: datetime
