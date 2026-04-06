# Embedding Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained embedding module that provides local vector embedding via Snowflake Arctic Embed M v2.0 (ONNX, CPU-only) with a priority queue system where queries always take precedence over bulk embedding.

**Architecture:** New module at `backend/modules/embedding/` following existing module patterns. ONNX model loaded at startup (blocking, with auto-download). Two asyncio queues feed a single worker that drains query requests before processing embed batches. All state changes emit events through the existing event bus.

**Tech Stack:** onnxruntime, transformers (tokenizer only), huggingface_hub, numpy

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `shared/dtos/embedding.py` | EmbeddingStatusDto, EmbedRequestDto |
| Create | `shared/events/embedding.py` | Model lifecycle + batch + error events |
| Modify | `shared/topics.py` | Add EMBEDDING_* constants |
| Create | `backend/modules/embedding/__init__.py` | Public API: embed_texts(), query_embed(), get_status(), startup() |
| Create | `backend/modules/embedding/_model.py` | ONNX model download, loading, inference |
| Create | `backend/modules/embedding/_queue.py` | Two queues, single worker, query-first drain |
| Create | `backend/modules/embedding/_handlers.py` | FastAPI router with /api/embedding/status endpoint |
| Modify | `backend/main.py` | Register embedding module, call startup in lifespan |
| Modify | `docker-compose.yml` | Add model volume mount |
| Modify | `.env.example` | Add EMBEDDING_MODEL_DIR, EMBEDDING_BATCH_SIZE |
| Modify | `.gitignore` | Add data/models/ |
| Modify | `pyproject.toml` | Add onnxruntime, transformers, huggingface_hub, numpy |
| Create | `tests/embedding/__init__.py` | Test package |
| Create | `tests/embedding/test_model.py` | Tests for model inference |
| Create | `tests/embedding/test_queue.py` | Tests for queue priority behaviour |
| Create | `tests/embedding/test_contracts.py` | Tests for DTOs and events |

---

### Task 1: Shared Contracts — Topics, DTOs, Events

**Files:**
- Modify: `shared/topics.py:73` (append after last line)
- Create: `shared/dtos/embedding.py`
- Create: `shared/events/embedding.py`
- Create: `tests/embedding/__init__.py`
- Create: `tests/embedding/test_contracts.py`

- [ ] **Step 1: Write failing tests for DTOs and events**

Create `tests/embedding/__init__.py` (empty file) and `tests/embedding/test_contracts.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/embedding/test_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add Topics constants**

Append to `shared/topics.py` at line 73 (after `MEMORY_BODY_ROLLBACK`):

```python
    # Embedding
    EMBEDDING_MODEL_LOADING = "embedding.model.loading"
    EMBEDDING_MODEL_READY = "embedding.model.ready"
    EMBEDDING_BATCH_COMPLETED = "embedding.batch.completed"
    EMBEDDING_ERROR = "embedding.error"
```

- [ ] **Step 4: Create DTOs**

Create `shared/dtos/embedding.py`:

```python
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
```

- [ ] **Step 5: Create Events**

Create `shared/events/embedding.py`:

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/embedding/test_contracts.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add shared/topics.py shared/dtos/embedding.py shared/events/embedding.py tests/embedding/
git commit -m "Add embedding shared contracts — topics, DTOs, events"
```

---

### Task 2: Model Manager — Download and ONNX Inference

**Files:**
- Create: `backend/modules/embedding/_model.py`
- Create: `tests/embedding/test_model.py`
- Modify: `pyproject.toml` (add dependencies)

- [ ] **Step 1: Add Python dependencies**

Run: `cd /home/chris/workspace/chatsune && uv add onnxruntime transformers huggingface-hub numpy`

This adds to `pyproject.toml` and updates `uv.lock`.

- [ ] **Step 2: Write failing tests for model manager**

Create `tests/embedding/test_model.py`:

