# Compact and Continue — Design Specification

**Date:** 2026-05-15
**Status:** Approved (pre-implementation)
**Source brief:** [COMPACT-AND-CONTINUE-FEATURE.md](../../COMPACT-AND-CONTINUE-FEATURE.md)
**Scope:** MVP — manual trigger plus a suggest-toast on threshold cross. Auto-mode and related edge handling are out of scope (see §10).

---

## 1. Vision

When the chat context window approaches its limit, the user can — with a single click — distil the earlier portion of the conversation into a compact briefing while keeping the most recent turns verbatim. The conversation then continues seamlessly: the model sees a short briefing plus the tail, the user sees the full chat with a visual marker showing where compaction happened.

Classical compaction (cf. Claude Code `/compact`) shrinks the whole transcript to ~40 %. Our approach is more aggressive — 5–10 % for the older portion, plus an untouched tail — which is materially more token-efficient while preserving conversational coherence.

---

## 2. MVP Scope

### In Scope

- **Manual trigger** via a sparkly button in the chat top-bar, with state-dependent visibility and animation (see §5.1).
- **Suggest-toast** on first crossing of 60 % context fill (non-blocking; suppressed during continuous voice).
- **Re-compaction**: each new checkpoint appends to a list. The model receives only the latest checkpoint as `<conversation_compact>`. When re-compacting, the previous checkpoint's markdown is fed in as "Previous Story" so no information is lost.
- **Visual compaction marker** in the chat (`TimelineEntry.kind = 'compacted'`); click opens a read-only drawer showing the markdown briefing plus metadata.
- **Edit protection** for messages before the latest tail-start; clear error message, no recovery path in MVP.
- **Pre-flight check** that rejects compaction when the source would not fit into the current model's context window.
- **Source truncation** when source > 70 % of model context, with a user-facing note in the success toast.

### Out of Scope (Phase 2)

- Auto-trigger mode (cancel-window, discovery dialog, voice block, model-switch edge cases, offline detection, threshold classes).
- Hierarchical chunking for sources that exceed model capacity (the MVP falls back to truncation plus a hard pre-flight fail).
- User editing of the compact markdown.
- "Remove snapshot" recovery for edit-protection.
- "Open as new session" from a checkpoint.
- Per-session threshold overrides.

---

## 3. Compaction Model Selection

Compaction runs on the **current session model** — `session.model_unique_id` if set, otherwise `persona.model_unique_id`. This mirrors memory-consolidation and matches the project's design guideline of "one model per persona". A dedicated compact-model setting is explicitly deferred to Phase 2.

---

## 4. Data Model

### 4.1 `CompactionCheckpoint`

Lives in `backend/modules/chat/_models.py`:

```python
class CompactionCheckpoint(BaseModel):
    id: str                                  # UUID
    created_at: datetime
    model_unique_id: str                     # which model produced this compact
    summary_markdown: str                    # the briefing itself
    last_message_id_before: str              # last source-range message
    tail_start_message_id: str               # first tail message
    tokens_before: int                       # source tokens (pre-compact)
    tokens_after: int                        # markdown tokens (count_tokens)
    tail_token_count: int                    # tail tokens carried forward
    prev_checkpoint_id: str | None = None    # set on re-compact
```

### 4.2 `ChatSessionDocument` extension

In `backend/modules/chat/_repository.py`:

```python
compaction_checkpoints: list[CompactionCheckpoint] = Field(default_factory=list)
```

Default `[]` satisfies the project's "no more wipes" rule — existing sessions deserialise without error. No migration needed.

**Append semantics**: each new checkpoint is appended. The model only ever sees the most recent one as `<conversation_compact>`. The UI shows all of them chronologically as markers in the chat.

### 4.3 Shared DTO

`shared/dtos/chat.py` carries `CompactionCheckpointDto` with the same shape (the backend `CompactionCheckpoint` either imports it directly or is structurally identical — pattern check at implementation time against existing chat DTOs).

### 4.4 `JobType`

`backend/jobs/types.py` (or wherever `JobType` lives) gains:

```python
class JobType(str, Enum):
    ...
    CHAT_COMPACTION = "chat_compaction"
```

