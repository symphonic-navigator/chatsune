# ollama_local Concurrency & Chat UI Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialise ollama_local inference via an adapter-declared concurrency policy, make chat regenerate robust after aborted inferences, and eliminate `edit_target_missing` errors caused by optimistic message IDs.

**Architecture:** Adapters expose a `ConcurrencyPolicy` (`none`/`global`/`per_user`). A process-local lock registry grants locks at inference time. When a waiting chat blocks on a lock, events flow to the frontend so a banner can be displayed. Thinking-only assistant messages are dropped, and the chat regenerate button works on trailing user messages too. Frontend swaps the optimistic ID for the real MongoDB ID as soon as `chat.message_created` arrives.

**Tech Stack:** Python 3, asyncio, FastAPI, Pydantic v2, React/TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-04-08-ollama-local-and-chat-ui-fixes-design.md`

---

## File Structure

**Create:**
- `backend/modules/llm/_concurrency.py` — `ConcurrencyPolicy` enum + `InferenceLockRegistry`
- `tests/test_llm_concurrency.py` — tests for lock behaviour
- `frontend/src/features/chat/InferenceWaitBanner.tsx` — lock-wait UI banner

**Modify:**
- `backend/modules/llm/_adapters/_base.py` — add `concurrency_policy` class attribute
- `backend/modules/llm/_adapters/_ollama_local.py` — set `concurrency_policy = GLOBAL`
- `backend/modules/llm/__init__.py` — wrap `stream_completion` in lock acquisition
- `backend/modules/chat/_inference.py` — drop thinking-only assistant messages
- `backend/modules/chat/_handlers_ws.py` — accept trailing user message in regenerate
- `frontend/src/features/chat/MessageList.tsx` — regenerate on trailing user message
- `frontend/src/features/chat/ChatView.tsx` — pass `client_message_id` on send
- `frontend/src/stores/chatStore.ts` (or equivalent) — swap optimistic → real ID
- `shared/topics.py` — add two new topics
- `shared/events/llm.py` — add two new events
- `shared/dtos/chat.py` — add `client_message_id` to send DTO
- `shared/events/chat.py` — echo `client_message_id` on `MessageCreatedEvent`

---

## Task 1: Add `ConcurrencyPolicy` enum and lock registry

**Files:**
- Create: `backend/modules/llm/_concurrency.py`
- Test: `tests/test_llm_concurrency.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_concurrency.py
import asyncio
import pytest

from backend.modules.llm._concurrency import (
    ConcurrencyPolicy,
    InferenceLockRegistry,
)


class _AdapterNone:
    provider_id = "x"
    concurrency_policy = ConcurrencyPolicy.NONE


class _AdapterGlobal:
    provider_id = "ollama_local"
    concurrency_policy = ConcurrencyPolicy.GLOBAL


class _AdapterPerUser:
    provider_id = "per_user_provider"
    concurrency_policy = ConcurrencyPolicy.PER_USER


def test_none_policy_returns_no_lock():
    reg = InferenceLockRegistry()
    assert reg.lock_for(_AdapterNone, user_id="u1") is None


def test_global_policy_returns_same_lock_for_all_users():
    reg = InferenceLockRegistry()
    a = reg.lock_for(_AdapterGlobal, user_id="u1")
    b = reg.lock_for(_AdapterGlobal, user_id="u2")
    assert a is b
    assert isinstance(a, asyncio.Lock)


