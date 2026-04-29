# Plan: Chronological Message Timeline

**Date:** 2026-04-29
**Spec:** [`devdocs/specs/2026-04-29-chronological-message-timeline.md`](../specs/2026-04-29-chronological-message-timeline.md)
**Status:** Ready for execution

---

## Execution model

Two backend + two frontend changes are largely independent once the spec is
locked. Two subagents work in parallel:

- **Subagent BE** — backend schema, synthesis, write path, KB-event
  correlation_id fix.
- **Subagent FE** — frontend store, hooks, MessageList render, PTI merge
  helper.

Then a **review subagent** reads both diffs against the spec. The orchestrator
runs the build-verification commands and hands off to Chris for manual
verification on real device. Merge to master happens last, by the
orchestrator, only after Chris's approval.

## Constraints carried into every dispatch

These are non-negotiable per CLAUDE.md and Chris's standing instructions:

- Do **not** merge.
- Do **not** push to remote.
- Do **not** switch or create branches.
- Do **not** commit unless explicitly asked. The orchestrator does the final
  commit on master.
- For Python deps: if any new package is needed, update **both** root
  `pyproject.toml` **and** `backend/pyproject.toml`.
- For comments: only where logic is non-obvious; no `// increment i`-style
  fluff.
- British English in code, comments, docs.
- Tests must be runnable on the host without Docker. If a test would require
  MongoDB, use mocks/fixtures instead — do not introduce host→Docker
  coupling for new tests.

## Stages

### Stage 1 (parallel) — Implementation

#### Subagent BE — Backend implementation

**Files to touch:**

- `shared/dtos/chat.py` — add `TimelineEntry*` Pydantic models, the
  discriminated union alias, and the `events: list[TimelineEntryDto] | None
  = None` field on `ChatMessageDto`. Keep all legacy fields with their
  current optional-with-default declarations.
- `backend/modules/chat/_repository.py` — write path: persist `events` and
  drop the legacy fields from new writes. Read path: in `message_to_dto`,
  call `synthesise_events` when the document has no `events` key but has
  any of the legacy keys, and populate `events` on the DTO.
- `backend/modules/chat/_inference.py` — replace the four parallel
  accumulators (`knowledge_context`, `web_search_context`, `tool_calls`,
  `artefact_refs` — also `image_refs` if present) with a single `events`
  list. Increment `next_seq` per appended entry. Pass `events` into the
  save path. Map tool→entry-kind per the spec's table.
- `backend/modules/tools/_executors.py` — line ~91: stop generating a fresh
  UUID for `KnowledgeSearchCompletedEvent.correlation_id`. Pull the
  chat-stream's correlation id from the existing tool-execution context
  (whichever parameter already carries it; if not there, add it). Same for
  any other tool-derived event publication that today generates a fresh
  UUID inside an executor.

**Tests to add:**

- `backend/tests/modules/chat/test_synthesise_events.py` — unit tests for
  `synthesise_events` covering: single knowledge_search, two
  knowledge_search calls, mixed tools, failed tool, missing artefact_ref,
  document with no `tool_calls` but with `knowledge_context`, document
  with `events` already (synthesis must not run).
- `backend/tests/modules/chat/test_inference_events.py` — unit test the
  `events` accumulation path with mocked tool-completion sequences. Assert
  monotonic `seq`, correct kind mapping, no entries written into legacy
  fields.

**Verification commands the subagent must run before reporting done:**

```bash
uv run python -m py_compile $(git ls-files 'backend/**/*.py' 'shared/**/*.py')
uv run pytest backend/tests/modules/chat/test_synthesise_events.py backend/tests/modules/chat/test_inference_events.py -v
```

Report: exact files changed, lines added/removed (rough counts ok), and
the full pytest output of the new test files.

#### Subagent FE — Frontend implementation

**Files to touch:**

- `frontend/src/core/api/chat.ts` (or wherever the TS types mirror
  `ChatMessageDto`) — add the `TimelineEntry*` discriminated-union TS
  types. Keep legacy fields on `ChatMessageDto` as optional.
- `frontend/src/core/store/chatStore.ts` — replace
  `streamingWebSearchContext`, `streamingKnowledgeContext`,
  `streamingArtefactRefs`, `streamingImageRefs` with a single
  `streamingEvents: TimelineEntry[]` and a single `appendStreamingEvent`
  action. Keep `activeToolCalls` as-is. `finishStreaming` discards
  `streamingEvents` and uses `finalMessage.events` exclusively.
- `frontend/src/features/chat/useChatStream.ts` — when a stream event
  signals a completed tool, build the appropriate `TimelineEntry` and call
  `appendStreamingEvent`. Use a per-stream local counter for `seq`.
