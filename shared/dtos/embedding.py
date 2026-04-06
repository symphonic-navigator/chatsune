"""Embedding module DTOs."""

from pydantic import BaseModel


class EmbeddingStatusDto(BaseModel):
    model_loaded: bool
    model_name: str
    dimensions: int
    query_queue_size: int
    embed_queue_size: int


class EmbedRequestDto(BaseModel):
    texts: list[str]
    reference_id: str
    correlation_id: str