def test_per_user_policy_returns_distinct_locks_per_user():
    reg = InferenceLockRegistry()
    a = reg.lock_for(_AdapterPerUser, user_id="u1")
    b = reg.lock_for(_AdapterPerUser, user_id="u2")
    c = reg.lock_for(_AdapterPerUser, user_id="u1")
    assert a is not b
    assert a is c
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_concurrency.py -v`
Expected: FAIL with `ModuleNotFoundError: backend.modules.llm._concurrency`

- [ ] **Step 3: Write the implementation**

```python
# backend/modules/llm/_concurrency.py
"""Inference concurrency control.

Adapters declare a ``ConcurrencyPolicy`` as a class attribute; the
:class:`InferenceLockRegistry` hands out the matching asyncio lock (or
``None`` for fully parallel providers) at inference time.

``ollama_local`` uses ``GLOBAL`` because the local engine cannot sensibly
serve two generations at once — a second request would need its own KV
cache and prefill, which the hardware can't provide. ``ollama_cloud``
and other remote providers leave it at the default ``NONE``.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Protocol


class ConcurrencyPolicy(str, Enum):
    NONE = "none"          # fully parallel (default)
    GLOBAL = "global"      # one inference at a time, process-wide
    PER_USER = "per_user"  # one inference at a time, per user


class _AdapterLike(Protocol):
    provider_id: str
    concurrency_policy: ConcurrencyPolicy


class InferenceLockRegistry:
    """Process-local registry of asyncio locks keyed by adapter policy."""

    def __init__(self) -> None:
        self._global: dict[str, asyncio.Lock] = {}
        self._per_user: dict[tuple[str, str], asyncio.Lock] = {}

    def lock_for(
        self, adapter_cls: type[_AdapterLike], user_id: str,
    ) -> asyncio.Lock | None:
        policy = adapter_cls.concurrency_policy
        if policy is ConcurrencyPolicy.NONE:
            return None
        if policy is ConcurrencyPolicy.GLOBAL:
            return self._global.setdefault(adapter_cls.provider_id, asyncio.Lock())
        if policy is ConcurrencyPolicy.PER_USER:
            key = (adapter_cls.provider_id, user_id)
            return self._per_user.setdefault(key, asyncio.Lock())
        raise ValueError(f"Unknown concurrency policy: {policy!r}")


# Single process-wide registry used by LlmService.
_registry = InferenceLockRegistry()


def get_lock_registry() -> InferenceLockRegistry:
    return _registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_concurrency.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_concurrency.py tests/test_llm_concurrency.py
git commit -m "Add ConcurrencyPolicy enum and InferenceLockRegistry"
```

---

## Task 2: Declare `concurrency_policy` on adapters

**Files:**
- Modify: `backend/modules/llm/_adapters/_base.py`
- Modify: `backend/modules/llm/_adapters/_ollama_local.py`

- [ ] **Step 1: Add default on `BaseAdapter`**

Edit `backend/modules/llm/_adapters/_base.py`. After the existing
`is_global: bool = False` line (around line 17), add:

```python
    # Concurrency: adapters opt into serialisation by setting this.
    # Default NONE — the adapter can handle as many parallel inferences
    # as the caller throws at it (cloud providers, for example).
    from backend.modules.llm._concurrency import ConcurrencyPolicy
    concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.NONE
```

(Note: the `from ... import` line is placed inside the class body to
keep the module-level import graph small; this is idiomatic here.)

- [ ] **Step 2: Override on `OllamaLocalAdapter`**

Edit `backend/modules/llm/_adapters/_ollama_local.py`:

```python
from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter
from backend.modules.llm._concurrency import ConcurrencyPolicy


class OllamaLocalAdapter(OllamaBaseAdapter):
    """Ollama Local adapter — talks to a self-hosted Ollama daemon, no API key."""

    provider_id = "ollama_local"
    provider_display_name = "Ollama Local"
    requires_key_for_listing: bool = False
    is_global: bool = True
    # Local engine can only run one generation at a time — serialise.
    concurrency_policy = ConcurrencyPolicy.GLOBAL

    def _auth_headers(self, api_key: str | None) -> dict:
        return {}

    async def validate_key(self, api_key: str | None) -> bool:
        return True
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_base.py backend/modules/llm/_adapters/_ollama_local.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_base.py backend/modules/llm/_adapters/_ollama_local.py
git commit -m "Declare concurrency policy on LLM adapters"
```

---

## Task 3: Add lock-wait topics and events

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/llm.py`

- [ ] **Step 1: Add topic constants**

Edit `shared/topics.py`. Add to the existing `Topics` class alongside the
other LLM topics (after `LLM_PROVIDER_STATUS_SNAPSHOT`):

```python
    INFERENCE_LOCK_WAIT_STARTED = "inference.lock.wait_started"
    INFERENCE_LOCK_WAIT_ENDED = "inference.lock.wait_ended"
```

- [ ] **Step 2: Add event classes**

Append to `shared/events/llm.py`:

```python
class InferenceLockWaitStartedEvent(BaseModel):
    """Emitted when a chat inference begins waiting on a provider lock."""
    type: str = "inference.lock.wait_started"
    correlation_id: str
    provider_id: str
    holder_source: str  # e.g. "job:memory_consolidation" or "chat"
    timestamp: datetime


class InferenceLockWaitEndedEvent(BaseModel):
    """Emitted when the waiting chat inference finally acquires the lock."""
    type: str = "inference.lock.wait_ended"
    correlation_id: str
    provider_id: str
    timestamp: datetime
```

- [ ] **Step 3: Verify**

Run: `uv run python -m py_compile shared/topics.py shared/events/llm.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add shared/topics.py shared/events/llm.py
git commit -m "Add inference lock-wait topics and events"
```

---

## Task 4: Serialise inference through the lock in `LlmService`

**Files:**
- Modify: `backend/modules/llm/__init__.py`
- Test: `tests/test_llm_concurrency.py`

- [ ] **Step 1: Extend the test to cover the wrapped `stream_completion` path**

Append to `tests/test_llm_concurrency.py`:

```python
@pytest.mark.asyncio
async def test_global_lock_serialises_parallel_streams(monkeypatch):
    """Two streams against a GLOBAL-policy adapter run sequentially."""
    from backend.modules.llm import _concurrency
    from backend.modules.llm._concurrency import ConcurrencyPolicy

    reg = _concurrency.InferenceLockRegistry()
    monkeypatch.setattr(_concurrency, "_registry", reg)

    class _FakeAdapter:
        provider_id = "fake_local"
        concurrency_policy = ConcurrencyPolicy.GLOBAL

    lock = reg.lock_for(_FakeAdapter, user_id="u1")
    assert lock is not None

    entered: list[int] = []
    released = asyncio.Event()

    async def stream_a():
        async with lock:
            entered.append(1)
            await released.wait()

    async def stream_b():
        async with lock:
            entered.append(2)

    task_a = asyncio.create_task(stream_a())
    await asyncio.sleep(0.01)
    task_b = asyncio.create_task(stream_b())
    await asyncio.sleep(0.01)

    # Only stream_a is inside the lock; stream_b is waiting.
    assert entered == [1]
    released.set()
    await asyncio.gather(task_a, task_b)
    assert entered == [1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_concurrency.py::test_global_lock_serialises_parallel_streams -v`
Expected: FAIL (if pytest-asyncio missing it will error; otherwise passes trivially because locks already work — the real coverage comes in Step 3).

Note: if this test passes trivially, that is fine — it documents the contract. The next task exercises `stream_completion` end-to-end.

- [ ] **Step 3: Wrap `stream_completion` in the lock**

Edit `backend/modules/llm/__init__.py`. Add imports near the existing
`_registry` import:

```python
from backend.modules.llm._concurrency import (
    ConcurrencyPolicy,
    get_lock_registry,
)
```

Replace the existing `stream_completion` function body (lines 53–111)
with the locked version. The existing `async for` loop becomes wrapped:

```python
async def stream_completion(
    user_id: str,
    provider_id: str,
    request: CompletionRequest,
    source: str = "chat",
) -> AsyncIterator[ProviderStreamEvent]:
    """Resolve user's API key, instantiate adapter, stream completion.

    Wraps the adapter call in an adapter-declared concurrency lock
    (see :mod:`backend.modules.llm._concurrency`). For ``ollama_local``
    this serialises all inferences across the process — a new chat
    request waits until any in-flight generation finishes.

    When a wait is needed and the current holder can be identified, the
    caller is responsible for emitting :class:`InferenceLockWaitStartedEvent`
    (we cannot do it here because we have no session scope). The chat
    handler emits those events — see :mod:`backend.modules.chat._inference`.
    """
    if provider_id not in ADAPTER_REGISTRY:
        raise LlmProviderNotFoundError(f"Unknown provider: {provider_id}")

    adapter_cls = ADAPTER_REGISTRY[provider_id]
    api_key: str | None = None
    if not adapter_cls.is_global:
        repo = CredentialRepository(get_db())
        cred = await repo.find(user_id, provider_id)
        if not cred:
            raise LlmCredentialNotFoundError(
                f"No API key configured for provider '{provider_id}'"
            )
        api_key = repo.get_raw_key(cred)

    adapter = adapter_cls(base_url=PROVIDER_BASE_URLS[provider_id])
    lock = get_lock_registry().lock_for(adapter_cls, user_id)

    inference_id = _tracker.register(
        user_id=user_id,
        provider_id=provider_id,
        model_slug=request.model,
        source=source,
    )
    await _publish_inference_started(
        inference_id=inference_id,
        user_id=user_id,
        provider_id=provider_id,
        model_slug=request.model,
        source=source,
    )
    started_at_perf = _now_perf()
    try:
        if lock is not None:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=300)
            except asyncio.TimeoutError as exc:
                raise LlmInferenceLockTimeoutError(
                    provider_id=provider_id,
                ) from exc
            try:
                async for event in adapter.stream_completion(api_key, request):
                    yield event
            finally:
                lock.release()
        else:
            async for event in adapter.stream_completion(api_key, request):
                yield event
    finally:
        _tracker.unregister(inference_id)
        await _publish_inference_finished(
            inference_id=inference_id,
            user_id=user_id,
            duration_seconds=_now_perf() - started_at_perf,
        )
```

Also add `import asyncio` at the top if not already present, and define
the new exception near the other two:

```python
class LlmInferenceLockTimeoutError(Exception):
    """Timed out waiting for the provider's concurrency lock (5 minutes)."""

    def __init__(self, provider_id: str) -> None:
        super().__init__(
            f"Timed out waiting for inference lock on provider '{provider_id}'"
        )
        self.provider_id = provider_id
