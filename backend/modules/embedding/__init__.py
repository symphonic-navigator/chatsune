"""Embedding module — local ONNX vector embedding with priority queue.

Public API: import only from this file.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.embedding._model import EmbeddingModel
from backend.modules.embedding._queue import EmbeddingQueue
from backend.modules.embedding._handlers import router
from shared.dtos.embedding import EmbeddingStatusDto
from shared.events.embedding import (
    EmbeddingModelLoadingEvent,
    EmbeddingModelReadyEvent,
)
from shared.topics import Topics

_log = logging.getLogger("chatsune.embedding")

_model: EmbeddingModel | None = None
_queue: EmbeddingQueue | None = None
_worker_task: asyncio.Task | None = None


async def startup(event_bus, model_dir: str, batch_size: int) -> None:
    """Load the ONNX model and start the queue worker.

    This is blocking on the model download/load — the backend is not
    considered healthy until this completes.
    """
    global _model, _queue, _worker_task

    correlation_id = str(uuid4())

    _model = EmbeddingModel()

    # Publish loading event before potentially slow download
    await event_bus.publish(
        Topics.EMBEDDING_MODEL_LOADING,
        EmbeddingModelLoadingEvent(
            model_name=_model.model_name,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
    )

    # Load model (blocking — runs download if needed)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _model.load, model_dir)

    # Publish ready event
    await event_bus.publish(
        Topics.EMBEDDING_MODEL_READY,
        EmbeddingModelReadyEvent(
            model_name=_model.model_name,
            dimensions=_model.dimensions,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
    )

    # Start queue worker
    _queue = EmbeddingQueue(
        model=_model,
        batch_size=batch_size,
        event_bus=event_bus,
    )
    _worker_task = asyncio.create_task(_queue.run())

    _log.info("Embedding module ready")


async def shutdown() -> None:
    """Stop the queue worker gracefully."""
    global _worker_task

    if _queue:
        await _queue.stop()
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _worker_task.cancel()

    _log.info("Embedding module shut down")


async def embed_texts(
    texts: list[str],
    reference_id: str,
    correlation_id: str,
) -> None:
    """Enqueue texts for background embedding. Returns immediately."""
    if not _queue:
        raise RuntimeError("Embedding module not initialised")
    _queue.submit_embed(texts, reference_id, correlation_id)


async def query_embed(text: str) -> list[float]:
    """Embed a single text with high priority. Blocks until done."""
    if not _queue:
        raise RuntimeError("Embedding module not initialised")
    return await _queue.submit_query(text)


def get_status() -> EmbeddingStatusDto:
    """Return current module status."""
    if not _model or not _queue:
        return EmbeddingStatusDto(
            model_loaded=False,
            model_name="",
            dimensions=0,
            query_queue_size=0,
            embed_queue_size=0,
        )
    return EmbeddingStatusDto(
        model_loaded=_model.is_loaded,
        model_name=_model.model_name,
        dimensions=_model.dimensions,
        query_queue_size=_queue.query_queue_size,
        embed_queue_size=_queue.embed_queue_size,
    )


__all__ = [
    "router",
    "startup",
    "shutdown",
    "embed_texts",
    "query_embed",
    "get_status",
]