```python
"""Tests for embedding model manager.

These tests use a tiny mock to avoid downloading the real 600MB model.
They verify the inference pipeline (tokenise → run → pool → normalise)
works correctly when an ONNX session is available.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.modules.embedding._model import EmbeddingModel


@pytest.fixture
def mock_session():
    """Create a mock ONNX session that returns fake hidden states."""
    session = MagicMock()
    # Simulate ONNX output: (batch_size, seq_len, hidden_dim=768)
    def mock_run(output_names, input_feed):
        batch_size = input_feed["input_ids"].shape[0]
        seq_len = input_feed["input_ids"].shape[1]
        hidden = np.random.randn(batch_size, seq_len, 768).astype(np.float32)
        return [hidden]
    session.run = mock_run
    return session


@pytest.fixture
def mock_tokenizer():
    """Create a mock tokenizer that returns numpy arrays."""
    tokenizer = MagicMock()
    def mock_call(texts, padding, truncation, max_length, return_tensors):
        batch_size = len(texts)
        seq_len = 16  # fixed for testing
        return {
            "input_ids": np.ones((batch_size, seq_len), dtype=np.int64),
            "attention_mask": np.ones((batch_size, seq_len), dtype=np.int64),
        }
    tokenizer.side_effect = mock_call
    tokenizer.return_value = mock_call(["test"], True, True, 8192, "np")
    tokenizer.__call__ = mock_call
    return tokenizer


def test_infer_returns_correct_shape(mock_session, mock_tokenizer):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._session = mock_session
    model._tokenizer = mock_tokenizer
    model._dimensions = 768

    vectors = model.infer(["hello", "world"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 768
    assert len(vectors[1]) == 768


def test_infer_vectors_are_l2_normalised(mock_session, mock_tokenizer):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._session = mock_session
    model._tokenizer = mock_tokenizer
    model._dimensions = 768

    vectors = model.infer(["test sentence"])

    vec = np.array(vectors[0])
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"


def test_infer_single_text(mock_session, mock_tokenizer):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model._session = mock_session
    model._tokenizer = mock_tokenizer
    model._dimensions = 768

    vectors = model.infer(["single"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 768
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/embedding/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError` (module not yet created)

- [ ] **Step 4: Implement model manager**

Create `backend/modules/embedding/_model.py`:

