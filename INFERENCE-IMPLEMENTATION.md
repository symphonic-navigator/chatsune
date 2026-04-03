# Inference Implementation Proposal

**Date:** 2026-04-03
**Status:** Draft
**Scope:** Complete inference pipeline -- streaming, tool calls, context management, embeddings

This document proposes the implementation of the inference pipeline for Chatsune (Prototype 3).
It incorporates lessons from Prototype 2's debriefing and adapts the architecture to Chatsune's
WebSocket-first, event-driven model.

---

## Design Principles

1. **Everything over WebSocket.** No SSE endpoint. Token deltas, tool calls, tool results,
   and stream lifecycle events all flow through the existing per-user WebSocket connection.
2. **Server owns the context.** The frontend never sees the system prompt, context selection
   logic, or raw LLM payload. It sees events.
3. **Tool calls are first-class events.** Both server-side (auto-executed) and client-side
   (round-trip to frontend) tool calls are modelled as events with correlation IDs.
4. **Adapter pattern carries forward.** The existing `BaseAdapter` is extended with streaming
   inference. Provider differences are fully absorbed by adapters.
5. **MongoDB Vector Search replaces Qdrant.** Chatsune already requires a single-node RS0
   for transactions -- Vector Search comes for free.

---

## 1. Extending the Adapter Interface

### Current State

`BaseAdapter` has two methods: `validate_key` and `fetch_models`. Inference is not yet wired.

### Proposed Extension

```python
# backend/modules/llm/_adapters/_base.py

class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool: ...

    @abstractmethod
    async def fetch_models(self) -> list[ModelMetaDto]: ...

    @abstractmethod
    async def stream_completion(
        self,
        api_key: str,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream inference events from the upstream provider.

        Yields ProviderStreamEvent variants (ContentDelta, ThinkingDelta,
        ToolCall, Done, Error). The caller consumes the iterator and
        translates events to Chatsune's event envelope.
        """
        ...
```

### Internal Models (`shared/dtos/inference.py`)

```python
class ContentPart(BaseModel):
    type: Literal["text", "image"]
    text: str | None = None
    data: str | None = None           # base64 for images
    media_type: str | None = None     # e.g. "image/png"

class CompletionMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]
    tool_calls: list[ToolCallResult] | None = None
    tool_call_id: str | None = None   # for role="tool" messages

class ToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    name: str
    description: str
    parameters: dict                  # JSON Schema object

class CompletionRequest(BaseModel):
    model: str                        # provider-specific slug (e.g. "qwen3:32b")
    messages: list[CompletionMessage]
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None
    reasoning_enabled: bool = False
```

### Provider Stream Events (`backend/modules/llm/_adapters/_events.py`)

```python
class ContentDelta(BaseModel):
    delta: str

class ThinkingDelta(BaseModel):
    delta: str

class ToolCallEvent(BaseModel):
    id: str                           # synthetic ID (adapters generate these)
    name: str
    arguments: str                    # JSON string

class StreamDone(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None

class StreamError(BaseModel):
    error_code: str                   # "invalid_api_key", "provider_unavailable", "model_not_found"
    message: str

ProviderStreamEvent = ContentDelta | ThinkingDelta | ToolCallEvent | StreamDone | StreamError
```

---

## 2. Ollama Cloud Adapter -- Streaming

### Request Translation (Chatsune -> Ollama)

The Ollama adapter translates `CompletionRequest` to Ollama's `/api/chat` format:

| Chatsune | Ollama |
|---|---|
| `CompletionMessage.content` (list of parts) | `content` (joined text) + `images` (base64 array) |
| `CompletionMessage.tool_calls` | `tool_calls` (with `function.name` + `function.arguments` as object) |
| `CompletionMessage.tool_call_id` | Dropped (Ollama uses positional matching) |
| `CompletionRequest.reasoning_enabled` | `think: true` |
| `CompletionRequest.tools` | `tools` (JSON Schema passthrough) |

### Response Translation (Ollama -> Chatsune)

Ollama streams NDJSON. Each line is parsed into `ProviderStreamEvent`:

| Ollama Chunk Field | ProviderStreamEvent |
|---|---|
| `message.content` (non-empty) | `ContentDelta` |
| `message.thinking` (non-empty) | `ThinkingDelta` |
| `message.tool_calls[*]` | `ToolCallEvent` (one per call, synthetic ID: `call_{uuid4}`) |
| `done: true` | `StreamDone` (with `prompt_eval_count` + `eval_count`) |
| Stream EOF without `done` | `StreamDone` (without usage -- safety fallback) |
| HTTP 401/403 | `StreamError(error_code="invalid_api_key")` |
| HTTP 502 (after retries) | `StreamError(error_code="provider_unavailable")` |

### Retry Logic

- **Only on HTTP 502** (reverse proxy issues with Ollama)
- Max 3 attempts, 1.5s delay between retries
- Only retries the initial connection (first chunk)
- Once streaming: no retries (partial responses cannot be safely retried)
- A per-request `CancellationToken` (caller-provided) governs overall timeout

### Key Learnings from Prototype 2

