# Refusal Detection & Artefact Persistence — Design

**Date:** 2026-04-11
**Status:** Design approved, ready for implementation
**Schübe:** Combines Schub 2 (Refusal detection) and Schub 3 (Artefact tool call persistence) from `STREAM-ABORT-FOLLOWUPS.md`, plus the opportunistic Schub 4.1 fix (`usage` persistence) as a piggyback.
**Predecessor:** `2026-04-11-stream-abort-and-error-toasts-design.md` (Schub 1)

---

## Context

Schub 1 delivered the abort/slow gutter state machine and the error-toast infrastructure. Two explicitly-deferred follow-ups remain from the same brainstorming session:

- **Schub 2 — Refusal detection.** When an LLM provider explicitly signals that it refused a request (via `done_reason="content_filter"` or similar), Chatsune should mark the message, filter it from subsequent LLM context (refusals poison context), and surface the refusal in the UI with a red warning band — clearly distinct from the amber abort band.
- **Schub 3 — Artefact tool call persistence.** Currently, an artefact card created during a stream disappears the moment the stream ends because the frontend clears `activeToolCalls` on `finishStreaming`. After a page refresh there is no visual trace of the artefact in the chat history — even though the artefact itself is safely in the database. Schub 3 persists references on the chat message so the card survives both.

During code exploration for this spec, a third drift was noticed: the `usage` dict computed in `_inference.py` during `StreamDone` handling is passed to `save_fn` but the orchestrator closure does not forward it to `repo.save_message()`. The Schub 1 spec called for `usage` persistence on line 262; the shipped code did not deliver it. Because we are already modifying `save_message`, the `save_fn` closure, and `message_to_dto` for this spec, fixing the `usage` gap costs roughly five extra lines. It is bundled in here as a piggyback.

Combining both schübe into one spec and one merge is the right call because:
- The two schübe touch the same files at the same seams (`ChatMessageDto`, `save_message`, `message_to_dto`, `MessageList.tsx`, `useChatStream.ts`, `AssistantMessage.tsx`).
- The DTO migration happens exactly once, not twice.
- The beta ships tomorrow morning and a single coordinated change is faster and less error-prone than two sequential merges.

---

## Goals

1. Detect refusals from Ollama (and any OpenAI-compatible upstream surfaced through Ollama Cloud) via `done_reason` matching, and signal them through the adapter event pipeline as a first-class `StreamRefused` event.
2. Persist refused assistant messages with a new `status="refused"` literal, including an optional `refusal_text` field for providers that surface a dedicated refusal body.
3. Filter refused messages from LLM context the same way aborted messages are filtered (protection from poison-context behaviour).
4. Render refused messages in the chat history with a red warning band (reserved colour — amber stays for interrupted/incomplete from Schub 1).
5. Show a refusal toast on the live stream with a Regenerate button — refusals can be retried because some models refuse inconsistently.
6. Persist references to `create_artefact` and `update_artefact` tool calls on the chat message, so the `ArtefactCard` survives stream end and page refresh.
7. Piggyback: persist `usage` (`input_tokens`, `output_tokens`) on chat messages, closing the Schub 1 gap noted above.

## Non-Goals

- **No heuristic refusal detection.** Chatsune only catches refusals that the provider explicitly signals (structured field). No text-pattern matching. Models that stream a refusal as natural prose and end with `done_reason="stop"` flow through as normal completed content — this is accepted, documented, and consistent with the decision from the original brainstorming session.
- **No gutter clock test-injection rework** (Schub 4.2 stays deferred).
- **No OpenAI-native adapter work.** Chatsune will not add a direct OpenAI adapter; Ollama Cloud is the only upstream bridge.
- **No generalisation of `artefact_refs` into a polymorphic `tool_call_refs`.** We keep the field narrow and purpose-built. YAGNI.

---

## Design

### 1. Shared contracts

Three shared files change. All changes are additive — no existing field is removed, no Mongo migration is required.

#### `shared/events/chat.py`

**`ChatStreamEndedEvent.status`** gains a fifth literal:

```python
class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    message_id: str | None = None
    status: Literal["completed", "cancelled", "error", "aborted", "refused"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float = 0.0
    timestamp: datetime
```

**`ChatToolCallCompletedEvent`** gains an optional `artefact_ref` field. Because `ArtefactRefDto` is defined in `shared/dtos/chat.py`, `shared/events/chat.py` must import it at the top of the module:

```python
from shared.dtos.chat import ArtefactRefDto  # new import

class ChatToolCallCompletedEvent(BaseModel):
    type: str = "chat.tool_call.completed"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    success: bool
    artefact_ref: ArtefactRefDto | None = None  # populated only for create/update_artefact
    timestamp: datetime
```

The field is only populated when `tool_name in ("create_artefact", "update_artefact")` and the tool execution succeeded. For every other tool call, the field stays `None`. This lets the frontend capture the full ref (including `artefact_id`) without polling the tool result and without changing the semantics of any existing event consumer.

