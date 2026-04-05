from datetime import datetime

from pydantic import BaseModel

from shared.dtos.storage import StorageFileDto


class StorageFileUploadedEvent(BaseModel):
    type: str = "storage.file.uploaded"
    file: StorageFileDto
    correlation_id: str
    timestamp: datetime


class StorageFileDeletedEvent(BaseModel):
    type: str = "storage.file.deleted"
    file_id: str
    correlation_id: str
    timestamp: datetime


class StorageFileRenamedEvent(BaseModel):
    type: str = "storage.file.renamed"
    file_id: str
    display_name: str
    correlation_id: str
    timestamp: datetime


class StorageQuotaWarningEvent(BaseModel):
    type: str = "storage.quota.warning"
    used_bytes: int
    limit_bytes: int
    percentage: float
    correlation_id: str
    timestamp: datetime