```

Export it from `__all__`:

```python
    "LlmInferenceLockTimeoutError",
```

- [ ] **Step 4: Run full test suite for the llm module**

Run: `uv run pytest tests/test_llm_concurrency.py -v`
Expected: all tests pass.

- [ ] **Step 5: Compile check**

Run: `uv run python -m py_compile backend/modules/llm/__init__.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/__init__.py tests/test_llm_concurrency.py
git commit -m "Serialise LLM inference through adapter-declared locks"
```

---

## Task 5: Emit lock-wait events from the chat inference path

**Files:**
- Modify: `backend/modules/chat/_inference.py`

- [ ] **Step 1: Detect wait and emit events around the upstream call**

The chat `_inference.py` wraps the upstream `llm_stream_completion` call.
Before pulling the first event from the iterator, check whether the
adapter's lock is currently held. If so, emit
`InferenceLockWaitStartedEvent`, then consume the stream; emit
`InferenceLockWaitEndedEvent` when the first chunk arrives (i.e. the
lock has been acquired and inference is actually producing output).

Read the current upstream-call site first to place the edit precisely:
the file constructs `upstream = llm_stream_completion(...)` — locate that
line (around line 505 in `_orchestrator.py` or the equivalent in
`_inference.py`; use `Grep` to find it in the chat module). The edit
below goes immediately around that loop.

```python
# At the top of the file, add:
from backend.modules.llm._concurrency import (
    ConcurrencyPolicy,
    get_lock_registry,
)
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm import _tracker as llm_tracker
from shared.events.llm import (
    InferenceLockWaitStartedEvent,
    InferenceLockWaitEndedEvent,
)
from shared.topics import Topics
```

Wrap the upstream iteration (the exact form depends on the current code;
adapt the shape but keep the semantics):

```python
# --- BEGIN lock-wait instrumentation ---
adapter_cls = ADAPTER_REGISTRY.get(provider_id)
lock = (
    get_lock_registry().lock_for(adapter_cls, user_id)
    if adapter_cls is not None else None
)
wait_emitted = False
if lock is not None and lock.locked():
    # Someone else is holding the lock — find out who, for the UI.
    holder_source = "unknown"
    for record in llm_tracker.snapshot():
        if record.provider_id == provider_id:
            holder_source = record.source
            break
    await emit_fn(InferenceLockWaitStartedEvent(
        correlation_id=correlation_id,
        provider_id=provider_id,
        holder_source=holder_source,
        timestamp=datetime.now(timezone.utc),
    ))
    wait_emitted = True
