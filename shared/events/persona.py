from datetime import datetime

from pydantic import BaseModel

from shared.dtos.persona import PersonaDto


class PersonaCreatedEvent(BaseModel):
    type: str = "persona.created"
    persona_id: str
    user_id: str
    persona: PersonaDto
    timestamp: datetime


class PersonaUpdatedEvent(BaseModel):
    type: str = "persona.updated"
    persona_id: str
    user_id: str
    persona: PersonaDto
    timestamp: datetime


class PersonaDeletedEvent(BaseModel):
    type: str = "persona.deleted"
    persona_id: str
    user_id: str
    timestamp: datetime


class PersonaReorderedEvent(BaseModel):
    type: str = "persona.reordered"
    user_id: str
    ordered_ids: list[str]
    timestamp: datetime
