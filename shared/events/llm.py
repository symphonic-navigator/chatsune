from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.dtos.llm import ApiKeyDto, ConnectionDto, HomelabDto, UserModelConfigDto


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


class PremiumProviderModelsRefreshedEvent(BaseModel):
    """Emitted after a Premium Provider model-listing refresh.

    Counterpart to :class:`LlmConnectionModelsRefreshedEvent` for the
    Premium Provider path (where there is no user-owned Connection document
    and the key is the ``provider_id`` slug instead of a connection UUID).
    """
    type: str = "providers.models_refreshed"
    provider_id: str
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


class ModelPullStartedEvent(BaseModel):
    type: str = "llm.model.pull.started"
    pull_id: str
    scope: str
    slug: str
    timestamp: datetime


class ModelPullProgressEvent(BaseModel):
    type: str = "llm.model.pull.progress"
    pull_id: str
    scope: str
    status: str
    digest: str | None = None
    completed: int | None = None
    total: int | None = None
    timestamp: datetime


class ModelPullCompletedEvent(BaseModel):
    type: str = "llm.model.pull.completed"
    pull_id: str
    scope: str
    slug: str
    timestamp: datetime


class ModelPullFailedEvent(BaseModel):
    type: str = "llm.model.pull.failed"
    pull_id: str
    scope: str
    slug: str
    error_code: str
    user_message: str
    timestamp: datetime


class ModelPullCancelledEvent(BaseModel):
    type: str = "llm.model.pull.cancelled"
    pull_id: str
    scope: str
    slug: str
    timestamp: datetime


class ModelDeletedEvent(BaseModel):
    type: str = "llm.model.deleted"
    scope: str
    name: str
    timestamp: datetime


# --- Community Provisioning ---


class HomelabCreatedEvent(BaseModel):
    type: str = "llm.homelab.created"
    homelab: HomelabDto
    timestamp: datetime


class HomelabUpdatedEvent(BaseModel):
    type: str = "llm.homelab.updated"
    homelab: HomelabDto
    timestamp: datetime


class HomelabDeletedEvent(BaseModel):
    type: str = "llm.homelab.deleted"
    homelab_id: str
    timestamp: datetime


class HomelabHostKeyRegeneratedEvent(BaseModel):
    type: str = "llm.homelab.host_key_regenerated"
    homelab: HomelabDto
    timestamp: datetime


class HomelabStatusChangedEvent(BaseModel):
    type: str = "llm.homelab.status_changed"
    homelab_id: str
    is_online: bool
    timestamp: datetime


class HomelabLastSeenEvent(BaseModel):
    type: str = "llm.homelab.last_seen"
    homelab_id: str
    last_seen_at: datetime
    timestamp: datetime


class ApiKeyCreatedEvent(BaseModel):
    type: str = "llm.api_key.created"
    api_key: ApiKeyDto
    timestamp: datetime


class ApiKeyUpdatedEvent(BaseModel):
    type: str = "llm.api_key.updated"
    api_key: ApiKeyDto
    timestamp: datetime


class ApiKeyRevokedEvent(BaseModel):
    type: str = "llm.api_key.revoked"
    api_key_id: str
    homelab_id: str
    timestamp: datetime
