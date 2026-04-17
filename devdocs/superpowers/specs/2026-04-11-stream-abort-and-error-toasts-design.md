# Stream Abort Handling & Error Toasts — Design

**Date:** 2026-04-11
**Status:** Draft
**Scope:** Backend (`modules/llm`, `modules/chat`, `shared/`), Frontend (`features/chat`, `core/store`)

## Context

Three related failure modes surfaced during chat testing, all caused by the
same underlying gap: the backend has no concept of "the upstream went silent
but did not legitimately finish", and the frontend has no path to surface
stream errors to the user as anything actionable.

1. **Silent gutter aborts.** `backend/modules/llm/_adapters/_ollama_base.py`
   applies a 30-second idle timeout between NDJSON chunks. When the timeout
   fires, the adapter yields a bare `StreamDone()` with no indication that
   the stream was cut off. Downstream, `backend/modules/chat/_inference.py`
   treats this as a normal completion, so the partially streamed assistant
   message is persisted with `status = "completed"` — the user sees a
   response that ends mid-sentence and has no way to tell it is broken.

2. **No error toasts on stream errors.** The frontend `useChatStream` hook
   routes `CHAT_STREAM_ERROR` events into `chatStore.error` but never
   surfaces them through the existing toast infrastructure. Only
   `session_expired` receives user-visible treatment (via a banner). All
   other errors fail silently from the user's perspective.

3. **Hot recovery path is invisible.** The existing regenerate button is
   attached to the last assistant message, but when the user sees a
   half-finished reply there is no explicit invitation to regenerate.
   Users who do not know the button exists simply see a broken reply and
   get stuck.

Chatsune's UX values are "don't make me think" and least astonishment. A
broken stream that looks complete violates both. The fix makes abort
handling explicit end-to-end, surfaces errors through toasts with inline
recovery actions, and marks affected messages so they stay identifiable
after page refresh.

## Goals

- Replace the single-stage silent gutter timeout with a two-stage state
  machine: a "slow" signal at 30 s idle, a hard abort at a configurable
  120 s idle.
- Introduce an `aborted` message status that is persisted in MongoDB, so
  a page refresh does not erase the warning.
- Surface `CHAT_STREAM_ERROR` events as toasts via the existing
  `notificationStore`, with an inline "regenerate" action for recoverable
  errors.
- Render a subtle, non-intrusive "model still working…" hint while a
  stream is in its slow phase.
- Render an amber warning band on aborted assistant messages, with clear
  instructions pointing at the regenerate button.
- Filter `aborted` assistant messages out of the LLM context build to
  prevent half-finished replies from polluting future turns.
- Keep all changes strictly additive. No data migration, no feature flags,
  no breaking contract changes.

## Non-Goals

- Refusal detection via provider `done_reason` parsing (Schub 2).
- Persisting artefact tool-call references on chat messages (Schub 3).
- Tool-call streaming (not supported by the Ollama API; out of our control).
- User-initiated cancellation status. "Cancelled" is semantically equivalent
  to "the user decided to stop here" and does not need a warning badge.
- Retroactive migration of existing `chat_messages` documents. The `status`
  field is defaulted on read.

---

## Design

### 1. Adapter state machine — `_ollama_base.py`

Replace `GUTTER_TIMEOUT_SECONDS` with two constants, the abort value
sourced from an environment variable, and introduce a module-level clock
indirection so tests can inject a fake time source:

```python
import os
import time

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"))

# Indirection so tests can override with a fake clock without having to
# monkey-patch the time module itself.
_clock = time.monotonic
```

Inside the streaming loop, use `_clock()` instead of `time.monotonic()`
directly. Tests override `_ollama_base._clock = fake_clock` to drive
deterministic virtual time.

Two new adapter-level stream event types alongside the existing
`ContentDelta`, `ThinkingDelta`, `ToolCallEvent`, `StreamDone`, `StreamError`:

