# Embedding Subsystem — Design Spec

**Date:** 2026-04-06
**Status:** Approved
**Scope:** Low-level embedding infrastructure only — no Knowledge Base, no RAG query integration

---

## Overview

A self-contained embedding module (`backend/modules/embedding/`) that provides local vector
embedding via Snowflake Arctic Embed M v2.0 (ONNX, CPU-only). The module serialises all
inference through a priority queue system where query requests (single text → vector) always
take precedence over bulk embedding requests (background document processing).

This module is the foundation layer. Higher-level consumers (Knowledge Base, semantic search,
memory retrieval) will call its public API but are not part of this spec.

---

## Model

| Property       | Value                                          |
|----------------|------------------------------------------------|
| Model          | Snowflake Arctic Embed M v2.0                  |
| HuggingFace ID | `Snowflake/snowflake-arctic-embed-m-v2.0`      |
| Parameters     | ~305M                                          |
| Dimensions     | 768                                            |
| Max Tokens     | 8192                                           |
| Languages      | 100+                                           |
| Licence        | Apache 2.0                                     |
| Runtime        | ONNX Runtime (CPU Provider, Sequential Mode)   |
| Pooling        | Mean pooling over attention mask, L2 normalised |

---

## Module Structure

```
backend/modules/embedding/
    __init__.py       ← Public API: embed_texts(), query_embed(), get_status()
    _model.py         ← ONNX model loading, inference, HuggingFace download
    _queue.py         ← Two queues + single worker with query-first drain
    _handlers.py      ← FastAPI endpoints (health/status)
```

All internal files are `_`-prefixed. No other module may import anything except the
public API from `__init__.py`.

---

## Public API

```python
async def embed_texts(
    texts: list[str],
    reference_id: str,
    correlation_id: str,
) -> None
```

Enqueues texts for background embedding. Returns immediately. Results are delivered
as `EMBEDDING_BATCH_COMPLETED` events. Errors are delivered as `EMBEDDING_ERROR` events.
Both carry the `reference_id` and `correlation_id` for precise identification.

```python
async def query_embed(text: str) -> list[float]
```

Embeds a single text with high priority. Blocks (awaits) until the vector is ready.
Returns a 768-dimensional L2-normalised vector. This path always takes precedence over
bulk embedding in the queue.

```python
async def get_status() -> EmbeddingStatusDto
```

Returns current module status: model loaded, model name, dimensions, queue sizes.

---

## Model Management (`_model.py`)

### Startup Sequence (Blocking)

1. Read `EMBEDDING_MODEL_DIR` from environment (default: `./data/models`)
2. Check if `snowflake-arctic-embed-m-v2.0/` with ONNX files exists at that path
3. If missing:
   - Publish `EMBEDDING_MODEL_LOADING` event
   - Download via `huggingface_hub`
   - Log progress every ~10% of download
4. Create ONNX `InferenceSession` (CPU Execution Provider, Sequential Mode)
5. Load tokenizer via `transformers.AutoTokenizer`
6. Publish `EMBEDDING_MODEL_READY` event
7. Health check reports "ready"

The backend process is not considered healthy until step 7 completes.

### Inference

```python
def infer(texts: list[str]) -> list[list[float]]
```

- Tokenises input via AutoTokenizer
- Runs ONNX inference
- Applies mean pooling over attention mask
- L2-normalises all output vectors
- Returns list of 768-dim float vectors

This function is called exclusively by the worker in `_queue.py` — never directly
by external code.

---

## Queue + Worker (`_queue.py`)

### Two Queues

- `_query_queue: asyncio.Queue[QueryRequest]` — single texts, high priority
- `_embed_queue: asyncio.Queue[EmbedBatchRequest]` — bulk texts, low priority

### Request Types

**QueryRequest:**
- `text: str` — the text to embed
- `future: asyncio.Future[list[float]]` — resolved by the worker after inference