No new `ChatStreamRefusedEvent` and no new topic. Refusals flow through the existing `ChatStreamErrorEvent` channel with `error_code="refusal"` and `recoverable=True`. The frontend toast handler is already generic over error codes; only the toast title text is specialised.

**`ChatStreamEndedEvent` status propagation**: Adding `"refused"` to the status literal on the shared event is the only contract change required. The backend emission path in `_orchestrator.py`/`_inference.py` already threads the local `status` variable into the event at the end of the inference loop; the new literal flows through without further structural change.

#### `shared/dtos/chat.py`

New DTO class:

```python
class ArtefactRefDto(BaseModel):
    artefact_id: str
    handle: str
    title: str
    artefact_type: str
    operation: Literal["create", "update"]
```

**`ChatMessageDto`** gains three new optional fields and an extended status literal:

```python
class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    attachments: list[AttachmentRefDto] | None = None
    web_search_context: list[WebSearchContextItemDto] | None = None
    knowledge_context: list[dict] | None = None
    vision_descriptions_used: list[VisionDescriptionSnapshotDto] | None = None
    created_at: datetime
    status: Literal["completed", "aborted", "refused"] = "completed"
    # New — Schub 2
    refusal_text: str | None = None
    # New — Schub 3
    artefact_refs: list[ArtefactRefDto] | None = None
    # New — Schub 4.1 piggyback
    usage: dict | None = None
```

- `refusal_text`: carries an optional provider-supplied refusal body. For Ollama-delivered refusals this will usually stay `None` because the refusal arrives as ordinary `content` deltas. The field is there for providers that surface a structured refusal body on the final chunk and for the fallback-text path when content is empty.
- `artefact_refs`: analogous to `web_search_context` in shape and persistence pattern, but artefact-specific.
- `usage`: `{"input_tokens": int, "output_tokens": int}` or `None`. Optional so legacy documents and future provider responses without usage info continue to work.

#### `shared/topics.py`

No new constants. Everything flows through the existing `CHAT_STREAM_ERROR`, `CHAT_STREAM_ENDED`, and `CHAT_TOOL_CALL_COMPLETED` topics.

---

### 2. Adapter layer — `backend/modules/llm/_adapters/_events.py`

New event class, added beside `StreamAborted`:

```python
class StreamRefused(BaseModel):
    """Provider explicitly signalled a refusal. Terminal event on this stream.

    Either the provider emitted a known refusal marker in done_reason
    (e.g. content_filter), or a dedicated refusal field was present in
    the final chunk. Refusals are distinct from errors: the stream
    itself was healthy, the model simply declined.
    """
    reason: str                       # raw done_reason value, e.g. "content_filter"
    refusal_text: str | None = None   # optional structured refusal body
```

Added to the `ProviderStreamEvent` union:

```python
ProviderStreamEvent = (
    ContentDelta
    | ThinkingDelta
    | ToolCallEvent
    | StreamDone
    | StreamError
    | StreamSlow
    | StreamAborted
    | StreamRefused
)
```

---

### 3. Adapter layer — `backend/modules/llm/_adapters/_ollama_base.py`

**New module-level detector** (placed near the imports, before the class):

```python
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def _is_refusal_reason(reason: str | None) -> bool:
    """Return True if the Ollama done_reason value marks a refusal.

    Case-insensitive. Extension point: when new upstream providers are
    observed in production logs emitting other refusal markers, add
    them here. This function is unit-tested against synthetic NDJSON.
    """
    if not reason:
        return False
    return reason.lower() in _REFUSAL_REASONS
```

**In `stream_completion`**, the final-chunk branch is extended. Current code (simplified, around line 240):

```python
if chunk.get("done"):
    seen_done = True
    yield StreamDone(
        input_tokens=chunk.get("prompt_eval_count"),
        output_tokens=chunk.get("eval_count"),
    )
    break
```

Becomes:

```python
if chunk.get("done"):
    seen_done = True
    done_reason = chunk.get("done_reason")

    # Observability: surface any non-vanilla done_reason value so we can
    # discover new refusal markers from the field after rollout.
    if done_reason and done_reason not in ("stop", "length"):
        _log.info(
            "ollama_base.done_reason model=%s reason=%s",
            payload.get("model"), done_reason,
        )

    if _is_refusal_reason(done_reason):
        msg = chunk.get("message", {})
        refusal_body = msg.get("refusal") or None
        yield StreamRefused(
            reason=done_reason,
            refusal_text=refusal_body,
        )
        return  # Refusal is terminal; no StreamDone after this.

    yield StreamDone(
        input_tokens=chunk.get("prompt_eval_count"),
        output_tokens=chunk.get("eval_count"),
    )
    break
```

Important details:
- `stop` and `length` are filtered out of the observability log to keep signal high; they are the normal termination reasons.
- The refusal branch `return`s early — no `StreamDone` is emitted after a refusal. Consumers that expect exactly one terminal event get exactly one.
- `message.refusal` is read optimistically. For most current Ollama responses this field will not exist and `refusal_body` will be `None`; the downstream render path is prepared to use `content` or the fallback string in that case.

---

### 4. Inference layer — `backend/modules/chat/_inference.py`