1. **Tool call arguments: Ollama sends complete objects, not streamed fragments.** The adapter
   yields one `ToolCallEvent` per tool call per chunk. No argument accumulation needed. Other
   providers (OpenAI) stream arguments incrementally -- their adapters will need accumulation
   logic. This is an adapter-level concern, not a Chatsune-level one.

2. **Content + tool calls can arrive in the same chunk.** The adapter must yield both.

3. **Thinking + content in the same chunk.** Also must yield both.

4. **No `num_ctx` passthrough.** Prototype 2 didn't tell Ollama the context budget, risking
   silent overflow. **Fix:** Pass `options.num_ctx` matching the context window from
   `ModelMetaDto.context_window`. This ensures Ollama and Chatsune agree on the budget.

---

## 3. WebSocket Inference Protocol

All inference events flow through the existing WebSocket connection. The frontend sends
a `chat.send` message; the backend streams events back on the same connection.

### Client -> Server Messages

```jsonc
// Start a new inference request
{
    "type": "chat.send",
    "session_id": "...",
    "content": [
        {"type": "text", "text": "Hello!"},
        {"type": "image", "data": "<base64>", "media_type": "image/png"}
    ],
    "client_tools": [                    // optional: tools the frontend can execute
        {
            "type": "function",
            "name": "show_notification",
            "description": "Show a notification to the user",
            "parameters": { ... }
        }
    ]
}

// Submit tool results (client-side tool calls)
{
    "type": "chat.tool_result",
    "session_id": "...",
    "correlation_id": "...",
    "results": [
        {
            "tool_call_id": "call_abc",
            "output": "{\"status\": \"shown\"}"
        }
    ]
}

// Cancel an in-progress stream
{
    "type": "chat.cancel",
    "session_id": "...",
    "correlation_id": "..."
}
```

### Server -> Client Events

All events share a `correlation_id` that ties them to the originating `chat.send`.
The `scope` field is `session:<session_id>`.

```jsonc
// Stream lifecycle
{"type": "chat.stream.started",      "correlation_id": "...", "scope": "session:..."}
{"type": "chat.stream.ended",        "correlation_id": "...", "scope": "session:...",
    "status": "completed",           // "completed" | "cancelled" | "error"
    "usage": {"input_tokens": 150, "output_tokens": 42},
    "context_status": "green"        // ampel: green/yellow/orange/red
}

// Content deltas (streamed tokens)
{"type": "chat.content.delta",       "correlation_id": "...", "scope": "session:...",
    "delta": "Hello"}
{"type": "chat.thinking.delta",      "correlation_id": "...", "scope": "session:...",
    "delta": "Let me think about this..."}

// Tool calls
{"type": "chat.tool_call",           "correlation_id": "...", "scope": "session:...",
    "tool_call_id": "call_abc",
    "tool_name": "web_search",
    "arguments": "{\"query\": \"...\"}",
    "execution": "server"            // "server" | "client"
}

// Server-side tool results (informational -- the frontend displays these but doesn't act on them)
{"type": "chat.tool_result",         "correlation_id": "...", "scope": "session:...",
    "tool_call_id": "call_abc",
    "tool_name": "web_search",
    "output_preview": "Found 3 results for...",    // truncated for display
    "iteration": 2                                  // which tool loop iteration
}

// Client-side tool call -- requires action from the frontend
{"type": "chat.tool_call.pending",   "correlation_id": "...", "scope": "session:...",
    "tool_call_id": "call_xyz",
    "tool_name": "show_notification",
    "arguments": "{...}"
    // The stream pauses here. The frontend must respond with chat.tool_result.
}

// Error during inference (not a global error -- scoped to this stream)
{"type": "chat.stream.error",        "correlation_id": "...", "scope": "session:...",
    "error_code": "invalid_api_key",
    "recoverable": false,
    "user_message": "Your API key for Ollama Cloud is invalid. Please update it in settings."
}
```

### Event Flow -- Happy Path

```
Client                          Server
  |                                |
  |-- chat.send ------------------>|
  |                                |-- assemble context
  |                                |-- stream from adapter
  |<--- chat.stream.started -------|
  |<--- chat.thinking.delta -------|  (optional, if reasoning_enabled)
  |<--- chat.thinking.delta -------|
  |<--- chat.content.delta --------|
  |<--- chat.content.delta --------|
  |<--- chat.stream.ended ---------|
  |                                |-- persist messages to MongoDB
```

### Event Flow -- Server-Side Tool Loop

```
Client                          Server
  |                                |
  |-- chat.send ------------------>|
  |<--- chat.stream.started -------|
  |<--- chat.content.delta --------|  (partial content before tool call)
  |<--- chat.tool_call ------------|  execution: "server"
  |                                |-- execute tool internally
  |<--- chat.tool_result ----------|  output_preview for display
  |                                |-- re-invoke LLM with tool result (iteration 2)
  |<--- chat.content.delta --------|
  |<--- chat.stream.ended ---------|
```

### Event Flow -- Client-Side Tool Call

