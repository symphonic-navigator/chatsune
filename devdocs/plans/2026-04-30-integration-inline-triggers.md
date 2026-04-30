# Integration Inline-Triggers Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents must NOT merge, push, or switch branches — those are reserved for the supervising session.

**Goal:** Build the generic foundation that future inline-trigger integrations (starting with Screen Effects) will consume: in-stream `<integration_id command args>` tags rendered as uniform pills, excluded from TTS, optionally synchronised with sentence-level playback.

**Architecture:** Frontend-only tag detection via existing `ResponseTagBuffer`, extended with UUID placeholders and a per-stream `pendingEffectsMap`. Plugin tag-execution callback becomes synchronous; async work moves into an optional `sideEffect` thunk. `SpeechSegment` carries effect metadata; `audioPlayback.onSegmentStart` emits `INTEGRATION_INLINE_TRIGGER` events at the right moment. New `IntegrationPill` React component renders all integration pills uniformly. Backend gains `default_enabled` flag and a tools-aware extension heuristic.

**Tech Stack:** Python (FastAPI, Pydantic v2), TypeScript (React, Vitest), pnpm, uv.

**Spec:** `devdocs/specs/2026-04-30-integration-inline-triggers-design.md`

**Branch:** `integration-inline-triggers-foundation` (already created with the spec committed)

---

## Phase Map

```
Phase 1: Backend Foundation                    (independent of Phase 2)
  Task 1.1: shared topic + event DTO
  Task 1.2: IntegrationDefinition + effective_enabled_map
  Task 1.3: prompt assembler refactor

Phase 2: Frontend Type Foundation              (independent of Phase 1)
  Task 2.1: TagExecutionResult shape + sync executeTag interface
  Task 2.2: SpeechSegment.effects field

Phase 3: ResponseTagBuffer + Lovense           (depends on Phase 2)
  Task 3.1: ResponseTagBuffer rewrite
  Task 3.2: Lovense plugin async->sync migration

Phase 4: Audio Pipeline                        (depends on Phase 2, 3)
  Task 4.1: audioParser placeholder extract
  Task 4.2: audioPlayback source param + segment-effects emit
  Task 4.3: playbackChild source pass-through

Phase 5: Stream Integration                    (depends on Phase 3, 4)
  Task 5.1: useChatStream streamSource detection
  Task 5.2: ReadAloudButton re-trigger path

Phase 6: Pill Component & Rendering            (depends on Phase 3)
  Task 6.1: IntegrationPill component + CSS tokens
  Task 6.2: Markdown/message renderer wiring

Phase 7: Verification
  Task 7.1: Build + lint + test sweep
  Task 7.2: Manual verification checklist (Chris)
```

## Test Execution Notes for Subagents

- **Backend tests (host):** Most pytest suites run fine on the host. Tests that touch MongoDB do NOT — they require Docker. Plan tasks below explicitly mark which tests are host-OK and which require Docker. Subagents working on the host MUST exclude DB-dependent test files when running the full suite.
- **Frontend tests (host):** Vitest runs on host: `pnpm vitest run <path>` for targeted tests, `pnpm vitest run` for the full suite.
- **Frontend build check:** Use `pnpm run build` (which invokes `tsc -b` internally), NOT `pnpm tsc --noEmit` — the latter misses stricter project-references-mode errors that CI catches.
- **Backend syntax check:** `uv run python -m py_compile <file>` for any modified Python file.

---

## Phase 1: Backend Foundation

### Task 1.1: INTEGRATION_INLINE_TRIGGER topic and event DTO

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/integrations.py`

- [ ] **Step 1: Add the topic constant**

In `shared/topics.py`, find the existing `INTEGRATION_*` group (look for `INTEGRATION_SECRETS_HYDRATED` / `INTEGRATION_ACTION_EXECUTED`). Add directly after them:

```
    INTEGRATION_INLINE_TRIGGER = "integration.inline.trigger"
```

- [ ] **Step 2: Add the event DTO**

In `shared/events/integrations.py`, ensure these imports are present (add what's missing):

```
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
```

Append at the end of the file:

```
class IntegrationInlineTriggerEvent(BaseModel):
    """Frontend-emitted event signalling an inline integration tag fired.

    The foundation only emits this on the front-end event bus; the topic
    and DTO live in shared/ so a future backend audit-emit path is a
    non-breaking addition.
    """
    integration_id: str
    command: str
    args: list[str]
    payload: Any
    source: Literal["live_stream", "text_only", "read_aloud"]
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 3: Verify Python syntax compiles**

Run: `uv run python -m py_compile shared/topics.py shared/events/integrations.py`
Expected: no output, exit 0.

- [ ] **Step 4: Verify the topic is importable end-to-end**

Run: `uv run python -c "from shared.topics import Topics; from shared.events.integrations import IntegrationInlineTriggerEvent; print(Topics.INTEGRATION_INLINE_TRIGGER); print(IntegrationInlineTriggerEvent.__name__)"`
Expected output: two lines — `integration.inline.trigger` and `IntegrationInlineTriggerEvent`.

- [ ] **Step 5: Commit**

```
git add shared/topics.py shared/events/integrations.py
git commit -m "Add INTEGRATION_INLINE_TRIGGER topic and event DTO"
```

---

### Task 1.2: `IntegrationDefinition.default_enabled` field and `effective_enabled_map`

**Files:**
- Modify: `backend/modules/integrations/_models.py`
- Modify: `backend/modules/integrations/__init__.py`
- Test: `backend/tests/test_integrations_default_enabled.py` (NEW; host-OK — pure unit, no DB)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_integrations_default_enabled.py` with four tests covering: no doc + default_enabled=True returns True; no doc + default_enabled=False returns False; explicit doc enabled=False overrides default_enabled=True; explicit doc enabled=True with default_enabled=False returns True. Each test patches `backend.modules.integrations._registry.get_all`, `IntegrationRepository.get_user_configs` (AsyncMock returning the desired list of config dicts), `PremiumProviderService.has_account` (AsyncMock returning False), and `backend.database.get_db`. Each test then awaits `effective_enabled_map("user-1")` and asserts the expected dict.

Use `IntegrationDefinition` directly with `default_enabled=True` or `False` as needed — that argument does not yet exist, which is why the tests will fail in Step 2.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_integrations_default_enabled.py -v`
Expected: 4 failures with `TypeError: ... got an unexpected keyword argument 'default_enabled'`.