#### 4a. New match arm for `StreamRefused`

Added to the match block over `ProviderStreamEvent` (currently around lines 102–160):

```python
case StreamRefused() as refused:
    _log.warning(
        "chat.stream.refused session=%s correlation_id=%s reason=%s",
        session_id, correlation_id, refused.reason,
    )
    status = "refused"
    iter_refusal_text = refused.refusal_text
    await emit_fn(ChatStreamErrorEvent(
        correlation_id=correlation_id,
        error_code="refusal",
        recoverable=True,  # decision S2-a, explained below
        user_message=refused.refusal_text or _REFUSAL_FALLBACK_TEXT,
        timestamp=datetime.now(timezone.utc),
    ))
```

The loop-local `iter_refusal_text: str | None = None` is initialised near the top of the per-iteration block alongside `iter_content` and `iter_thinking`. On a clean turn it stays `None` and flows through `save_fn` as `None`.

`_REFUSAL_FALLBACK_TEXT` is a module-level constant defined at the top of `_inference.py`:

```python
_REFUSAL_FALLBACK_TEXT = "The model declined this request."
```

This constant is also the single source of truth for the frontend fallback string (mirrored in `AssistantMessage.tsx`), so that the user sees identical wording regardless of which path (live event vs. persisted reload) drove the render.

The `recoverable=True` decision is deliberate (see `STREAM-ABORT-FOLLOWUPS.md` Schub 2, decision S2-a, revised in the design session): some local and cloud models refuse inconsistently; for user-facing refusals the Regenerate affordance is worth keeping.

#### 4b. Artefact capture in the tool loop

Added beside the existing web-search capture (currently lines 200–260). A new loop-local list is initialised at the top alongside `web_search_context` and `knowledge_context`:

```python
artefact_refs: list[dict] = []
```

Inside the tool loop, the existing `ChatToolCallCompletedEvent` emission block is restructured: the artefact-capture step runs **before** the emission so the computed ref can be attached to the event. The existing `web_search`/`knowledge_search` capture blocks that currently live **after** the emission are unchanged and remain where they are — only the new artefact block moves above the emission.

```python
ref_for_event: ArtefactRefDto | None = None
if tc.name in ("create_artefact", "update_artefact"):
    try:
        parsed = json.loads(result_str)
        if isinstance(parsed, dict) and parsed.get("ok"):
            ref_dict = {
                "artefact_id": parsed.get("artefact_id", ""),
                "handle": parsed.get("handle") or arguments.get("handle", ""),
                "title": arguments.get("title", ""),
                "artefact_type": arguments.get("type", ""),
                "operation": (
                    "create" if tc.name == "create_artefact" else "update"
                ),
            }
            artefact_refs.append(ref_dict)
            ref_for_event = ArtefactRefDto(**ref_dict)
    except (json.JSONDecodeError, TypeError):
        pass

await emit_fn(ChatToolCallCompletedEvent(
    correlation_id=correlation_id,
    tool_call_id=tc.id,
    tool_name=tc.name,
    success=tool_success,
    artefact_ref=ref_for_event,
    timestamp=datetime.now(timezone.utc),
))
```

Details:
- `update_artefact` results do not carry an `artefact_id` — the update result is `{"ok": true, "handle": ..., "version": ...}`. In that case `artefact_id` ends up empty, which is acceptable because `ArtefactCard` opens the overlay via `handle`, not `artefact_id`. The empty-string case is documented in Risks.
- The append order matches the order of tool calls within the turn, satisfying the chronological ordering requirement (S3-c).
- Failed tool calls (result shaped like `{"error": "..."}`) fall through without appending to `artefact_refs` — no phantom cards for failed calls.

#### 4c. `save_fn` call extended

Current code (around lines 304–313):

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

Becomes:

```python
if full_content or status == "refused":
    resolved_status: Literal["completed", "aborted", "refused"] = (
        "refused" if status == "refused"
        else "aborted" if status == "aborted"
        else "completed"
    )
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        usage=usage,
        web_search_context=web_search_context or None,
        knowledge_context=knowledge_context or None,
        artefact_refs=artefact_refs or None,
        refusal_text=iter_refusal_text,
        status=resolved_status,
    )
```

Two things changed:
1. The guard `if full_content:` became `if full_content or status == "refused":`, so content-less refusals are still persisted. This is the central decision from design section 1 — users see the refusal in history even if the provider sent no body.
2. New kwargs `artefact_refs` and `refusal_text` are added to the call.

The `status` computation is extracted into `resolved_status` for readability and because the ternary grew a third branch.

---

### 5. Orchestrator — `backend/modules/chat/_orchestrator.py`

#### 5a. Context filter extension

Current code (lines 311–314):

```python
history_docs = [
    d for d in history_docs
    if d.get("status", "completed") != "aborted"
]
```

Becomes:

```python
history_docs = [
    d for d in history_docs
    if d.get("status", "completed") not in ("aborted", "refused")
]
```

The default `"completed"` preserves legacy documents without a `status` field.

#### 5b. `save_fn` closure