```
Client                          Server
  |                                |
  |-- chat.send ------------------>|
  |<--- chat.stream.started -------|
  |<--- chat.tool_call.pending ----|  execution: "client"
  |                                |-- persist messages, set session state = RequiresAction
  |                                |-- stream paused, waiting for client
  |                                |
  |-- chat.tool_result ----------->|
  |                                |-- re-invoke LLM with tool result
  |<--- chat.content.delta --------|
  |<--- chat.stream.ended ---------|
```

### Event Flow -- Cancellation

```
Client                          Server
  |                                |
  |-- chat.send ------------------>|
  |<--- chat.stream.started -------|
  |<--- chat.content.delta --------|
  |-- chat.cancel ----------------->|
  |                                |-- cancel CancellationToken
  |<--- chat.stream.ended ---------|  status: "cancelled"
  |                                |-- persist partial content
```

---

## 4. Chat Module Architecture

The chat module (`backend/modules/chat/`) orchestrates inference. It does not call
adapters directly -- it goes through the LLM module's public API.

### Files

```
backend/modules/chat/
    __init__.py               # Public API: ChatService, router
    _handlers.py              # WebSocket message handlers (chat.send, chat.tool_result, chat.cancel)
    _repository.py            # MongoDB: chat_sessions, chat_messages
    _context.py               # System prompt assembly + context window selection
    _tool_registry.py         # Server-side tool definitions + executors
    _models.py                # Internal document models
```

### LLM Module Extension

The LLM module's public API gains a new method:

```python
# backend/modules/llm/__init__.py (addition)

async def stream_completion(
    user_id: str,
    provider_id: str,
    request: CompletionRequest,
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve user's API key, instantiate adapter, stream completion.

    Raises:
        LlmCredentialNotFoundError: user has no key for this provider.
        LlmProviderNotFoundError: provider_id not in registry.
    """
```

This is the **only** way the chat module interacts with inference. It never imports adapters,
never reads credentials, never handles HTTP.

### Chat Service Flow

```python
class ChatService:
    async def handle_send(self, user_id: str, message: ChatSendMessage) -> None:
        """Handle a chat.send WebSocket message."""

        # 1. Load session, persona, model metadata
        session = await self._repo.get_session(message.session_id)
        persona = await persona_service.get_persona(session.persona_id)
        model = await self._resolve_model(session.model_unique_id)

        # 2. Persist the user message
        user_msg = await self._repo.save_message(...)

        # 3. Assemble context (system prompt + selected history + new message)
        context = await self._context.build(
            session=session,
            persona=persona,
            model=model,
            user_id=user_id,
            new_message=user_msg,
        )

        # 4. Build tool definitions
        tools = self._tool_registry.get_tools(session, model, message.client_tools)

        # 5. Build CompletionRequest
        request = CompletionRequest(
            model=model.model_id,
            messages=context.messages,
            temperature=persona.temperature,
            tools=tools or None,
            reasoning_enabled=persona.reasoning_enabled and model.supports_reasoning,
        )

        # 6. Emit chat.stream.started
        await self._emit(user_id, ChatStreamStartedEvent(...))

        # 7. Tool loop (max 5 iterations)
        await self._run_inference_loop(user_id, session, request, context)

    async def _run_inference_loop(self, user_id, session, request, context):
        for iteration in range(5):
            full_content = ""
            full_thinking = ""
            tool_calls = []

            async for event in llm.stream_completion(
                user_id=user_id,
                provider_id=session.provider_id,
                request=request,
            ):
                match event:
                    case ContentDelta(delta=d):
                        full_content += d
                        await self._emit(user_id, ChatContentDeltaEvent(...))

                    case ThinkingDelta(delta=d):
                        full_thinking += d
                        await self._emit(user_id, ChatThinkingDeltaEvent(...))

                    case ToolCallEvent() as tc:
                        tool_calls.append(tc)
                        # Determine server vs client
                        execution = self._tool_registry.classify(tc.name)
                        await self._emit(user_id, ChatToolCallEvent(
                            ..., execution=execution))

                    case StreamDone() as done:
                        # usage stats collected
                        pass

                    case StreamError() as err:
                        await self._emit(user_id, ChatStreamErrorEvent(...))
                        return

            # Process tool calls
            client_tools = [tc for tc in tool_calls
                            if self._tool_registry.classify(tc.name) == "client"]
            server_tools = [tc for tc in tool_calls
                            if self._tool_registry.classify(tc.name) == "server"]

            if client_tools:
                # Persist state, emit pending events, pause
                await self._handle_client_tool_calls(user_id, session, client_tools, ...)
                return  # Stream resumes when client sends chat.tool_result

            if server_tools:
                # Execute server tools, append results, continue loop
                results = await self._execute_server_tools(server_tools)
                request = self._extend_request(request, full_content, tool_calls, results)
                for result in results:
                    await self._emit(user_id, ChatToolResultEvent(...))
                continue

            # No tool calls -- done
            break

        # Persist assistant message + emit stream.ended
        await self._finalise(user_id, session, full_content, full_thinking, context)
```

---

## 5. Context Management

### System Prompt Assembly

Carried over from Prototype 2 with improvements. Three-layer hierarchy
(already documented in INS-007):

