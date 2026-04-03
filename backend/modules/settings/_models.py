from datetime import datetime

from pydantic import BaseModel, Field


class AppSettingDocument(BaseModel):
    """Internal MongoDB document for app settings. Never expose outside settings module."""

    key: str = Field(alias="_id")
    value: str
    updated_at: datetime
    updated_by: str

    model_config = {"populate_by_name": True}