- `frontend/src/features/knowledge/useKnowledgeEvents.ts` — same: instead
  of `setStreamingKnowledgeContext`, call `appendStreamingEvent` with a
  `knowledge_search` entry.
- `frontend/src/features/chat/MessageList.tsx` — collapse the dual render
  paths: one `events`-driven path used both for persisted messages
  (`msg.events`) and for the live block (`streamingEvents`). Keep
  `ToolCallActivity` for in-flight tools rendered after the events list,
  before the message body. Add the `mergePtiIntoFirstKnowledgeEntry`
  helper as described in the spec (render-only, never reaches the store).
- Any tests under `frontend/src/features/chat/__tests__/` and
  `frontend/src/core/store/chatStore.test.ts` that reference the removed
  streaming slots — update or replace.

**Tests to add/update:**

- Update `chatStore.test.ts` and `useChatStream.test.ts` to use the new
  `streamingEvents` shape; remove `streamingArtefactRefs` /
  `streamingImageRefs` assertions.
- Add a test for `mergePtiIntoFirstKnowledgeEntry` covering the three
  cases from the spec (existing entry → prepended, no entry → synthetic,
  empty PTI → unchanged).
- Add a render test (or snapshot) for `MessageList` with a persisted
  message carrying `events = [knowledge_search@0, web_search@1,
  artefact@2]` and assert DOM ordering.

**Verification commands the subagent must run before reporting done:**

```bash
cd frontend && pnpm install --frozen-lockfile  # only if package.json changed
cd frontend && pnpm run build                  # NOT just `pnpm tsc --noEmit`
cd frontend && pnpm test --run                 # vitest one-shot
```

`pnpm run build` is mandatory (per Chris's memory: `tsc -b` catches
stricter errors than `tsc --noEmit`).

Report: exact files changed, build output (or last 30 lines if huge), test
summary.

### Stage 2 — Code review

**Subagent role:** read-only review of both diffs against the spec.

Brief:

- Read `devdocs/specs/2026-04-29-chronological-message-timeline.md`
  thoroughly first.
- Read the BE and FE diffs (use `git diff` on the working tree — work has
  not been committed).
- Verify: does the implementation match the spec? Are the legacy fields
  still readable on existing documents? Does the synthesis function
  produce stable output for the same input? Does `MessageList` render the
  exact same DOM for live and persisted given the same `events` list? Is
  PTI handling render-only (not in the store)? Is the KB-event
  correlation_id pulling from the stream context, not generating fresh?
- Flag only **high-confidence** issues. Skip stylistic nits unless they
  affect maintainability.
- Report findings as a numbered list with file:line citations.

Stage 2 runs **after** Stage 1 reports back from both subagents.

### Stage 3 — Build verification (orchestrator)

The orchestrator (me) runs:

```bash
cd /home/chris/workspace/chatsune
uv run python -m py_compile $(find backend shared -name '*.py' -type f)
cd frontend && pnpm run build
```

If anything fails, dispatch a follow-up subagent with the error output to
fix. Repeat until clean.

### Stage 4 — Manual verification (Chris)

Hand off to Chris with the spec's "Manual verification" steps 1-12.
Chris reports back. If issues, loop back to Stage 1 with a focused
subagent dispatch.

### Stage 5 — Merge (orchestrator)

Once Chris approves:

```bash
git add <touched files>
git commit -m "<imperative message>"
# (no remote push; user pushes separately if they want)
```

Per CLAUDE.md "Implementation defaults": always merge to master after
implementation. We are already on master, so this is a regular commit on
master.

## Sequencing

```
[ Stage 1 BE ]  ─┐
                 ├──► [ Stage 2 review ] ──► [ Stage 3 build ] ──► [ Stage 4 manual (Chris) ] ──► [ Stage 5 commit ]
[ Stage 1 FE ]  ─┘
```

Stage 1 BE and Stage 1 FE run **in the same orchestrator message** as two
parallel `Agent` tool calls.

## Risk register (execution-time)

- **DTO drift between Pydantic and TS.** Mitigated by both subagents
  reading the spec's exact discriminated-union shape verbatim. Review
  stage cross-checks.
- **Frontend tests reach into removed slots.** Subagent FE must update or
  remove every reference to `streamingWebSearchContext`,
  `streamingKnowledgeContext`, `streamingArtefactRefs`,
  `streamingImageRefs` in test files. Search-and-replace, then verify all
  tests still pass.
- **Legacy synthesis differs from what frontend used to render.** Old
  documents that today show, say, a tool_call with no matching knowledge
  result might render slightly differently after synthesis. Manual
  verification step 7 (reload an old chat) catches this.
- **Continuous voice path.** Steps 10-12 of manual verification cover
  this. If the voice pipeline does not go through `useChatStream`, the
  subagent may miss it; review stage explicitly checks the voice phase
  module.