```
<systeminstructions priority="highest">
  [Admin global system prompt -- from Settings "global_system_prompt"]
</systeminstructions>

<modelinstructions priority="high">
  [Per-user, per-model system prompt addition -- from UserModelConfig]
</modelinstructions>

<you priority="normal">
  [Persona system prompt -- from session override OR persona default]
</you>

<userinfo priority="low">
  [User's "About Me" field]
</userinfo>

<usermemory priority="low">
  [Assembled memory content -- consolidated + recent conversation blocks]
</usermemory>
```

**Sanitisation:** All user-controlled parts are stripped of reserved XML tags
(`<systeminstructions>`, `<modelinstructions>`, `<you>`, `<userinfo>`, `<usermemory>`).
The admin system prompt is not sanitised (trusted content).

**Preview vs Actual:** The frontend can request a preview (human-readable, excludes
admin prompt) via REST. The actual prompt uses XML tags with priority attributes.

### Context Window Selection

Algorithm from Prototype 2, with fixes:

```
available_for_chat = model.context_window
                   - safety_reserve (16.5%)
                   - system_prompt_tokens
                   - response_reserve (1000 tokens)
```

1. Load all persisted messages from MongoDB for this session
2. Group into `ChatPair` objects (user message + assistant reply)
3. Iterate **newest-first** (backread), adding pairs while they fit
4. Reverse to chronological order
5. Compute ampel status based on fill percentage

**Fixes from Prototype 2:**

- **No double-counting of new user message tokens.** The new message is counted once as
  actual content, not also in the reserve. The reserve is a fixed 1000 tokens for the
  model's response.
- **Tool exchange messages ARE included in pairs.** When a tool call occurred in a previous
  turn, the assistant's tool-call message and tool result messages are part of the pair.
  This preserves tool context across turns.

### Token Counting

- **Primary:** `tiktoken` with `cl100k_base` encoder
- **Rationale:** Pessimistic (over-counts for most models) but safe. Over-counting wastes
  a small amount of context; under-counting risks overflow.
- **Cached:** Token count is stored on `ChatMessage.token_count` at creation time.
  Never recomputed.

### Ampel Thresholds

| Status | Fill % | Meaning |
|--------|--------|---------|
| Green | 0--50% | Plenty of space |
| Yellow | 50--75% | User can compress |
| Orange | 75--95% | User should compress |
| Red | >95% | Rolling window active, oldest messages being dropped |

The ampel status is emitted on every `chat.stream.ended` event so the frontend
can display it. It is also persisted on the session for quick access without recomputation.

---

## 6. Tool System

### Two Categories

| | Server-Side Tools | Client-Side Tools |
|---|---|---|
| **Defined by** | Backend (`_tool_registry.py`) | Frontend (`chat.send.client_tools`) |
| **Executed by** | Backend (automatic) | Frontend (user interaction) |
| **Max iterations** | 5 rounds of server tool calls | 1 pending round (stream pauses) |
| **Result flow** | Backend appends to messages, re-invokes LLM | Frontend sends `chat.tool_result`, backend resumes |
| **Visible to user** | `chat.tool_call` + `chat.tool_result` events | `chat.tool_call.pending` event |

### Server-Side Tools (Phase 1)

| Tool | Description | When Available |
|---|---|---|
| `knowledge_search` | Search user's knowledge base via vector similarity | If session has active knowledge items AND model.supports_tool_calls |

**Phase 2+ (not implemented now, but the architecture supports them):**

| Tool | Description |
|---|---|
| `create_artefact` | Create a code/text artefact in the session |
| `update_artefact` | Modify an existing artefact |
| `read_artefact` | Read an artefact's content |
| `web_search` | Search the web (via SearXNG or similar) |
| `web_fetch` | Fetch and extract content from a URL |

### Client-Side Tools

The frontend can supply arbitrary tool definitions in `chat.send.client_tools`.
These are appended to the tool list sent to the LLM. When the LLM calls one,
the stream pauses and the frontend is responsible for executing it and returning
the result via `chat.tool_result`.

**Use cases:**

- **UI interactions:** "Show a notification", "Open a modal", "Navigate to a page"
- **Local computation:** "Calculate a hash", "Format a date"
- **User confirmation:** "Ask the user to confirm before proceeding"

The backend does not know or care what client-side tools do. It only:
1. Passes their definitions to the LLM
2. Emits `chat.tool_call.pending` when the LLM invokes one
3. Waits for `chat.tool_result` from the frontend
4. Appends the result to the message history and resumes inference

### Tool Loop Mechanics

```
Iteration limit: 5 (server-side only)

For each iteration:
    1. Stream from provider
    2. Collect: content, thinking, tool calls
    3. Classify tool calls as server or client

    If any client-side tool calls:
        -> Emit chat.tool_call.pending for each
        -> Persist messages (assistant + pending tool calls)
        -> Set session.state = "requires_action"
        -> STOP (wait for chat.tool_result from frontend)

    If only server-side tool calls:
        -> Execute each tool
        -> Append assistant message (with tool_calls) to history
        -> Append tool result messages to history
        -> Emit chat.tool_result for each (informational)
        -> CONTINUE (re-invoke LLM)

    If no tool calls:
        -> BREAK (done)
```

