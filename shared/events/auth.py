from datetime import datetime

from pydantic import BaseModel


class UserCreatedEvent(BaseModel):
    type: str = "user.created"
    user_id: str
    username: str
    role: str
    timestamp: datetime


class UserUpdatedEvent(BaseModel):
    type: str = "user.updated"
    user_id: str
    changes: dict
    timestamp: datetime


class UserDeactivatedEvent(BaseModel):
    type: str = "user.deactivated"
    user_id: str
    timestamp: datetime


class UserPasswordResetEvent(BaseModel):
    type: str = "user.password_reset"
    user_id: str
    timestamp: datetime