---

## 5. Frontend Flow

### 5.1 Sparkly button — visibility states

Lives in the top-bar (desktop: `ChatView.tsx` near line 1187, right of `ContextStatusPill`; mobile: in the indicator row near line 1222 as an icon-only pill). All visibility states require the minimum-size precondition `total_messages > 12 AND total_tokens > 4000`:

| `context_fill_percentage` | Button state |
|---|---|
| < 30 % | Hidden in top-bar; reachable via settings overflow as "Compact conversation" (greyed with tooltip `"Conversation too short to compact yet"` when minimum-size precondition not met) |
| 30 – 60 % | Hidden in top-bar; active in settings overflow |
| 60 – 75 % | Visible, subtle, tooltip "Compact this conversation?" + suggest-toast once on threshold cross |
| 75 – 90 % | Visible, sparkle animation, tooltip "Context is filling up — compact soon" + modal-hint once on 75 % cross |
| > 90 % | Visible with warning indicator (orange/red), tooltip "Compaction may fail — consider switching to a larger model" |
| Pre-flight fail | Disabled, tooltip "Model context too small to compact — switch to a larger model or start a new session" |

### 5.2 Confirm card

Opened on button click. Contents:

- Current token state: `"87,300 / 128,000 tokens, 68%"`
- Estimated outcome: `"After compact: ~4,000 tokens"` (heuristic: 5–10 % of source plus full tail)
- Explanation: `"The last 6 turns stay verbatim; everything before is condensed into a briefing."`
- Buttons: **Compact** (primary) / **Cancel**

While the job runs: button becomes loading spinner `"✨ Compacting…"`; input area is locked with overlay `"Compacting your conversation — one moment"`.

### 5.3 Suggest-toast

- Trigger: frontend tracks the last seen `context_fill_percentage`; on transition from `< 0.60` to `>= 0.60`, show toast.
- **Hard suppress** when `phase === 'continuous_voice'` (per `usePhase`).
- Content: `"Conversation is at {N}% context. Compact now?"` + buttons **Compact** / **Later**.
- Once per threshold cross — the next toast only appears after a re-cross (i.e. fill must dip below 60 % and come back, which naturally happens after a successful compact).

### 5.4 Compacted marker

A new `TimelineEntry.kind = 'compacted'` in `MessageList.tsx` (current renderer block around lines 94–144).

Rendering:

- Horizontal divider with a centred pill label.
- Pill content: `"✨ Compacted · 14:23 · 87k → 4k tokens"`.
- Click opens a drawer (desktop: right-side slide-over; mobile: bottom-sheet).

Drawer contents (read-only):

- Header: `"Compact snapshot · 14:23 · Llama 3.2 70B"`
- Meta line: `"Original 87,300 tokens → Briefing 4,012 tokens"`
- Body: rendered markdown of `summary_markdown`
- No actions

### 5.5 Toasts after compaction

- **Success**: `"✨ Compacted — saved 83k tokens"`, auto-dismiss ~4 s. When `truncated_message_count > 0`, append `"Note: the {N} oldest messages didn't fit into the briefing."`
- **Failure**: `event.user_message` plus a Retry button when `recoverable: true`; auto-dismiss after 8 s.

### 5.6 Edit-protection in the UI

The pencil button on source-range messages (those before `latest_checkpoint.tail_start_message_id`) is visually greyed with tooltip `"Part of a compact snapshot"`. The backend rejects edit attempts that bypass the UI (§6.5).

### 5.7 WS subscriptions

In `useChatStream.ts` (current handler block 36–150), add handling for:

- `CHAT_COMPACTION_STARTED` → set loading state, lock input.
- `CHAT_COMPACTION_PROGRESS` → optional spinner-text update (MVP: ignore details).
- `CHAT_COMPACTION_COMPLETED` → append checkpoint to session store, render new `compacted` timeline entry, update token pill, show success toast, clear loading state.
- `CHAT_COMPACTION_FAILED` → clear loading state, show failure toast.

A 90 s frontend timeout on the loading overlay drops the input lock if no event arrives, with a soft toast: `"Compaction is taking longer than expected. Reload the page if it doesn't complete soon."` The job is **not** marked failed at this point — it may still complete in the background.

