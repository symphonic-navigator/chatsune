from datetime import datetime

from pydantic import BaseModel


class SettingUpdatedEvent(BaseModel):
    type: str = "setting.updated"
    key: str
    value: str
    updated_by: str
    timestamp: datetime


class SettingDeletedEvent(BaseModel):
    type: str = "setting.deleted"
    key: str
    deleted_by: str
    timestamp: datetime