The closure that wraps `repo.save_message()` (lines 485–503) is extended to accept and forward the new kwargs. Current signature approximately:

```python
async def save_fn(
    content: str,
    thinking: str | None = None,
    usage: dict | None = None,
    web_search_context: list | None = None,
    knowledge_context: list | None = None,
    status: Literal["completed", "aborted"] = "completed",
) -> str:
    doc = await repo.save_message(
        session_id=session_id,
        role="assistant",
        content=content,
        token_count=_compute_token_count(content, thinking),
        thinking=thinking,
        web_search_context=web_search_context,
        knowledge_context=knowledge_context,
        status=status,
    )
    return doc["_id"]
```

Becomes:

```python
async def save_fn(
    content: str,
    thinking: str | None = None,
    usage: dict | None = None,
    web_search_context: list | None = None,
    knowledge_context: list | None = None,
    artefact_refs: list | None = None,
    refusal_text: str | None = None,
    status: Literal["completed", "aborted", "refused"] = "completed",
) -> str:
    doc = await repo.save_message(
        session_id=session_id,
        role="assistant",
        content=content,
        token_count=_compute_token_count(content, thinking),
        thinking=thinking,
        usage=usage,                         # Schub 4.1 piggyback
        web_search_context=web_search_context,
        knowledge_context=knowledge_context,
        artefact_refs=artefact_refs,         # Schub 3
        refusal_text=refusal_text,           # Schub 2
        status=status,
    )
    return doc["_id"]
```

The `usage=usage` line is the fix that closes the Schub 4.1 gap: the value is already passed into the closure today, it was simply never being forwarded.

---

### 6. Repository — `backend/modules/chat/_repository.py`

#### 6a. `save_message` signature

Extended signature (current lines 301–314):

```python
async def save_message(
    self,
    session_id: str,
    role: str,
    content: str,
    token_count: int,
    thinking: str | None = None,
    usage: dict | None = None,                        # Schub 4.1 piggyback
    web_search_context: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,
    attachment_ids: list[str] | None = None,
    attachment_refs: list[dict] | None = None,
    vision_descriptions_used: list[dict] | None = None,
    artefact_refs: list[dict] | None = None,          # Schub 3
    refusal_text: str | None = None,                  # Schub 2
    status: Literal["completed", "aborted", "refused"] = "completed",
) -> dict:
    now = datetime.now(UTC)
    doc = {
        "_id": str(uuid4()),
        "session_id": session_id,
        "role": role,
        "content": content,
        "thinking": thinking,
        "token_count": token_count,
        "created_at": now,
        "status": status,
    }
    if usage:
        doc["usage"] = usage
    if web_search_context:
        doc["web_search_context"] = web_search_context
    if knowledge_context:
        doc["knowledge_context"] = knowledge_context
    if attachment_ids:
        doc["attachment_ids"] = attachment_ids
    if attachment_refs:
        doc["attachment_refs"] = attachment_refs
    if vision_descriptions_used:
        doc["vision_descriptions_used"] = vision_descriptions_used
    if artefact_refs:
        doc["artefact_refs"] = artefact_refs
    if refusal_text:
        doc["refusal_text"] = refusal_text
    await self._messages.insert_one(doc)
    return doc
```

All three new fields use the existing pattern of only setting the key if the value is truthy, keeping legacy-compatible documents minimal.

#### 6b. `message_to_dto`

The read path (lines 484–542) gains three new read-backs:

```python
@staticmethod
def message_to_dto(doc: dict) -> ChatMessageDto:
    # ... existing web_search_context, attachments, vision_descriptions_used reads ...

    raw_artefact_refs = doc.get("artefact_refs")
    artefact_refs = (
        [
            ArtefactRefDto(
                artefact_id=ref.get("artefact_id", ""),
                handle=ref.get("handle", ""),
                title=ref.get("title", ""),
                artefact_type=ref.get("artefact_type", ""),
                operation=ref.get("operation", "create"),
            )
            for ref in raw_artefact_refs
        ]
        if raw_artefact_refs
        else None
    )

    return ChatMessageDto(
        id=doc["_id"],
        session_id=doc["session_id"],
        role=doc["role"],
        content=doc["content"],
        thinking=doc.get("thinking"),
        token_count=doc["token_count"],
        attachments=attachments,
        web_search_context=ws_ctx,
        knowledge_context=doc.get("knowledge_context"),
        vision_descriptions_used=vision_snaps,
        created_at=doc["created_at"],
        status=doc.get("status", "completed"),
        refusal_text=doc.get("refusal_text"),
        artefact_refs=artefact_refs,
        usage=doc.get("usage"),
    )
```

`doc.get(...)` with a default of `None` keeps legacy documents valid: absent fields simply yield `None`, and the DTO defaults them to `None` as well.

---

### 7. Frontend types — `frontend/src/core/api/chat.ts`

New type and extended interface:

