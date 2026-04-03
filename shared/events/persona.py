from datetime import datetime

from pydantic import BaseModel


class PersonaCreatedEvent(BaseModel):
    type: str = "persona.created"
    persona_id: str
    user_id: str
    name: str
    timestamp: datetime


class PersonaUpdatedEvent(BaseModel):
    type: str = "persona.updated"
    persona_id: str
    user_id: str
    timestamp: datetime


class PersonaDeletedEvent(BaseModel):
    type: str = "persona.deleted"
    persona_id: str
    user_id: str
    timestamp: datetime
