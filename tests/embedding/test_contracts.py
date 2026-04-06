"""Tests for embedding shared contracts."""

from datetime import datetime, timezone

from shared.dtos.embedding import EmbeddingStatusDto, EmbedRequestDto
from shared.events.embedding import (
    EmbeddingBatchCompletedEvent,
    EmbeddingErrorEvent,
    EmbeddingModelLoadingEvent,
    EmbeddingModelReadyEvent,
)
from shared.topics import Topics


def test_embedding_status_dto():
    dto = EmbeddingStatusDto(
        model_loaded=True,
        model_name="snowflake-arctic-embed-m-v2.0",
        dimensions=768,
        query_queue_size=0,
        embed_queue_size=5,
    )
    assert dto.model_loaded is True
    assert dto.dimensions == 768
    assert dto.query_queue_size == 0
    assert dto.embed_queue_size == 5


def test_embed_request_dto():
    dto = EmbedRequestDto(
        texts=["hello", "world"],
        reference_id="doc-123",
        correlation_id="corr-abc",
    )
    assert len(dto.texts) == 2
    assert dto.reference_id == "doc-123"


def test_model_loading_event():
    evt = EmbeddingModelLoadingEvent(
        model_name="snowflake-arctic-embed-m-v2.0",
        correlation_id="startup-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert evt.type == "embedding.model.loading"
    assert evt.model_name == "snowflake-arctic-embed-m-v2.0"


def test_model_ready_event():
    evt = EmbeddingModelReadyEvent(
        model_name="snowflake-arctic-embed-m-v2.0",
        dimensions=768,
        correlation_id="startup-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert evt.type == "embedding.model.ready"
    assert evt.dimensions == 768


def test_batch_completed_event():
    evt = EmbeddingBatchCompletedEvent(
        reference_id="doc-123",
        count=8,
        vectors=[[0.1] * 768],
        correlation_id="batch-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert evt.type == "embedding.batch.completed"
    assert evt.count == 8
    assert len(evt.vectors) == 1


def test_error_event():
    evt = EmbeddingErrorEvent(
        reference_id="doc-456",
        error="ONNX inference failed",
        recoverable=True,
        correlation_id="batch-2",
        timestamp=datetime.now(timezone.utc),
    )
    assert evt.type == "embedding.error"
    assert evt.recoverable is True
    assert evt.reference_id == "doc-456"


def test_topics_constants():
    assert Topics.EMBEDDING_MODEL_LOADING == "embedding.model.loading"
    assert Topics.EMBEDDING_MODEL_READY == "embedding.model.ready"
    assert Topics.EMBEDDING_BATCH_COMPLETED == "embedding.batch.completed"
    assert Topics.EMBEDDING_ERROR == "embedding.error"