```typescript
export interface ArtefactRef {
  artefact_id: string
  handle: string
  title: string
  artefact_type: string
  operation: 'create' | 'update'
}

export interface ChatMessageDto {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  thinking: string | null
  token_count: number
  attachments: AttachmentRefDto[] | null
  web_search_context: WebSearchContextItem[] | null
  knowledge_context: RetrievedChunkDto[] | null
  vision_descriptions_used?: VisionDescriptionSnapshot[] | null
  created_at: string
  status?: 'completed' | 'aborted' | 'refused'
  refusal_text?: string | null
  artefact_refs?: ArtefactRef[] | null
  usage?: { input_tokens?: number; output_tokens?: number } | null
}
```

The implementer must also extend any TypeScript mirror of `ChatToolCallCompletedEvent` — search for `chat.tool_call.completed` in the frontend and add the optional `artefact_ref?: ArtefactRef | null` field wherever a payload interface is declared.

---

### 8. Frontend UI — `frontend/src/features/chat/AssistantMessage.tsx`

#### 8a. Props extension

```typescript
interface AssistantMessageProps {
  content: string
  thinking: string | null
  isStreaming: boolean
  accentColour: string
  highlighter: Highlighter | null
  isBookmarked?: boolean
  onBookmark?: () => void
  canRegenerate?: boolean
  onRegenerate?: () => void
  status?: 'completed' | 'aborted' | 'refused'
  refusalText?: string | null
}
```

#### 8b. Content render hierarchy

A module-level constant at the top of `AssistantMessage.tsx` mirrors the backend fallback string so both paths (live stream event and persisted reload) show the same text:

```tsx
const REFUSAL_FALLBACK_TEXT = 'The model declined this request.'
```

The main content render (currently `<MarkdownRenderer content={content} ... />`) resolves `effectiveContent` first:

```tsx
const effectiveContent = (() => {
  if (content) return content
  if (refusalText) return refusalText
  if (status === 'refused') return REFUSAL_FALLBACK_TEXT
  return ''
})()

return (
  <div>
    {effectiveContent && (
      <MarkdownRenderer content={effectiveContent} ... />
    )}
    {/* ... existing aborted amber band ... */}
    {/* ... new refused red band (below) ... */}
  </div>
)
```

This implements the render rule from design section 1: content beats refusalText beats fallback string. All three paths for `status === 'refused'` converge on the same short wording, matching the `_REFUSAL_FALLBACK_TEXT` constant in `_inference.py`.

#### 8c. New refused red band

Placed beside the existing amber aborted band (currently lines 43–66):

```tsx
{status === 'refused' && !isStreaming && (
  <div className="mt-2 flex items-start gap-2 rounded-md border border-red-400/40 bg-red-500/5 px-3 py-2">
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      className="text-red-400 mt-0.5 shrink-0"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
    <div className="text-[11px] leading-snug text-red-200/90">
      The model declined this request. Click <strong>Regenerate</strong> to try again.
    </div>
  </div>
)}
```

The "crossed circle" icon is chosen deliberately to be semantically distinct from the amber triangle used for interrupts. Colour language across the app: **amber = interrupted, red = refused**. Keep this consistent.

---

### 9. Frontend UI — `frontend/src/features/chat/MessageList.tsx`

The persisted-messages map gains an `ArtefactCard` render pass between `KnowledgePills` and `AssistantMessage`:

```tsx
{messages.map((msg, i) => {
  // ... existing user-message branch ...

  if (msg.role === 'assistant') {
    return (
      <div key={msg.id}>
        <div id={`msg-${msg.id}`} />
        {msg.web_search_context && msg.web_search_context.length > 0 && (
          <WebSearchPills items={msg.web_search_context} />
        )}
        {msg.knowledge_context && msg.knowledge_context.length > 0 && (
          <KnowledgePills items={msg.knowledge_context} />
        )}
        {msg.artefact_refs && msg.artefact_refs.length > 0 && (
          <div className="my-2 flex flex-col gap-2">
            {msg.artefact_refs.map((ref) => (
              <ArtefactCard
                key={`${msg.id}-${ref.artefact_id || ref.handle}-${ref.operation}`}
                handle={ref.handle}
                title={ref.title}
                artefactType={ref.artefact_type}
                isUpdate={ref.operation === 'update'}
                sessionId={sessionId!}
              />
            ))}
          </div>
        )}
        <AssistantMessage
          content={msg.content}
          thinking={msg.thinking}
          isStreaming={false}
          accentColour={accentColour}
          highlighter={highlighter}
          isBookmarked={isBm}
          onBookmark={() => onBookmark(msg.id)}
          canRegenerate={canRegenerate && i === lastAssistantIdx}
          onRegenerate={onRegenerate}
          status={msg.status ?? 'completed'}
          refusalText={msg.refusal_text ?? null}
        />
      </div>
    )
  }
  return null
})}
```

The `key` composition falls back to `handle` when `artefact_id` is empty (the `update_artefact` case), keeping React keys unique across renders.

The live-streaming block below (the `{isStreaming && (...)}` section that renders `activeToolCalls`) is **unchanged**. The live path and the persisted path are intentionally two separate render trees. Duplication is acceptable because the live path renders from the `activeToolCalls` transient state, and the persisted path renders from the committed `msg.artefact_refs` field — they serve different concerns and cannot be unified without adding edge cases.