- [ ] **Step 3: Add `default_enabled` field to `IntegrationDefinition`**

In `backend/modules/integrations/_models.py`, append a new field after `assignable: bool = False`:

```
    assignable: bool = False
    # When True, the integration is treated as enabled for any user that
    # has not explicitly stored a config document for it. Explicit user
    # toggles always win over this default.
    default_enabled: bool = False
```

- [ ] **Step 4: Update `effective_enabled_map`**

In `backend/modules/integrations/__init__.py`, replace the unlinked-integration branch (currently around lines 65-71). Find:

```
        else:
            cfg = cfg_map.get(iid)
            result[iid] = bool(cfg and cfg.get("enabled", False))
    return result
```

Replace with:

```
        else:
            cfg = cfg_map.get(iid)
            if cfg is None:
                # No explicit config doc — fall back to the integration's
                # default. This makes "default-on" a code property, not
                # something we have to backfill into the database.
                result[iid] = defn.default_enabled
            else:
                # Explicit user choice always wins (True or False).
                result[iid] = bool(cfg.get("enabled", False))
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_integrations_default_enabled.py -v`
Expected: 4 passes.

- [ ] **Step 6: Commit**

```
git add backend/modules/integrations/_models.py backend/modules/integrations/__init__.py backend/tests/test_integrations_default_enabled.py
git commit -m "Add default_enabled to IntegrationDefinition and effective_enabled_map"
```

---

### Task 1.3: Prompt assembler heuristic refactor

