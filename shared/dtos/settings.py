from datetime import datetime

from pydantic import BaseModel


class AppSettingDto(BaseModel):
    key: str
    value: str
    updated_at: datetime
    updated_by: str


class SetSettingDto(BaseModel):
    value: str
