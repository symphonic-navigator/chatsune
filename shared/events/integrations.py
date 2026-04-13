from datetime import datetime

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