**Files:**
- Modify: `backend/modules/chat/_prompt_assembler.py:118-140`
- Test: `backend/tests/test_prompt_assembler_extensions.py` (NEW; host-OK)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_prompt_assembler_extensions.py` with three async pytest tests, all using `patch` to stub out: `_get_admin_prompt`, `_get_model_instructions`, `_get_persona_prompt`, `_get_persona_doc`, `_get_user_about_me` (all `AsyncMock(return_value=None)`); plus `backend.modules.integrations.get_enabled_integration_ids` (returning the IDs you want active) and `backend.modules.integrations.get_integration` (side_effect resolving each ID to a stub `IntegrationDefinition`).

Build two stub definitions: a "voice" integration with `system_prompt_template="<voice-prompt>VOICE</voice-prompt>"` and `tool_definitions=[]`; a "lovense" integration with `system_prompt_template="<lovense-prompt>LOVENSE</lovense-prompt>"` and `tool_definitions=[ToolDefinition(name="...", description="", parameters={"type":"object","properties":{}})]`.

Tests:
1. `tools_enabled=True` → assembled prompt contains both VOICE and LOVENSE; does not contain "no tools available".
2. `tools_enabled=False` → contains VOICE but NOT LOVENSE; contains "no tools available".
3. `tools_enabled=True` with both stubs having empty `system_prompt_template` → contains neither VOICE nor LOVENSE.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_prompt_assembler_extensions.py -v`
Expected: tests fail because the current code skips ALL extensions when `tools_enabled=False` (so test #2 fails: VOICE missing).

- [ ] **Step 3: Refactor the prompt assembler**

In `backend/modules/chat/_prompt_assembler.py`, locate the block currently spanning roughly lines 118-140 (the `# Layer: Integration prompt extensions` comment through the closing `</toolavailability>`). Replace it with:

```
    # Layer: Integration prompt extensions (active integrations for this persona).
    # An extension whose integration has tools is gated on tools_enabled —
    # otherwise its instructions on how to call tools would be misleading.
    # Extensions for tool-less integrations (xai_voice, screen_effects, ...)
    # are always injected when the integration is active.
    from backend.modules.integrations import (
        get_enabled_integration_ids,
        get_integration,
    )
    enabled_ids = await get_enabled_integration_ids(user_id, persona_id)
    extensions: list[str] = []
    for iid in enabled_ids:
        defn = get_integration(iid)
        if not defn or not defn.system_prompt_template:
            continue
        has_tools = bool(defn.tool_definitions)
        if has_tools and not tools_enabled:
            continue
        extensions.append(defn.system_prompt_template)
    if extensions:
        parts.append("\n\n".join(extensions))

    if not tools_enabled:
        # Without an explicit "no tools available" instruction, the model
        # answers "which tools do you have?" from its own training / the
        # prior assistant turns in the conversation history — where
        # previous responses may have listed tools that were once active.
        # This layer tells it plainly that nothing is callable right now.
        parts.append(
            '<toolavailability priority="high">\n'
            'You have no tools available in this conversation right now. '
            'Do not attempt to call any tool, and do not claim to have '
            'any — if asked about your tools, say they are disabled for '
            'this session.\n'
            '</toolavailability>'
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_prompt_assembler_extensions.py -v`
Expected: 3 passes.

- [ ] **Step 5: Run the broader chat tests to confirm nothing else broke**

Run: `uv run pytest backend/tests/ -k "prompt or chat" --ignore=backend/tests/test_database.py --ignore=backend/tests/test_persona_repository.py --ignore=backend/tests/test_user_repository.py --ignore=backend/tests/test_chat_repository.py -v`
Expected: all listed tests pass (DB-dependent suites are explicitly excluded — they need Docker).

- [ ] **Step 6: Commit**

```
git add backend/modules/chat/_prompt_assembler.py backend/tests/test_prompt_assembler_extensions.py
git commit -m "Decouple integration prompt extensions from tools_enabled gate"
```

---

## Phase 2: Frontend Type Foundation

### Task 2.1: TagExecutionResult shape change and sync `executeTag` interface

**Files:**
- Modify: `frontend/src/features/integrations/types.ts`

This task introduces the breaking interface change. Plugins (Lovense) and the buffer (responseTagProcessor) are migrated in Phase 3, immediately after.

- [ ] **Step 1: Update `TagExecutionResult` shape**

In `frontend/src/features/integrations/types.ts`, find the existing block:

```
/** Result of a response tag execution. */
export interface TagExecutionResult {
  success: boolean
  displayText: string
}
```

Replace with:

```
/** Result of a response tag execution.
 *
 * Returned synchronously by plugins. Async work (e.g. hardware API calls)
 * goes into the optional sideEffect thunk, which the ResponseTagBuffer
 * fires-and-forgets — the pill and the optional sentence-synced trigger
 * event are decided from the synchronous fields alone. */
export interface TagExecutionResult {
  /** Text shown in the inline pill. Plain text — rendered via IntegrationPill. */
  pillContent: string
  /** When true, the trigger event fires in lockstep with TTS sentence-start.
   *  When false, fires immediately on detection. Ignored in text-only streams
   *  (always fires immediately when no TTS pipeline is active). */
  syncWithTts: boolean
  /** Free, plugin-specific data carried in the trigger event payload. */
  effectPayload: unknown
  /** Optional async work invoked fire-and-forget by ResponseTagBuffer.
   *  Errors are logged; do not affect pill or event emission. */
  sideEffect?: () => Promise<void>
}
```

- [ ] **Step 2: Update the `IntegrationPlugin.executeTag` signature**

In the same file, find:

```
  /** Execute a response tag found in the LLM output. */
  executeTag?: (command: string, args: string[], config: Record<string, unknown>) => Promise<TagExecutionResult>
```

Replace with:

```
  /** Execute a response tag found in the LLM output. Synchronous — must
   *  return pill content and sync-decision without awaiting. Async work
   *  goes into the optional sideEffect field of the result. */
  executeTag?: (command: string, args: string[], config: Record<string, unknown>) => TagExecutionResult
```

- [ ] **Step 3: Append `IntegrationInlineTrigger` DTO to the same file**

At the end of `frontend/src/features/integrations/types.ts`, append:

```
/** Frontend-bus event payload for INTEGRATION_INLINE_TRIGGER.
 *  Mirrors the shared backend DTO (kept structurally identical so a
 *  future backend audit-emit path is a non-breaking addition). */
export interface IntegrationInlineTrigger {
  integration_id: string
  command: string
  args: string[]
  payload: unknown
  source: 'live_stream' | 'text_only' | 'read_aloud'
  correlation_id: string
  timestamp: string
}
```

- [ ] **Step 4: Verify TypeScript would catch every consumer that breaks**

Run from `frontend/`: `pnpm run build`
Expected: TypeScript errors in `responseTagProcessor.ts` (uses `await plugin.executeTag(...)` and `result.displayText`) and `plugins/lovense/tags.ts` (returns Promise + uses `success`/`displayText`). These are the two files Phase 3 fixes — the errors are the proof that we have full coverage of the migration.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/integrations/types.ts
git commit -m "Change TagExecutionResult to sync result with sideEffect thunk"
```

The frontend build will not succeed until Task 3.2 lands. This is intentional and serves as the proof that the migration covers every consumer.

---

### Task 2.2: `SpeechSegment.effects` field

**Files:**
- Modify: `frontend/src/features/voice/types.ts`

- [ ] **Step 1: Read the current `SpeechSegment` definition**

Open `frontend/src/features/voice/types.ts` and locate the `SpeechSegment` interface. Note its current fields so the new `effects?` slots in alongside them.

- [ ] **Step 2: Add the import**

Near the top of `frontend/src/features/voice/types.ts`, add:

```
import type { IntegrationInlineTrigger } from '../integrations/types'
```

- [ ] **Step 3: Add the `effects?` field to `SpeechSegment`**

In the `SpeechSegment` interface, append:

```
  /** Inline-trigger events bound to this segment by audioParser.
   *  audioPlayback emits each one to the eventBus when this segment
   *  starts playing. */
  effects?: IntegrationInlineTrigger[]
```

- [ ] **Step 4: Verify type compiles**

Run from `frontend/`: `pnpm tsc --noEmit -p .`
Expected: still fails on Phase-3 sites — but the new field-related errors should NOT be among them. If new errors complain about `IntegrationInlineTrigger`, fix the import path.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/voice/types.ts
git commit -m "Add effects field to SpeechSegment"
```

---

## Phase 3: ResponseTagBuffer + Lovense

### Task 3.1: Rewrite `ResponseTagBuffer` for sync execution and pendingEffectsMap

**Files:**
- Modify: `frontend/src/features/integrations/responseTagProcessor.ts`
- Test: `frontend/src/features/integrations/__tests__/responseTagProcessor.test.ts` (NEW)

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/integrations/__tests__/responseTagProcessor.test.ts`. The test file should cover the following nine cases (use Vitest, mock the registry and store via `vi.doMock`):

1. **Tag detected and replaced with UUID placeholder, stored in pendingEffectsMap.** Plugin returns `{pillContent: 'fx test', syncWithTts: true, effectPayload: {kind: 'demo'}}`. Stream input: `'hello <fx test arg1>world'`. Assert: output starts with `'hello '`, ends with `'world'`, contains a placeholder matching `​[effect:UUID]​`. Plugin called with `('test', ['arg1'], {})`. `pending.size === 1`.
2. **Multiple tag occurrences yield distinct UUIDs.** Stream `'<fx a> and <fx b>'`. Assert: two distinct UUIDs in output.
3. **`syncWithTts=false` with `live_stream` source → emit immediately.** Assert: `emittedEvents.length === 1`, `source === 'live_stream'`, `pending.size === 0`.
4. **`syncWithTts=true` with `text_only` source → emit immediately.** Assert: `emittedEvents.length === 1`, `source === 'text_only'`, `pending.size === 0`.
5. **`syncWithTts=true` with `live_stream` source → entry stays in map.** Assert: `emittedEvents.length === 0`, `pending.size === 1`.
6. **`syncWithTts=true` with `read_aloud` source → entry stays in map** (TTS active during read-aloud). Same shape as case 5.
7. **`flush()` emits residual pending entries.** Process a tag with `syncWithTts=true` + `live_stream` (parks in map), then call `flush()`. Assert: `emittedEvents.length === 1`, `pending.size === 0`.
8. **`sideEffect` rejection is caught.** Plugin returns `{..., sideEffect: () => Promise.reject(new Error('boom'))}`. Assert: pill placeholder still inserted, event still emitted, no exception thrown.
9. **Synchronous throw in `executeTag` → error pill, no event, no map entry.** Plugin's `executeTag` throws. Assert: output contains `'[error:'`, `emittedEvents.length === 0`, `pending.size === 0`.

The buffer constructor signature for these tests is:
```
new ResponseTagBuffer(onTagResolved, streamSource, pendingEffectsMap, emitTrigger)
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `frontend/`: `pnpm vitest run src/features/integrations/__tests__/responseTagProcessor.test.ts`
Expected: all tests fail (file doesn't yet export `PendingEffect`, constructor signature differs).

- [ ] **Step 3: Rewrite `responseTagProcessor.ts`**

Replace the entire content of `frontend/src/features/integrations/responseTagProcessor.ts` with the new implementation. The file must export:

- `PendingEffect` interface with fields: `effectId, integration_id, command, args, pillContent, effectPayload`.
- `StreamSource` type alias: `'live_stream' | 'text_only' | 'read_aloud'`.
- `ResponseTagBuffer` class with the new four-argument constructor: `(onTagResolved, streamSource, pendingEffectsMap, emitTrigger)`.

Implementation notes:
- **UUID generation:** prefer `crypto.randomUUID()` with a Math.random fallback for older test environments.
- **Placeholder format:** `'​[effect:' + effectId + ']​'` (zero-width-space wrappers, matching the existing Lovense convention).
- **Tag parsing loop:** keep the existing character-by-character buffer-on-`<`, flush-on-`>` logic. When a complete tag is parsed and `tagPrefixes.has(integrationId)`, call a private `handleTag(integrationId, command, args)` that returns the placeholder string.
- **`handleTag` flow:**
  1. Generate `effectId` and `placeholder`.
  2. If `plugin?.executeTag` is missing → call `onTagResolved(placeholder, '[error: no tag handler for ' + integrationId + ']')` and return placeholder.
  3. Try-catch synchronous call to `plugin.executeTag(command, args, userConfig)`. On throw → call `onTagResolved(placeholder, '[error: ' + integrationId + ': ' + msg + ']')` and return placeholder.
  4. If `result.sideEffect` is set, invoke it as `void result.sideEffect().catch(err => console.error(...))` — fire-and-forget.
  5. Build a `PendingEffect` with the result data, store in `pendingEffectsMap`.
  6. If `!result.syncWithTts || (streamSource !== 'live_stream' && streamSource !== 'read_aloud')`, immediately call `emitTrigger(toEvent(entry))` and `pending.delete(effectId)`.
  7. Return placeholder.
- **`flush()`:** clear residual `buffer`/`insideTag`, then for every entry in `pending` call `emitTrigger(toEvent(entry))` and clear `pending`. Returns the buffered residual text (empty string if none).
- **`toEvent(entry)`:** construct an `IntegrationInlineTrigger` with `source = this.streamSource`, `correlation_id = ''` (caller can populate), `timestamp = new Date().toISOString()`.

- [ ] **Step 4: Run tests to verify they pass**

Run from `frontend/`: `pnpm vitest run src/features/integrations/__tests__/responseTagProcessor.test.ts`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/integrations/responseTagProcessor.ts frontend/src/features/integrations/__tests__/responseTagProcessor.test.ts
git commit -m "Rewrite ResponseTagBuffer for sync executeTag and pendingEffectsMap"
```

---

### Task 3.2: Migrate Lovense plugin to sync `executeTag` plus `sideEffect`

**Files:**
- Modify: `frontend/src/features/integrations/plugins/lovense/tags.ts`

- [ ] **Step 1: Rewrite the Lovense `tags.ts` to be synchronous**

The current implementation is `async function executeTag(...): Promise<TagExecutionResult>` and returns `{success, displayText}`. Rewrite it as a synchronous function returning the new `TagExecutionResult` shape: `{pillContent, syncWithTts, effectPayload, sideEffect?}`.

Apply the following transformations consistently to each branch:
- `success: false, displayText: '_[Lovense: no IP configured]_'` → `pillContent: 'Lovense: no IP configured', syncWithTts: false, effectPayload: { error: 'no_ip' }`
- `success: true, displayText: '_stop all toys_'` (from `<lovense stopall>`) → `pillContent: 'stop all toys', syncWithTts: false, effectPayload: { kind: 'stopall' }, sideEffect: () => api.stopAll(ip)`
- `success: true, displayText: '_stop ${toyName}_'` (from `<lovense TOYNAME stop>`) → `pillContent: 'stop ${toyName}', syncWithTts: false, effectPayload: { kind: 'stop', toy: toyName }, sideEffect: () => api.stopToy(ip, toyName)`
- `<lovense TOYNAME stroke ...>` branch: build the same `pillContent` text (`'stroke ${toyName} at ${strokePos}/${thrustStrength}${timeText}'`), `syncWithTts: false`, `effectPayload: { kind: 'stroke', toy, strokePos, thrustStrength, seconds }`, and `sideEffect: async () => { const r = await api.strokeCommand(...); if (r.code === 400) throw new Error(r.message) }`.
- The simple-action branch (`vibrate`, `rotate`, etc.): build the same `pillContent` text by joining the parts with spaces (drop the surrounding underscores), `syncWithTts: false`, `effectPayload: { kind: 'simple', toy, action: cappedAction, strength, seconds, loopRun, loopPause, layer }`, and `sideEffect: () => api.functionCommand(ip, { action: cappedAction, strength, timeSec: seconds, toy: toyName, loopRunningSec: loopRun, loopPauseSec: loopPause, stopPrevious: layer ? false : undefined })`.
- The unknown-action terminal branch: `pillContent: 'Lovense: unknown action "${action}"', syncWithTts: false, effectPayload: { error: 'unknown_action', action }`.
- The outer `try { ... } catch (err)` block disappears — synchronous code only throws on programmer error, and synchronous throws are caught by `ResponseTagBuffer` itself.

All hardware actions stay `syncWithTts: false` so they feel responsive (fire when parsed, not when the sentence is spoken).

- [ ] **Step 2: Verify the frontend builds**

Run from `frontend/`: `pnpm run build`
Expected: build succeeds. If errors remain, search for sites still calling `await plugin.executeTag(...)` or reading `result.success` / `result.displayText` outside of tests.

- [ ] **Step 3: Commit**

```
git add frontend/src/features/integrations/plugins/lovense/tags.ts
git commit -m "Migrate Lovense plugin to sync executeTag with sideEffect"
```

---

## Phase 4: Audio Pipeline

### Task 4.1: `audioParser` claims pending effects at sentence boundaries

**Files:**
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts`
- Test: `frontend/src/features/voice/pipeline/__tests__/audioParser.test.ts` (extend existing if present, otherwise create)

- [ ] **Step 1: Read the current `parseForSpeech` signature and shape**

Read `frontend/src/features/voice/pipeline/audioParser.ts` and identify: the exported `parseForSpeech` function and its current signature; where it currently strips voice-expression tags; whether it returns one segment or multiple. The Step-3 changes assume `parseForSpeech` is the single export of interest; if the file has a different shape (e.g. multiple helpers), preserve the existing exports and only modify the function that produces `SpeechSegment`s.

- [ ] **Step 2: Write failing tests**

Append to or create `frontend/src/features/voice/pipeline/__tests__/audioParser.test.ts` with four tests:

1. **Strips effect placeholder from synth text and binds payload to segment.** Build a `pendingEffectsMap` with one entry (effectId `'aaa'`, integration_id `'fx'`, command `'shower'`, args `['💖']`, pillContent `'fx shower 💖'`, effectPayload `{emojis:['💖']}`). Call `parseForSpeech("Sehr gut! ​[effect:aaa]​ Wie geht's?", pending, 'live_stream')`. Assert: `segments[0].text` does NOT contain `'[effect:'` or the zero-width-space character; `segments[0].effects` has length 1 with `command === 'shower'`; `pending.has('aaa') === false`.
2. **Multiple placeholders attach in encounter order.** Two pending entries `'a1'` (command `'one'`) and `'a2'` (command `'two'`). Input: `"​[effect:a1]​ hello ​[effect:a2]​ world"`. Assert: `segments[0].effects.map(e => e.command) === ['one', 'two']`.
3. **Placeholder for an unknown effectId is removed but no effect bound.** Input contains `'[effect:ghost]'` with empty pending map. Assert: text has no placeholder, `segments[0].effects` is undefined or empty.
4. **`source` is propagated to the bound effect events.** Pending entry, call with `streamSource='read_aloud'`. Assert: `segments[0].effects[0].source === 'read_aloud'`.

- [ ] **Step 3: Run tests to verify they fail**

Run from `frontend/`: `pnpm vitest run src/features/voice/pipeline/__tests__/audioParser.test.ts`
Expected: tests fail because `parseForSpeech` doesn't accept the new parameters and segments don't have an `effects` field.

- [ ] **Step 4: Extend `parseForSpeech`**

In `frontend/src/features/voice/pipeline/audioParser.ts`, add at the top alongside existing imports:

```
import type { PendingEffect } from '../../integrations/responseTagProcessor'
import type { IntegrationInlineTrigger } from '../../integrations/types'

const EFFECT_PLACEHOLDER_RE = /​\[effect:([0-9a-f-]+)\]​/g
```

Update the `parseForSpeech` signature to additionally accept the optional `pendingEffectsMap` and `streamSource` parameters:

```
export function parseForSpeech(
  text: string,
  pendingEffectsMap?: Map<string, PendingEffect>,
  streamSource?: 'live_stream' | 'text_only' | 'read_aloud',
): SpeechSegment[] {
```

(Both new params are optional so legacy callers continue to compile; Phase 5 wires up the real callers.)

Inside the function, BEFORE the existing voice-expression-tag stripping, add an effect-extraction step that:

1. Initialises `claimedEffects: IntegrationInlineTrigger[] = []`.
2. If `pendingEffectsMap` is set and non-empty, runs the `EFFECT_PLACEHOLDER_RE` regex over the input (reset `lastIndex = 0` first), and for each match:
   - Looks up the entry in `pendingEffectsMap`.
   - If found: pushes a new `IntegrationInlineTrigger` onto `claimedEffects` with `source: streamSource ?? 'live_stream'`, `correlation_id: ''`, `timestamp: new Date().toISOString()`; deletes the entry from the map.
3. Always strips the placeholder pattern from `text` (also handles orphan placeholders).

Just before `return segments` (or its equivalent), if `claimedEffects.length > 0 && segments.length > 0`, attach all claimed effects to the first segment:

```
segments[0] = { ...segments[0], effects: claimedEffects }
```

This makes the trigger fire at the very start of the synth chunk that contained the tag.

- [ ] **Step 5: Run tests to verify they pass**

Run from `frontend/`: `pnpm vitest run src/features/voice/pipeline/__tests__/audioParser.test.ts`
Expected: all four tests pass.

- [ ] **Step 6: Commit**

```
git add frontend/src/features/voice/pipeline/audioParser.ts frontend/src/features/voice/pipeline/__tests__/audioParser.test.ts
git commit -m "Extend audioParser to claim pending effects at sentence boundary"
```

---

### Task 4.2: `audioPlayback.enqueue` carries `source`; `onSegmentStart` emits effects

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts`

- [ ] **Step 1: Read current `audioPlayback.enqueue` signature**

Open `frontend/src/features/voice/infrastructure/audioPlayback.ts` and locate `enqueue`. Note its current arguments (likely `audio, segment`) and the queue entry shape (`PlaybackEntry` or similar).

- [ ] **Step 2: Add `source` to the queue entry and `enqueue` signature**

Find the `PlaybackEntry`-style internal type. Add a `source` field:

```
interface PlaybackEntry {
  audio: AudioBuffer
  segment: SpeechSegment
  source: 'live_stream' | 'read_aloud'
}
```

(Adapt the surrounding type to what the file actually uses.)

Update `enqueue` to accept and store the new field, defaulting to `'live_stream'` if omitted (so existing call-sites still type-check):

```
public enqueue(
  audio: AudioBuffer,
  segment: SpeechSegment,
  source: 'live_stream' | 'read_aloud' = 'live_stream',
): void {
  this.queue.push({ audio, segment, source })
  // ... existing logic ...
}
```

- [ ] **Step 3: Add `onInlineTrigger` to the callbacks interface**

Find the callbacks interface defined in this file. Add an optional callback:

```
onInlineTrigger?: (event: IntegrationInlineTrigger) => void
```

Import `IntegrationInlineTrigger` from `'../../integrations/types'` at the top.

- [ ] **Step 4: Emit effects in the `onSegmentStart` path**

Locate the spot where `onSegmentStart` is called (around line 201; the spec describes it as "just before `source.start(0)`"). Just before the existing `onSegmentStart` invocation, add:

```
if (entry.segment.effects && entry.segment.effects.length > 0) {
  for (const effect of entry.segment.effects) {
    this.callbacks?.onInlineTrigger?.({ ...effect, source: entry.source })
  }
}
this.callbacks?.onSegmentStart(entry.segment)
```

- [ ] **Step 5: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit -p .`
Expected: no errors specific to this file. Errors elsewhere (`playbackChild.ts` not yet wired, `useChatStream.ts` not yet updated) are tolerated until Phase 5.

- [ ] **Step 6: Commit**

```
git add frontend/src/features/voice/infrastructure/audioPlayback.ts
git commit -m "Add source param and inline-trigger emit hook to audioPlayback"
```

---

### Task 4.3: `playbackChild` passes `source` and emits to event bus

**Files:**
- Modify: `frontend/src/features/voice/children/playbackChild.ts`

- [ ] **Step 1: Read current `playbackChild`**

Open `frontend/src/features/voice/children/playbackChild.ts`. Find where it constructs the audioPlayback callbacks and where it calls `audioPlayback.enqueue`.

- [ ] **Step 2: Add `streamSource` to the child's setup**

Add a constructor argument or setter:

```
constructor(/* existing args */, streamSource: 'live_stream' | 'read_aloud' = 'live_stream') {
  // ...
  this.streamSource = streamSource
}
```

When invoking `audioPlayback.enqueue`, pass `this.streamSource` as the third argument.

- [ ] **Step 3: Wire `onInlineTrigger` callback to the event bus**

In the callbacks object passed to `audioPlayback`, add:

```
onInlineTrigger: (event) => {
  eventBus.emit(Topics.INTEGRATION_INLINE_TRIGGER, event)
},
```

Search for an existing `eventBus` import in the file; if none, follow the pattern used in sibling files like `sentencerChild.ts`. Import `Topics` similarly.

If the project's frontend `Topics` constant does not yet have `INTEGRATION_INLINE_TRIGGER`, add a corresponding string constant in the same place the frontend stores topic strings (search for `'chat.content.delta'` to locate it):

```
INTEGRATION_INLINE_TRIGGER: 'integration.inline.trigger',
```

This must match the value of `Topics.INTEGRATION_INLINE_TRIGGER` from `shared/topics.py`.

- [ ] **Step 4: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit -p .`
Expected: no errors in this file. Outstanding errors in `useChatStream.ts` and `ReadAloudButton.tsx` are tolerated; Phase 5 wires those.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/voice/children/playbackChild.ts
git commit -m "Wire playbackChild inline-trigger emit to eventBus"
```

---

## Phase 5: Stream Integration

### Task 5.1: `useChatStream` constructs `ResponseTagBuffer` with `streamSource`

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts:35` (and surrounding setup)

- [ ] **Step 1: Read current ResponseTagBuffer construction**

Open `frontend/src/features/chat/useChatStream.ts`. Locate the `new ResponseTagBuffer(...)` call (around line 35). Note what it passes as callbacks and what surrounding state determines whether the chat is in voice mode.

- [ ] **Step 2: Detect voice-mode**

Identify the predicate the file already uses to know if voice is active for this stream. Common candidates: a `voiceGroup` reference passed in, a property on `g`, or a hook from `cockpitStore` / `voiceStore`. Search for `voice` usages in the file to find it. The detection should read once at stream-start (not per delta). Variable name: `streamSource: 'live_stream' | 'text_only'`.

- [ ] **Step 3: Construct shared `pendingEffectsMap`**

At stream start (same place as the buffer construction):

```
import { ResponseTagBuffer, type PendingEffect } from '../integrations/responseTagProcessor'

const pendingEffectsMap = new Map<string, PendingEffect>()
```

The audio pipeline (sentencer -> audioParser) runs inside `g`. The map needs to be accessible to that pipeline. If `g` already has slots for per-stream state, park it there:

```
g.pendingEffectsMap = pendingEffectsMap
g.streamSource = streamSource
```

(If `g` has no extension point, add typed slots in its type definition near where `g` is constructed.)

Where `parseForSpeech` is invoked downstream (search the file for the existing call site; it may live inside `g`'s sentencer/synth wiring), update it to pass the map and source:

```
parseForSpeech(text, g.pendingEffectsMap, g.streamSource)
```

- [ ] **Step 4: Update `ResponseTagBuffer` construction**

```
import { eventBus } from '../../core/websocket/eventBus'  // adapt path
import { Topics } from '../../shared/topics'              // adapt path

const buffer = new ResponseTagBuffer(
  onTagResolved,
  streamSource,
  pendingEffectsMap,
  (event) => eventBus.emit(Topics.INTEGRATION_INLINE_TRIGGER, event),
)
```

(Search the codebase for an existing `Topics` import to copy the exact path.)

- [ ] **Step 5: Call `buffer.flush()` at stream end**

Find the existing stream-end handler (likely a `chat.completion.done` or `chat.error` event handler). Add:

```
buffer.flush()
```

This drains any orphan pending effects (tags that arrived after the last sentence boundary).

- [ ] **Step 6: Verify TypeScript compiles**

Run from `frontend/`: `pnpm tsc --noEmit -p .`
Expected: this file's errors are gone. `ReadAloudButton.tsx` may still error until Task 5.2.

- [ ] **Step 7: Commit**

```
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Wire useChatStream to construct ResponseTagBuffer with streamSource"
```

---

### Task 5.2: `ReadAloudButton` re-runs the buffer pipeline

**Files:**
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Read current `ReadAloudButton` flow**

Open `frontend/src/features/voice/components/ReadAloudButton.tsx`. Locate `runReadAloud` (around line 128 per the spec). Note where it calls `parseForSpeech` and `audioPlayback.enqueue`.

- [ ] **Step 2: Add a fresh `pendingEffectsMap` and ResponseTagBuffer pre-pass**

In `runReadAloud`, before the `parseForSpeech` call, add:

```
import { ResponseTagBuffer, type PendingEffect } from '../../integrations/responseTagProcessor'
import { eventBus } from '../../../core/websocket/eventBus'  // adapt path
import { Topics } from '../../../shared/topics'              // adapt path

// inside runReadAloud body:
const pending = new Map<string, PendingEffect>()
const buffer = new ResponseTagBuffer(
  () => {},  // onTagResolved no-op for read-aloud (pill rendering is already-rendered HTML)
  'read_aloud',
  pending,
  (event) => eventBus.emit(Topics.INTEGRATION_INLINE_TRIGGER, event),
)
const sanitisedContent = buffer.process(originalContent) + buffer.flush()
```

(`flush()` returns the buffered residual text and emits any orphan pending effects.)

- [ ] **Step 3: Pass `pending` and `'read_aloud'` to `parseForSpeech`**

```
const segments = parseForSpeech(sanitisedContent, pending, 'read_aloud')
```

- [ ] **Step 4: Pass `'read_aloud'` to `audioPlayback.enqueue`**

```
audioPlayback.enqueue(audio, segment, 'read_aloud')
```

- [ ] **Step 5: Verify TypeScript compiles**

Run from `frontend/`: `pnpm run build`
Expected: clean build, no TypeScript errors.

- [ ] **Step 6: Commit**

```
git add frontend/src/features/voice/components/ReadAloudButton.tsx
git commit -m "Wire ReadAloudButton to re-run ResponseTagBuffer pipeline"
```

---

## Phase 6: Pill Component & Rendering

### Task 6.1: `IntegrationPill` React component plus shared CSS tokens

**Files:**
- Create: `frontend/src/features/integrations/IntegrationPill.tsx`
- Create: `frontend/src/features/integrations/integrationPill.css`

- [ ] **Step 1: Inspect xAI voice-tag pill styling**

Read `frontend/src/features/voice/expressionTags.ts` and search the codebase for where its pills are rendered (`rg -l "expressionTag" frontend/src/`). Capture the exact CSS values used (font-family, font-size, padding, background, color, border-radius). The `IntegrationPill` must look identical.

- [ ] **Step 2: Create the CSS file**

Create `frontend/src/features/integrations/integrationPill.css` with the values copied from voice-expression-tag styling:

```
.integration-pill {
  display: inline-block;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85em;
  padding: 0 0.4em;
  margin: 0 0.15em;
  border-radius: 0.3em;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.78);
  vertical-align: baseline;
  user-select: text;
}
```

(Adjust the hard-coded values to match what Step 1 found. If voice-expression-tag pills use a Tailwind utility class, use the same one rather than duplicating CSS.)

- [ ] **Step 3: Create the component**

Create `frontend/src/features/integrations/IntegrationPill.tsx`:

```
import './integrationPill.css'

interface Props {
  pillContent: string
}

/** Inline pill rendered in chat for an integration's stream tag.
 *  Used by all integrations (Lovense, future Screen Effects, ...) for
 *  visual consistency with xAI voice-expression tag pills. */
export function IntegrationPill({ pillContent }: Props) {
  return <span className="integration-pill">{pillContent}</span>
}
```

- [ ] **Step 4: Verify component compiles**

Run from `frontend/`: `pnpm tsc --noEmit -p .`
Expected: clean.

- [ ] **Step 5: Commit**

```
git add frontend/src/features/integrations/IntegrationPill.tsx frontend/src/features/integrations/integrationPill.css
git commit -m "Add IntegrationPill component and shared CSS tokens"
```

---

### Task 6.2: Wire the message renderer to substitute `[effect:UUID]` placeholders

**Files:**
- Modify: wherever the message renderer currently substitutes the legacy `[id:command]` placeholders. Located in Step 1 below.

This task is the only one in the plan that asks the engineer to **stop and check** before implementing if the existing substitution path looks tangled. The spec author flagged this as the foggy spot.

- [ ] **Step 1: Locate the placeholder substitution site**

Search:
- `rg "u200B" frontend/src/features/chat/ frontend/src/features/integrations/ -l`
- `rg "onTagResolved" frontend/src/`

Find where `onTagResolved` is wired up — its callback site is what currently performs placeholder->displayText substitution in the rendered message. That file is what needs the IntegrationPill wiring.

- [ ] **Step 2: Update the substitution logic**

Two changes are needed:

1. **Recognise the new placeholder pattern:** `​[effect:UUID]​` instead of (or in addition to) `​[id:command]​`. Use the regex `/​\[effect:([0-9a-f-]+)\]​/g`.
2. **Render each match as `<IntegrationPill pillContent={...}>`** instead of inserting raw text.

The `pillContent` for a placeholder comes from:
- **Live stream:** the per-stream `pendingEffectsMap` (parked there by Task 5.1).
- **Persisted message render:** at render time, run the original message content through a fresh `ResponseTagBuffer` (with `streamSource='live_stream'` and a temporary local pending map), then resolve placeholders against that local map.

Plumbing options for live stream — pick the one that fits existing patterns:
- React context (`PendingEffectsContext`).
- Zustand store keyed by stream/correlation id.
- Direct prop drilling through the message-rendering component tree.

**If this turns out to be more entangled than expected** (e.g. multiple message renderers, no clear injection point), STOP and report what you found rather than forcing a solution. The spec explicitly flags this as a known foggy spot.

- [ ] **Step 3: Replace any markdown-text styling around former pills**

The Lovense plugin used to wrap `displayText` in `_..._` (Markdown emphasis). Now `pillContent` is plain text. If any renderer was relying on the underscore styling for italic Lovense pills, remove it — `IntegrationPill` provides the visual treatment.

- [ ] **Step 4: Manually verify in browser**

Run the frontend dev server (`pnpm dev`) and trigger a Lovense-tagged response (or a stub message in the dev tools that contains `<lovense vibrate 5>`). Confirm:
- The pill renders with the new `IntegrationPill` styling.
- It is visually identical to xAI voice-tag pills.

- [ ] **Step 5: Run frontend tests and build**

Run from `frontend/`:
- `pnpm vitest run`
- `pnpm run build`

Expected: all tests pass, build succeeds.

- [ ] **Step 6: Commit**

```
git add <files modified in Step 2>
git commit -m "Render integration tag placeholders via IntegrationPill component"
```

---

## Phase 7: Verification

### Task 7.1: Build, lint, and full-test sweep

- [ ] **Step 1: Backend syntax sweep**

Run: `uv run python -m compileall backend/ shared/ -q`
Expected: no output, all files compile.

- [ ] **Step 2: Backend test sweep (host-OK only)**

Run: `uv run pytest backend/tests/ -v --ignore=backend/tests/test_database.py --ignore=backend/tests/test_persona_repository.py --ignore=backend/tests/test_user_repository.py --ignore=backend/tests/test_chat_repository.py`
Expected: all listed tests pass. (DB-dependent suites are excluded — they need Docker.)

- [ ] **Step 3: Frontend test sweep**

Run from `frontend/`: `pnpm vitest run`
Expected: all tests pass.

- [ ] **Step 4: Frontend full build**

Run from `frontend/`: `pnpm run build`
Expected: build completes, dist/ produced.

- [ ] **Step 5: Frontend lint (if configured)**

Run from `frontend/`: `pnpm lint`
Expected: no errors. Warnings are acceptable but should be reviewed.

- [ ] **Step 6: Commit only if anything was fixed during the sweep**

If the sweep surfaced fixes, commit them. Otherwise no commit is needed — this task is a verification gate, not a code-producer.

---

### Task 7.2: Manual verification (Chris)

This task is for Chris — not a subagent. The plan must be functionally verified on real devices before merging.

- [ ] **Step 1: Stub a test plugin**

Add a temporary `test_inline` plugin in `backend/modules/integrations/_registry.py` and a matching FE plugin in `frontend/src/features/integrations/plugins/test_inline/`, with `default_enabled=True` and two commands: `sync` returning `syncWithTts: true` and `now` returning `syncWithTts: false`.

- [ ] **Steps 2-9: Run the verification checklist**

Follow each Manual Verification step in `devdocs/specs/2026-04-30-integration-inline-triggers-design.md` (section "Manual Verification"). Check off each step as it passes.

- [ ] **Step 10: Remove the test plugin**

Once verification is complete, revert the test-plugin commits (or delete the files and remove from the registry).

- [ ] **Step 11: Commit removal of test plugin if changes were made**

```
git add -A
git commit -m "Remove temporary test_inline plugin used for foundation verification"
```

---

## Self-Review Notes

**Spec coverage check:**
- Goal 1 (in-stream commands, TTS-excluded, pill-rendered, frontend events) → Tasks 3.1, 4.1, 4.2, 4.3, 6.1, 6.2 ✓
- Goal 2 (sentence-sync vs immediate emit) → Tasks 3.1 (decision logic), 4.1 (claim), 4.2-4.3 (emit) ✓
- Goal 3 (single catch-all topic) → Task 1.1 ✓
- Goal 4 (default-on with explicit opt-out) → Task 1.2 ✓
- Goal 5 (decouple prompt extension from tools_enabled) → Task 1.3 ✓
- Goal 6 (Read-Aloud / Auto-Read-Aloud re-trigger) → Task 5.2 ✓

**Spec edge-case coverage:**
- Tag before first sentence → Task 4.1 (audioParser claims at first sentence boundary) ✓
- Tag after final sentence → Task 3.1 Step 3 (`flush()` drains residual) ✓
- Multiple tags per sentence → Task 4.1 tests ("multiple placeholders attach in encounter order") ✓
- Stream aborted → `pendingEffectsMap` is local to stream's `g` reference; garbage-collected ✓
- Plugin sync throw → Task 3.1 tests ✓
- sideEffect rejection → Task 3.1 tests ✓
- Unknown integration_id → preserved from current ResponseTagBuffer behaviour (tag passes as plain text) ✓
- Re-trigger overlap with live → independent `pendingEffectsMap` plus `audioPlayback` instances (Task 5.2) ✓

**Open implementation question for Task 6.2:**
The exact site that today substitutes `displayText` placeholders in the rendered message is not fully nailed down in the spec. The plan flags this as a tricky point and explicitly tells the implementer to stop and ask if it gets entangled. This is the right behaviour — it's a known foggy spot.

**Migration safety:**
- No DB migrations (compliant with no-more-wipes rule)
- `default_enabled=False` default → existing integrations unchanged
- Lovense visual change is intentional and was approved during brainstorming
