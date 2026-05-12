# Imported-Conversation Memory Extraction — Design Spec

**Date:** 2026-05-12
**Status:** Draft, awaiting review
**Scope:** Extend the ChatGPT-import feature so imported conversations are
processed by the memory-extraction pipeline. Currently they are persisted as
sessions but never reach the extractor — neither via the periodic loop, the
disconnect trigger, nor the manual button.

---

## 1. Context & Motivation

The ChatGPT-import feature (merged 2026-05-12, PR #8) creates native Chatsune
sessions from a user's ChatGPT export. The original architectural goal was
"ChatGPT conversations become native Chatsune sessions so the existing memory
pipeline picks them up automatically."

That goal is **not met**. Investigation shows the entire memory-extraction
trigger system is gated on a Redis counter
`memory:extraction:{user_id}:{persona_id}`, incremented exclusively by
`track_extraction_trigger` (`backend/modules/chat/_orchestrator.py:1261`),
which is called only from the live inference path. `create_imported_session`
bypasses this trigger.

Consequences:

- **Periodic loop** (`backend/main.py:389`) scans for keys with counter > 0
  — imported personas never appear.
- **Disconnect trigger** (`backend/ws/router.py:122`) uses the same scan —
  same gap.
- **Manual "Extract now" button** is gated on
  `messages_since_extraction >= MIN_MESSAGES` — disabled because the counter
  was never incremented.

The imported messages themselves are valid extraction targets
(`list_unextracted_user_messages` only filters on `role="user"` and missing
`extracted_at`) — nothing reaches them.

Memory-extraction is one of the core value propositions of Chatsune. An
import path that silently skips it ships a half-finished feature.

---

## 2. Goals & Non-Goals

### Goals

- Imported conversations are processed by the memory extractor as part of
  the import flow, without user action.
- Processing happens **chronologically**, oldest ChatGPT conversation first
  (anti-contradiction invariant: later conversations may legitimately
  correct earlier facts; reversed order would mark corrections as
  duplicates and discard them).
- Processing happens **one conversation at a time per persona** so each
  conversation's extraction sees the journal entries created by the
  preceding conversations.
- Per-conversation **progress is visible** in the UI: "3 / 7 extracted".
- On failure (provider unavailable, daily budget exhausted, terminal error)
  the batch **pauses** rather than retries silently. The user sees a
  paused-state UI with **Resume** and **Discard remaining** buttons.
- The live memory-extraction flow continues to work unchanged for
  non-imported sessions and for follow-up messages the user sends in an
  imported session after import.

### Non-Goals

- No re-implementation of the LLM-streaming / prompt-building / parser
  logic. The existing extraction core in
  `backend/jobs/handlers/_memory_extraction.py` is **refactored** into a
  reusable function and called from both the live-chat job handler and
  the new import-batch handler.
- No retroactive backfill of conversations imported before this change.
  Existing imports stay un-extracted; a follow-up admin migration can
  enqueue a batch for them if a user asks.
- No per-message UI feedback inside the extractor itself — progress is
  per conversation, not per chunk. Internal chunking (`limit=20` per LLM
  call) remains an implementation detail.
- No rollback of journal entries on failure (Option B in the design
  discussion): completed work is kept; only the remaining unprocessed
  conversations stop. See §5.

---

## 3. Architecture Overview

### 3.1 Flow

```
User clicks "Import N conversations" in chatgpt_import UI
    │
    ▼
Backend submits N CHATGPT_IMPORT_CONVERSATION jobs (one per conversation,
existing flow, runs in parallel through the job queue)
    │
    ▼
Each per-conversation job:
  - parses conv → CreateImportedSessionRequest
  - calls create_imported_session() → session_id
  - records (chatgpt_conversation_id, persona_id, session_id) in the
    parent chatgpt_imports doc's `import_pairs` array (NEW field, see
    §4.3)
  - atomically increments `conversations_imported` counter on the parent
  - if counter == target_count: submits exactly one
    CHATGPT_IMPORT_MEMORY_BATCH job for (user_id, persona_id, batch_id)
    │
    ▼
CHATGPT_IMPORT_MEMORY_BATCH job:
  - loads parent doc, reads import_pairs filtered to this batch and persona
  - sorts session_ids by original ChatGPT create_time ascending
  - acquires the per-persona memory_extraction in-flight slot with a
    long TTL (1 h, refreshed per session)
  - iterates sessions sequentially:
      - emit ChatGptImportMemoryProgressEvent {session_index, total,
        title, state="extracting"}
      - load up to MAX_MESSAGES_PER_BATCH (e.g. 200) unextracted
        user-messages for this session
      - if none: continue to next session
      - call extract_and_store_messages(...) — the refactored extraction
        core (see §3.2)
      - on success: emit progress with state="done" for that session,
        continue
      - on terminal failure: emit ChatGptImportMemoryPausedEvent
        {reason, recoverable, paused_at_session_index}, persist
        paused-state in parent doc, release slot, return
  - on full completion: emit ChatGptImportMemoryBatchDoneEvent, clear
    paused-state, release slot
```

### 3.2 Extraction-core refactor

Today, `backend/jobs/handlers/_memory_extraction.py::handle_memory_extraction`
mixes three concerns:

1. Job-system housekeeping (in-flight slot, dedup token, retry semantics)
2. Event publishing (started, completed, failed, skipped)
3. The actual extraction: prompt build → LLM stream → parse → dedupe →
   store-in-transaction → mark messages extracted.

We refactor (3) into a pure function in
`backend/modules/memory/_extraction_core.py` (new file, internal to
the memory module per CLAUDE.md boundary rules):

```python
async def extract_and_store_messages(
    *,
    user_id: str,
    persona_id: str,
    session_id: str,
    model_unique_id: str,
    messages: list[str],
    message_ids: list[str],
    correlation_id: str,
    redis,
) -> ExtractionResult:
    """Build prompt, call LLM, parse, store entries + mark messages
    extracted in a single transaction. Returns counts. Raises on
    terminal failure (caller decides retry / pause semantics)."""
```

`ExtractionResult` carries `entries_created: int`,
`messages_processed: int`, `input_tokens`, `output_tokens`.

Both existing live-chat handler and new import-batch handler call this.
The live-chat handler retains its own retry / cooldown / event-publishing
wrappers; the import-batch handler implements its own pause semantics.

Internal chunking: the function reads at most `MAX_LLM_INPUT_MESSAGES`
user-messages per LLM call (current default in live flow is 20). For
sessions with more, the function loops internally until all messages are
processed or until a failure surfaces.

### 3.3 Cross-flow coordination — the in-flight slot

The per-persona slot `memory_extraction_slot_key(user_id, persona_id)`
already serialises extraction. The import-batch handler acquires it with
a 1-hour TTL and refreshes it after every conversation (`redis.expire`).

While the slot is held:

- Live-chat triggers (`track_extraction_trigger` → submit) will see the
  slot via `try_acquire_inflight_slot` and skip submission — they do
  **not** queue. This is correct: live-chat memory for this persona
  briefly waits until the batch finishes.
- Manual "Extract now" UI button reads the same slot and shows
  "Extraction in progress" instead of being clickable. (Today it just
  refuses with 409 if a slot is held; UI follow-up to surface state more
  clearly is **out of scope** here.)

While the batch is **paused** (terminal failure, user has not yet acted):

- The slot is **released** (Resume re-acquires it). Reason: a paused
  batch may sit unresolved for hours; holding the slot would freeze the
  user's live-chat memory for this persona.
- The live-chat flow may pick up new messages in the meantime via the
  normal trigger. Anti-contradiction caveat: if the user writes in an
  *imported* session while the batch is paused, the live flow may extract
  some imported messages out of chronological order across sessions.
  This is an accepted trade-off — see §5.4 for mitigations considered
  and rejected.

---

## 4. Data Model & Contracts

### 4.1 New JobType

In `backend/jobs/_models.py::JobType`:

```python
CHATGPT_IMPORT_MEMORY_BATCH = "chatgpt_import_memory_batch"
```

Registered with the existing job consumer; no special retry semantics —
on terminal failure the handler itself emits the paused event and
returns. The job-system retry mechanism is **disabled** for this type
(`max_retries=0` in `JobConfig`) because we want explicit user-driven
resume, not silent retry.

### 4.2 New Events

In `shared/events/chatgpt_import.py`:

```python
class ChatGptImportMemoryProgressEvent(BaseModel):
    type: Literal["chatgpt_import.memory.progress"] = "chatgpt_import.memory.progress"
    import_id: str
    persona_id: str
    session_id: str
    session_title: str
    session_index: int           # 1-based for UI
    total: int
    state: Literal["extracting", "done"]
    entries_created: int | None = None  # filled when state == "done"
    correlation_id: str
    timestamp: datetime

class ChatGptImportMemoryPausedEvent(BaseModel):
    type: Literal["chatgpt_import.memory.paused"] = "chatgpt_import.memory.paused"
    import_id: str
    persona_id: str
    paused_at_session_index: int     # 1-based
    paused_at_session_id: str
    total: int
    reason: Literal["provider_unavailable", "budget_exhausted", "other"]
    user_message: str                # human-readable reason for the UI
    detail: str | None               # technical message, dev-only
    correlation_id: str
    timestamp: datetime

class ChatGptImportMemoryBatchDoneEvent(BaseModel):
    type: Literal["chatgpt_import.memory.done"] = "chatgpt_import.memory.done"
    import_id: str
    persona_id: str
    total: int
    total_entries_created: int
    correlation_id: str
    timestamp: datetime
```

In `shared/topics.py`:

```python
CHATGPT_IMPORT_MEMORY_PROGRESS = "chatgpt_import.memory.progress"
CHATGPT_IMPORT_MEMORY_PAUSED   = "chatgpt_import.memory.paused"
CHATGPT_IMPORT_MEMORY_DONE     = "chatgpt_import.memory.done"
```

All three published on **two scopes** (matching the existing import
events): `chatgpt_import:{import_id}` (the import-detail tab) and
`persona:{persona_id}` (the persona-detail page surfaces a banner).

### 4.3 Parent-import doc changes

Add three fields to the `chatgpt_imports` collection (§4.1 in the
2026-05-11 import spec):

```python
{
    # ... existing fields ...
    "memory_batch_state": "idle" | "running" | "paused" | "done" | None,
    "memory_batch_paused_at": {
        "session_index": int,
        "session_id": str,
        "reason": str,
        "user_message": str,
        "at": datetime,
    } | None,
    "memory_batch_total_entries_created": int,    # cumulative
}
```

`memory_batch_state == "paused"` is the source of truth for the UI's
Resume button and for the import-batch job's idempotent re-entry on
Resume.

**Backwards compatibility:** existing imports have these fields missing.
Defaults in the Pydantic model handle that (`= None` / `= 0`). No
migration required for read-side compatibility. The fields are populated
the first time the batch handler runs against an import.

### 4.4 New REST endpoints

In `backend/modules/chatgpt_import/_handlers.py`:

```
POST /api/chatgpt_import/{import_id}/memory_batch/resume
    body: { persona_id: str }
    Effect: if memory_batch_state == "paused" and matches persona_id,
            re-submits CHATGPT_IMPORT_MEMORY_BATCH job.
            Returns 409 if state != "paused".

POST /api/chatgpt_import/{import_id}/memory_batch/discard
    body: { persona_id: str }
    Effect: if memory_batch_state == "paused", sets state to "idle",
            clears paused_at, emits ChatGptImportMemoryBatchDoneEvent
            with total_entries_created reflecting what was done so far.
            Does NOT touch journal entries or imported sessions.
            Returns 409 if state != "paused".
```

---

## 5. Failure Modes & Recovery

### 5.1 Failure taxonomy

| Failure | Where | Handling |
|---|---|---|
| Provider unavailable (TCP refused, 5xx) | LLM call | Pause, `reason="provider_unavailable"`, user msg: "Provider {x} not reachable. Try Resume later." |
| Daily budget exhausted | `check_and_reserve_budget` | Pause, `reason="budget_exhausted"`, user msg: "Daily budget exhausted. Resume tomorrow." |
| LLM returns malformed JSON | `parse_extraction_output` | Per-conversation: skip session (entries_created=0), mark its messages extracted, continue batch. Same semantics as live flow for the same failure. |
| Mongo write failure | `repo.create_journal_entry` / `mark_messages_extracted` | Inside a Mongo transaction — atomic rollback. Surface as terminal pause, `reason="other"`. |
| Pydantic / coding error in our handler | anywhere | Pause, `reason="other"`, log full traceback. |
| User closes browser mid-batch | n/a — batch runs in backend | No-op. Job continues. State visible on reconnect via WS catchup. |

### 5.2 Resume semantics

`POST /memory_batch/resume` re-submits the batch job. The handler:

1. Reads `import_pairs` filtered to the persona.
2. Sorts session_ids by original ChatGPT create_time.
3. For each session in order: `list_unextracted_user_messages(session_id)`.
   If empty → session was fully processed in a prior run, skip it.
   If non-empty → process it.

This makes Resume idempotent. Same call works whether the batch was paused
mid-session (last session has partial unextracted) or between sessions
(last processed session has none unextracted).

### 5.3 Discard semantics

`POST /memory_batch/discard` does not delete journal entries or sessions.
It only clears the paused state so the UI stops nagging. The user can
re-trigger extraction later via the existing per-persona manual "Extract"
button, which will then pick up the unextracted messages via the live-flow
path. That path is out-of-order across sessions, but the user has
explicitly opted into that by clicking Discard.

### 5.4 Trade-offs considered

**Holding the in-flight slot while paused:** Rejected because a paused
batch may sit unresolved for hours or days, freezing the user's live
memory extraction for that persona.

**Blocking live-flow extraction for imported messages during paused
state:** Rejected because it requires either (a) tagging individual
messages as "batch-pending", which leaks batch state into the messages
collection, or (b) checking `memory_batch_state` on every live trigger,
which couples the chat module to the import module's state. The
out-of-order extraction during paused windows is a real but small
risk, and a paused batch is intended to be resolved quickly.

**Auto-retry with exponential backoff (like the live flow):** Rejected
in favour of explicit user control. The live flow auto-retries because
the user has a continuous expectation that memory works in the
background. The import batch is a one-shot operation the user just
initiated; failure should be visible and actionable, not buried in
retries.

---

## 6. UI Flow

### 6.1 ChatGPT-import tab (persona-detail view)

After import:

```
┌─────────────────────────────────────────────────┐
│ Imported 7 conversations into "Grok"            │
│                                                  │
│ Memory extraction: 3 / 7  ████████░░░░░░░ 43%   │
│ Currently processing: "Hühnerbrust Geschnetzeltes" │
└─────────────────────────────────────────────────┘
```

On `ChatGptImportMemoryProgressEvent`, the bar advances and the title
updates. On `ChatGptImportMemoryBatchDoneEvent`, the panel collapses to
"7 / 7 extracted — 24 memories created". On `ChatGptImportMemoryPausedEvent`:

```
┌─────────────────────────────────────────────────┐
│ Memory extraction paused at 3 / 7                │
│ Reason: Daily budget exhausted                   │
│                                                  │
│ [Resume]   [Discard remaining]                  │
└─────────────────────────────────────────────────┘
```

### 6.2 Persona-detail page (top-level)

A subtle inline pill in the persona header during an active batch:

```
Grok      [memory: 3 / 7]    ⏸ Settings
```

Click → opens the import tab pre-scrolled to the batch panel.

### 6.3 Discoverability of the existing manual "Extract" button

While a batch is running for this persona, the manual button is
disabled with tooltip "Import memory extraction in progress" — same UI
treatment as `feedback_disabled_over_hidden` in memory.

While a batch is paused, the manual button is **enabled** — the user
can still manually trigger live-flow extraction for new messages they
write. The paused batch sits separately in the import panel.

---

## 7. Implementation Notes

### 7.1 Module boundaries

- `backend/jobs/handlers/_chatgpt_import_memory_batch.py` (NEW) lives
  under jobs, calls into `backend/modules/memory` and
  `backend/modules/chatgpt_import` via their public APIs only.
- `backend/modules/memory/_extraction_core.py` (NEW, refactored from
  `_memory_extraction.py`) exports `extract_and_store_messages` via the
  memory module's `__init__.py`.
- `backend/modules/chatgpt_import` gains the two REST endpoints
  (resume, discard) and a small `record_import_pair` helper added to
  its repository.

### 7.2 Submit-trigger location

The per-conversation job handler
(`backend/jobs/handlers/_chatgpt_import_conversation.py`) gains an
atomic Mongo update after `record_import`:

```python
# Pseudocode
result = await imports.find_one_and_update(
    {"_id": import_id},
    {"$inc": {"conversations_imported": 1}},
    return_document=ReturnDocument.AFTER,
)
target = result.get("conversation_count")  # set when parse finished
if result["conversations_imported"] == target:
    await submit(JobType.CHATGPT_IMPORT_MEMORY_BATCH, ...)
```

The atomic `$inc` guarantees exactly one submit even when N
per-conversation jobs finish concurrently.

If a per-conversation job **fails** (the existing failed-event path),
`conversations_imported` is **not** incremented. The batch then waits
for the failed conversation to be retried or for the user to skip it.
**Open question Q1:** If the user gives up on a failed conversation and
the counter never reaches target, the batch never fires. Decision in §8.

### 7.3 Test surface

Unit tests (no Mongo/Redis) in `backend/tests/modules/memory/`:
- `test_extraction_core.py` — exercising the refactored extractor with
  a fake LLM stream + in-memory repo

Integration-ish tests in `backend/tests/jobs/handlers/`:
- `test_chatgpt_import_memory_batch.py` — drive the handler with a
  fake event_bus and a real-shape Mongo via the existing test fixtures.
  Covers: chronological order, pause on provider failure, resume
  idempotency, slot acquire/release.

These tests are out of scope for the chatgpt_import-only test pass
(separate branch already in flight); they are part of this feature's
own delivery.

### 7.4 Migration

No migration required. Existing imports get `memory_batch_state = None`
on first read (Pydantic default). They are **not** retroactively
processed. If a tester asks for that, we add a one-shot admin script
later.

---

## 8. Open Questions

**Q1 — Stuck batch trigger:** If 1 out of 7 per-conversation imports
fails permanently and the user does not retry, the
`conversations_imported == target` condition never holds and the batch
never submits. Options:

  - (a) Trigger the batch on `conversations_imported + permanent_failures
    == target`. Simple, but couples failure tracking to the trigger.
  - (b) Schedule a 5-minute timer after the parse-done event: when it
    fires, submit the batch with whatever has been imported by then.
  - (c) Manual "Start memory extraction" button on the import panel —
    user-controlled trigger, never automatic. Most explicit.

  **Recommendation:** (a) — keeps the flow uniform with one trigger
  point. We already publish `conversation_import_failed`, so the
  per-conversation handler can `$inc: {"permanent_failures": 1}` on
  failure and check against the same target. Decision pending review.

**Q2 — Budget-exhausted resume:** Should Resume re-check the daily
budget before re-acquiring the slot? Or trust the user clicking Resume
to mean "I know there's headroom now"? Cheap to check; recommend
checking and short-circuiting back to paused if still over.

**Q3 — Multiple personas in one import batch:** Today a user can import
the same conversation into multiple personas. Each persona gets its
own session, and our design submits **one batch per (import_id,
persona_id)** pair. The atomic counter logic in §7.2 doesn't cleanly
handle that — `conversations_imported` is per import_id, not per
persona. Likely solution: scope the counter to `(import_id, persona_id)`
via a nested object. Defer to Plan.

---

## 9. Manual Verification (required before merging)

Run these on a real Chatsune dev environment with at least one valid
LLM connection for the test persona.

### 9.1 Happy path

1. Import 3+ ChatGPT conversations into one persona (varied
   create-times so chronology matters).
2. Observe: import panel shows "Memory extraction: 0 / 3" → progresses
   → "3 / 3 extracted — N memories created".
3. Open the persona's Memory tab. Expect `N` uncommitted journal
   entries, oldest entry referencing the oldest conversation
   (correlation IDs in logs should match).
4. Open backend logs:
   `rg "chatgpt_import.memory" backend/logs/chatsune.log.YYYY-MM-DD`.
   Expect: one batch start, three per-session extract spans (in
   chronological order by session_id), one batch done.

### 9.2 Anti-contradiction order

1. Pick two ChatGPT conversations where the later one corrects a fact
   from the earlier one (e.g. earlier: "user likes hot tea"; later:
   "user prefers iced tea now"). Import both.
2. Inspect the resulting journal entries. The later correction should
   be present and **marked `is_correction: true`**. Were the order
   reversed, the corrected entry would be discarded as a duplicate of
   the original.

### 9.3 Pause + Resume

1. Disable the persona's LLM connection (revoke API key or stop local
   Ollama) before importing.