---

## 6. Backend Flow

### 6.1 Trigger handler

New WS handler in `backend/modules/chat/_handlers_ws.py`:

```
handle_chat_compaction_request({ session_id, correlation_id })
```

Steps:

1. **Ownership**: verify the session belongs to the user.
2. **Minimum size**: `total_messages > 12 AND total_tokens > 4000`. Otherwise emit `ChatCompactionFailedEvent(error_code="too_small", recoverable=False)`.
3. **Lower threshold**: `context_fill_percentage >= 0.30`. Otherwise emit `error_code="below_threshold", recoverable=False`.
4. **Idempotency lock**: `SET compaction:lock:{session_id} {correlation_id} NX EX 600`. If the lock is held: emit `error_code="already_running", recoverable=True`.
5. **Determine source range and tail** (helper, see §6.3). Compute `source_tokens`.
6. **Pre-flight check**:
   ```python
   overhead = COMPACTION_SYSTEM_PROMPT_TOKENS + MAX_OUTPUT_TOKENS + SAFETY_MARGIN  # ~3,500
   if source_tokens + overhead > model_context:
       emit ChatCompactionFailedEvent(
           error_code="compaction_source_too_large",
           recoverable=False,
           user_message=(
               "Conversation is too large for the current model to compact. "
               "Switch to a model with a larger context window or start a "
               "new session."
           ),
       )
       release lock
       return
   ```
7. **Resolve `prev_checkpoint_id`**: if `session.compaction_checkpoints` is non-empty, take `session.compaction_checkpoints[-1].id`; otherwise `None`.
8. **Submit job** `JobType.CHAT_COMPACTION` with payload `{ session_id, correlation_id, prev_checkpoint_id }` and `model_unique_id` from session/persona.
9. **Emit** `ChatCompactionStartedEvent` immediately, with `tokens_before` (computed source tokens), `estimated_tokens_after` (heuristic: `max(500, int(tokens_before * 0.08))`), `tail_message_count`.

### 6.2 Job handler

`backend/jobs/handlers/_chat_compaction.py`, modelled on `_memory_consolidation.py`.

Steps:

1. **Duplicate-execution guard**: `redis.set("job:executed:{execution_token}", "1", nx=True, ex=48*3600)` — bail if already set.
2. **Load** session and all messages (chronological).
3. **Determine tail** (see §6.3) → `tail_start_message_id`.
4. **Determine source range**:
   - No previous checkpoint: all messages before `tail_start_message_id`.
   - With `prev_checkpoint_id`: messages between the previous checkpoint's `tail_start_message_id` and the new `tail_start_message_id`.
5. **Sanitise source**: drop tool-role messages and assistant messages that are pure tool calls. User and assistant content messages remain.
6. **Source-token guard** (truncation):
   ```python
   truncation_target = int(model_context * 0.70)
   truncated_count = 0
   while sum(m["token_count"] for m in source_messages) > truncation_target:
       source_messages.pop(0)
       truncated_count += 1
   if truncated_count > 0:
       _log.warning("compaction.source.truncated",
           count=truncated_count, session_id=session_id,
           correlation_id=correlation_id)
   ```
7. **Build compaction prompt** (§6.4). When `prev_checkpoint_id` is present, the previous checkpoint's markdown is folded in as a `## Previous Story (from earlier checkpoint)` block in the user-prompt transcript.
8. **LLM call** via `stream_completion()`:
   - `temperature=0.3`
   - `max_output_tokens=2000`
   - `source="job:chat_compaction"`
   - `extras=ChatSessionExtras(tools_enabled=False, reasoning_mode="off", reasoning_effort=None)`
   - Stream output is collected; no frontend streaming for this job.
9. **Validate output** (§6.5). On failure: one retry with explicit reminder prompt; on second failure, emit `ChatCompactionFailedEvent(error_code="validation_failed", recoverable=True)`.
10. **Persist**: append `CompactionCheckpoint` to `session.compaction_checkpoints`.
11. **Release lock**: `redis.delete("compaction:lock:{session_id}")` (in `finally`).
12. **Emit** `ChatCompactionCompletedEvent` with the new checkpoint, `tokens_saved`, `new_context_used_tokens`, `new_context_fill_percentage`, `truncated_message_count`.

