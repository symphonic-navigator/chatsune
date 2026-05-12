# Implementation Plan — Imported-Conversation Memory Extraction

**Spec:** [`devdocs/specs/2026-05-12-imported-conversation-memory-extract-design.md`](../specs/2026-05-12-imported-conversation-memory-extract-design.md)
**Date:** 2026-05-12
**Branches:** see §6 dispatch strategy

---

## 1. Phasing Overview

Three sequential phases, each on its own feature branch, each ending
with merge to master before the next phase starts. Sequenced because:

- Phase 2 (batch backend) consumes the function refactored out in
  Phase 1.
- Phase 3 (frontend) consumes the events / endpoints added in Phase 2.

```
Phase 1: extraction-core refactor          [behaviour-preserving]
   ↓ merge to master
Phase 2: backend batch feature             [new behaviour]
   ↓ merge to master
Phase 3: frontend wiring + UI              [new UI]
   ↓ merge to master
Phase 4: manual verification (§9 of spec)  [tester-driven]
```

Each phase is dispatched to one subagent with hard "no merge, no push,
no branch switch" constraints. I review and merge between phases.

---

## 2. Phase 1 — Extraction-Core Refactor

**Branch:** `feature/memory-extraction-core-refactor`
**Behaviour change:** none. Live-flow memory extraction continues to
work exactly as today; this is internal-structure work that prepares
for re-use.

### 2.1 Files

| Action | Path | What |
|---|---|---|
| Create | `backend/modules/memory/_extraction_core.py` | New module with `ExtractionResult` dataclass + `extract_and_store_messages` async function. Pure logic: build prompt, stream LLM, parse, dedup, store entries in Mongo transaction, mark messages extracted. Raises `ProviderUnavailableError` / generic `Exception` on failure — caller decides retry/pause. |
| Modify | `backend/modules/memory/__init__.py` | Re-export `extract_and_store_messages` and `ExtractionResult` as part of the memory module public API. |
| Modify | `backend/jobs/handlers/_memory_extraction.py` | Replace the inline prompt-build → stream → parse → store block with a call to `extract_and_store_messages`. Keep all the existing job-system wrappers (in-flight slot, dedup token, event-publishing, on-failure handling, terminal-failure semantics). |

### 2.2 Function signature

```python
@dataclass
class ExtractionResult:
    entries_created: int
    messages_processed: int
    input_tokens: int | None
    output_tokens: int | None

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
    db,
    event_bus,
    skip_budget_reserve: bool = False,
) -> ExtractionResult: ...
```

`event_bus` is passed because the per-entry `MemoryEntryCreated` events
are emitted from inside this function (they belong to the extraction
itself, not the calling wrapper). The wrapper handlers retain
`started` / `completed` / `failed` / `skipped` event publication.

`skip_budget_reserve` is False everywhere in Phase 1 (live flow keeps
checking). Phase 2 uses it from the batch handler.

### 2.3 Tests

- `backend/tests/modules/memory/__init__.py` (new, empty)
- `backend/tests/modules/memory/test_extraction_core.py`
  - Happy path: fake LLM stream yields 2 valid entries → 2 created,
    messages marked extracted, MemoryEntryCreated emitted twice
  - Dedup: existing journal contains identical content → 0 entries
    created
  - All messages filter to empty after `strip_technical_content` → 0
    entries created, messages still marked extracted, no LLM call
  - Provider unavailable: stream raises `ProviderUnavailableError` →
    function re-raises, messages NOT marked extracted, no journal
    entries created (transaction rolled back)
  - `skip_budget_reserve=True` → no `check_and_reserve_budget` call,
    `record_handler_tokens` still called

Use a fake `event_bus`, fake `redis`, and a real-shape `db` only if
trivially mockable. Tests must run on host without Mongo/Redis (see
MEMORY `feedback_db_tests_on_host`). If Mongo transactions are too
deeply baked in, structure the test with a thin in-memory repo
abstraction; do not require Docker.

### 2.4 Verification