The caller of `query_embed()` creates the Future and awaits it. The worker resolves
it with the resulting vector.

**EmbedBatchRequest:**
- `texts: list[str]` — texts to embed
- `reference_id: str` — identifies what is being embedded (e.g. document ID)
- `correlation_id: str` — groups related events

No Future — results are published as events.

### Worker Loop (Single asyncio.Task)

```
while True:
    1. Drain _query_queue completely (process all waiting queries)
    2. If _embed_queue is not empty:
       a. Take one EmbedBatchRequest
       b. Split texts into chunks of EMBEDDING_BATCH_SIZE
       c. For each chunk:
          - Run inference
          - Check _query_queue — if not empty, drain it before continuing
       d. Publish EMBEDDING_BATCH_COMPLETED event
    3. If both queues empty:
       await asyncio.wait() on both queues (sleep until work arrives)
```

**Key property:** After every single inference call during bulk processing, the worker
checks the query queue. This means a query request waits at most for one inference call
(one batch of up to `EMBEDDING_BATCH_SIZE` texts), not for an entire bulk job.

### Lifecycle

- Worker starts as `asyncio.Task` after model is ready
- Graceful shutdown via sentinel value (`None`), in-progress batch completes before exit

### Error Handling

- If inference fails for a query: the Future is resolved with an exception
- If inference fails for a bulk batch: `EMBEDDING_ERROR` event published with
  `reference_id`, `correlation_id`, error description, and `recoverable: bool`

---

## Shared Contracts

### Events (`shared/events/embedding.py`)

All events extend `BaseEvent` (with `id`, `type`, `sequence`, `scope`,
`correlation_id`, `timestamp`, `payload`).

```python
class EmbeddingModelLoadingEvent(BaseEvent):
    """Model download/load has started."""
    # payload:
    #   model_name: str

class EmbeddingModelReadyEvent(BaseEvent):
    """Model is loaded and ready for inference."""
    # payload:
    #   model_name: str
    #   dimensions: int

class EmbeddingBatchCompletedEvent(BaseEvent):
    """A bulk embedding batch has finished successfully."""
    # payload:
    #   reference_id: str
    #   count: int  (number of texts embedded)
    #   vectors: list[list[float]]  (the resulting embeddings, in input order)

class EmbeddingErrorEvent(BaseEvent):
    """Embedding inference failed."""
    # payload:
    #   reference_id: str | None
    #   error: str
    #   recoverable: bool
```

### DTOs (`shared/dtos/embedding.py`)

```python
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

### Topics (`shared/topics.py` — new entries)

```python
EMBEDDING_MODEL_LOADING = "embedding.model.loading"
EMBEDDING_MODEL_READY = "embedding.model.ready"
EMBEDDING_BATCH_COMPLETED = "embedding.batch.completed"
EMBEDDING_ERROR = "embedding.error"
```

---

## Configuration

### Environment Variables

| Variable              | Default          | Description                              |
|-----------------------|------------------|------------------------------------------|
| `EMBEDDING_MODEL_DIR` | `./data/models`  | Path to model weights directory          |
| `EMBEDDING_BATCH_SIZE`| `8`              | Number of texts per inference call       |

### Docker Compose

```yaml
backend:
  volumes:
    - ${EMBEDDING_MODEL_DIR:-./data/models}:/app/data/models
```

### .gitignore

```
data/models/
```

---

## Dependencies

New Python packages required:

- `onnxruntime` — ONNX inference runtime (CPU)
- `transformers` — tokenizer loading (AutoTokenizer)
- `huggingface_hub` — model download with progress callbacks

These are added via `uv add`.

---

## What This Spec Does NOT Cover

These are explicitly out of scope and will be separate specs:

- Knowledge Base (document ingestion, chunking, storage)
- Semantic search / RAG query integration
- MongoDB Vector Search index creation and querying
- Frontend UI for embedding status
- Remote embedding providers (Ollama Cloud, etc.)
- REST API endpoints beyond health/status
