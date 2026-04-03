from datetime import datetime

from pydantic import BaseModel

from shared.dtos.llm import ModelMetaDto, UserModelConfigDto


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


class LlmUserModelConfigUpdatedEvent(BaseModel):
    """Emitted when a user updates OR deletes their model config. Delete sends defaults."""
    type: str = "llm.user_model_config.updated"
    model_unique_id: str
    config: UserModelConfigDto
