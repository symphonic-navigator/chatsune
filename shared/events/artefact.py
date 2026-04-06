"""Artefact events — published through the event bus."""

from datetime import datetime

from pydantic import BaseModel


class ArtefactCreatedEvent(BaseModel):
    """An artefact has been created in a chat session."""
    type: str = "artefact.created"
    session_id: str
    artefact_id: str
    handle: str
    title: str
    artefact_type: str
    language: str | None = None
    size_bytes: int
    correlation_id: str
    timestamp: datetime


class ArtefactUpdatedEvent(BaseModel):
    """An artefact has been updated (content or metadata changed)."""
    type: str = "artefact.updated"
    session_id: str
    handle: str
    title: str
    artefact_type: str
    size_bytes: int
    version: int
    correlation_id: str
    timestamp: datetime


class ArtefactDeletedEvent(BaseModel):
    """An artefact has been deleted."""
    type: str = "artefact.deleted"
    session_id: str
    handle: str
    correlation_id: str
    timestamp: datetime


class ArtefactUndoEvent(BaseModel):
    """An undo operation has been performed on an artefact."""
    type: str = "artefact.undo"
    session_id: str
    handle: str
    version: int
    correlation_id: str
    timestamp: datetime


class ArtefactRedoEvent(BaseModel):
    """A redo operation has been performed on an artefact."""
    type: str = "artefact.redo"
    session_id: str
    handle: str
    version: int
    correlation_id: str
    timestamp: datetime