**Why client-side tools take priority:** If the LLM returns both server and client tool
calls in one response, the client-side call blocks everything. This is correct --
the LLM expects all tool results before continuing. Executing server-side tools while
waiting for the client would desynchronise the message history.

### Message Format for Tool Loop Re-invocation

When server-side tools are executed and the LLM needs to be re-invoked:

```
[...original messages...]
assistant: {content: "...", tool_calls: [{id, name, arguments}, ...]}
tool: {content: "result JSON", tool_call_id: "call_xxx"}  // one per tool
```

The adapter translates these to the provider's format. For Ollama, tool_call_id is
dropped (positional matching). For future OpenAI-compatible providers, it is preserved.

---

## 7. Embedding System

### Architecture Change: MongoDB Vector Search

Prototype 2 used Qdrant. Chatsune already requires MongoDB with RS0 (for transactions).
MongoDB 7.0+ with Atlas Search / Vector Search provides native vector indexing within
the same database. This eliminates an external dependency.

### Embedding Model: `intfloat/multilingual-e5-small`

Replacing `distiluse-base-multilingual-cased-v2` (Prototype 2). Rationale from debriefing:

| | distiluse (old) | **multilingual-e5-small** (new) |
|---|---|---|
| Max Tokens | **128** | **512** |
| Dimensions | 512 | 384 |
| ONNX Size (int8) | ~130 MB | ~113 MB |
| Languages | 50+ | 100+ |
| Quality (MIRACL) | Weak | ~64.4 avg |
| Licence | Apache 2.0 | MIT |

**Critical fix:** The token counter mismatch bug from Prototype 2 is resolved by this
model's 512-token limit. The document chunker targets 512 `cl100k_base` tokens, which
maps conservatively to the model's 512 BERT token limit. No more silent truncation.

### Query/Passage Prefixes

`multilingual-e5-small` requires prefixes:
- **Indexing:** `"passage: " + chunk_text`
- **Retrieval:** `"query: " + search_query`

These are applied in the embedding provider, not in the chunker or retrieval service.

### Document Chunking

Algorithm from Prototype 2 with improvements:

1. **Heading-split:** Markdown headings as section boundaries, heading stack for hierarchy
2. **Oversized-section-split:** Paragraph -> sentence -> word boundaries (fallback chain)
3. **Small-chunk-merge:** Chunks under 64 tokens merged with same-heading neighbours
4. **Preroll:** Heading path as context prefix for mid-section splits

**Improvements:**

- **10% overlap between chunks.** The last ~50 tokens of each chunk are prepended to the
  next chunk (within the same section). This improves retrieval at chunk boundaries.
- **Token counter alignment.** The chunker uses `cl100k_base` (pessimistic but safe).
  With the new model's 512-token limit, 512 `cl100k_base` tokens always fit within
  the BERT tokeniser's budget.

### MongoDB Vector Search Index

```javascript
// Created on the chat module's embedding collection
db.knowledge_chunks.createSearchIndex({
    name: "vector_index",
    type: "vectorSearch",
    definition: {
        fields: [
            {
                type: "vector",
                path: "embedding",
                numDimensions: 384,
                similarity: "cosine"
            },
            {
                type: "filter",
                path: "user_id"
            },
            {
                type: "filter",
                path: "document_id"
            }
        ]
    }
})
```

### Chunk Document Schema

```python
class KnowledgeChunkDocument(BaseModel):
    id: str = Field(alias="_id")       # uuid
    user_id: str
    knowledge_base_id: str
    document_id: str
    chunk_index: int
    heading_path: list[str]            # ["# Chapter 1", "## Section A"]
    preroll_text: str                  # "# Chapter 1 > ## Section A"
    chunk_text: str
    token_count: int
    embedding: list[float]             # 384-dimensional vector
    created_at: datetime
```

### Bulk Embedding Pipeline

Same pattern as Prototype 2 (background worker + queue), adapted for Python:

```
User uploads document
    |
    v
PersonaService.add_knowledge_document()
    |
    v
Emit knowledge.document.created event
    |
    v  (background task via asyncio)
EmbeddingWorker.process(document_id)
    |
    +---> DocumentChunker.chunk(content)
    +---> For each batch of 16 chunks:
    |       OnnxEmbeddingProvider.embed_batch(texts)
    |       MongoDB bulk insert (knowledge_chunks)
    |       Emit knowledge.embedding.progress event
    |       200ms throttle delay
    +---> Emit knowledge.embedding.completed event
```

### Retrieval at Chat Time

When the LLM calls `knowledge_search`:

```python
async def execute_knowledge_search(query: str, user_id: str, session: ChatSession) -> dict:
    # 1. Resolve active document IDs (persona pinned + session ad-hoc)
    doc_ids = resolve_active_documents(session)

    # 2. Embed the query
    query_vector = await embedding_provider.embed(f"query: {query}")

    # 3. MongoDB Vector Search aggregation
    results = await db.knowledge_chunks.aggregate([
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 50,
                "limit": 5,
                "filter": {
                    "$and": [
                        {"user_id": user_id},
                        {"document_id": {"$in": doc_ids}}
                    ]
                }
            }
        },
        {
            "$project": {
                "heading_path": 1,
                "preroll_text": 1,
                "chunk_text": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]).to_list()

    # 4. Return as tool result
    return {
        "results": [
            {
                "heading": r["preroll_text"],
                "content": r["chunk_text"][:8000],
                "score": r["score"]
            }
            for r in results
        ]
    }
```

