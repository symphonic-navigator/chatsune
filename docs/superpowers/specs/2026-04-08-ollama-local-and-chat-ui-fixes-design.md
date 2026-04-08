# ollama_local Concurrency & Chat UI Fixes — Design

**Date:** 2026-04-08
**Status:** Draft
**Scope:** Backend (`modules/llm`, `modules/chat`), Frontend (`features/chat`)

## Context

Four related bugs were identified during testing:

1. **ollama_local concurrency:** Parallel inferences against the local Ollama
   instance (e.g. background jobs and interactive chat) interfere with each
   other. A new inference appears to interrupt the running one. Investigation
   confirmed that there is **no** "cancel previous" logic in our code — the
   root cause is that the local engine cannot sensibly serve concurrent
   requests, so we must serialise access ourselves.

2. **Regenerate blocked after abort during thinking:** When a user aborts an
   inference while the model is still in the thinking phase, no "regenerate"
   button appears. This is a downstream consequence of bug 1: the thinking
   stream was truncated mid-flight, leaving the chat in an inconsistent state.

3. **`edit_target_missing` on edit-and-save:** Editing a freshly sent user
   message occasionally fails because the frontend submits an
   `optimistic-<uuid>` placeholder ID instead of the real MongoDB ID assigned
   by the backend.

4. **No regenerate path when the last message is a user message:** The chat UI
   only renders a regenerate button under assistant messages. If an inference
   was aborted before any assistant content was persisted, the user can only
   recover by editing their own message — which is unintuitive.

Chatsune is a persona-oriented chat client optimised for creative prosumer use
— not a research platform requiring exhaustive traceability. Stability and
continuity of the chat experience take priority over preserving every partial
artefact.

## Goals

- Serialise ollama_local inference through a configurable, adapter-declared
  concurrency policy, without impacting ollama_cloud or other providers.
- Guarantee that the user can always regenerate after an aborted inference,
  regardless of whether the partial message reached persistence.
- Eliminate `edit_target_missing` errors caused by optimistic ID races.
- Keep module boundaries intact. No cross-module DB access, no magic strings.

## Non-Goals

- Preserving thinking-only partial assistant messages. They will be dropped.
- Multi-user fairness or queueing beyond FIFO lock acquisition.
- Concurrency handling for providers other than ollama_local.

---

## Bug 1 — ollama_local Concurrency

### Design

Adapters declare their own concurrency requirements via a `ConcurrencyPolicy`
attribute. The LLM registry provisions and hands out locks accordingly.

```python
# backend/modules/llm/_concurrency.py  (new)
from enum import Enum

class ConcurrencyPolicy(str, Enum):
    NONE = "none"          # fully parallel (default)
    GLOBAL = "global"      # one inference at a time, process-wide
    PER_USER = "per_user"  # one inference at a time, per user
```

Each adapter class sets `concurrency_policy: ClassVar[ConcurrencyPolicy]`.
`ollama_local` sets `GLOBAL`. `ollama_cloud` keeps the default `NONE`.

A lock registry lives alongside the adapter registry:

```python
# backend/modules/llm/_concurrency.py
class InferenceLockRegistry:
    def __init__(self) -> None:
        self._global: dict[str, asyncio.Lock] = {}
        self._per_user: dict[tuple[str, str], asyncio.Lock] = {}

    def lock_for(self, adapter_cls, user_id: str) -> asyncio.Lock | None:
        policy = adapter_cls.concurrency_policy
        if policy is ConcurrencyPolicy.NONE:
            return None
        key = adapter_cls.provider_id
        if policy is ConcurrencyPolicy.GLOBAL:
            return self._global.setdefault(key, asyncio.Lock())
        if policy is ConcurrencyPolicy.PER_USER:
            return self._per_user.setdefault((key, user_id), asyncio.Lock())
```

The `LlmService.stream_completion()` method wraps the adapter call:

```python
lock = lock_registry.lock_for(adapter_cls, user_id)
if lock is not None:
    try:
        await asyncio.wait_for(lock.acquire(), timeout=300)
    except asyncio.TimeoutError:
        await emit(ChatStreamErrorEvent(
            error_code="inference_lock_timeout",
            recoverable=True,
            user_message="The local model is still busy. Please try again shortly.",
            ...
        ))
        return
    try:
        async for chunk in adapter.stream_completion(...):
            yield chunk
    finally:
        lock.release()
else:
    async for chunk in adapter.stream_completion(...):
        yield chunk
```

### Error Handling

- **Timeout (5 minutes):** Emit `ChatStreamErrorEvent` with
  `error_code="inference_lock_timeout"`, `recoverable=True`. The frontend
  shows the normal retry affordance.
- **Exception inside the critical section:** The `finally` releases the lock
  before the exception propagates.
- **User-initiated abort inside the critical section:** Normal cancellation
  path — the lock is released in `finally`, the waiting inference proceeds.