```python
@dataclass
class StreamSlow:
    """Emitted when the upstream has been idle for GUTTER_SLOW_SECONDS
    without yet being considered aborted. Informational only."""
    pass


@dataclass
class StreamAborted:
    """Emitted when the upstream has been idle for GUTTER_ABORT_SECONDS.
    The stream is dead. Any previously accumulated content should be
    persisted with status='aborted'."""
    reason: str = "gutter_timeout"
```

The streaming loop is rewritten as a single-loop two-budget state machine.
A monotonic clock drives both budgets so tests can inject time:

```python
stream_iter = resp.aiter_lines().__aiter__()
line_start = _clock()
slow_fired = False

while True:
    elapsed = _clock() - line_start
    budget = (GUTTER_ABORT_SECONDS if slow_fired else GUTTER_SLOW_SECONDS) - elapsed

    if budget <= 0:
        if not slow_fired:
            _log.info(
                "ollama_base.gutter_slow model=%s idle=%.1fs",
                payload.get("model"), elapsed,
            )
            yield StreamSlow()
            slow_fired = True
            continue  # re-evaluate against abort deadline
        _log.warning(
            "ollama_base.gutter_abort model=%s idle=%.1fs",
            payload.get("model"), elapsed,
        )
        yield StreamAborted(reason="gutter_timeout")
        return

    try:
        line = await asyncio.wait_for(
            stream_iter.__anext__(), timeout=budget,
        )
    except asyncio.TimeoutError:
        continue  # loop back, recompute budget
    except StopAsyncIteration:
        break

    # Successful line — reset the window. slow_fired is cleared here so
    # that a subsequent silence phase will re-announce. The frontend also
    # clears its slow flag implicitly on any content/thinking delta.
    line_start = _clock()
    slow_fired = False

    # ... existing NDJSON parsing: done, content, thinking, tool_calls
```

The existing `asyncio.CancelledError` and `httpx.ConnectError` handlers at
the end of the function remain unchanged.

### 2. Shared contracts

**`shared/events/chat.py`** — new event:

```python
class ChatStreamSlowEvent(BaseEvent):
    """The upstream has been silent for a while but has not aborted yet.
    Frontend shows a subtle hint; the flag auto-clears on the next
    ChatContentDeltaEvent / ChatThinkingDeltaEvent / ChatStreamEndedEvent
    in the same correlation_id."""
    correlation_id: str
    timestamp: datetime
```

**`shared/events/chat.py`** — extend `ChatStreamEndedEvent.status`:

```python
status: Literal["completed", "cancelled", "error", "aborted"]
```

**`shared/topics.py`** — new constant:

```python
CHAT_STREAM_SLOW = "chat.stream.slow"
```

**`shared/dtos/chat.py`** — extend `ChatMessageDto`:

```python
status: Literal["completed", "aborted"] = "completed"
```

The DTO default allows old clients and old documents to flow through
unchanged. Only the assistant role ever carries a non-default value; user
and tool messages always read as `"completed"`. The `"completed"` /
`"aborted"` naming matches the existing `ChatStreamEndedEvent.status`
convention rather than introducing a parallel `"complete"` form.

### 3. Chat inference handler — `_inference.py`

Extend the event match block around lines 100-131 with two new cases:

```python
case StreamSlow():
    await emit_fn(ChatStreamSlowEvent(
        correlation_id=correlation_id,
        timestamp=datetime.now(timezone.utc),
    ))

case StreamAborted() as ab:
    status = "aborted"
    await emit_fn(ChatStreamErrorEvent(
        correlation_id=correlation_id,
        error_code="stream_aborted",
        recoverable=True,
        user_message="The response was interrupted. Please regenerate.",
        timestamp=datetime.now(timezone.utc),
    ))
    break  # exit the tool loop
```

The `StreamSlow` branch is informational and changes no state. The
`StreamAborted` branch sets the local `status` variable to `"aborted"`,
emits a recoverable error event (which drives both the toast and any
inline error banner on the frontend), and breaks out of the tool loop so
the orchestrator proceeds to the save-and-emit-ended phase.

