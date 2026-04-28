"""Priority queue with query-first drain for embedding inference.

Two queues feed a single async worker. The worker always drains the query
queue before processing embed batches. Between each batch chunk, it re-checks
the query queue to ensure queries never wait longer than one inference call.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from shared.events.embedding import (
    EmbeddingBatchCompletedEvent,
    EmbeddingErrorEvent,
)
from shared.topics import Topics

_log = logging.getLogger("chatsune.embedding.queue")


@dataclass
class QueryRequest:
    text: str
    # Future is created by submit_query() once an event loop is guaranteed to be running.
    future: asyncio.Future | None = field(default=None)


@dataclass
class EmbedBatchRequest:
    texts: list[str]
    reference_id: str
    correlation_id: str
    # The owning user. Carried through to the completion/error events so
    # consumers can scope their reference_id lookup by owner instead of
    # trusting the reference_id alone.
    user_id: str | None = None


class EmbeddingQueue:
    """Two-queue embedding worker with query-first priority."""

    def __init__(self, model, batch_size: int, event_bus) -> None:
        self._model = model
        self._batch_size = batch_size
        self._event_bus = event_bus
        self._query_queue: asyncio.Queue[QueryRequest | None] = asyncio.Queue()
        self._embed_queue: asyncio.Queue[EmbedBatchRequest | None] = asyncio.Queue()
        self._running = False

    @property
    def query_queue_size(self) -> int:
        return self._query_queue.qsize()

    @property
    def embed_queue_size(self) -> int:
        return self._embed_queue.qsize()

    async def submit_query(self, text: str) -> list[float]:
        """Submit a query for high-priority embedding. Awaits the result."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request = QueryRequest(text=text, future=future)
        await self._query_queue.put(request)
        return await future

    def submit_embed(
        self,
        texts: list[str],
        reference_id: str,
        correlation_id: str,
        user_id: str | None = None,
    ) -> None:
        """Submit texts for background embedding. Returns immediately."""
        request = EmbedBatchRequest(
            texts=texts,
            reference_id=reference_id,
            correlation_id=correlation_id,
            user_id=user_id,
        )
        self._embed_queue.put_nowait(request)

    async def run(self) -> None:
        """Main worker loop. Call as an asyncio task."""
        self._running = True
        _log.info("Embedding worker started (batch_size=%d)", self._batch_size)

        while self._running:
            # 1. Drain all pending queries first
            await self._drain_queries()

            # 2. Try to get an embed batch (non-blocking)
            try:
                embed_req = self._embed_queue.get_nowait()
            except asyncio.QueueEmpty:
                embed_req = None

            if embed_req is None:
                pass  # nothing to do here, fall through to wait
            elif isinstance(embed_req, EmbedBatchRequest):
                await self._process_embed(embed_req)
                continue
            else:  # sentinel (None placed via stop) — actually unreachable since None handled above
                break

            # 3. Both queues empty — wait for either
            query_wait = asyncio.ensure_future(self._query_queue.get())
            embed_wait = asyncio.ensure_future(self._embed_queue.get())

            done, pending = await asyncio.wait(
                [query_wait, embed_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            for task in done:
                result = task.result()
                if result is None:  # sentinel
                    self._running = False
                    break
                if isinstance(result, QueryRequest):
                    await self._process_query(result)
                elif isinstance(result, EmbedBatchRequest):
                    # But first check if queries arrived while we waited
                    await self._drain_queries()
                    await self._process_embed(result)

    async def stop(self) -> None:
        """Signal the worker to stop after current work completes."""
        self._running = False
        await self._query_queue.put(None)

    async def _drain_queries(self) -> None:
        """Process all currently queued query requests."""
        while not self._query_queue.empty():
            try:
                request = self._query_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if request is None:  # sentinel
                self._running = False
                return
            await self._process_query(request)

    async def _process_query(self, request: QueryRequest) -> None:
        """Run inference for a single query and resolve its future."""
        try:
            vectors = await asyncio.get_running_loop().run_in_executor(
                None, self._model.infer, [request.text],
            )
            request.future.set_result(vectors[0])
        except Exception as exc:
            _log.exception("Query embedding failed")
            if not request.future.done():
                request.future.set_exception(exc)

    async def _process_embed(self, request: EmbedBatchRequest) -> None:
        """Process a bulk embed request in chunks, checking for queries between each."""
        all_vectors: list[list[float]] = []
        texts = request.texts

        for i in range(0, len(texts), self._batch_size):
            # Check for queries before each chunk
            await self._drain_queries()
            if not self._running:
                return

            chunk = texts[i : i + self._batch_size]
            try:
                vectors = await asyncio.get_running_loop().run_in_executor(
                    None, self._model.infer, chunk,
                )
                all_vectors.extend(vectors)
                _log.debug(
                    "Embedded chunk %d-%d/%d for ref=%s",
                    i, i + len(chunk), len(texts), request.reference_id,
                )
            except Exception as exc:
                _log.exception(
                    "Embed batch failed for ref=%s chunk=%d",
                    request.reference_id, i,
                )
                if self._event_bus:
                    await self._event_bus.publish(
                        Topics.EMBEDDING_ERROR,
                        EmbeddingErrorEvent(
                            reference_id=request.reference_id,
                            error=str(exc),
                            recoverable=True,
                            correlation_id=request.correlation_id,
                            timestamp=datetime.now(timezone.utc),
                            user_id=request.user_id,
                        ),
                    )
                return

        # All chunks done — publish completion event
        if self._event_bus:
            await self._event_bus.publish(
                Topics.EMBEDDING_BATCH_COMPLETED,
                EmbeddingBatchCompletedEvent(
                    reference_id=request.reference_id,
                    count=len(all_vectors),
                    vectors=all_vectors,
                    correlation_id=request.correlation_id,
                    timestamp=datetime.now(timezone.utc),
                    user_id=request.user_id,
                ),
            )

        _log.info(
            "Embed batch complete: ref=%s count=%d",
            request.reference_id, len(all_vectors),
        )