---

## 8. WebSocket Router Extension

The existing `ws/router.py` handles `ping`. It needs to dispatch inference messages
to the chat module.

### Proposed Extension

```python
# backend/ws/router.py (extended message dispatch)

while True:
    data = await ws.receive_json()
    msg_type = data.get("type")

    match msg_type:
        case "ping":
            await ws.send_json({"type": "pong"})

        case "chat.send":
            # Validate, then hand off to ChatService
            asyncio.create_task(
                chat_service.handle_send(user_id, ChatSendMessage(**data))
            )

        case "chat.tool_result":
            asyncio.create_task(
                chat_service.handle_tool_result(user_id, ChatToolResultMessage(**data))
            )

        case "chat.cancel":
            chat_service.handle_cancel(user_id, data["correlation_id"])
```

**Why `asyncio.create_task`:** The inference loop is long-running. It must not block
the WebSocket receive loop -- the client needs to be able to send `chat.cancel` or
`chat.tool_result` while a stream is in progress.

### Cancellation

`ChatService` maintains a `dict[str, asyncio.Event]` keyed by `correlation_id`.
When `chat.cancel` arrives, the corresponding event is set, which signals the
inference loop to stop consuming the adapter stream.

---

## 9. Shared Contracts

### New DTOs (`shared/dtos/inference.py`)

Already outlined in section 1: `ContentPart`, `CompletionMessage`, `ToolDefinition`,
`CompletionRequest`.

### New Events (`shared/events/chat.py`)

```python
class ChatStreamStartedEvent(BaseModel):
    type: str = "chat.stream.started"
    session_id: str
    correlation_id: str
    timestamp: datetime

class ChatContentDeltaEvent(BaseModel):
    type: str = "chat.content.delta"
    correlation_id: str
    delta: str

class ChatThinkingDeltaEvent(BaseModel):
    type: str = "chat.thinking.delta"
    correlation_id: str
    delta: str

class ChatToolCallEvent(BaseModel):
    type: str = "chat.tool_call"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    arguments: str
    execution: Literal["server", "client"]

class ChatToolCallPendingEvent(BaseModel):
    type: str = "chat.tool_call.pending"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    arguments: str

class ChatToolResultEvent(BaseModel):
    type: str = "chat.tool_result"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    output_preview: str
    iteration: int

class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    status: Literal["completed", "cancelled", "error"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    timestamp: datetime

class ChatStreamErrorEvent(BaseModel):
    type: str = "chat.stream.error"
    correlation_id: str
    error_code: str
    recoverable: bool
    user_message: str
    timestamp: datetime
```

### New Topics (`shared/topics.py`)

```python
# Chat inference
CHAT_STREAM_STARTED = "chat.stream.started"
CHAT_CONTENT_DELTA = "chat.content.delta"
CHAT_THINKING_DELTA = "chat.thinking.delta"
CHAT_TOOL_CALL = "chat.tool_call"
CHAT_TOOL_CALL_PENDING = "chat.tool_call.pending"
CHAT_TOOL_RESULT = "chat.tool_result"
CHAT_STREAM_ENDED = "chat.stream.ended"
CHAT_STREAM_ERROR = "chat.stream.error"

# Knowledge / Embedding
KNOWLEDGE_DOCUMENT_CREATED = "knowledge.document.created"
KNOWLEDGE_EMBEDDING_PROGRESS = "knowledge.embedding.progress"
KNOWLEDGE_EMBEDDING_COMPLETED = "knowledge.embedding.completed"
KNOWLEDGE_EMBEDDING_FAILED = "knowledge.embedding.failed"
```

---

## 10. Event Persistence and Catchup

### Which Events Go to Redis Streams?

Not all inference events should be persisted in Redis Streams. Token deltas are
high-frequency and ephemeral -- they are useful only during the active stream.
On reconnect, the frontend should re-fetch the session's message history, not replay
hundreds of delta events.

| Event | Redis Stream | Rationale |
|---|---|---|
| `chat.stream.started` | Yes | Client needs to know a stream is/was in progress |
| `chat.content.delta` | **No** | Ephemeral; message is persisted in MongoDB after stream |
| `chat.thinking.delta` | **No** | Ephemeral; thinking is persisted on the message |
| `chat.tool_call` | Yes | Client may need to display tool call history |
| `chat.tool_call.pending` | Yes | Client needs to re-show the pending tool call on reconnect |
| `chat.tool_result` | Yes | Client may need to display tool results |
| `chat.stream.ended` | Yes | Client needs final status |
| `chat.stream.error` | Yes | Client needs to show the error |

### Reconnect Strategy for Active Streams

If a client disconnects and reconnects while a stream is in progress:

1. Redis catchup replays `chat.stream.started` (so the client knows a stream is active)
2. The client fetches the session's current state via REST (`GET /api/chat/sessions/{id}`)
3. If the session state is `streaming`, the client knows to expect more events
4. Delta events resume on the live WebSocket connection from wherever the stream is