The final `save_fn` call at line 276 passes the new status field through:

```python
if full_content:
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        usage=usage,
        web_search_context=web_search_context or None,
        knowledge_context=knowledge_context or None,
        status="aborted" if status == "aborted" else "completed",
    )
```

Only `"aborted"` is persisted. `"cancelled"` and `"error"` collapse to
`"completed"` because those cases either have no content (and thus are
not saved at all) or represent legitimate user-driven stops that need no
warning.

### 4. Repository — `_repository.py`

`save_message()` accepts a new optional keyword:

```python
async def save_message(
    self,
    session_id: str,
    role: str,
    content: str,
    thinking: str | None = None,
    usage: dict | None = None,
    web_search_context: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,
    attachment_ids: list[str] | None = None,
    vision_descriptions_used: list[dict] | None = None,
    status: Literal["completed", "aborted"] = "completed",
) -> str:
    ...
    doc = {
        ...,
        "status": status,
    }
```

`list_messages()` and `get_message()` apply `doc.setdefault("status",
"completed")` before constructing the DTO, so legacy documents without
the field are handled transparently. No index is added — `status` is
never a query predicate, only a render-time decoration.

### 5. Orchestrator context filter — `_orchestrator.py`

Immediately after fetching history (current line 305):

```python
history_docs = await repo.list_messages(session_id)
# Aborted assistant messages pollute the LLM context with half-finished
# thoughts or truncated code. Strip them before pair selection. The
# corresponding user prompts remain in place so the user can regenerate
# without losing their own input.
history_docs = [
    d for d in history_docs
    if d.get("status", "completed") != "aborted"
]
```

The user turn that preceded an aborted assistant message stays in the
history. When the user regenerates, that prompt is still in context.
The trade-off is explicit: the user loses the half-finished reply from
context (which is what we want), but keeps their own prompt.

### 6. Frontend — store (`core/store/chatStore.ts`)

Add one state field:

```typescript
interface ChatStoreState {
  // ... existing fields
  streamingSlow: boolean
}
```

State transitions for `streamingSlow`:

| Event                                | Action            |
|--------------------------------------|-------------------|
| `CHAT_STREAM_STARTED`                | set `false`       |
| `CHAT_STREAM_SLOW`                   | set `true`        |
| `CHAT_CONTENT_DELTA`                 | set `false`       |
| `CHAT_THINKING_DELTA`                | set `false`       |
| `CHAT_STREAM_ENDED`                  | set `false`       |
| `CHAT_STREAM_ERROR`                  | set `false`       |

Add one new store action:

```typescript
regenerateLast: (sessionId: string) => void
```

This action performs the same work the manual regenerate button does
today (dispatching the `chat.regenerate` WebSocket command for the given
session). It is session-bound by its parameter, so a toast fired in
session A does not regenerate session B if the user has switched views
between the abort and the click.

When building message objects on `CHAT_STREAM_ENDED`, the store copies
`status` from the event into the new `ChatMessageDto` field, defaulting
to `"complete"` when absent.

### 7. Frontend — event handler (`features/chat/useChatStream.ts`)

**New handler** for `CHAT_STREAM_SLOW`:

```typescript
case Topics.CHAT_STREAM_SLOW:
  setStreamingSlow(true)
  break
```

**Extended handler** for `CHAT_STREAM_ERROR`:

```typescript
case Topics.CHAT_STREAM_ERROR: {
  const ev = event as ChatStreamErrorEventDto
  setError({
    errorCode: ev.error_code,
    recoverable: ev.recoverable,
    userMessage: ev.user_message,
  })
  // session_expired has its own banner path; everything else uses the
  // toast system for visibility.
  if (ev.error_code !== 'session_expired') {
    const title = ev.recoverable ? 'Response interrupted' : 'Error'
    const action = ev.recoverable && sessionId
      ? {
          label: 'Regenerate',
          onClick: () => chatStore.regenerateLast(sessionId),
        }
      : undefined
    notificationStore.addNotification(
      'error',
      title,
      ev.user_message,
      action,
    )
  }
  break
}
```