### 6.3 Tail determination

Walk messages from newest to oldest, accumulating `token_count`. Stop when **either** of these is satisfied — whichever yields the **larger** tail:

- 6 turns (12 messages, paired user+assistant) reached, **or**
- 20 % of `model_context_window` accumulated.

Return the `_id` of the oldest message that should remain in the tail (= `tail_start_message_id`).

### 6.4 Compaction prompt

System prompt (verbatim, English):

```
You are a conversation-compaction assistant. Below is a transcript of a
conversation between a user and an AI assistant. Your job is to extract a
structured briefing that allows another AI to seamlessly continue this
conversation in a new context window.

Output rules:
- Output Markdown only. No preamble, no "I have summarised", no meta-commentary.
- Use the exact section headings shown below, in order.
- Be terse but complete. Aim for 5–10 % of the original token count.
- Preserve the user's language preferences, name, and any established facts
  about them.
- Quote critical user phrasings verbatim if they carry intent
  (e.g. preferences, decisions).
- Do not invent information. If a section has no content, write "_(none)_".

Required sections:

## Topic & Goal
What is this conversation about? What is the user trying to achieve?

## Established Facts
Concrete facts, decisions, names, numbers, conclusions reached. Bullet list.

## Open Threads
Questions left unanswered, things the user said they would come back to.

## User Preferences Observed
Communication style, expertise level, language preferences, anything that
should shape how the next AI responds.

## Pending References
Files, URLs, artefacts, tools that the user mentioned and that the next
assistant should know about. Do not paste their content — just reference them
by name.

## Tone & Persona Adherence
One sentence on how the persona has been speaking (formal/informal, etc.).
```

User prompt: the sanitised source messages rendered as plain text, each prefixed with `User:` or `Assistant:`. When `prev_checkpoint_id` is present, the prior briefing is prepended:

```
## Previous Story (from earlier checkpoint)

{previous summary_markdown}

---

## Conversation since the previous checkpoint

User: …
Assistant: …
```

Retry reminder (appended to the system prompt on attempt 2):

```
IMPORTANT: The previous attempt was missing required sections. Output MUST
contain all six headings exactly as specified, in the order shown.
```

### 6.5 Output validation

Validate the model's markdown response:

- Output is non-empty (`len(stripped) > 0`).
- All six required headings are present case-sensitively: `## Topic & Goal`, `## Established Facts`, `## Open Threads`, `## User Preferences Observed`, `## Pending References`, `## Tone & Persona Adherence`.
- No unclosed code fences (count of triple-backtick lines is even).
- No unclosed angle-bracket tags (rudimentary check; the LLM should not emit XML here).

On the first validation failure, retry once with the reminder prompt. On the second failure, emit `validation_failed` (recoverable, so the user can retry manually).

### 6.6 Inference slicer

In `backend/modules/chat/_orchestrator.run_inference` (current entry point around line 605):

```python
all_messages = await repo.list_messages(session_id)
compact_markdown = None
if session.get("compaction_checkpoints"):
    latest = session["compaction_checkpoints"][-1]
    # Locate the tail-start message by ID, then slice by its created_at.
    # Using created_at (not _id) keeps message ordering well-defined even
    # if the ID format changes in future.
    tail_start_msg = next(
        (m for m in all_messages
         if m["_id"] == latest["tail_start_message_id"]),
        None,
    )
    if tail_start_msg is None:
        # Defensive: dangling tail_start_message_id (e.g. message deleted).
        # Log and fall back to full history.
        _log.error("compaction.checkpoint.dangling",
            session_id=session_id,
            tail_start_message_id=latest["tail_start_message_id"])
        history_for_llm = _filter_usable_history(all_messages)
    else:
        cutoff = tail_start_msg["created_at"]
        tail_msgs = [m for m in all_messages if m["created_at"] >= cutoff]
        history_for_llm = _filter_usable_history(tail_msgs)
        compact_markdown = latest["summary_markdown"]
else:
    history_for_llm = _filter_usable_history(all_messages)

system_prompt = await assemble(
    user_id=user_id,
    persona_id=persona_id,
    model_unique_id=model_unique_id,
    project_id=session.get("project_id"),
    supports_reasoning=supports_reasoning,
    extras=extras,
    compact_markdown=compact_markdown,           # new optional parameter
)
```

