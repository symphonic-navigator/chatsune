"""Tests for embedding queue with query-first priority drain."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.embedding._queue import (
    EmbedBatchRequest,
    EmbeddingQueue,
    QueryRequest,
)


@pytest.fixture
def mock_model():
    model = MagicMock()
    model.infer.return_value = [[0.1] * 768]
    return model


@pytest.fixture
def mock_event_bus():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=None)
    return bus


async def test_query_returns_vector(mock_model):
    queue = EmbeddingQueue(model=mock_model, batch_size=8, event_bus=None)
    worker_task = asyncio.create_task(queue.run())

    try:
        vector = await asyncio.wait_for(
            queue.submit_query("hello world"),
            timeout=2.0,
        )
        assert len(vector) == 768
        assert vector == [0.1] * 768
    finally:
        await queue.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


async def test_embed_batch_is_processed(mock_model, mock_event_bus):
    mock_model.infer.return_value = [[0.1] * 768] * 3
    queue = EmbeddingQueue(model=mock_model, batch_size=8, event_bus=mock_event_bus)
    worker_task = asyncio.create_task(queue.run())

    try:
        queue.submit_embed(
            texts=["a", "b", "c"],
            reference_id="doc-1",
            correlation_id="corr-1",
        )
        # Give the worker time to process
        await asyncio.sleep(0.2)
        assert mock_model.infer.called
    finally:
        await queue.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


async def test_query_takes_priority_over_embed(mock_model, mock_event_bus):
    """Queries submitted while embeds are queued get processed first."""
    call_order: list[str] = []

    def tracking_infer(texts):
        if len(texts) == 1 and texts[0] == "query-text":
            call_order.append("query")
        else:
            call_order.append("embed")
        return [[0.1] * 768] * len(texts)

    mock_model.infer.side_effect = tracking_infer

    queue = EmbeddingQueue(model=mock_model, batch_size=8, event_bus=mock_event_bus)

    # Pre-fill embed queue BEFORE starting worker
    queue.submit_embed(
        texts=["embed-1", "embed-2"],
        reference_id="doc-1",
        correlation_id="corr-1",
    )

    # Submit a query (it should be processed before the embed)
    query_future = asyncio.ensure_future(queue.submit_query("query-text"))

    # Now start the worker — query should drain first
    worker_task = asyncio.create_task(queue.run())

    try:
        await asyncio.wait_for(query_future, timeout=2.0)
        await asyncio.sleep(0.2)  # Let embed process too

        assert call_order[0] == "query", f"Expected query first, got: {call_order}"
    finally:
        await queue.stop()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


async def test_queue_sizes_reported(mock_model):
    queue = EmbeddingQueue(model=mock_model, batch_size=8, event_bus=None)

    queue.submit_embed(
        texts=["a", "b"],
        reference_id="doc-1",
        correlation_id="corr-1",
    )

    assert queue.embed_queue_size == 1
    assert queue.query_queue_size == 0