```python
"""ONNX embedding model — download, load, and inference.

Manages the full lifecycle of the Snowflake Arctic Embed M v2.0 model:
download from HuggingFace if missing, load ONNX session, tokenise,
infer, mean-pool, and L2-normalise.
"""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import snapshot_download
from transformers import AutoTokenizer

_log = logging.getLogger("chatsune.embedding.model")

_HF_REPO_ID = "Snowflake/snowflake-arctic-embed-m-v2.0"
_MODEL_SUBDIR = "snowflake-arctic-embed-m-v2.0"
_DIMENSIONS = 768
_MAX_TOKENS = 8192


class EmbeddingModel:
    """Manages ONNX model loading and inference."""

    def __init__(self) -> None:
        self._session: ort.InferenceSession | None = None
        self._tokenizer = None
        self._dimensions: int = _DIMENSIONS

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    @property
    def model_name(self) -> str:
        return _MODEL_SUBDIR

    def load(self, model_dir: str) -> None:
        """Download (if needed) and load the ONNX model. Blocking."""
        model_path = Path(model_dir) / _MODEL_SUBDIR

        if not (model_path / "onnx" / "model.onnx").exists():
            _log.info("Model not found at %s — downloading from HuggingFace", model_path)
            self._download(model_dir)
        else:
            _log.info("Model found at %s", model_path)

        onnx_path = str(model_path / "onnx" / "model.onnx")
        _log.info("Loading ONNX session from %s", onnx_path)

        sess_opts = ort.SessionOptions()
        sess_opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        sess_opts.inter_op_num_threads = 2
        sess_opts.intra_op_num_threads = 2

        self._session = ort.InferenceSession(
            onnx_path,
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )

        self._tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        _log.info("Model loaded — dimensions=%d, max_tokens=%d", _DIMENSIONS, _MAX_TOKENS)

    def _download(self, model_dir: str) -> None:
        """Download model from HuggingFace with per-file progress logging."""
        from huggingface_hub import HfApi, hf_hub_download

        target = Path(model_dir) / _MODEL_SUBDIR
        target.mkdir(parents=True, exist_ok=True)

        api = HfApi()
        repo_info = api.repo_info(repo_id=_HF_REPO_ID)
        siblings = repo_info.siblings or []
        files = [s.rfilename for s in siblings]
        total_size = sum(s.size for s in siblings if s.size)

        _log.info(
            "Downloading %s (%d files, %.1f MB) to %s",
            _HF_REPO_ID, len(files), total_size / (1024 * 1024), target,
        )

        downloaded_size = 0
        last_logged_pct = 0

        for sibling in siblings:
            hf_hub_download(
                repo_id=_HF_REPO_ID,
                filename=sibling.rfilename,
                local_dir=str(target),
                local_dir_use_symlinks=False,
            )
            if sibling.size:
                downloaded_size += sibling.size
            if total_size > 0:
                pct = int(downloaded_size / total_size * 100)
                if pct >= last_logged_pct + 10:
                    last_logged_pct = pct - (pct % 10)
                    _log.info("Download progress: %d%%", last_logged_pct)

        _log.info("Download complete")

    def infer(self, texts: list[str]) -> list[list[float]]:
        """Tokenise, run ONNX inference, mean-pool, L2-normalise.

        Returns a list of 768-dimensional unit vectors.
        """
        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=_MAX_TOKENS,
            return_tensors="np",
        )

        input_ids = encoded["input_ids"]
        attention_mask = encoded["attention_mask"]

        outputs = self._session.run(
            ["last_hidden_state"],
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )

        hidden_states = outputs[0]  # (batch, seq_len, hidden_dim)

        # Mean pooling: average hidden states weighted by attention mask
        mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        sum_hidden = np.sum(hidden_states * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        pooled = sum_hidden / sum_mask  # (batch, hidden_dim)

        # L2 normalisation
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        normalised = pooled / norms

        return normalised.tolist()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/embedding/test_model.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock backend/modules/embedding/_model.py tests/embedding/test_model.py
git commit -m "Add embedding model manager with ONNX inference"
```

---

### Task 3: Priority Queue and Worker

**Files:**
- Create: `backend/modules/embedding/_queue.py`
- Create: `tests/embedding/test_queue.py`

- [ ] **Step 1: Write failing tests for queue priority behaviour**

Create `tests/embedding/test_queue.py`:

```python
"""Tests for embedding queue with query-first priority drain."""

import asyncio
from unittest.mock import MagicMock

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
    bus.publish = MagicMock(return_value=asyncio.coroutine(lambda *a, **kw: None)())
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
    original_infer = mock_model.infer

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/embedding/test_queue.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement queue and worker**

Create `backend/modules/embedding/_queue.py`:

```python
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
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