The action button is bound to the session ID captured at event time, so
a later session switch does not misroute the regenerate.

### 8. Frontend — UI components

**Slow hint.** In `features/chat/MessageList.tsx`, inside the existing
`{isStreaming && ...}` block, render a small text line when
`streamingSlow` is true:

```tsx
{isStreaming && streamingSlow && (
  <div className="text-xs text-white/50 italic mt-1">
    Model still working…
  </div>
)}
```

Deliberately plain: no icon, no animation, no colour. The user sees "we
haven't forgotten about you" and nothing more. Disappears automatically
on the next delta.

**Aborted warning band.** In `features/chat/AssistantMessage.tsx`, below
the message content and above the action buttons, render an amber band
when `status === 'aborted'`:

```tsx
{status === 'aborted' && (
  <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-400/30 bg-amber-400/5 px-3 py-2">
    <WarningIcon className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
    <div className="text-xs text-amber-200/90">
      This response was interrupted and may be incomplete.
      Click <strong>Regenerate</strong> to produce a fresh response.
    </div>
  </div>
)}
```

`AssistantMessage` gains a new optional prop `status?: 'complete' |
'aborted'` with default `'complete'`. `MessageList` passes `msg.status`
through to it. Amber is reserved for "incomplete but recoverable"; red
will be reserved for refusals in Schub 2.

### 9. Environment configuration

**New variable:** `LLM_STREAM_ABORT_SECONDS`
**Default:** `120`
**Unit:** seconds
**Purpose:** How long the LLM upstream may stay silent before we declare
the stream aborted. The slow-phase threshold remains hard-coded at 30 s.

Added to `.env.example`:

```
# How many seconds the LLM upstream may stay silent before the stream is
# declared aborted. Should be larger than 30 (the slow-phase threshold).
LLM_STREAM_ABORT_SECONDS=120
```

Documented in `README.md` under the environment-variables section, in
the same style as existing entries.

---

## Testing

### Backend

- **Gutter state machine** (`_ollama_base.py`) — unit tests with an
  injected monotonic clock, against a stubbed NDJSON line iterator:
  - Continuous token flow → no `StreamSlow`, natural `StreamDone`.
  - Silence for 35 s then tokens → exactly one `StreamSlow`, no abort.
  - Silence forever → `StreamSlow` at 30 s, `StreamAborted` at 120 s,
    generator terminates.
  - Two silence phases separated by tokens → two `StreamSlow`, no abort.
  The injected clock is required because real-time tests would take two
  minutes each.

- **Inference handler** (`_inference.py`):
  - `StreamSlow` propagates as `ChatStreamSlowEvent`; local status stays
    `"completed"`; tool loop continues.
  - `StreamAborted` sets local status to `"aborted"`, emits a
    `ChatStreamErrorEvent` with `error_code="stream_aborted"` and
    `recoverable=True`, emits `ChatStreamEndedEvent` with
    `status="aborted"`, breaks the tool loop.
  - `StreamAborted` with no prior content does not call `save_fn`.
  - `StreamAborted` with prior content calls `save_fn(..., status="aborted")`.

- **Repository** (`_repository.py`):
  - `save_message(..., status="aborted")` writes the field.
  - `list_messages` on a legacy document without `status` yields a DTO
    with `status="complete"`.

- **Context filter** (`_orchestrator.py`):
  - Mixed history with complete and aborted assistant messages → only
    complete assistants reach pair selection; user prompts are preserved
    regardless.

### Frontend

