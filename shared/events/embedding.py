"""Embedding events — published through the event bus."""

from datetime import datetime

from pydantic import BaseModel


class EmbeddingModelLoadingEvent(BaseModel):
    """Model download or loading has started."""
    type: str = "embedding.model.loading"
    model_name: str
    correlation_id: str
    timestamp: datetime


class EmbeddingModelReadyEvent(BaseModel):
    """Model is loaded and ready for inference."""
    type: str = "embedding.model.ready"
    model_name: str
    dimensions: int
    correlation_id: str
    timestamp: datetime


class EmbeddingBatchCompletedEvent(BaseModel):
    """A bulk embedding batch has finished successfully."""
    type: str = "embedding.batch.completed"
    reference_id: str
    count: int
    vectors: list[list[float]]
    correlation_id: str
    timestamp: datetime


class EmbeddingErrorEvent(BaseModel):
    """Embedding inference failed."""
    type: str = "embedding.error"
    reference_id: str | None
    error: str
    recoverable: bool
    correlation_id: str
    timestamp: datetime
