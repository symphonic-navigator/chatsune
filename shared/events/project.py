"""Event models for the project module."""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.project import ProjectDto


class ProjectCreatedEvent(BaseModel):
    type: str = "project.created"
    project_id: str
    user_id: str
    project: ProjectDto
    timestamp: datetime


class ProjectUpdatedEvent(BaseModel):
    type: str = "project.updated"
    project_id: str
    user_id: str
    project: ProjectDto
    timestamp: datetime


class ProjectDeletedEvent(BaseModel):
    type: str = "project.deleted"
    project_id: str
    user_id: str
    timestamp: datetime
