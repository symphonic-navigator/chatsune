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


class UserProfileUpdatedEvent(BaseModel):
    type: str = "user.profile.updated"
    user_id: str
    display_name: str
    timestamp: datetime


class UserDeletedEvent(BaseModel):
    """Emitted after a user has exercised their right to be forgotten.

    The event is broadcast to admins only — the target user is already
    logged out and disconnected by the time this fires, so there is no
    point delivering it back to them.

    ``username`` is included so admin dashboards can surface a human-
    readable notification without having to query a collection that no
    longer contains the record.
    """

    type: str = "user.deleted"
    user_id: str
    username: str
    timestamp: datetime
