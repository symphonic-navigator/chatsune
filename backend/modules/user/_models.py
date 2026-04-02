from datetime import datetime

from pydantic import BaseModel, Field


class UserDocument(BaseModel):
    """Internal MongoDB document model for users. Never expose outside the user module."""

    id: str = Field(alias="_id")
    username: str
    email: str
    display_name: str
    password_hash: str
    role: str  # "master_admin" | "admin" | "user"
    is_active: bool = True
    must_change_password: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"populate_by_name": True}


class AuditLogDocument(BaseModel):
    """Internal MongoDB document model for audit log entries."""

    id: str = Field(alias="_id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None

    model_config = {"populate_by_name": True}