### 6.7 `assemble()` signature change

`backend/modules/chat/_prompt_assembler.py` — `assemble()` gains a new optional keyword parameter:

```python
async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
    *,
    project_id: str | None = None,
    supports_reasoning: bool = False,
    extras: ChatSessionExtras | None = None,
    compact_markdown: str | None = None,         # new
) -> str:
```

When `compact_markdown` is set, the assembler inserts a block **between the memory layer (current lines 156–164) and the integration extensions (current lines 166–176)**:

```xml
<conversation_compact>
The earlier portion of this conversation has been compacted into the briefing
below. Use it as authoritative context. Do not refer to it explicitly unless
the user asks about earlier topics.

{compact_markdown}
</conversation_compact>
```

The block is omitted entirely when `compact_markdown` is `None`.

### 6.8 Edit protection

In `backend/modules/chat/_handlers_ws.handle_chat_edit` (and `handle_chat_regenerate` if it targets specific message IDs):

```python
checkpoints = session.get("compaction_checkpoints", [])
if checkpoints:
    latest = checkpoints[-1]
    tail_start_msg = await repo.get_message(latest["tail_start_message_id"])
    if tail_start_msg and message["created_at"] < tail_start_msg["created_at"]:
        emit ErrorEvent(
            error_code="edit_before_compact",
            recoverable=False,
            user_message=(
                "This message is part of a compact snapshot and can no "
                "longer be edited. Start a new session if you need to go "
                "back further."
            ),
        )
        return
```

### 6.9 Inflight-edit race

If a user manages to edit a source-range message in the millisecond window between job submission and persistence: the job handler operates on a snapshot of `repo.list_messages()` taken at job start, not on live DB state. The edit handler is also gated by §6.8 against the existing latest checkpoint. Result: no race-window inconsistency.

---

## 7. Events & Contracts

### 7.1 Topics

`shared/topics.py`:

```python
CHAT_COMPACTION_REQUEST = "chat.compaction.request"        # client → server
CHAT_COMPACTION_STARTED = "chat.compaction.started"        # server → client
CHAT_COMPACTION_PROGRESS = "chat.compaction.progress"      # server → client
CHAT_COMPACTION_COMPLETED = "chat.compaction.completed"    # server → client
CHAT_COMPACTION_FAILED = "chat.compaction.failed"          # server → client
```

### 7.2 Events

`shared/events/chat.py`:

```python
class ChatCompactionStartedEvent(BaseModel):
    type: Literal["chat.compaction.started"] = "chat.compaction.started"
    session_id: str
    correlation_id: str
    tokens_before: int
    estimated_tokens_after: int
    tail_message_count: int
    timestamp: datetime

class ChatCompactionProgressEvent(BaseModel):
    type: Literal["chat.compaction.progress"] = "chat.compaction.progress"
    session_id: str
    correlation_id: str
    stage: Literal["preparing", "calling_model", "validating", "persisting"]
    timestamp: datetime

class ChatCompactionCompletedEvent(BaseModel):
    type: Literal["chat.compaction.completed"] = "chat.compaction.completed"
    session_id: str
    correlation_id: str
    checkpoint: CompactionCheckpointDto
    tokens_saved: int
    new_context_used_tokens: int
    new_context_fill_percentage: float
    truncated_message_count: int = 0
    timestamp: datetime

class ChatCompactionFailedEvent(BaseModel):
    type: Literal["chat.compaction.failed"] = "chat.compaction.failed"
    session_id: str
    correlation_id: str
    error_code: Literal[
        "compaction_source_too_large",
        "below_threshold",
        "too_small",
        "already_running",
        "llm_failed",
        "validation_failed",
        "unknown",
    ]
    user_message: str
    recoverable: bool
    timestamp: datetime
```