# --- END lock-wait instrumentation ---

upstream = llm_stream_completion(user_id, provider_id, req, source="chat")

first_chunk_seen = False
async for event in upstream:
    if not first_chunk_seen:
        first_chunk_seen = True
        if wait_emitted:
            await emit_fn(InferenceLockWaitEndedEvent(
                correlation_id=correlation_id,
                provider_id=provider_id,
                timestamp=datetime.now(timezone.utc),
            ))
    # ... existing per-event handling ...
```

Also handle the timeout case: wrap the `async for` in `try/except
LlmInferenceLockTimeoutError` and emit a `ChatStreamErrorEvent` with
`error_code="inference_lock_timeout"`, `recoverable=True`,
`user_message="The local model is still busy. Please try again shortly."`.

- [ ] **Step 2: Compile check**

Run: `uv run python -m py_compile backend/modules/chat/_inference.py backend/modules/chat/_orchestrator.py`
Expected: no output.

- [ ] **Step 3: Smoke-test the full backend still starts**

Run: `uv run python -c "import backend.main"` (or the project's standard import check).
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_inference.py backend/modules/chat/_orchestrator.py
git commit -m "Emit inference lock-wait events from chat stream"
```

---

## Task 6: Drop thinking-only assistant messages on save

**Files:**
- Modify: `backend/modules/chat/_inference.py`

