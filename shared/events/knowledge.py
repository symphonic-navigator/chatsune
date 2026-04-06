from datetime import datetime

from pydantic import BaseModel

from shared.dtos.knowledge import KnowledgeDocumentDto, KnowledgeLibraryDto, RetrievedChunkDto


class KnowledgeLibraryCreatedEvent(BaseModel):
    type: str = "knowledge.library.created"
    library: KnowledgeLibraryDto
    correlation_id: str
    timestamp: datetime


class KnowledgeLibraryUpdatedEvent(BaseModel):
    type: str = "knowledge.library.updated"
    library: KnowledgeLibraryDto
    correlation_id: str
    timestamp: datetime


class KnowledgeLibraryDeletedEvent(BaseModel):
    type: str = "knowledge.library.deleted"
    library_id: str
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentCreatedEvent(BaseModel):
    type: str = "knowledge.document.created"
    document: KnowledgeDocumentDto
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentUpdatedEvent(BaseModel):
    type: str = "knowledge.document.updated"
    document: KnowledgeDocumentDto
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentDeletedEvent(BaseModel):
    type: str = "knowledge.document.deleted"
    library_id: str
    document_id: str
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentEmbeddingEvent(BaseModel):
    type: str = "knowledge.document.embedding"
    document_id: str
    chunk_count: int
    retry_count: int
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentEmbeddedEvent(BaseModel):
    type: str = "knowledge.document.embedded"
    document_id: str
    chunk_count: int
    correlation_id: str
    timestamp: datetime


class KnowledgeDocumentEmbedFailedEvent(BaseModel):
    type: str = "knowledge.document.embed_failed"
    document_id: str
    error: str
    retry_count: int
    recoverable: bool
    correlation_id: str
    timestamp: datetime


class KnowledgeSearchCompletedEvent(BaseModel):
    type: str = "knowledge.search.completed"
    session_id: str
    results: list[RetrievedChunkDto]
    correlation_id: str
    timestamp: datetime