### 7.3 Scope routing

All compaction events publish with `scope=f"session:{session_id}"` and `target_user_ids=[user_id]`, matching the rest of the chat-event flow. Multiple tabs on the same session stay in sync; other sessions are undisturbed.

---

## 8. Error Handling & Robustness

### 8.1 Lock lifecycle

- **Acquire** in the trigger handler with TTL 600 s.
- **Release** explicitly at end of the job handler (happy path).
- **Release** in a `finally` block on any exception path.
- **Stale lock**: the 10-minute TTL is the backstop for hard crashes (worker killed, process restarted). It blocks parallel trigger clicks but does not strand the user indefinitely.

### 8.2 LLM transport failure

`stream_completion()` may raise on network failure, 4xx, rate limit, etc. The job handler catches `LlmConnectionError` and `LlmStreamError` and emits `ChatCompactionFailedEvent(error_code="llm_failed", recoverable=True, user_message="The model could not be reached. Please try again.")`. The lock is released in `finally`.

### 8.3 Validation failure

Per §6.5: one retry with reminder prompt, then `validation_failed` with `recoverable: true`. The user retries manually.

### 8.4 Job worker crash

If the worker dies mid-job, the lock expires after TTL and the user can retry. The frontend overlay has a 90 s soft-timeout (§5.7): the lock-icon overlay disappears, but the job is not flagged failed — if it completes later, the events still arrive and update the UI.

### 8.5 Dangling checkpoint state

If `tail_start_message_id` points to a message that no longer exists at inference time: §6.6 fallback uses the full history, logs `compaction.checkpoint.dangling`. The user notices nothing; we get an operational signal.

### 8.6 No cancel button in MVP

The job typically runs 5–20 s. The loading overlay locks the input but does not provide a cancel action. The 90 s frontend timeout (§5.7) is the user's "back to work" escape hatch if the job stalls.

---

## 9. Manual Verification Plan

Each scenario is run once. Desktop is the primary surface; mobile is verified separately where UI differs (7.4).

### 9.1 Happy path — desktop manual

1. Build a long conversation (tiktoken-based fill to ~68 %).
2. Sparkly button appears in top-bar, subtle.
3. Click → confirm card shows token forecast.
4. **Compact** → spinner, input locked.
5. After 5–20 s: compacted marker appears, token pill drops to ~10 %, success toast `"Compacted — saved 83k tokens"`.
6. Follow-up question → model answers coherently, references both the tail and topics from the briefing correctly.
7. Click on the compacted pill → drawer shows read-only markdown.

### 9.2 Happy path — suggest-toast

1. Fill conversation until crossing 60 %.
2. Toast appears: `"Conversation is at 64% context. Compact now?"`.
3. Click **Compact** → identical flow to 9.1 from step 4.
4. Alternative: **Later** → toast dismissed, does not return until a re-cross.

### 9.3 Re-compaction

1. After the first compact, continue the session until 65 % again.
2. Trigger a second compact.
3. **Both** compacted markers remain visible chronologically in the chat.
4. Drawer on the first marker shows the old markdown; drawer on the second shows the new (which incorporates the first as "Previous Story").
5. Follow-up question → the model references content from before the first compact (proves the previous-story handoff worked).

### 9.4 Mobile

1. Same conversation on mobile.
2. Mobile indicator row shows the compact icon-pill from 60 %.
3. Tap opens a bottom-sheet (not a confirm card).
4. Compacted marker is centred with a readable touch-target for the drawer.
5. Drawer opens as bottom-sheet, scrollable.

### 9.5 Edit protection

1. After a compact, attempt to edit a source-range message.
2. UI: pencil button is greyed with tooltip.
3. Bypass the UI (via dev tools) and POST an edit → backend rejects with `edit_before_compact`.
4. Tail-range messages remain editable normally.

### 9.6 Pre-flight failure

1. Session on an 8 k model; build until ~90 %.
2. Trigger compact.
3. `ChatCompactionFailedEvent(error_code="compaction_source_too_large")`; toast suggests model switch.
4. Sparkly button becomes disabled with the matching tooltip.