- [ ] **Step 1: Narrow the persistence condition**

In `backend/modules/chat/_inference.py` around line 271, change:

```python
if full_content or full_thinking:
    message_id = await save_fn(...)
```

to:

```python
# Only persist assistant messages with visible content. Thinking-only
# streams (e.g. aborted mid-thinking, or ollama_local interrupted by
# another request) are dropped so the user can simply regenerate.
# See docs/superpowers/specs/2026-04-08-ollama-local-and-chat-ui-fixes-design.md.
if full_content:
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        usage=usage,
        web_search_context=web_search_context or None,
        knowledge_context=knowledge_context or None,
    )
```

- [ ] **Step 2: Compile check**

Run: `uv run python -m py_compile backend/modules/chat/_inference.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_inference.py
git commit -m "Drop thinking-only assistant messages on save"
```

---

## Task 7: Allow regenerate on trailing user message (backend)

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Relax the regenerate guard**

In `backend/modules/chat/_handlers_ws.py` around line 284, change:

```python
last_msg = await repo.get_last_message(session_id)
if last_msg is None or last_msg["role"] != "assistant":
    return
```

to:

```python
last_msg = await repo.get_last_message(session_id)
if last_msg is None:
    return
if last_msg["role"] not in ("assistant", "user"):
    return
```

Then make the existing delete-last-assistant block conditional:

```python
correlation_id = str(uuid4())
now = datetime.now(timezone.utc)
event_bus = get_event_bus()

if last_msg["role"] == "assistant":
    # Delete the last assistant message — we're going to replace it.
    await repo.delete_message(last_msg["_id"])
    await delete_bookmarks_for_message(last_msg["_id"])

    await event_bus.publish(
        Topics.CHAT_MESSAGE_DELETED,
        ChatMessageDeletedEvent(
            session_id=session_id,
            message_id=last_msg["_id"],
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
# If last_msg is a user message, nothing to delete — just re-infer.
```

The subsequent `run_inference` call stays unchanged.

- [ ] **Step 2: Compile check**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Accept trailing user message in chat regenerate handler"
```

---

## Task 8: Add `client_message_id` to send DTO and created event

**Files:**
- Modify: `shared/dtos/chat.py`
- Modify: `shared/events/chat.py`

- [ ] **Step 1: Extend the send DTO**

Read the current file first to find the send-message DTO. Add an
optional `client_message_id` field:

```python
class ChatSendMessageDto(BaseModel):
    session_id: str
    content_parts: list[ContentPartDto]
    attachment_ids: list[str] | None = None
    # Frontend-generated optimistic ID ("optimistic-<uuid>"). Echoed
    # back on MessageCreatedEvent so the frontend can atomically swap
    # the optimistic entry for the real MongoDB ID.
    client_message_id: str | None = None
```

(Adapt the class name to whatever already exists.)

- [ ] **Step 2: Extend the created event**

In `shared/events/chat.py`, add the same field to `ChatMessageCreatedEvent`
(or whatever the class is called):

```python
class ChatMessageCreatedEvent(BaseModel):
    type: str = "chat.message.created"
    session_id: str
    message_id: str
    role: str
    content: str
    ...  # existing fields
    # Optional: set only for user messages sent with an optimistic ID.
    client_message_id: str | None = None