- `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/memory/ -q`
- All existing memory tests still pass:
  `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/ -q --ignore=backend/tests/<DB-deps>`
  (use the existing ignore list from MEMORY)
- `uv run python -m py_compile` on every changed file
- Spot-check by running the live flow once via the existing manual
  extraction button against a real persona — entry-created events must
  still arrive on the frontend WS. (Subagent reports this as "did
  manual run? yes/no" without me needing to run it.)

### 2.5 Subagent dispatch

One subagent. Constraint: stay on `feature/memory-extraction-core-refactor`,
do not merge / push / switch. Final commit:
"Extract memory extraction core into reusable function".

---

## 3. Phase 2 — Backend Batch Feature

**Branch:** `feature/imported-memory-batch-backend`
**Depends on:** Phase 1 merged.

### 3.1 Files — data model

| Action | Path | What |
|---|---|---|
| Modify | `backend/jobs/_models.py` | Add `JobType.CHATGPT_IMPORT_MEMORY_BATCH = "chatgpt_import_memory_batch"`. |
| Modify | `backend/jobs/_registry.py` | Register handler + `JobConfig(max_retries=0)`. |
| Create | `backend/modules/chatgpt_import/_memory_batch_repository.py` | Repository for `chatgpt_import_memory_batches` collection. Methods: `ensure_batch(import_id, persona_id, user_id, model_unique_id, target_count)` (upsert with `state="pending"` on insert), `increment_imported(...)`, `increment_failures(...)`, `claim_running(import_id, persona_id, session_ids)` (atomic state pending→running, sets session_ids), `mark_paused(...)`, `mark_done(...)`, `mark_discarded(...)`, `get(import_id, persona_id)`. Includes idempotent index creation `{user_id: 1, state: 1}` at module init. |
| Modify | `backend/modules/chatgpt_import/__init__.py` | Re-export batch-repo public API. |
| Create | `shared/events/chatgpt_import.py` (extend existing) | Add `ChatGptImportMemoryProgressEvent`, `ChatGptImportMemoryPausedEvent`, `ChatGptImportMemoryBatchDoneEvent` per §4.2 of spec. |
| Modify | `shared/topics.py` | Add three new topic constants. |
| Modify | `backend/ws/event_bus.py` | Register the three new topics in the topic-spec table. |

### 3.2 Files — trigger logic

| Action | Path | What |
|---|---|---|
| Modify | `backend/jobs/handlers/_chatgpt_import_conversation.py` | After `record_import` (success path): call `batch_repo.ensure_batch(...)` (idempotent), then `increment_imported(...)`. On failure (terminal path in the existing `_publish_failure` block before `raise`): call `increment_failures(...)`. After either branch: if `imported + permanent_failures == target_count`, atomically `claim_running(...)` + submit `CHATGPT_IMPORT_MEMORY_BATCH` job. The `target_count` is the size of the original `import_conversations` request — that count is currently lost; preserve it via a new payload field on the per-conversation job (see below). |
| Modify | `backend/modules/chatgpt_import/_handlers.py` | In the existing `import_conversations` POST handler: when submitting N per-conversation jobs, include `persona_id_target_count` in each job's payload. This is the cohort size for the (import_id, persona_id) batch. Plus: the `_chatgpt_import_parse.py` handler does not need changes — it does not submit the per-conversation jobs (the REST handler does). |

### 3.3 Files — batch handler

| Action | Path | What |
|---|---|---|
| Create | `backend/jobs/handlers/_chatgpt_import_memory_batch.py` | The main batch handler. Payload: `{import_id, persona_id, force_budget}`. Pseudocode below. |

```python
async def handle_chatgpt_import_memory_batch(job, config, redis, event_bus):
    payload = job.payload
    import_id = payload["import_id"]
    persona_id = payload["persona_id"]
    force_budget = payload.get("force_budget", False)
    user_id = job.user_id

    repo = batch_repo(db)
    chat_repo = ChatRepository(db)

    batch = await repo.get(import_id, persona_id)
    # state must be "running" — claim happened in the trigger
    if batch["state"] != "running":
        log.warning("batch not in running state", state=batch["state"])
        return

    # Acquire per-persona slot. TTL 1h, refresh after each session.
    slot_key = memory_extraction_slot_key(user_id, persona_id)
    if not await try_acquire_inflight_slot(redis, slot_key, ttl_seconds=3600):
        # Another extraction is in flight. Pause without progress so
        # the user sees the state and can retry later via Resume.
        await repo.mark_paused(import_id, persona_id, paused_at=...,
            reason="other",
            user_message="Memory extraction is busy for this persona — "
                         "click Resume in a moment.")
        await event_bus.publish(...PausedEvent...)
        return

    try:
        for index, session_id in enumerate(batch["session_ids"], start=1):
            # Tolerate deleted sessions
            session = await chat_repo.get_session(session_id, user_id)
            if not session:
                continue

            # Progress: extracting
            title = session.get("title", "")
            await event_bus.publish(...ProgressEvent(extracting, index, total)...)

            # Loop until session has no unextracted user messages
            entries_total = 0
            while True:
                unextracted = await chat_repo.list_unextracted_user_messages(
                    session_id, limit=20,
                )
                if not unextracted:
                    break
                msg_ids = [m["_id"] for m in unextracted]
                msg_contents = [m["content"] for m in unextracted]
                try:
                    result = await extract_and_store_messages(
                        user_id=user_id, persona_id=persona_id,
                        session_id=session_id,
                        model_unique_id=batch["model_unique_id"],
                        messages=msg_contents, message_ids=msg_ids,
                        correlation_id=job.correlation_id,
                        redis=redis, db=db, event_bus=event_bus,
                        skip_budget_reserve=force_budget,
                    )
                except ProviderUnavailableError as e:
                    await repo.mark_paused(import_id, persona_id,
                        paused_at={"session_index": index, "session_id": session_id, ...},
                        reason="provider_unavailable", user_message=...)
                    await event_bus.publish(...PausedEvent...)
                    return
                except BudgetExhaustedError as e:    # raised by check_and_reserve_budget
                    await repo.mark_paused(import_id, persona_id, ...,
                        reason="budget_exhausted", user_message=...)
                    await event_bus.publish(...PausedEvent...)
                    return
                except Exception as e:
                    await repo.mark_paused(import_id, persona_id, ...,
                        reason="other", user_message=str(e)[:200])
                    await event_bus.publish(...PausedEvent...)
                    return
                entries_total += result.entries_created
                await repo.add_entries_created(import_id, persona_id, result.entries_created)

            # Refresh slot TTL after each session
            await redis.expire(slot_key, 3600)
            # Progress: done for this session
            await event_bus.publish(...ProgressEvent(done, index, total,
                entries_created=entries_total)...)

        # All sessions done
        await repo.mark_done(import_id, persona_id)
        await event_bus.publish(...DoneEvent...)
    finally:
        # On paused: slot stays held with 7-day TTL (set by mark_paused
        # via redis.expire). On done/discarded: release.
        if batch_state_now in ("done", "discarded"):
            await release_inflight_slot(redis, slot_key)
        elif batch_state_now == "paused":
            await redis.expire(slot_key, 7 * 24 * 3600)
```

Note: `BudgetExhaustedError` may not exist as a distinct exception type
today — check `check_and_reserve_budget` source. If it raises a generic
`Exception` with a known message, match on that; otherwise add the
typed exception in this phase (small refactor, justified).

### 3.4 Files — REST endpoints

| Action | Path | What |
|---|---|---|
| Modify | `backend/modules/chatgpt_import/_handlers.py` | Add `POST /api/chatgpt_import/{import_id}/memory_batch/resume` and `POST .../discard` per §4.4 of spec. Both verify ownership via `require_active_session`. Resume reads current `state`, returns 409 if not `"paused"`, otherwise re-claims `state="paused"→"running"` atomically and submits the job. Discard transitions `"paused"→"discarded"`, releases the in-flight slot, emits `BatchDoneEvent` with current `total_entries_created`. |
| Modify | `shared/dtos/chatgpt_import.py` | Add `MemoryBatchResumeRequest` and `MemoryBatchDiscardRequest` DTOs. Add response shape for GET-style reads (used by frontend on reconnect to learn paused state). |
| Modify | `backend/modules/chatgpt_import/_handlers.py` | Add `GET /api/chatgpt_import/{import_id}/memory_batch?persona_id=...` returning the current batch doc (or 404 if none). Frontend uses this on persona-detail load to reconstruct paused-state UI without needing WS catchup. |

### 3.5 Tests

- `backend/tests/jobs/handlers/test_chatgpt_import_memory_batch.py`
  - Happy path: 3 sessions, all extract successfully → DoneEvent
  - Sessions iterated chronologically (verify via captured event order)
  - Session deleted between submit and run → skipped silently
  - Provider unavailable mid-batch → PausedEvent with correct
    session_index, slot TTL extended to 7d
  - Budget exhausted → PausedEvent reason="budget_exhausted"
  - `force_budget=True` payload → `extract_and_store_messages` called
    with `skip_budget_reserve=True`
  - Resume after pause: idempotent re-iteration skips already-extracted
    messages (uses `extracted_at` check inside `list_unextracted_user_messages`)
- `backend/tests/modules/chatgpt_import/test_memory_batch_repository.py`
  - `ensure_batch` upsert behaviour (insert vs. no-op)
  - `claim_running` atomic guard: two concurrent claims, only one wins
  - `increment_imported` / `increment_failures` + target-check semantics
- `backend/tests/modules/chatgpt_import/test_handlers_memory_batch.py`
  - Resume returns 409 when state != "paused"
  - Resume with `force_budget=true` injects into job payload
  - Discard transitions correctly + emits done event with current totals
  - GET endpoint shape

All tests host-runnable (no real Mongo/Redis). Where a Mongo collection
is required, use the in-memory fake from existing test fixtures
(`backend/tests/...` has one; subagent should locate and re-use).

### 3.6 Verification

- All new tests green
- All existing tests still green
- `uv run python -m py_compile` clean
- Backend boots via the standard dev script
- One real end-to-end smoke run (subagent reports — no, can be deferred
  to Phase 4 manual verification)

### 3.7 Subagent dispatch

One subagent for all of Phase 2. Constraint: stay on
`feature/imported-memory-batch-backend`, do not merge / push / switch.
Final commit (or two commits if size demands): primary message
"Add imported-conversation memory extraction batch backend".

---

## 4. Phase 3 — Frontend Wiring + UI

**Branch:** `feature/imported-memory-batch-frontend`
**Depends on:** Phase 2 merged.

### 4.1 Files

| Action | Path | What |
|---|---|---|
| Modify | `frontend/src/core/types/events.ts` (or wherever event types live) | Add the three new event types matching `shared/events/chatgpt_import.py` shape. |
| Modify | `frontend/src/core/stores/chatgptImportStore.ts` (or equivalent) | Add memory-batch state slice: `{ persona_id → { state, current_index, total, entries_created, paused_at? } }`. Subscribers update on progress/paused/done events. |
| Modify | `frontend/src/features/chatgptImport/...` | Render the progress panel per §6.1. Two layouts: running (progress bar) and paused (depending on reason). |
| Create | `frontend/src/features/chatgptImport/MemoryBatchProgressPanel.tsx` | Reusable panel component, props: batch state object + persona_id + import_id. Includes Resume / Discard / force-budget Resume buttons. |
| Modify | `frontend/src/features/personaDetail/PersonaHeader.tsx` (or wherever the persona header lives) | Add the inline pill from §6.2 when an active batch exists for the persona. Click navigates to the import panel. |
| Modify | `frontend/src/core/api/chatgptImport.ts` | Add `resumeMemoryBatch(importId, personaId, forceBudget)`, `discardMemoryBatch(importId, personaId)`, `getMemoryBatchState(importId, personaId)`. |
| Modify | persona-detail "Extract now" button location | Disable + tooltip "Import memory extraction in progress / paused" when an active or paused batch exists for the persona. |

### 4.2 Tests

Component tests (Vitest, no real backend):
- `MemoryBatchProgressPanel`:
  - Running state: bar advances, title updates
  - Paused (provider_unavailable): Resume + Discard buttons, no force option
  - Paused (budget_exhausted): two Resume variants ("tomorrow" + "now — exceed budget") + Discard
  - Done: success summary (collapses to "N / N extracted")

Store tests:
- Progress event updates index + entries_created
- Paused event sets paused_at object
- Done event clears paused_at, sets state to "done"

### 4.3 Verification

- `cd frontend && pnpm run build` clean (NOT just tsc --noEmit — see
  MEMORY `feedback_frontend_build_check`)
- Component tests green: `cd frontend && pnpm test`
- Manual: start dev backend with fake batch event publication (or wait
  until Phase 4)

### 4.4 Subagent dispatch

One subagent. Constraint as before. Final commit: "Add memory-batch
progress UI for ChatGPT-imported conversations".

---

## 5. Phase 4 — Manual Verification

I run §9 of the spec together with you on a real dev environment.
This is not subagent work. Required scenarios:

- §9.1 Happy path
- §9.2 Anti-contradiction order
- §9.3 Pause + Resume
- §9.4 Discard
- §9.4b Force-budget Resume
- §9.5 Live-chat parallel
- §9.6 Counter sanity after import

If any scenario fails, file findings as a follow-up branch — do not
back-patch the merged Phase 1-3 work. Manual verification is the
quality gate; bugs found here get their own commit.

---

## 6. Dispatch Strategy

### 6.1 Branch hygiene

Subagents always: do **not** merge, do **not** push, do **not** switch
branches. They commit only on their own feature branch. I (main session)
review after completion, run a sanity check (`git diff --stat master`,
build, tests), then merge to master with `--no-ff` per repo
convention. Each phase ends with master at a clean ready-to-deploy
state.

### 6.2 Cross-phase coordination

Phase 1 must merge before Phase 2 dispatches (Phase 2 imports
`extract_and_store_messages`). Phase 2 must merge before Phase 3
dispatches (Phase 3 calls Phase 2 endpoints and subscribes to Phase 2
events). No parallel work across phases.

### 6.3 Recovery from subagent failure

If a subagent's report shows:
- **Failed tests:** I read the failures, decide whether to fix in-line
  or send the subagent back with the specific diagnosis. No blind
  retries.
- **Out-of-scope changes:** I revert the offending commit, re-dispatch
  with tighter scope.
- **Module-boundary violation:** I reject and re-dispatch with a
  specific call-out.

### 6.4 Commit hygiene

Each phase ends with **one** merge commit on master, plus the phase's
internal commits visible in the merged branch's log. No squash. Repo
convention is `--no-ff` merges (verified in recent `git log`).

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Refactor in Phase 1 silently breaks live-flow extraction | All existing memory tests must pass before Phase 1 merges. Subagent reports test count delta. |
| Atomic counter logic in Phase 2 fails under concurrent per-conversation jobs | Test explicitly exercises concurrency: two simulated finishes hitting the trigger condition simultaneously; only one batch submit observed. |
| Slot held with 7d TTL during paused leaks to live-flow user surprise | UI disables manual "Extract now" with explanatory tooltip. §6.1 covers this. |
| Frontend pill misses an event due to WS reconnect mid-batch | `GET /memory_batch` endpoint on persona-detail load reconstructs state from server. |
| Tests requiring Mongo transactions force Docker dependency | Use in-memory shape fakes; if not feasible, mark those tests Docker-only and ensure the host-runnable subset still covers the critical paths. |

---

## 8. Out of Scope

- Retroactive batch for imports made before this change ships.
- Per-message progress within a single conversation.
- "Re-extract everything for this persona" admin action.
- Telemetry / cost reporting for force-budget Resume invocations.

These are all listed in §10 of the spec; the plan adds nothing new
beyond it.