---

### 10. Frontend stream — `frontend/src/features/chat/useChatStream.ts`

#### 10a. New store slice: `streamingArtefactRefs`

The chat store gains a new streaming state field alongside `streamingWebSearchContext`:

```typescript
// in chatStore.ts
interface ChatStoreState {
  // ... existing ...
  streamingArtefactRefs: ArtefactRef[]
}

// actions
appendArtefactRef: (ref: ArtefactRef) =>
  set((s) => ({
    streamingArtefactRefs: [...s.streamingArtefactRefs, ref],
  })),

// the streamingRefusalText state
streamingRefusalText: string | null
setStreamingRefusalText: (text: string | null) => void
```

And the `finishStreaming` reducer clears both new fields alongside the existing streaming state:

```typescript
finishStreaming: (finalMessage, contextStatus, fillPercentage) =>
  set((s) => ({
    isWaitingForResponse: false,
    isStreaming: false,
    correlationId: null,
    streamingContent: '',
    streamingThinking: '',
    streamingWebSearchContext: [],
    streamingKnowledgeContext: [],
    streamingArtefactRefs: [],     // new
    streamingRefusalText: null,    // new
    activeToolCalls: [],
    streamingSlow: false,
    messages: [...s.messages, finalMessage],
    contextStatus,
    contextFillPercentage: fillPercentage,
  })),
```

#### 10b. `CHAT_TOOL_CALL_COMPLETED` handler

Appends the `artefact_ref` from the event payload into the new store slice:

```typescript
case Topics.CHAT_TOOL_CALL_COMPLETED: {
  if (event.correlation_id !== getStore().correlationId) return
  getStore().completeToolCall(p.tool_call_id as string)
  const artefactRef = p.artefact_ref as ArtefactRef | null | undefined
  if (artefactRef) {
    getStore().appendArtefactRef(artefactRef)
  }
  break
}
```

#### 10c. `CHAT_STREAM_ERROR` handler — refusal toast title

The existing handler (lines 127–182) is mostly generic. Only the toast title calculation is specialised:

```typescript
const title = (() => {
  if (errorCode === 'refusal') return 'Request declined'
  if (recoverable) return 'Response interrupted'
  return 'Error'
})()
```

Everything else — `action` (the Regenerate button), `level: 'error'`, the `recoverable` flag handling — remains as-is. Because refusals send `recoverable=true` (see design section 4a), the existing action-assembly code path automatically provides the Regenerate button.

The refusal text from the event's `user_message` field is picked up and stored so the `finishStreaming` call can propagate it to the final message. Add alongside the existing `setError` call:

```typescript
if (errorCode === 'refusal') {
  getStore().setStreamingRefusalText(userMessage)
}
```

#### 10d. `CHAT_STREAM_ENDED` handler — assemble final message

The current finalMessage construction (lines 103–119) extends to include the new fields:

```typescript
const backendMessageId = p.message_id as string | undefined
const content = getStore().streamingContent
const thinking = getStore().streamingThinking
const webSearchContext = getStore().streamingWebSearchContext
const knowledgeContext = getStore().streamingKnowledgeContext
const artefactRefs = getStore().streamingArtefactRefs
const refusalText = getStore().streamingRefusalText
const messageStatus = (p.status as 'completed' | 'aborted' | 'refused' | 'error' | 'cancelled') === 'refused'
  ? 'refused'
  : (p.status === 'aborted' ? 'aborted' : 'completed')

if (backendMessageId && (content || thinking || messageStatus === 'refused')) {
  getStore().finishStreaming(
    {
      id: backendMessageId,
      session_id: sessionId,
      role: 'assistant',
      content,
      thinking: thinking || null,
      token_count: 0,
      attachments: null,
      web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
      knowledge_context: knowledgeContext.length > 0 ? knowledgeContext : null,
      artefact_refs: artefactRefs.length > 0 ? artefactRefs : null,
      refusal_text: refusalText || null,
      created_at: new Date().toISOString(),
      status: messageStatus,
    },
    contextStatus,
    fillPercentage,
  )
}
```

The `if (backendMessageId && (content || thinking || messageStatus === 'refused'))` guard is the frontend analogue of the backend `if full_content or status == "refused":` guard — it preserves content-less refusals in the live UI without waiting for a refresh.

---

## Testing

### Backend unit tests

Synthetic tests, no real Ollama required. All tests use fake NDJSON streams piped through the adapter or mocked `emit_fn`/`save_fn` callables.

#### `_ollama_base` — `_is_refusal_reason` and stream parsing