### Why `GLOBAL` and not `PER_USER` for ollama_local

There is a single local GPU shared by all users of this self-hosted instance.
Per-user locks would still contend at the hardware level. `PER_USER` exists in
the enum for future adapters (e.g. hosted local instances keyed by tenant) but
is not used in Phase 1.

---

## Bug 2 + Bug 4 — Regenerate After Aborted Inference

These are treated together because the fix for bug 4 makes bug 2 go away.

### Design

**Backend:** Stop persisting assistant messages that contain only thinking and
no visible content. Update `_inference.py` around line 271:

```python
# Only persist messages with visible content. Thinking-only messages
# are dropped — the user can regenerate. See design doc 2026-04-08.
if full_content:
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        ...
    )
```

**Frontend:** `MessageList.tsx` computes `canRegenerate` based on whether the
last message is *either* a trailing assistant message *or* a trailing user
message (i.e. the previous inference produced nothing persistable):

```tsx
const lastMsg = messages[messages.length - 1]
const canRegenerate =
  !isStreaming &&
  lastMsg !== undefined &&
  (lastMsg.role === 'assistant' || lastMsg.role === 'user')
```

When the trailing message is a user message, the regenerate affordance is
rendered as a **standalone button below the last user message**, not attached
to the bubble. This signals clearly: "generate a response for this message",
distinct from the assistant-row inline button which signals "replace this
response".

### Backend Regenerate Handler

The existing handler in `_handlers_ws.py:284-286` currently rejects regenerate
unless the last message is an assistant message. It must accept either:

```python
last_msg = await repo.get_last_message(session_id)
if last_msg is None:
    # reject — empty session
    ...
if last_msg["role"] == "assistant":
    # existing behaviour: delete last assistant, regenerate
    await repo.delete_message(last_msg["_id"])
    await delete_bookmarks_for_message(last_msg["_id"])
elif last_msg["role"] == "user":
    # new: no assistant message to delete, just trigger inference
    pass
else:
    # reject
    ...
```

---

## Bug 3 — Optimistic ID Race on Edit

### Design

The frontend optimistically assigns `optimistic-<uuid>` as the message ID when
the user sends a message, then receives the real ID via the `message.created`
event. The store must atomically rewrite the message entry when the real ID
arrives.

**Mechanism:** Include a `client_message_id` field on the outbound
`chat.send_message` payload (the `optimistic-<uuid>` string). The backend
echoes it on the `message.created` event. The store locates the optimistic
entry by `client_message_id` and swaps its `id` field to the real ID.

```ts
// chatStore.ts — on message.created
const idx = messages.findIndex(m => m.clientMessageId === event.client_message_id)
if (idx !== -1) {
  messages[idx] = { ...messages[idx], id: event.message_id }
}
```

**Contract changes (`shared/`):**

- `shared/dtos/chat.py`: add optional `client_message_id: str | None` to the
  send-message DTO.
- `shared/events/chat.py`: add optional `client_message_id: str | None` to
  `MessageCreatedEvent` so the frontend can correlate.

**Edit flow:** Unchanged. Because the store has replaced the optimistic ID
with the real ID by the time the user clicks edit, the edit call naturally
carries the correct ID. As a safety net, the edit handler on the frontend
refuses to send the edit if the target ID still starts with `optimistic-`
(defence in depth — should not be reachable once the store swap works).

---

## Testing

### Backend

- **ollama_local lock:** unit test that two concurrent `stream_completion`
  calls through an adapter with `GLOBAL` policy execute sequentially; a
  `NONE`-policy adapter runs them in parallel.
- **Lock timeout:** unit test that a blocked acquirer emits
  `ChatStreamErrorEvent` with `inference_lock_timeout` after the timeout.
- **Regenerate on trailing user message:** handler test that regenerate
  succeeds when the last message in the session is a user message.
- **Thinking-only not persisted:** inference test verifying that an abort
  during the thinking phase leaves no assistant message in the repository.

### Frontend

- **Regenerate button visibility:** component test for `MessageList` covering
  trailing assistant, trailing user, and empty-session cases.
- **Optimistic ID swap:** store test that `message.created` replaces the
  optimistic entry's ID.

### Manual

- Trigger a background job (memory consolidation) and immediately start a
  chat inference against ollama_local. Expect serial execution, both
  complete, no interruption.
- Abort a chat inference during thinking. Expect regenerate button under
  last user message. Click regenerate — expect normal inference.
- Edit a user message within the first second after sending. Expect no
  `edit_target_missing` error.

---

## Out of Scope / Future Work

- A more sophisticated queue with prioritisation (e.g. chat over background
  jobs) — revisit if serial execution feels too slow in practice.
- Preserving partial thinking content in a separate, hidden field for debug
  purposes — not needed for Phase 1.
- Applying the same lock mechanism to embeddings or other local inference
  paths — they are not affected by this bug report.