The client is responsible for fetching the partial content accumulated so far (it is
persisted periodically during streaming, or at minimum when the stream completes).

---

## 11. MongoDB Collections (Chat Module)

| Collection | Document | Owned By |
|---|---|---|
| `chat_sessions` | Session metadata, state, model, persona reference | Chat |
| `chat_messages` | Individual messages (user, assistant, tool) | Chat |
| `knowledge_chunks` | Embedded document chunks with vectors | Chat (via Persona) |
| `knowledge_documents` | Document metadata, content, embedding status | Persona |
| `knowledge_bases` | Container for documents, per persona | Persona |

---

## 12. Implementation Phases

### Phase 1: Minimal Inference Loop

1. Extend `BaseAdapter` with `stream_completion`
2. Implement Ollama Cloud streaming in `OllamaCloudAdapter`
3. Add `CompletionRequest` and `ProviderStreamEvent` models
4. Build `ChatService` with basic streaming (no tools)
5. Extend WebSocket router for `chat.send` and `chat.cancel`
6. Add shared events and topics
7. Persist messages to MongoDB
8. Frontend: display streaming tokens in real-time

**Validates:** End-to-end inference over WebSocket.

### Phase 2: Context Management

1. System prompt assembly (three-layer hierarchy)
2. Context window selection (backread pairs, ampel)
3. Token counting with tiktoken
4. Session message history persistence
5. Frontend: ampel status display

**Validates:** Multi-turn conversation with context limits.

### Phase 3: Server-Side Tool Loop

1. Tool registry with `knowledge_search`
2. Tool loop (max 5 iterations)
3. Tool call / tool result events
4. Frontend: display tool calls and results inline

**Validates:** Autonomous tool use.

### Phase 4: Client-Side Tool Calls

1. `chat.send.client_tools` support
2. `chat.tool_call.pending` and `chat.tool_result` round-trip
3. Session state management (`requires_action`)
4. Frontend: tool call UI (execute + submit result)

**Validates:** Frontend-executed tools.

### Phase 5: Embedding System

1. ONNX embedding provider with `multilingual-e5-small`
2. Document chunker (heading-split + overlap)
3. Bulk embedding worker (background task)
4. MongoDB Vector Search index
5. `knowledge_search` tool executor
6. Frontend: document upload + embedding progress

**Validates:** RAG pipeline end-to-end.

---

## 13. Key Differences from Prototype 2

| Aspect | Prototype 2 | Chatsune (Prototype 3) |
|---|---|---|
| Delivery | SSE (HTTP streaming) | WebSocket (bidirectional) |
| Language | C# / .NET | Python / FastAPI |
| Vector DB | Qdrant (external) | MongoDB Vector Search (built-in) |
| Embedding model | distiluse (128 tokens, 512 dim) | multilingual-e5-small (512 tokens, 384 dim) |
| Tool call round-trip | Separate REST endpoint for tool results | WebSocket message (`chat.tool_result`) |
| Context rebuild | SSE endpoint per request | Per `chat.send` message, same WS |
| Cancellation | Client disconnects SSE | Explicit `chat.cancel` message |
| Client-side tools | Partially implemented | First-class with pause/resume protocol |
| Token counting | cl100k_base for everything | cl100k_base (pessimistic, safe) |
| num_ctx | Not sent to Ollama | Sent to Ollama (prevents silent overflow) |
| Chunk overlap | None | 10% overlap |
| Session state machine | Implicit | Explicit (`idle`, `streaming`, `requires_action`) |

---

## 14. Resolved Design Decisions

### 14.1 Thinking Tokens -- Persist for Display, Never Re-inject

**Decision:** Thinking tokens (chain-of-thought / extended reasoning) are persisted on
the `ChatMessage` document for frontend display (collapsible thinking blocks) but are
**never** sent back to the LLM in subsequent turns.

**Rationale:** The LLM's output is what matters for conversation continuity -- how it
arrived at that output is irrelevant for the next step. Models prefer to reason freshly
each turn rather than reuse previous CoT traces. Re-injecting thinking tokens would
waste context budget on content the model ignores anyway.

**Implementation:**
- `ChatMessage.thinking: str | None` -- persisted alongside `content`
- `chat.thinking.delta` events streamed to frontend during inference
- `ContextBuilder` reads only `message.content` when assembling history -- `thinking` is skipped
- Frontend displays thinking blocks as collapsible UI elements

### 14.2 Attachments -- Permanent Storage with Per-User Quota

**Decision:** Attachments (images, files) are stored permanently in MongoDB (GridFS).
No expiry. Each user has a configurable storage quota (default: 1 GB). When the quota
is reached, the user must delete old attachments before uploading new ones.

**Rationale:** Prototype 2's blob expiry was problematic -- vision context silently
degraded as blobs expired, and expired attachments could not be re-referenced in
follow-up turns. For a self-hosted platform, disk is cheap. Permanent storage is
simpler and preserves full conversation fidelity.

