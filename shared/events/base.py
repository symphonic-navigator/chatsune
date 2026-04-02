from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    sequence: str = ""  # set by EventBus after XADD
    scope: str = "global"
    correlation_id: str
    timestamp: datetime
    payload: dict