```

- [ ] **Step 3: Compile check**

Run: `uv run python -m py_compile shared/dtos/chat.py shared/events/chat.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/chat.py shared/events/chat.py
git commit -m "Add client_message_id to chat send DTO and created event"
```

---

## Task 9: Plumb `client_message_id` through the backend send handler

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Read the optimistic ID from the inbound payload**

Find the `handle_chat_send` function in `_handlers_ws.py`. After the
payload is parsed, capture `client_message_id = data.get("client_message_id")`.
Pass it through to the event that announces the newly created user
message.

- [ ] **Step 2: Emit it on `ChatMessageCreatedEvent`**

Locate the event emission for the new user message (search the file for
`ChatMessageCreatedEvent`). Add the `client_message_id=client_message_id`
kwarg.

- [ ] **Step 3: Compile check**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Echo client_message_id on chat message created event"
```

---

## Task 10: Frontend — swap optimistic ID on message.created

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`
- Modify: the chat store (locate via `grep -r "optimistic-" frontend/src`)

- [ ] **Step 1: Send `client_message_id` with the outbound payload**

In `ChatView.tsx` where the optimistic `optimistic-<uuid>` is generated
(around line 393), include it in the outbound WebSocket payload as
`client_message_id`:

```tsx
const clientMessageId = `optimistic-${uuidv4()}`
// ... existing optimistic message insertion ...
send({
  type: 'chat.send_message',
  session_id: sessionId,
  content_parts: parts,
  attachment_ids: attachmentIds,
  client_message_id: clientMessageId,
})
```

- [ ] **Step 2: Swap the ID in the store when `message.created` arrives**

Locate the store's handler for `chat.message.created`. Before the
existing insertion logic, check whether an entry with the matching
`client_message_id` already exists; if so, rewrite its `id` field
instead of appending a new message:

```ts
// chatStore.ts (or equivalent) — chat.message.created handler
const clientId = event.client_message_id
if (clientId) {
  const idx = state.messages.findIndex(m => m.id === clientId)
  if (idx !== -1) {
    state.messages[idx] = {
      ...state.messages[idx],
      id: event.message_id,
    }
    return  // do not also append
  }
}
// ... existing append logic for fresh messages ...
```

- [ ] **Step 3: Defence-in-depth — refuse to send edits on optimistic IDs**

In the edit handler, guard against sending an edit while the ID is
still optimistic:

```ts
function handleEdit(messageId: string, content: string) {
  if (messageId.startsWith('optimistic-')) {
    console.warn('Refusing to edit optimistic message — ID not swapped yet')
    return
  }
  // ... existing edit logic ...
}
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "Swap optimistic chat message ID when server confirms"
```

---

## Task 11: Frontend — regenerate under trailing user message

**Files:**
- Modify: `frontend/src/features/chat/MessageList.tsx`

- [ ] **Step 1: Compute `canRegenerate` for trailing user messages too**

Replace lines 48–49 of `MessageList.tsx`:

```tsx
const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null
const canRegenerate =
  !isStreaming &&
  lastMsg !== null &&
  (lastMsg.role === 'assistant' || lastMsg.role === 'user')
const showStandaloneRegenerate =
  canRegenerate && lastMsg !== null && lastMsg.role === 'user'
```

- [ ] **Step 2: Render a standalone button below the last user message**

After the `.map(...)` that renders the messages, but before the
bottom-ref sentinel, add:

```tsx
{showStandaloneRegenerate && (
  <div className="flex justify-center py-2">
    <button
      type="button"
      onClick={onRegenerate}
      className="px-3 py-1 text-sm rounded-md border border-white/10 hover:bg-white/5 transition"
    >
      Generate response
    </button>
  </div>
)}
```

(Adjust classes to match the existing chat surface palette — check
sibling components for the correct colour tokens.)

Leave the existing assistant-row regenerate button wiring untouched so
the trailing-assistant case keeps its current behaviour.

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Build check**

Run: `cd frontend && pnpm run build`
Expected: clean build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/MessageList.tsx
git commit -m "Show regenerate button under trailing user message"
```

