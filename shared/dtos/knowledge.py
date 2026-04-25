from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RefreshFrequency = Literal["rarely", "standard", "often"]


class KnowledgeLibraryDto(BaseModel):
    id: str
    name: str
    description: str | None = None
    nsfw: bool = False
    document_count: int = 0
    created_at: datetime
    updated_at: datetime
    default_refresh: RefreshFrequency = "standard"


class KnowledgeDocumentDto(BaseModel):
    id: str
    library_id: str
    title: str
    media_type: Literal["text/markdown", "text/plain"]
    size_bytes: int
    chunk_count: int = 0
    embedding_status: Literal["pending", "processing", "completed", "failed"]
    embedding_error: str | None = None
    created_at: datetime
    updated_at: datetime
    trigger_phrases: list[str] = Field(default_factory=list)
    refresh: RefreshFrequency | None = None  # None = inherit from library


class KnowledgeDocumentDetailDto(KnowledgeDocumentDto):
    content: str


class CreateLibraryRequest(BaseModel):
    name: str
    description: str | None = None
    nsfw: bool = False


class UpdateLibraryRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    nsfw: bool | None = None


class CreateDocumentRequest(BaseModel):
    title: str
    content: str
    media_type: Literal["text/markdown", "text/plain"] = "text/markdown"


class UpdateDocumentRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    media_type: Literal["text/markdown", "text/plain"] | None = None


class RetrievedChunkDto(BaseModel):
    library_name: str
    document_title: str
    heading_path: list[str]
    preroll_text: str
    content: str
    score: float


class SetKnowledgeLibrariesRequest(BaseModel):
    library_ids: list[str]
