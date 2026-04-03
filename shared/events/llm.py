from datetime import datetime

from pydantic import BaseModel


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