1. **Normal completion stream**: NDJSON with content chunks and a final `{"done": true, "done_reason": "stop", ...}`. Assert the emitted events end with `StreamDone`, no `StreamRefused`, no warning log for `done_reason`.
2. **Content-filter refusal**: NDJSON ending with `{"done": true, "done_reason": "content_filter", "message": {}}`. Assert the final event is `StreamRefused(reason="content_filter", refusal_text=None)` and that no `StreamDone` follows.
3. **Explicit refusal with body**: NDJSON ending with `{"done": true, "done_reason": "refusal", "message": {"refusal": "I can't help with that"}}`. Assert `StreamRefused(reason="refusal", refusal_text="I can't help with that")`.
4. **Unknown `done_reason` value**: NDJSON ending with `{"done": true, "done_reason": "something_new"}`. Assert `StreamDone` is emitted (not refusal), and assert the observability log line `ollama_base.done_reason model=... reason=something_new` was produced (use `caplog`).
5. **Case insensitivity**: `done_reason="Content_Filter"` — expect `StreamRefused` because `_is_refusal_reason` lowercases.
6. **Vanilla reasons do not log**: `done_reason="stop"` and `done_reason="length"` do not emit the info log (avoid noise).

#### `_inference` — refusal handling and artefact capture

7. **Refused match arm**: Feed a stream iterator that yields `ContentDelta("declining...")` then `StreamRefused(reason="content_filter", refusal_text=None)`. Assert:
   - `status = "refused"` at the end
   - `iter_refusal_text` is `None`
   - A `ChatStreamErrorEvent` with `error_code="refusal"`, `recoverable=True` was emitted
   - A warning log `chat.stream.refused session=...` was produced
   - `save_fn` was called with `status="refused"`, content containing "declining..."
8. **Content-less refusal persisted**: Stream yields only `StreamRefused(reason="content_filter", refusal_text=None)` with zero content deltas. Assert `save_fn` is still called (the `or status == "refused"` guard), with empty `content=""` and `refusal_text=None`, `status="refused"`.
9. **Refusal with provider body**: Stream yields `StreamRefused(reason="refusal", refusal_text="I can't help")`. Assert `save_fn` is called with `refusal_text="I can't help"`.
10. **Successful `create_artefact` capture**: Tool-loop fixture simulates a `create_artefact` call with result `{"ok": true, "artefact_id": "a1", "handle": "h1"}`. Assert:
    - `artefact_refs` has one entry with `artefact_id="a1"`, `handle="h1"`, `operation="create"`, `title` and `artefact_type` from the tool call arguments
    - The emitted `ChatToolCallCompletedEvent` has a matching `artefact_ref`
11. **Successful `update_artefact` capture**: Simulates an update with result `{"ok": true, "handle": "h2", "version": 2}` (no `artefact_id`). Assert `artefact_refs` entry has `artefact_id=""`, `operation="update"`, `handle="h2"`.
12. **Failed artefact tool call**: Result is `{"error": "validation failed"}`. Assert `artefact_refs` stays empty and `ChatToolCallCompletedEvent.artefact_ref` is `None`.
13. **Ordering of multiple artefact calls**: Two tool calls in a turn (create then update) — assert `artefact_refs` preserves the order `[create, update]`.

#### `_orchestrator` — context filter

14. **History with mixed statuses**: Inject documents with `status` values `completed`, `aborted`, `refused`. Assert only the `completed` ones survive the filter.
15. **Legacy documents without status**: Documents where `status` is missing default to `completed` and are kept.

#### `_repository` — save and read roundtrip

16. **Full roundtrip with all new fields**: Call `save_message(status="refused", refusal_text="body", artefact_refs=[{"artefact_id": "a1", ...}], usage={"input_tokens": 10, "output_tokens": 5})`. Fetch the document. Run `message_to_dto`. Assert the DTO has all four fields populated correctly.
17. **Legacy document read**: Insert a document without `status`, `refusal_text`, `artefact_refs`, or `usage`. Assert `message_to_dto` returns a DTO with `status="completed"`, `refusal_text=None`, `artefact_refs=None`, `usage=None`.
18. **Empty `artefact_refs` list**: Pass `artefact_refs=[]`. Assert the field is not written to the document (the truthy guard filters empty lists).

### Frontend unit tests

Use the existing Vitest + RTL setup. Mock `useChatStore` where needed.

#### `AssistantMessage`

19. **Refused with content**: Props `{status: "refused", content: "Sorry, I will not help with that", refusalText: null}`. Assert the red band is rendered, and the content "Sorry, I will not help with that" is shown in the main area.
20. **Refused with empty content and refusalText**: Props `{status: "refused", content: "", refusalText: "Model declined"}`. Assert the red band is rendered, and "Model declined" is shown in the main area.
21. **Refused with empty content and no refusalText**: Props `{status: "refused", content: "", refusalText: null}`. Assert the red band is rendered, and the fallback string "The model declined this request." (matching `REFUSAL_FALLBACK_TEXT`) is shown.
22. **Completed message with refusalText accidentally set**: Props `{status: "completed", content: "Hello", refusalText: "Stray"}`. Assert the main content is "Hello" (refusalText is ignored when content is present and status is not refused).
23. **Aborted band still works**: Regression test — props `{status: 'aborted'}` still renders the amber band, not the red one.

#### `MessageList`