---

## Task 12: Frontend — inference wait banner

**Files:**
- Create: `frontend/src/features/chat/InferenceWaitBanner.tsx`
- Modify: chat store (add `waitingForLock` state)
- Modify: chat view to render the banner

- [ ] **Step 1: Add store state for lock wait**

In the chat store, add a new state slice:

```ts
waitingForLock: { providerId: string; holderSource: string } | null
```

Handle `inference.lock.wait_started` → set it; handle
`inference.lock.wait_ended` → clear it; also clear on `chat.stream.ended`
and `error` as a safety net.

- [ ] **Step 2: Build the banner component**

```tsx
// frontend/src/features/chat/InferenceWaitBanner.tsx
import React from 'react'

interface InferenceWaitBannerProps {
  holderSource: string
}

function describeHolder(source: string): string {
  if (source.startsWith('job:memory_consolidation')) return 'memory consolidation'
  if (source.startsWith('job:memory_extraction')) return 'memory extraction'
  if (source.startsWith('job:title_generation')) return 'title generation'
  if (source.startsWith('job:')) return 'a background task'
  if (source === 'chat') return 'another chat'
  return 'a local inference task'
}

export function InferenceWaitBanner({ holderSource }: InferenceWaitBannerProps) {
  return (
    <div
      role="status"
      className="mx-4 my-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-200"
    >
      Waiting for {describeHolder(holderSource)} to finish — your message will
      start as soon as the local model is free.
    </div>
  )
}
```

- [ ] **Step 3: Render the banner in the chat view**

Above the composer, wire in the banner from store state:

```tsx
const waitingForLock = useChatStore(s => s.waitingForLock)
// ...
{waitingForLock && (
  <InferenceWaitBanner holderSource={waitingForLock.holderSource} />
)}
```

- [ ] **Step 4: Type-check & build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "Add inference wait banner for ollama_local lock contention"
```

---

## Task 13: End-to-end manual verification

- [ ] **Step 1: Bring the stack up**

Run: `docker compose up -d`

- [ ] **Step 2: Background job + chat serialisation**

Trigger a memory consolidation job (via the admin UI or by sending
enough messages to cross the threshold). While it is running, send a
chat message. Expect:
- The chat message does not start inference immediately.
- The wait banner appears with "memory consolidation".
- Once the job finishes, the banner disappears and the chat stream
  begins.
- The job completes cleanly (no interruption).

- [ ] **Step 3: Abort during thinking → regenerate**

Start a chat inference with a reasoning model. Abort while the model is
still in the thinking phase. Expect:
- No assistant message is persisted (the session ends with the user
  message).
- A "Generate response" button appears below the last user message.
- Clicking it starts a fresh inference.

- [ ] **Step 4: Edit immediately after send**

Send a chat message and immediately click edit within the first second.
Expect: the edit flows through without `edit_target_missing`; the
backend log shows no rejection.

- [ ] **Step 5: Lock timeout error path**

(Optional, hard to provoke manually.) Simulate by holding the lock for
>5 minutes via a long-running job. Expect a `ChatStreamErrorEvent` with
`inference_lock_timeout` and a retry affordance in the UI.

- [ ] **Step 6: Commit any final adjustments**

If the manual run surfaces small tweaks (copy, colours, log messages),
apply them now and commit.

```bash
git add -A
git commit -m "Post-verification polish for ollama_local fixes"
```

---

## Final Verification

- [ ] **Backend tests**

Run: `uv run pytest tests/test_llm_concurrency.py tests/test_heartbeat_watchdog.py -v`
Expected: all pass.

- [ ] **Frontend build**

Run: `cd frontend && pnpm run build`
Expected: clean.

- [ ] **Module boundary audit**

Run: `rg -n "from backend\.modules\.\w+\._" backend/modules/` and confirm
that no module reaches into another module's internals. Lock registry
imports inside `backend/modules/llm/` are fine.

- [ ] **Log sanity check**

Tail `backend.log` during the manual run. Confirm that:
- lock acquisition / release is visible (add a log line in Task 4 if
  not — do so only if the log is otherwise silent).
- no `edit_target_missing` errors appear.
- `inference.lock.wait_started` and `inference.lock.wait_ended` events
  bracket the wait window.