- **`chatStore`** unit tests:
  - `CHAT_STREAM_SLOW` sets `streamingSlow=true`.
  - `CHAT_CONTENT_DELTA` clears it.
  - `CHAT_STREAM_STARTED` resets it.
  - `CHAT_STREAM_ENDED` with `status="aborted"` persists the message
    with `status="aborted"` and clears `streamingSlow`.
  - `regenerateLast(sessionId)` dispatches the same payload as the
    manual regenerate path.

- **`useChatStream`** handler tests:
  - `CHAT_STREAM_ERROR` with `recoverable=true` calls
    `notificationStore.addNotification` with an action button.
  - `CHAT_STREAM_ERROR` with `error_code="session_expired"` does not
    call the notification store.
  - The action button's callback calls `chatStore.regenerateLast` with
    the session ID that was current when the event arrived.

- **`AssistantMessage`** render tests:
  - `status="complete"` → no warning band.
  - `status="aborted"` → warning band visible with expected text.

### Manual verification

1. Happy path: normal short response → no slow hint, no warning band,
   no toast.
2. Long stream: a multi-minute response with continuous token flow →
   no slow hint (budget resets on every delta).
3. Simulated silence: run the backend with `LLM_STREAM_ABORT_SECONDS=5`
   and a debug adapter that stops emitting after 1 s → slow hint
   appears after 30 s (or reduced slow threshold for the test),
   abort toast with regenerate action appears at the abort deadline,
   warning band survives a browser refresh.
4. Refresh test: produce an aborted message, reload the page, confirm
   the warning band is still rendered (`status` came from MongoDB).
5. Context filter: regenerate after an abort, inspect backend logs for
   the LLM call payload, confirm the aborted assistant content is not
   present. The previous user prompt must still be present.
6. Error toast without content: break the Ollama Cloud API key → toast
   fires, no warning-band message appears in history because nothing
   was persisted.

---

## Migration & Rollout

- **MongoDB:** no migration. The new `status` field is added to new
  documents; legacy documents are defaulted on read.
- **Redis Streams:** the new `chat.stream.slow` event type is unknown
  to old clients. The existing EventBus dispatcher already tolerates
  unknown types (no exception is raised on unmatched events).
- **No feature flag.** All changes are strictly additive: a new event
  type, a new optional field on an existing DTO, a new optional prop
  on a UI component, a new environment variable with a sensible default.
- **Rollout order** within a single feature branch:
  1. Shared contracts (topics, events, DTOs).
  2. Backend adapter state machine.
  3. Backend inference handler.
  4. Backend repository and orchestrator.
  5. Frontend store and event handler.
  6. Frontend UI components.
  7. `.env.example` and `README.md` documentation.
  8. Tests alongside each layer via the TDD path.
  9. `pnpm run build` and `uv run python -m py_compile` verification.
  10. Manual verification per the section above.
  11. Commit and merge to master.

## Risks & Trade-offs

- **120 s may be too tight for very large artefacts on slow providers.**
  If this materialises, the abort deadline can be extended via
  `LLM_STREAM_ABORT_SECONDS` without a code change.
- **Spurious slow hint on a one-off upstream hiccup.** The hint
  disappears as soon as tokens resume. This is the desired behaviour.
- **Context-filtering aborted assistant messages is a deliberate
  context-hygiene choice**, aligned with the project's "keep the
  context tidy" principle. If a future use case needs the aborted
  content in context (e.g. for "continue from here" semantics), it
  will require an explicit opt-in mechanism.

## Out of Scope / Future Work

- Provider-specific refusal detection via `done_reason` or equivalent
  explicit signals (Schub 2).
- Heuristic refusal detection by text matching — explicitly rejected
  as too unreliable and language-dependent.
- Persisting artefact tool-call references on chat messages so an
  artefact pill survives stream end (Schub 3).
- Adaptive slow/abort thresholds based on whether a tool call is in
  flight. Deferred until empirical evidence shows the fixed thresholds
  are insufficient.
- Upstream-level keep-alive pings from Ollama Cloud. Outside our
  control; the two-stage gutter is our workaround.
