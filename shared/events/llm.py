from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared.dtos.llm import FaultyProviderDto, ModelMetaDto, UserModelConfigDto


class LlmCredentialSetEvent(BaseModel):
    type: str = "llm.credential.set"
    provider_id: str
    user_id: str
    timestamp: datetime


class LlmCredentialRemovedEvent(BaseModel):
    type: str = "llm.credential.removed"
    provider_id: str
    user_id: str
    timestamp: datetime


class LlmCredentialTestedEvent(BaseModel):
    type: str = "llm.credential.tested"
    provider_id: str
    user_id: str
    valid: bool
    timestamp: datetime


class LlmModelCuratedEvent(BaseModel):
    """Carries the full updated model DTO so clients can update in place."""
    type: str = "llm.model.curated"
    provider_id: str
    model_slug: str
    model: ModelMetaDto
    curated_by: str
    timestamp: datetime


class LlmModelsRefreshedEvent(BaseModel):
    """Trigger-only: tells clients to re-fetch the model list."""
    type: str = "llm.models.refreshed"
    provider_id: str
    timestamp: datetime


class LlmModelsFetchStartedEvent(BaseModel):
    """Published when the backend begins fetching models from upstream providers."""
    type: str = "llm.models.fetch_started"
    provider_ids: list[str]
    correlation_id: str
    timestamp: datetime


class LlmModelsFetchCompletedEvent(BaseModel):
    """Published when model fetching from upstream providers finishes.

    faulty_providers lists providers that returned errors.
    """
    type: str = "llm.models.fetch_completed"
    status: Literal["success", "partial", "failed"]
    total_models: int
    faulty_providers: list[FaultyProviderDto]
    correlation_id: str
    timestamp: datetime


class LlmUserModelConfigUpdatedEvent(BaseModel):
    """Emitted when a user updates OR deletes their model config. Delete sends defaults."""
    type: str = "llm.user_model_config.updated"
    model_unique_id: str
    config: UserModelConfigDto
    timestamp: datetime


class LlmProviderStatusChangedEvent(BaseModel):
    type: str = "llm.provider_status.changed"
    provider_id: str
    available: bool
    model_count: int
    timestamp: datetime


class LlmProviderStatusSnapshotEvent(BaseModel):
    type: str = "llm.provider_status.snapshot"
    statuses: dict[str, bool]
    timestamp: datetime


class InferenceLockWaitStartedEvent(BaseModel):
    """Emitted when a chat inference begins waiting on a provider lock."""
    type: str = "inference.lock.wait_started"
    correlation_id: str
    provider_id: str
    holder_source: str  # e.g. "job:memory_consolidation" or "chat"
    timestamp: datetime


class InferenceLockWaitEndedEvent(BaseModel):
    """Emitted when the waiting chat inference finally acquires the lock."""
    type: str = "inference.lock.wait_ended"
    correlation_id: str
    provider_id: str
    timestamp: datetime