24. **Persisted message with artefact_refs**: Given a message with `artefact_refs: [{handle: 'h1', title: 't1', artefact_type: 'code', operation: 'create', artefact_id: 'a1'}]`, assert that one `ArtefactCard` is rendered with the right props (`isUpdate={false}`).
25. **Persisted message with update operation**: `operation: 'update'` → `ArtefactCard` is rendered with `isUpdate={true}`.
26. **Multiple artefact_refs render in order**: Two refs, first create then update. Assert the two cards render in that order in the DOM.
27. **Persisted message without artefact_refs**: Does not render any extra `ArtefactCard` (regression guard).

#### `useChatStream` / chat store

28. **`CHAT_TOOL_CALL_COMPLETED` with artefact_ref**: Dispatching the event populates `streamingArtefactRefs`.
29. **`CHAT_TOOL_CALL_COMPLETED` without artefact_ref** (e.g. for `web_search`): Does not touch `streamingArtefactRefs`.
30. **`CHAT_STREAM_ERROR` with `error_code="refusal"`**: Toast title is "Request declined", action (Regenerate) is present, `recoverable` respected.
31. **`CHAT_STREAM_ENDED` with `status="refused"`**: `finalMessage` in `finishStreaming` has `status="refused"`, `refusal_text` from the streaming store, `artefact_refs` from the streaming store.
32. **`CHAT_STREAM_ENDED` with content-less refused**: Even with empty `streamingContent`, the final message is still pushed (via the `|| messageStatus === 'refused'` guard).
33. **`finishStreaming` clears new streaming state**: After the reducer runs, `streamingArtefactRefs` and `streamingRefusalText` are reset to empty/`null`.

### Manual verification

Maintained as a separate living checklist at the repo root: **`MANUAL-TESTS-REFUSAL-AND-ARTEFACTS.md`**. Tick items off during the beta smoke test.

---

## Migration & Rollout

- **No Mongo migration.** Every new field on the chat-message document is optional and additive. Legacy documents read correctly through `message_to_dto` because every read uses `doc.get(...)` with a safe default.
- **No new topics.** No WebSocket reconnect logic changes.
- **Coordinated deploy.** Backend and frontend ship together (confirmed by Chris). No feature flag needed.
- **Post-rollout observation window.** For the first two days after the Beta ships, watch the backend logs for `ollama_base.done_reason model=... reason=...` entries to learn which `done_reason` values real providers emit. Any value not in `_REFUSAL_REASONS` that looks like a refusal marker can be added to the frozenset in a follow-up one-liner.

---

## Risks & Trade-offs

1. **Structured-only refusal detection.** Models that stream a refusal as natural prose and end with `done_reason="stop"` flow through as normal `completed` content. The user sees the text but without the red band and without context filtering. This is accepted, consistent with the original brainstorming decision, and documented. The observation window above will tell us whether GPT-OSS (which Chris uses heavily) surfaces refusals as structured markers or as prose.

2. **Empty `artefact_id` for update calls.** The `update_artefact` tool result has no `artefact_id` field, only `handle` and `version`. The persisted ref stores `artefact_id=""`, which is a valid-but-meaningless value. `ArtefactCard` opens via `handle`, so there is no functional impact. React keys fall back to the handle when `artefact_id` is empty. If we ever need to uniquely reference an artefact by ID from a persisted update-ref, we would need the update tool result to include the ID — a small backend change in `backend/modules/artefact/`. Out of scope here.

3. **Piggyback scope creep.** Including the Schub 4.1 `usage` fix in this spec means reviewers see two independent changes bundled together. The line-count cost is tiny (one line in `save_fn`, one line in `save_message`'s new dict-write guard, one line in `message_to_dto`, one TypeScript field), but the conceptual cost is that if a rollback is ever needed, the `usage` piggyback rolls back with it. Judged acceptable because the `usage` fix is purely additive and cannot break any existing reader.

4. **Red-vs-amber colour distinction**. The distinction relies on users perceiving colour. For users with red-green colour blindness the distinction is weaker but still present because the icons are different shapes (amber triangle vs red crossed circle) and the text is different ("interrupted" vs "declined"). No WCAG audit required for the beta.

5. **Refused context filter and Regenerate interaction.** A user clicks Regenerate after a refusal → the new stream runs with the refused message filtered out of context → the retry has a cleaner context and may succeed where the first attempt failed. This is exactly the desired behaviour. The risk is that users may be confused by the message being "gone" from the LLM's perspective even though it is still visible in their UI. The red band text ("Click Regenerate to try again") makes this implicit behaviour explicit enough.

---

## Out of Scope / Future Work

- **Schub 4.2 — Gutter clock test-injection seam.** Documented in `STREAM-ABORT-FOLLOWUPS.md` as a nachzügler from Schub 1. Not touched here.
- **Generalisation of `artefact_refs` to a polymorphic `tool_call_refs`.** Explicitly rejected on YAGNI grounds.
- **Heuristic refusal detection based on text patterns.** Rejected in the original brainstorming for internationalisation reasons.
- **Per-message token cost UI.** `usage` is now persisted, but rendering it in the UI (e.g. a token counter beside each message) is a separate design decision and a separate small schub.