**Implementation:**
- GridFS collection: `user_attachments` (files) + `user_attachments.chunks`
- Metadata per file: `user_id`, `session_id`, `message_id`, `media_type`, `size_bytes`, `created_at`
- Per-user storage tracking: sum of `size_bytes` across all user attachments
- Upload rejected with `413 + user_message` when quota would be exceeded
- Global admin setting: `attachment_quota_bytes` (default: `1073741824` = 1 GB)
- Frontend: storage usage indicator + "free up space" prompt when nearing quota

### 14.3 Concurrent Streams -- One at a Time, Serialised Per User

**Decision:** One active inference stream per user at a time. If a user has multiple
sessions, only one can stream at any given moment. Additional `chat.send` messages
are queued and processed sequentially.

**Rationale:** Ollama Cloud has per-user rate limits. Parallel streams from the same
user would compete for the same API key quota with no user benefit -- you can only
read one response at a time. Serialisation is simple and predictable.

**Implementation:**
- `ChatService` maintains an `asyncio.Lock` per `user_id`
- The lock covers **active streaming only**, not `requires_action` state
- `handle_send` acquires the lock before starting inference
- When a client-side tool call pauses the stream (`requires_action`), the lock is
  **released**. The user can interact with other sessions while the paused session
  waits for a tool result.
- When `chat.tool_result` arrives and the stream resumes, the lock is re-acquired.
  If another stream is active at that moment, the tool result resumption waits.
- If a second `chat.send` arrives while streaming, it waits for the lock
- `chat.cancel` releases the lock after the stream is stopped
- The frontend may choose to disable the send button per session while streaming
  (but the backend enforces serialisation regardless)

**Why release during `requires_action`:** A held lock during client-side tool
execution would deadlock the user. Scenario: Session A pauses for a client tool,
user switches to Session B and sends a message -- Session B would hang indefinitely
waiting for the user to respond to Session A first. Releasing the lock avoids this
by treating `requires_action` as "not actively streaming."

### 14.4 Embedding Model -- Auto-Download to Mounted Volume

**Decision:** The ONNX model files are **not** baked into the Docker image. Instead,
`docker-compose.yml` mounts a host directory for model storage. On backend startup,
the embedding provider checks for the model files and downloads them automatically
if missing.

**Rationale:** Baking the model into the image inflates image size by ~113 MB, slows
build times, and means model upgrades require a full image rebuild. A mounted volume
with auto-download keeps images lean, allows model swaps without rebuilds, and avoids
storing binary blobs in git.

**Implementation:**
- `docker-compose.yml` volume: `./data/models:/app/models`
- Environment variable: `ONNX_MODEL_DIR=/app/models/multilingual-e5-small`
- On startup: `OnnxEmbeddingProvider.__init__()` checks for `model.onnx` + `vocab.txt`
- If missing: downloads from HuggingFace (`intfloat/multilingual-e5-small` ONNX release)
- Download progress logged to stdout (visible in `docker compose logs`)
- Startup blocks until download completes (embedding is not available until then)
- `.env.example` documents the volume mount and model directory

---

## 15. Known Weaknesses

Acknowledged trade-offs that are acceptable for the prototype but should be revisited
as the system matures.

### 15.1 Token Counting Inaccuracy (`cl100k_base` for All Models)

`cl100k_base` (GPT-4's tokeniser) is used universally for context window budgeting
and the ampel display. This over-counts tokens for most models (Llama, Qwen, Mistral
all use different tokenisers), which means:

- **Context budget:** 10--20% of the context window is wasted. Acceptable -- over-counting
  is always safer than under-counting.
- **Ampel display:** Users see "orange" when there is actually more space available. This
  creates unnecessary urgency. Power users may find this frustrating.

**Future fix:** Maintain a tokeniser mapping per provider or per model family. The adapter
could expose a `tokenise(text) -> int` method, or the model metadata could declare which
tokeniser to use. Not worth the complexity for the prototype, but worth tracking.

### 15.2 Tool Loop Limit Not Communicated to the Model

The 5-iteration tool loop limit is enforced server-side, but the model does not know
it has a budget. If the model attempts a 6th tool call, the loop breaks and whatever
partial content exists is returned -- potentially mid-thought.

**Mitigation:** Inject a hint into the system prompt assembly:

```
You have a limited number of tool call rounds per response (maximum 5).
Plan your tool usage efficiently -- batch related lookups where possible
rather than making sequential single-purpose calls.
```

This is soft guidance, not a guarantee. Models may still exceed the budget, but the
incidence drops significantly with an explicit instruction. The hard server-side limit
remains as a safety net.

### 15.3 GridFS Read Performance for Attachments

GridFS splits files into 255 KB chunks and requires multiple reads to reconstruct a file.
For a chat system where image attachments are re-injected into the LLM context on every
turn, this adds latency -- especially for sessions with many images.

**Acceptable for the prototype** because:
- Context assembly happens once per `chat.send`, not per token
- Most attachments are small (< 2 MB)
- The bottleneck is LLM inference time, not attachment reads

**Future optimisation options:**
- Store attachments below a size threshold (e.g. 2 MB) as `Binary` directly on the
  `ChatMessage` document, bypassing GridFS entirely
- Cache recently accessed attachments in memory (LRU) during context assembly
- Use a pre-assembled base64 cache on the message document, populated at upload time