### 9.7 Source truncation

1. Session on a 32 k model; build source > 70 % model context.
2. Trigger compact.
3. Compact succeeds with `truncated_message_count > 0`.
4. Success toast: `"Compacted — saved 28k tokens. Note: the 14 oldest messages didn't fit into the briefing."`
5. Drawer shows the normal briefing.
6. Backend log contains `compaction.source.truncated count=14`.

### 9.8 LLM transport failure

1. Disable the LLM connection.
2. Trigger compact → `ChatCompactionFailedEvent(error_code="llm_failed", recoverable=True)`.
3. Toast offers retry; click triggers a fresh job.
4. Lock has been released: `redis-cli get compaction:lock:{session_id}` → `nil`.

### 9.9 Validation failure with retry

1. With an instrumented prompt that produces malformed output: trigger compact.
2. First attempt is invalid → retry path fires with reminder.
3. Second attempt either valid (success) or invalid (`validation_failed` event).
4. Backend log shows `attempt=2` on the retry.

### 9.10 Continuous-voice suppression

1. Continuous voice active; conversation reaches 65 %.
2. Verify: **no** suggest-toast appears during the voice session.
3. End the voice session → if still over threshold, the toast appears once at the next normal turn end (one-shot per threshold cross).

### 9.11 Backwards compatibility

1. Load a session from the staging dump that pre-dates this feature.
2. Session loads without Pydantic error (`compaction_checkpoints` defaults to `[]`).
3. Compact works normally on this session.

### 9.12 Provider switch with active compact

1. Session on an Ollama model + compact.
2. Switch the session model to an xAI model (different context window).
3. Follow-up question → model still references the compact content correctly. (Markdown is plain text; provider switch has no impact.)

### 9.13 Very short session

1. Fresh session with four turns.
2. Sparkly button in settings overflow is greyed.
3. Tooltip: `"Conversation too short to compact yet"`.

---

## 10. Implementation Order

Inside-out; each step lands as its own commit with build verified (`pnpm run build` for frontend, `uv run python -m py_compile` for changed Python).

1. **Shared contracts** — `Topics`, `JobType`, DTOs, events. Nothing else compiles without these.
2. **Backend data model** — `CompactionCheckpoint` in `_models.py`, `ChatSessionDocument.compaction_checkpoints`. Verify backwards-compat with an old session document.
3. **Job handler** — `_chat_compaction.py` modelled on `_memory_consolidation.py`. Isolated test with a manually constructed session payload.
4. **Inference slicer** — extend `assemble()` signature, add slicing in `run_inference`. Verify that sessions without checkpoints behave exactly as before.
5. **Edit protection** — guard in `handle_chat_edit` (and `handle_chat_regenerate` where applicable).
6. **Trigger handler** — `handle_chat_compaction_request`, Redis lock, pre-flight check, source/tail determination.
7. **Frontend session store** — `compaction_checkpoints` in session state; WS subscriptions for the four compaction topics.
8. **Frontend sparkly button** — desktop and mobile placements, state table from §5.1, confirm card, loading overlay.
9. **Frontend suggest-toast** — 60 % crossing detection, voice suppression.
10. **Frontend compacted marker + drawer** — `TimelineEntry.kind = 'compacted'`, slide-over (desktop) and bottom-sheet (mobile).
11. **Frontend success/failure toasts** — including the truncation note.
12. **Manual verification run** — desktop and mobile against §9.

Phase 1 covers steps 1–11. Step 12 is the verification gate before merge.

---

## 11. Out of Scope (Phase 2+)

For future briefs:

- **Auto-mode** trigger with cancel-window, discovery dialog, voice block, model-switch handling, offline detection, threshold classes.
- **Hierarchical chunking** for source ranges that exceed `model_context * 0.95` after truncation.
- **User editing** of the compact markdown directly in the drawer.
- **Snapshot removal / recovery path** to allow editing source-range messages after compaction.
- **Open as new session** action that uses a checkpoint as the seed for a fresh session.
- **Per-session threshold overrides** (currently per-user, MVP has no setting at all).
- **Dedicated compact-model setting** per user (currently uses the persona's model).
