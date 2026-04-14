from datetime import datetime

from pydantic import BaseModel


class WebSearchCredentialSetEvent(BaseModel):
    type: str = "websearch.credential.set"
    provider_id: str
    timestamp: datetime


class WebSearchCredentialRemovedEvent(BaseModel):
    type: str = "websearch.credential.removed"
    provider_id: str
    timestamp: datetime


class WebSearchCredentialTestedEvent(BaseModel):
    type: str = "websearch.credential.tested"
    provider_id: str
    valid: bool
    error: str | None = None
    timestamp: datetime