2. Import 3 conversations.
3. Expect: batch starts, fails on conversation 1, paused state visible
   with reason "provider_unavailable".
4. Re-enable the connection. Click Resume.
5. Expect: batch continues from conversation 1, runs to "3 / 3".

### 9.4 Discard

1. Pause a batch (as in 9.3).
2. Click Discard remaining.
3. Expect: paused-state UI disappears. Memory tab shows entries from any
   conversation that completed before pause (if any). Manual "Extract
   now" button is enabled again.

### 9.5 Live-chat continues to work for this persona

1. Start a fresh import batch for persona X.
2. While it is running, send a normal chat message to a **different**
   persona Y. Expect: that persona's live-extraction trigger fires
   normally (independent in-flight slot).
3. While the batch is running, send a message to persona X (the one
   being imported). Expect: the message is delivered, but the
   live-extraction submit is skipped (slot held). When the batch
   finishes, the next message-send triggers extraction normally.

### 9.6 Counter sanity after import

1. Right after a successful batch for persona X:
   `docker exec chatsune-redis-1 redis-cli HGETALL "memory:extraction:<uid>:<pid>"`.
   Expect: `messages_since_extraction` == 0, `last_extraction_at`
   matches the batch's done time.
2. Send a normal chat message. Expect counter == 1. Live flow resumes
   normally.

---

## 10. Out of Scope (Follow-ups)

- Bulk-retroactive batch for users who already imported before this
  change ships.
- Per-message progress within a single conversation.
- "Re-extract everything for this persona" as a user-facing action
  (operationally useful but a separate UX surface).
- Memory-batch progress shown on the global notification panel — for
  now it's confined to the import / persona views.
