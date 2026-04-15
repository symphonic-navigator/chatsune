from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.dtos.llm import ConnectionDto, UserModelConfigDto


class LlmConnectionCreatedEvent(BaseModel):
    type: str = "llm.connection.created"
    connection: ConnectionDto
    timestamp: datetime


class LlmConnectionUpdatedEvent(BaseModel):
    type: str = "llm.connection.updated"
    connection: ConnectionDto
    timestamp: datetime


class LlmConnectionRemovedEvent(BaseModel):
    type: str = "llm.connection.removed"
    connection_id: str
    affected_persona_ids: list[str] = Field(default_factory=list)
    timestamp: datetime


class LlmConnectionTestedEvent(BaseModel):
    type: str = "llm.connection.tested"
    connection_id: str
    valid: bool
    error: str | None = None
    timestamp: datetime


class LlmConnectionStatusChangedEvent(BaseModel):
    type: str = "llm.connection.status_changed"
    connection_id: str
    status: Literal["reachable", "unreachable", "unauthorised", "disconnected"]
    timestamp: datetime


class LlmConnectionModelsRefreshedEvent(BaseModel):
    type: str = "llm.connection.models_refreshed"
    connection_id: str
    success: bool = True
    error: str | None = None
    timestamp: datetime


class ConnectionSlugRenamedEvent(BaseModel):
    type: str = "llm.connection.slug_renamed"
    connection_id: str
    old_slug: str
    new_slug: str
    timestamp: datetime


class LlmUserModelConfigUpdatedEvent(BaseModel):
    """Emitted when a user updates OR deletes their model config. Delete sends defaults."""
    type: str = "llm.user_model_config.updated"
    model_unique_id: str
    config: UserModelConfigDto
    timestamp: datetime