@dataclass
class EmbedBatchRequest:
    texts: list[str]
    reference_id: str
    correlation_id: str


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
    ) -> None:
        """Submit texts for background embedding. Returns immediately."""
        request = EmbedBatchRequest(
            texts=texts,
            reference_id=reference_id,
            correlation_id=correlation_id,
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

            if embed_req is not None:
                if embed_req is None:  # sentinel
                    break
                await self._process_embed(embed_req)
                continue

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
                ),
            )

        _log.info(
            "Embed batch complete: ref=%s count=%d",
            request.reference_id, len(all_vectors),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/embedding/test_queue.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/embedding/_queue.py tests/embedding/test_queue.py
git commit -m "Add embedding priority queue with query-first drain"
```

---

### Task 4: Module Public API and Handlers

**Files:**
- Create: `backend/modules/embedding/__init__.py`
- Create: `backend/modules/embedding/_handlers.py`

- [ ] **Step 1: Create module public API**

Create `backend/modules/embedding/__init__.py`:

```python
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
```

- [ ] **Step 2: Create handlers**

Create `backend/modules/embedding/_handlers.py`:

```python
"""Embedding module HTTP endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/embedding")


@router.get("/status")
async def embedding_status():
    from backend.modules.embedding import get_status
    return get_status()
```

- [ ] **Step 3: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/embedding/__init__.py && uv run python -m py_compile backend/modules/embedding/_handlers.py`
Expected: No output (clean compilation)

- [ ] **Step 4: Commit**

```bash
git add backend/modules/embedding/__init__.py backend/modules/embedding/_handlers.py
git commit -m "Add embedding module public API and status endpoint"
```

---

### Task 5: Integration into Main App

**Files:**
- Modify: `backend/main.py:10-17` (add import), `backend/main.py:36-43` (add startup), `backend/main.py:276-297` (add shutdown), `backend/main.py:300-309` (add router)
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Add import to main.py**

Add after line 17 (`from backend.modules.memory import ...`):

```python
from backend.modules.embedding import router as embedding_router, startup as embedding_startup, shutdown as embedding_shutdown
```

- [ ] **Step 2: Add startup call in lifespan**

Add after `await memory_init_indexes(db)` (line 36) and after `set_event_bus(event_bus)` (line 40), so the event bus is available:

```python
    # Load embedding model and start worker (blocking on first download)
    import os
    embedding_model_dir = os.environ.get("EMBEDDING_MODEL_DIR", "./data/models")
    embedding_batch_size = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))
    await embedding_startup(event_bus, embedding_model_dir, embedding_batch_size)
```

- [ ] **Step 3: Add shutdown call**

Add before `await disconnect_db()` (line 297):

```python
    await embedding_shutdown()
```

- [ ] **Step 4: Add router**

Add after `app.include_router(memory_router)` (line 308):

```python
app.include_router(embedding_router)
```

- [ ] **Step 5: Update docker-compose.yml**

Add volume mount to the backend service. Since there is no backend service in docker-compose.yml yet (it only has mongodb and redis), add the mount path as a comment or note for when the backend service is added:

Add to `.env.example` after the avatar line:

```
# Embedding model weights — downloaded on first start if missing
EMBEDDING_MODEL_DIR=./data/models
EMBEDDING_BATCH_SIZE=8
```

- [ ] **Step 6: Update .gitignore**

Add to `.gitignore`:

```
data/models/
```

- [ ] **Step 7: Verify syntax**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/main.py`
Expected: No output (clean compilation)

- [ ] **Step 8: Commit**

```bash
git add backend/main.py .env.example .gitignore
git commit -m "Integrate embedding module into app startup and routing"
```

---

### Task 6: Frontend Build Verification

**Files:** None (verification only)

- [ ] **Step 1: Run backend syntax check on all new files**

```bash
cd /home/chris/workspace/chatsune
uv run python -m py_compile backend/modules/embedding/__init__.py
uv run python -m py_compile backend/modules/embedding/_model.py
uv run python -m py_compile backend/modules/embedding/_queue.py
uv run python -m py_compile backend/modules/embedding/_handlers.py
uv run python -m py_compile shared/dtos/embedding.py
uv run python -m py_compile shared/events/embedding.py
```

Expected: No output for each (all clean)

- [ ] **Step 2: Run all embedding tests**

```bash
cd /home/chris/workspace/chatsune
uv run pytest tests/embedding/ -v
```

Expected: All tests PASS

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
cd /home/chris/workspace/chatsune
uv run pytest tests/ -v
```

Expected: All existing tests still PASS

- [ ] **Step 4: Run frontend build**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: Clean build (no TypeScript errors). The embedding module has no frontend changes, so this is a regression check.

- [ ] **Step 5: Final commit if any fixes were needed**

Only if previous steps required fixes:

```bash
git add -A
git commit -m "Fix issues found during embedding module verification"
```
