from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class IntegrationConfigUpdatedEvent(BaseModel):
    type: str = "integration.config.updated"
    integration_id: str
    enabled: bool
    correlation_id: str
    timestamp: datetime


class IntegrationActionExecutedEvent(BaseModel):
    """Emitted when a response tag triggers an integration action."""
    type: str = "integration.action.executed"
    integration_id: str
    action: str
    success: bool
    display_text: str
    correlation_id: str
    timestamp: datetime


class IntegrationEmergencyStopEvent(BaseModel):
    type: str = "integration.emergency_stop"
    integration_id: str | None = None
    correlation_id: str
    timestamp: datetime


class IntegrationSecretsHydratedEvent(BaseModel):
    type: Literal["integration.secrets.hydrated"] = "integration.secrets.hydrated"
    integration_id: str
    secrets: dict[str, str]
    correlation_id: str
    timestamp: datetime


class IntegrationSecretsClearedEvent(BaseModel):
    type: Literal["integration.secrets.cleared"] = "integration.secrets.cleared"
    integration_id: str
    correlation_id: str
    timestamp: datetime


class IntegrationInlineTriggerEvent(BaseModel):
    """Frontend-emitted event signalling an inline integration tag fired.

    The foundation only emits this on the front-end event bus; the topic
    and DTO live in shared/ so a future backend audit-emit path is a
    non-breaking addition.
    """
    type: Literal["integration.inline.trigger"] = "integration.inline.trigger"
    integration_id: str
    command: str
    args: list[str]
    payload: Any
    source: Literal["live_stream", "text_only", "read_aloud"]
    correlation_id: str
    timestamp: datetime
