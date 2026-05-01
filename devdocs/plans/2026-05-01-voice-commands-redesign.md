# Voice Commands Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Subagent constraint (project policy):** every subagent dispatch for this plan must include the explicit instruction: *do not merge, do not push, do not switch branches*. The dispatcher (Claude main session) commits and integrates between tasks.

**Goal:** Replace the `companion`-triggered voice-command lifecycle with a `voice`-triggered redesign — synonym-tolerant, strict-reject for misheard 2-token commands, amber pause indicator in cockpit + top-bar with click-to-resume, hidden Hold-to-keep-talking in paused mode, and an updated Vosk OFF-state grammar.

**Architecture:** Bottom-up rebuild. Store + types first, then handler with synonym dispatch, then dispatcher's strict-reject, then Vosk grammar, then the three UI surfaces (cockpit derive + button, top-bar pill, ChatView wiring). Each task is TDD with one failing test, minimal implementation, run, commit.

**Tech Stack:** TypeScript + React 18 + Vite + Tailwind. Zustand for the lifecycle store. Vitest for tests. Vosk-browser for the local OFF-state recogniser. No backend changes.

**Spec:** [`devdocs/specs/2026-05-01-voice-commands-redesign-design.md`](../specs/2026-05-01-voice-commands-redesign-design.md)

**Branch:** `voice-commands-redesign` (already created; spec already committed).

**Build verification:** every commit must pass `pnpm run build` from `frontend/` (catches the strict `tsc -b` errors that `tsc --noEmit` misses — see memory `feedback_frontend_build_check.md`).

**Test verification:** vitest commands run from the project root via `cd frontend && pnpm vitest run <path>`.

---

## Task ordering and parallelism

```
Task 1 — store rename       ┐
Task 2 — handler rewrite    │  sequential
Task 3 — dispatcher reject  ┘
Task 4 — vosk grammar          (parallel with 1–3)
Task 5 — _voiceState derive ┐
Task 6 — cockpit button     │  sequential
Task 7 — top-bar pill          (parallel with 5–6)
Task 8 — ChatView wiring       (after 6 + 7)
Task 9 — final build + manual verification
```

---

### Task 1: Rename `companionLifecycleStore` → `voiceLifecycleStore`

**Files:**
- Create: `frontend/src/features/voice-commands/voiceLifecycleStore.ts`
- Create: `frontend/src/features/voice-commands/__tests__/voiceLifecycleStore.test.ts`
- Delete: `frontend/src/features/voice-commands/companionLifecycleStore.ts`
- Delete: `frontend/src/features/voice-commands/__tests__/companionLifecycleStore.test.ts`
- Modify: `frontend/src/features/voice-commands/index.ts` (re-export rename)
- Modify: `frontend/src/features/voice-commands/handlers/companion.ts` (import rename, will be replaced in Task 2 — minimal touch only)
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts` (import + reset call)

- [ ] **Step 1: Write the new store test**

Create `frontend/src/features/voice-commands/__tests__/voiceLifecycleStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useVoiceLifecycleStore } from '../voiceLifecycleStore'

describe('voiceLifecycleStore', () => {
  beforeEach(() => {
    useVoiceLifecycleStore.getState().reset()
  })

  it('starts in active state', () => {
    expect(useVoiceLifecycleStore.getState().state).toBe('active')
  })

  it('setPause() transitions to paused', () => {
    useVoiceLifecycleStore.getState().setPause()
    expect(useVoiceLifecycleStore.getState().state).toBe('paused')
  })

  it('setActive() transitions back to active', () => {
    useVoiceLifecycleStore.getState().setPause()
    useVoiceLifecycleStore.getState().setActive()
    expect(useVoiceLifecycleStore.getState().state).toBe('active')
  })

  it('reset() returns to active from any state', () => {
    useVoiceLifecycleStore.getState().setPause()
    useVoiceLifecycleStore.getState().reset()
    expect(useVoiceLifecycleStore.getState().state).toBe('active')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/voiceLifecycleStore.test.ts`
Expected: FAIL — module `../voiceLifecycleStore` not found.

- [ ] **Step 3: Write the new store**

Create `frontend/src/features/voice-commands/voiceLifecycleStore.ts`:

```ts
import { create } from 'zustand'

/**
 * Lifecycle of the voice companion.
 *
 * - 'active' : normal continuous-voice operation. External STT is the audio sink.
 * - 'paused' : assistant is paused. External STT receives no audio; only the
 *              local Vosk recogniser listens for the resume / status phrases.
 *
 * Transitions are triggered by the voice handler. Side-effecting consumers
 * (audio routing in useConversationMode, vosk feeding) read the current state
 * at their callsite — the store itself is intentionally inert.
 *
 * reset() on continuous-voice stop ensures every fresh session starts in
 * 'active'. No persistence across reloads — the paused state has no meaning
 * outside an active continuous-voice session.
 */
export type VoiceLifecycle = 'active' | 'paused'

interface VoiceLifecycleStore {
  state: VoiceLifecycle
  setPause: () => void
  setActive: () => void
  reset: () => void
}

export const useVoiceLifecycleStore = create<VoiceLifecycleStore>((set) => ({
  state: 'active',
  setPause: () => set({ state: 'paused' }),
  setActive: () => set({ state: 'active' }),
  reset: () => set({ state: 'active' }),
}))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/voiceLifecycleStore.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Update `index.ts` re-export**

In `frontend/src/features/voice-commands/index.ts`, replace:

```ts
export { useCompanionLifecycleStore } from './companionLifecycleStore'
```

with:

```ts
export { useVoiceLifecycleStore } from './voiceLifecycleStore'
export type { VoiceLifecycle } from './voiceLifecycleStore'
```

- [ ] **Step 6: Update `handlers/companion.ts` import (minimal touch)**

In `frontend/src/features/voice-commands/handlers/companion.ts`, replace the import line:

```ts
import { useCompanionLifecycleStore } from '../companionLifecycleStore'
```

with:

```ts
import { useVoiceLifecycleStore } from '../voiceLifecycleStore'
```

Then update the three call-sites within the file: `useCompanionLifecycleStore.getState()` → `useVoiceLifecycleStore.getState()`, and the existing `lifecycle.setOff()` / `lifecycle.setOn()` calls → `lifecycle.setPause()` / `lifecycle.setActive()`. Update the `lifecycle.state === 'off' ? ... : ...` check to `lifecycle.state === 'paused' ? ... : ...`. The whole file is replaced in Task 2; this is a temporary build-keep-green patch only.

- [ ] **Step 7: Update `handlers/companion.ts` test imports**

In `frontend/src/features/voice-commands/__tests__/handlers/companion.test.ts`, replace `useCompanionLifecycleStore` with `useVoiceLifecycleStore`, and the literal state values `'on'`/`'off'` with `'active'`/`'paused'`. The whole test is replaced in Task 2.

- [ ] **Step 8: Update `useConversationMode.ts`**

In `frontend/src/features/voice/hooks/useConversationMode.ts:15`, replace:

```ts
import { tryDispatchCommand, vosk, useCompanionLifecycleStore } from '../../voice-commands'
```

with:

```ts
import { tryDispatchCommand, vosk, useVoiceLifecycleStore } from '../../voice-commands'
```

Then update the three call sites within the file:
- Line ~286: `useCompanionLifecycleStore.getState().state === 'off'` → `useVoiceLifecycleStore.getState().state === 'paused'`
- Line ~524: `useCompanionLifecycleStore.getState().reset()` → `useVoiceLifecycleStore.getState().reset()`

- [ ] **Step 9: Delete the old store and its test**

```bash
rm frontend/src/features/voice-commands/companionLifecycleStore.ts
rm frontend/src/features/voice-commands/__tests__/companionLifecycleStore.test.ts
```

- [ ] **Step 10: Verify build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds, no type errors.

- [ ] **Step 11: Run the affected tests**

Run: `cd frontend && pnpm vitest run src/features/voice-commands src/features/voice`
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/features/voice-commands/voiceLifecycleStore.ts \
        frontend/src/features/voice-commands/__tests__/voiceLifecycleStore.test.ts \
        frontend/src/features/voice-commands/index.ts \
        frontend/src/features/voice-commands/handlers/companion.ts \
        frontend/src/features/voice-commands/__tests__/handlers/companion.test.ts \
        frontend/src/features/voice/hooks/useConversationMode.ts
git rm frontend/src/features/voice-commands/companionLifecycleStore.ts \
       frontend/src/features/voice-commands/__tests__/companionLifecycleStore.test.ts
git commit -m "Rename companionLifecycleStore to voiceLifecycleStore (active/paused)

Lifecycle states 'on'/'off' become 'active'/'paused'; method names
become setActive()/setPause(); reset() target updated. Existing
companion handler keeps working — replaced wholesale in the next
commit."
```

---

### Task 2: Rewrite the handler as `voiceCommand` with synonyms

**Files:**
- Create: `frontend/src/features/voice-commands/handlers/voice.ts`
- Create: `frontend/src/features/voice-commands/__tests__/handlers/voice.test.ts`
- Delete: `frontend/src/features/voice-commands/handlers/companion.ts`
- Delete: `frontend/src/features/voice-commands/__tests__/handlers/companion.test.ts`
- Modify: `frontend/src/features/voice-commands/index.ts` (export rename)

- [ ] **Step 1: Write the handler test**

Create `frontend/src/features/voice-commands/__tests__/handlers/voice.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { voiceCommand } from '../../handlers/voice'
import { useVoiceLifecycleStore } from '../../voiceLifecycleStore'

const PAUSE_TOAST = 'Paused — say "voice on" to resume.'
const ACTIVE_TOAST = 'Listening — say "voice off" to pause.'

describe('voiceCommand', () => {
  beforeEach(() => {
    useVoiceLifecycleStore.getState().reset()
  })

  describe('pause synonyms', () => {
    for (const sub of ['pause', 'off', 'of'] as const) {
      it(`'${sub}' transitions to paused, plays off cue, abandons`, async () => {
        const r = await voiceCommand.execute(sub)
        expect(r.level).toBe('success')
        expect(r.cue).toBe('off')
        expect(r.displayText).toBe(PAUSE_TOAST)
        expect(r.onTriggerWhilePlaying).toBeUndefined()
        expect(useVoiceLifecycleStore.getState().state).toBe('paused')
      })
    }
  })

  describe('active synonyms', () => {
    for (const sub of ['continue', 'on', 'resume'] as const) {
      it(`'${sub}' from paused transitions to active`, async () => {
        useVoiceLifecycleStore.getState().setPause()
        const r = await voiceCommand.execute(sub)
        expect(r.level).toBe('success')
        expect(r.cue).toBe('on')
        expect(r.displayText).toBe(ACTIVE_TOAST)
        expect(useVoiceLifecycleStore.getState().state).toBe('active')
      })
    }

    it('idempotent already-active path returns resume override', async () => {
      const r = await voiceCommand.execute('on')
      expect(r.level).toBe('info')
      expect(r.onTriggerWhilePlaying).toBe('resume')
      expect(useVoiceLifecycleStore.getState().state).toBe('active')
    })
  })

  describe('status synonyms', () => {
    for (const sub of ['status', 'state'] as const) {
      it(`'${sub}' while active returns active toast and on cue`, async () => {
        const r = await voiceCommand.execute(sub)
        expect(r.cue).toBe('on')
        expect(r.displayText).toBe(ACTIVE_TOAST)
        expect(r.onTriggerWhilePlaying).toBe('resume')
        expect(useVoiceLifecycleStore.getState().state).toBe('active')
      })

      it(`'${sub}' while paused returns paused toast and off cue`, async () => {
        useVoiceLifecycleStore.getState().setPause()
        const r = await voiceCommand.execute(sub)
        expect(r.cue).toBe('off')
        expect(r.displayText).toBe(PAUSE_TOAST)
        expect(r.onTriggerWhilePlaying).toBe('resume')
        expect(useVoiceLifecycleStore.getState().state).toBe('paused')
      })
    }
  })

  describe('unknown sub', () => {
    it('returns error and does not transition', async () => {
      const r = await voiceCommand.execute('nope')
      expect(r.level).toBe('error')
      expect(r.onTriggerWhilePlaying).toBe('resume')
      expect(useVoiceLifecycleStore.getState().state).toBe('active')
    })
  })

  describe('static spec metadata', () => {
    it('has the trigger "voice"', () => {
      expect(voiceCommand.trigger).toBe('voice')
    })
    it('defaults onTriggerWhilePlaying to abandon', () => {
      expect(voiceCommand.onTriggerWhilePlaying).toBe('abandon')
    })
    it('source is core', () => {
      expect(voiceCommand.source).toBe('core')
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/handlers/voice.test.ts`
Expected: FAIL — module `../../handlers/voice` not found.

- [ ] **Step 3: Implement the handler**

Create `frontend/src/features/voice-commands/handlers/voice.ts`:

```ts
import { useVoiceLifecycleStore } from '../voiceLifecycleStore'
import type { CommandSpec, CommandResponse } from '../types'

const PAUSE_SYNONYMS  = new Set(['pause', 'off', 'of'])
const ACTIVE_SYNONYMS = new Set(['continue', 'on', 'resume'])
const STATUS_SYNONYMS = new Set(['status', 'state'])

const PAUSE_TOAST  = 'Paused — say "voice on" to resume.'
const ACTIVE_TOAST = 'Listening — say "voice off" to pause.'

/** True if `token` is a recognised voice subcommand. Used by the dispatcher's
 *  strict-reject pre-check (see dispatcher.ts). Exported deliberately. */
export function isKnownVoiceSub(token: string): boolean {
  return PAUSE_SYNONYMS.has(token) || ACTIVE_SYNONYMS.has(token) || STATUS_SYNONYMS.has(token)
}

/**
 * Built-in voice-lifecycle command. Single trigger `voice`, three actions
 * selected by the first token of the body (synonym sets above):
 *
 *  - pause   → setPause(), off cue, PAUSE_TOAST, default abandon
 *  - active  → setActive(), on cue, ACTIVE_TOAST, default abandon (no-op when
 *              entering from paused — no Group exists); already-active path
 *              returns 'resume' override so the persona is not interrupted.
 *  - status  → no transition, current-state cue + toast, always 'resume'.
 */
export const voiceCommand: CommandSpec = {
  trigger: 'voice',
  onTriggerWhilePlaying: 'abandon',
  source: 'core',
  execute: async (body: string): Promise<CommandResponse> => {
    const lifecycle = useVoiceLifecycleStore.getState()
    const sub = body.trim().split(/\s+/)[0] ?? ''

    if (PAUSE_SYNONYMS.has(sub)) {
      lifecycle.setPause()
      return { level: 'success', cue: 'off', displayText: PAUSE_TOAST }
    }

    if (ACTIVE_SYNONYMS.has(sub)) {
      if (lifecycle.state === 'active') {
        return {
          level: 'info',
          cue: 'on',
          displayText: ACTIVE_TOAST,
          onTriggerWhilePlaying: 'resume',
        }
      }
      lifecycle.setActive()
      return { level: 'success', cue: 'on', displayText: ACTIVE_TOAST }
    }

    if (STATUS_SYNONYMS.has(sub)) {
      const paused = lifecycle.state === 'paused'
      return {
        level: 'info',
        cue: paused ? 'off' : 'on',
        displayText: paused ? PAUSE_TOAST : ACTIVE_TOAST,
        onTriggerWhilePlaying: 'resume',
      }
    }

    return {
      level: 'error',
      displayText: `Unknown voice command: '${sub}'.`,
      onTriggerWhilePlaying: 'resume',
    }
  },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/handlers/voice.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Update `index.ts`**

In `frontend/src/features/voice-commands/index.ts`, replace:

```ts
import { companionCommand } from './handlers/companion'
```

with:

```ts
import { voiceCommand } from './handlers/voice'
```

Update `registerCoreBuiltins` and `unregisterCoreBuiltins`:

```ts
export function registerCoreBuiltins(): void {
  registerCommand(debugCommand)
  registerCommand(voiceCommand)
}

export function unregisterCoreBuiltins(): void {
  unregisterCommand(debugCommand.trigger)
  unregisterCommand(voiceCommand.trigger)
}
```

- [ ] **Step 6: Delete the old handler and its test**

```bash
rm frontend/src/features/voice-commands/handlers/companion.ts
rm frontend/src/features/voice-commands/__tests__/handlers/companion.test.ts
```

- [ ] **Step 7: Verify build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds.

- [ ] **Step 8: Run the affected tests**

Run: `cd frontend && pnpm vitest run src/features/voice-commands`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/voice-commands/handlers/voice.ts \
        frontend/src/features/voice-commands/__tests__/handlers/voice.test.ts \
        frontend/src/features/voice-commands/index.ts
git rm frontend/src/features/voice-commands/handlers/companion.ts \
       frontend/src/features/voice-commands/__tests__/handlers/companion.test.ts
git commit -m "Replace companionCommand with voiceCommand (synonyms + b-variant toasts)

Trigger 'voice' with three synonym sets: pause/off/of, continue/on/resume,
status/state. Toasts include the synonym hint per design (b). Status
always returns 'resume' override; idempotent already-active path likewise."
```

---

### Task 3: Strict-reject for 2-token `voice <unknown>` in dispatcher

**Files:**
- Modify: `frontend/src/features/voice-commands/dispatcher.ts`
- Modify: `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts`

- [ ] **Step 1: Read the current dispatcher test**

Open `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts` to understand the existing structure (registry mocking, etc.). New tests follow the same pattern.

- [ ] **Step 2: Add strict-reject tests**

Append the following describe block to `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts`. (The exact registry-setup pattern is whatever the existing tests use — copy that for consistency.)

```ts
import { tryDispatchCommand } from '../dispatcher'
import { registerCommand, unregisterCommand } from '../registry'
import { voiceCommand } from '../handlers/voice'
// (other imports are whatever the existing test file uses)

describe('strict-reject for 2-token "voice <unknown>"', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    registerCommand(voiceCommand)
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    unregisterCommand(voiceCommand.trigger)
    warnSpy.mockRestore()
  })

  it('rejects "voice nope" without dispatching to LLM', async () => {
    const r = await tryDispatchCommand('voice nope')
    expect(r.dispatched).toBe(true)
    if (r.dispatched) expect(r.onTriggerWhilePlaying).toBe('resume')
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining('Rejected 2-token'),
      expect.anything(),
    )
  })

  it('does NOT reject "voice off" (known sub) — dispatches normally', async () => {
    const r = await tryDispatchCommand('voice off')
    expect(r.dispatched).toBe(true)
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('does NOT reject 3-token "voice that is great" — falls through to LLM', async () => {
    const r = await tryDispatchCommand('voice that is great')
    expect(r.dispatched).toBe(false)
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('does NOT reject single-token "voice"', async () => {
    const r = await tryDispatchCommand('voice')
    expect(r.dispatched).toBe(false)
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('strips trailing punctuation before reject check ("voice nope.")', async () => {
    const r = await tryDispatchCommand('voice nope.')
    expect(r.dispatched).toBe(true)
    expect(warnSpy).toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/dispatcher.test.ts`
Expected: the strict-reject tests fail (existing tests still pass).

- [ ] **Step 4: Implement strict-reject in `dispatcher.ts`**

Modify `frontend/src/features/voice-commands/dispatcher.ts`. Add the import:

```ts
import { isKnownVoiceSub } from './handlers/voice'
```

Insert the reject block immediately after `const tokens = normalise(text)` and before `const hit = match(tokens)`:

```ts
// Strict-reject for 2-token "voice <unknown>": the user almost certainly
// intended a command but mis-spoke or was misheard. Suppress LLM dispatch
// rather than letting "voice pose" become a chat message.
//
// TODO: add error toast and audible feedback with error sound
if (tokens.length === 2 && tokens[0] === 'voice' && !isKnownVoiceSub(tokens[1])) {
  console.warn('[VoiceCommand] Rejected 2-token "voice <unknown>":', tokens)
  return { dispatched: true, onTriggerWhilePlaying: 'resume' }
}
```

- [ ] **Step 5: Run all dispatcher tests**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/dispatcher.test.ts`
Expected: all pass (including pre-existing).

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice-commands/dispatcher.ts \
        frontend/src/features/voice-commands/__tests__/dispatcher.test.ts
git commit -m "Strict-reject 2-token 'voice <unknown>' in dispatcher

Suppresses LLM dispatch for the most common misheard-command shape
without affecting longer sentences that legitimately start with 'voice'.
TODO comment marks the follow-up: error toast + audible feedback."
```

---

### Task 4: Vosk OFF-state grammar update

**Files:**
- Modify: `frontend/src/features/voice-commands/vosk/grammar.ts`
- Modify: `frontend/src/features/voice-commands/__tests__/vosk/grammar.test.ts`

- [ ] **Step 1: Update the grammar test**

Replace `frontend/src/features/voice-commands/__tests__/vosk/grammar.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { ACCEPT_TEXTS, VOSK_GRAMMAR } from '../../vosk/grammar'

describe('VOSK_GRAMMAR / ACCEPT_TEXTS', () => {
  it('accept set contains exactly the five voice phrases', () => {
    expect([...ACCEPT_TEXTS].sort()).toEqual([
      'voice continue',
      'voice on',
      'voice resume',
      'voice state',
      'voice status',
    ])
  })

  it('grammar contains the [unk] garbage path', () => {
    expect(VOSK_GRAMMAR).toContain('[unk]')
  })

  it('grammar contains every accept phrase', () => {
    for (const phrase of ACCEPT_TEXTS) {
      expect(VOSK_GRAMMAR).toContain(phrase)
    }
  })

  it('every standalone distractor also appears with each subcommand', () => {
    const subs = ['on', 'continue', 'resume', 'status', 'state'] as const
    const distractors = ['noise', 'choice', 'boys', 'poise', 'vice', 'rice'] as const
    for (const d of distractors) {
      expect(VOSK_GRAMMAR).toContain(d)
      for (const s of subs) {
        expect(VOSK_GRAMMAR).toContain(`${d} ${s}`)
      }
    }
  })

  it('voice itself appears as a standalone distractor (drop, do not collapse)', () => {
    expect(VOSK_GRAMMAR).toContain('voice')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/vosk/grammar.test.ts`
Expected: tests fail against the old `companion`-based grammar.

- [ ] **Step 3: Replace `vosk/grammar.ts`**

Replace `frontend/src/features/voice-commands/vosk/grammar.ts`:

```ts
/**
 * Vosk constrained grammar for the paused-state recogniser.
 *
 * Discipline (lifted from VOSK-STT.md spike):
 *  - Only the accept phrases are actionable. Any other final-result text is
 *    rejected at recogniser level via ACCEPT_TEXTS.
 *  - Every standalone phonetic distractor of 'voice' appears both standalone
 *    AND with each subcommand — without the second-word forms, the second
 *    word collapses onto the accept set when the first word is misheard
 *    (VOSK-STT.md pitfall #7).
 *  - 'voice' itself appears as a standalone distractor: a user who says
 *    'voice' and trails off must drop, not collapse onto an accept entry.
 *  - '[unk]' is mandatory: gives Viterbi a "this isn't a wake phrase" path
 *    and prevents near-misses from collapsing onto the accept set with
 *    full confidence (VOSK-STT.md pitfall #6).
 *  - 'voice off' / 'voice pause' / 'voice of' are deliberately omitted: in
 *    the paused state, hearing them again is a no-op, and adding the path
 *    only increases competition for the decoder.
 *
 * If false positives surface in production from new word neighbours,
 * extend BOTH the standalone list AND the second-word phrases. Skipping
 * the second-word entries reproduces pitfall #7.
 */

export const VOSK_GRAMMAR: readonly string[] = [
  // Accept set
  'voice on',
  'voice continue',
  'voice resume',
  'voice status',
  'voice state',

  // Phonetic distractors of 'voice' — standalone (VOSK-STT.md pitfall #6)
  'noise',
  'choice',
  'boys',
  'voice',
  'poise',
  'vice',
  'rice',

  // Phonetic distractors of 'voice' — with each subcommand (pitfall #7)
  'noise on',  'noise continue',  'noise resume',  'noise status',  'noise state',
  'choice on', 'choice continue', 'choice resume', 'choice status', 'choice state',
  'boys on',   'boys continue',   'boys resume',   'boys status',   'boys state',
  'poise on',  'poise continue',  'poise resume',  'poise status',  'poise state',
  'vice on',   'vice continue',   'vice resume',   'vice status',   'vice state',
  'rice on',   'rice continue',   'rice resume',   'rice status',   'rice state',

  // Garbage model
  '[unk]',
]

/** Set of texts that are valid resume / status phrases. Recogniser drops anything else. */
export const ACCEPT_TEXTS: ReadonlySet<string> = new Set([
  'voice on',
  'voice continue',
  'voice resume',
  'voice status',
  'voice state',
])
```

- [ ] **Step 4: Run grammar test**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/vosk/grammar.test.ts`
Expected: all pass.

- [ ] **Step 5: Run the recogniser test**

Run: `cd frontend && pnpm vitest run src/features/voice-commands/__tests__/vosk/recogniser.test.ts`
Expected: pass — the recogniser test asserts ACCEPT_TEXTS membership semantically, not by content; the new accept set is still a `Set<string>`. If a test contains the literal `'companion on'` or `'companion status'`, replace with `'voice on'` / `'voice status'`.

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm run build`
Expected: succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice-commands/vosk/grammar.ts \
        frontend/src/features/voice-commands/__tests__/vosk/grammar.test.ts \
        frontend/src/features/voice-commands/__tests__/vosk/recogniser.test.ts
git commit -m "Update Vosk OFF-state grammar to voice trigger

Five accept phrases (voice on/continue/resume/status/state), six
phonetic distractors with full second-word matrix, plus voice itself
as standalone distractor. voice off/pause/of deliberately omitted —
no-op in paused state, only adds decoder competition."
```

---

### Task 5: Cockpit `_voiceState` derive — new `live-paused` kind

**Files:**
- Modify: `frontend/src/features/chat/cockpit/buttons/_voiceState.ts`
- Modify: `frontend/src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`

- [ ] **Step 1: Read the existing derive function**

Open `frontend/src/features/chat/cockpit/buttons/_voiceState.ts` and inspect the input shape and the existing `kind` union. The new input field is `lifecycle: VoiceLifecycle` and the new kind is `'live-paused'`. The branch takes precedence over both `live-mic-on` and `live-mic-muted` when in live mode.

- [ ] **Step 2: Add tests for `live-paused`**

In `frontend/src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`, add tests at the end:

```ts
import type { VoiceLifecycle } from '@/features/voice-commands'

describe('live-paused state', () => {
  const baseInput = {
    personaHasVoice: true,
    liveMode: true,
    ttsPlaying: false,
    autoRead: false,
    micMuted: false,
    lifecycle: 'paused' as VoiceLifecycle,
  }

  it('returns live-paused when live and paused', () => {
    expect(deriveVoiceUIState(baseInput).kind).toBe('live-paused')
  })

  it('takes precedence over mic-on', () => {
    expect(deriveVoiceUIState({ ...baseInput, micMuted: false }).kind).toBe('live-paused')
  })

  it('takes precedence over mic-muted', () => {
    expect(deriveVoiceUIState({ ...baseInput, micMuted: true }).kind).toBe('live-paused')
  })

  it('does NOT trigger when not in live mode', () => {
    const r = deriveVoiceUIState({ ...baseInput, liveMode: false })
    expect(r.kind).not.toBe('live-paused')
  })

  it('does NOT trigger when lifecycle is active', () => {
    const r = deriveVoiceUIState({ ...baseInput, lifecycle: 'active' })
    expect(r.kind).not.toBe('live-paused')
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`
Expected: new tests fail (TS error: `lifecycle` not in input type).

- [ ] **Step 4: Update `_voiceState.ts`**

In `frontend/src/features/chat/cockpit/buttons/_voiceState.ts`:

1. Add the import: `import type { VoiceLifecycle } from '@/features/voice-commands'`
2. Add `'live-paused'` to the `VoiceUIState` union: `| { kind: 'live-paused' }`
3. Add `lifecycle: VoiceLifecycle` to the input type.
4. In `deriveVoiceUIState`, insert the precedence branch — before the existing `live-mic-on`/`live-mic-muted` check, after the `personaHasVoice`/`liveMode` gates:

```ts
if (liveMode && lifecycle === 'paused') {
  return { kind: 'live-paused' }
}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && pnpm vitest run src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`
Expected: all pass.

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm run build`
Expected: build will likely fail in `VoiceButton.tsx` because the call site does not yet pass `lifecycle`. The next task fixes that. Acceptable to commit only after Task 6 if you want a green tree per commit; otherwise commit now and pick up the build at the end of Task 6. **Recommended:** defer the commit to the end of Task 6 to keep `main`-style green-build discipline.

---

### Task 6: Cockpit `VoiceButton` — paused branch + click handler + visual

**Files:**
- Modify: `frontend/src/features/chat/cockpit/buttons/VoiceButton.tsx`
- Possibly modify: `frontend/src/features/chat/cockpit/CockpitButton.tsx` (only if the `state` discriminator needs a new `'paused'` value)

- [ ] **Step 1: Inspect `CockpitButton`'s state discriminator**

Read `frontend/src/features/chat/cockpit/CockpitButton.tsx`. If the `state` prop is typed `'idle' | 'active' | 'playback' | 'disabled'`, extend it: add `'paused'` and a corresponding visual (amber border + amber pulse). If the visual is driven entirely by Tailwind classes passed via props, no change is needed — the parent owns the styling.

- [ ] **Step 2: Update `VoiceButton.tsx`**

In `frontend/src/features/chat/cockpit/buttons/VoiceButton.tsx`:

1. Add the import:

```ts
import { useVoiceLifecycleStore } from '@/features/voice-commands'
```

2. Read the lifecycle in the component body alongside the other `useStore` calls:

```ts
const lifecycle = useVoiceLifecycleStore((s) => s.state)
const setActive = useVoiceLifecycleStore((s) => s.setActive)
```

3. Pass `lifecycle` into `deriveVoiceUIState({...})`:

```ts
const ui = deriveVoiceUIState({
  personaHasVoice,
  liveMode: liveActive,
  ttsPlaying,
  autoRead,
  micMuted,
  lifecycle,
})
```

4. Extend `iconNode` so `live-paused` renders the muted mic glyph:

```ts
const iconNode: ReactNode =
  ui.kind === 'live-mic-on'     ? <MicIcon muted={false} /> :
  ui.kind === 'live-mic-muted'  ? <MicIcon muted={true}  /> :
  ui.kind === 'live-paused'     ? <MicIcon muted={true}  /> :
  iconFor[ui.kind]
```

5. Extend `iconFor` (the `Record` for non-mic states): no change needed — `live-paused` is handled in `iconNode` directly.

6. Add the click branch in `onClick`:

```ts
case 'live-paused':     return setActive()
```

7. Extend `stateClass` (the variable that picks `'playback' | 'idle' | 'active'`). Add a `'paused'` value:

```ts
const stateClass: 'playback' | 'idle' | 'active' | 'paused' =
  ui.kind === 'normal-playing' || ui.kind === 'live-playing' ? 'playback' :
  ui.kind === 'live-paused'                                  ? 'paused'   :
  (ui.kind === 'normal-off' || ui.kind === 'live-mic-muted') ? 'idle'     : 'active'
```

8. Add a `live-paused` case to `labelFor` and `statusFor`:

```ts
function labelFor(kind: Exclude<VoiceUIState['kind'], 'disabled'>): string {
  switch (kind) {
    case 'normal-off':     return 'Auto-read · off'
    case 'normal-on':      return 'Auto-read · on'
    case 'normal-playing': return 'Stop playback'
    case 'live-mic-on':    return 'Mic is listening'
    case 'live-mic-muted': return 'Mic is muted'
    case 'live-playing':   return 'Interrupt'
    case 'live-paused':    return 'Voice paused'
  }
}

function statusFor(kind: VoiceUIState['kind'], autoRead: boolean): string {
  if (kind === 'normal-off' || kind === 'normal-on') return `Auto-read · ${autoRead ? 'on' : 'off'}`
  if (kind === 'normal-playing') return 'Playing'
  if (kind === 'live-mic-on') return 'Mic is listening'
  if (kind === 'live-mic-muted') return 'Mic is muted'
  if (kind === 'live-playing') return 'Interrupt'
  if (kind === 'live-paused') return 'Voice paused — click to resume'
  return ''
}
```

- [ ] **Step 3: Update `CockpitButton.tsx` if needed**

If `CockpitButton`'s `state` prop is typed and the new `'paused'` value isn't accepted, extend the union and add the visual (amber border, amber pulse, amber background):

```tsx
// in the className composition:
state === 'paused'
  ? 'border-amber-400/55 bg-amber-400/15 text-amber-400 animate-pulse shadow-[0_0_18px_rgba(251,191,36,0.35)]'
  : ...
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds.

- [ ] **Step 5: Run the affected tests**

Run: `cd frontend && pnpm vitest run src/features/chat/cockpit`
Expected: pass.

- [ ] **Step 6: Commit (covers Task 5 + Task 6)**

```bash
git add frontend/src/features/chat/cockpit/buttons/_voiceState.ts \
        frontend/src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts \
        frontend/src/features/chat/cockpit/buttons/VoiceButton.tsx \
        frontend/src/features/chat/cockpit/CockpitButton.tsx
git commit -m "Cockpit VoiceButton: amber paused indicator + click-to-resume

New 'live-paused' kind in deriveVoiceUIState takes precedence over
mic-on/muted. Click resumes via voiceLifecycleStore.setActive().
Visual: amber border + pulse + strikethrough mic; label 'Voice paused'."
```

---

### Task 7: Top-bar `ConversationModeButton` — paused branch

**Files:**
- Modify: `frontend/src/features/voice/components/ConversationModeButton.tsx`
- Modify: `frontend/src/features/voice/components/ConversationModeButton.test.tsx`

- [ ] **Step 1: Read the existing test**

Open `frontend/src/features/voice/components/ConversationModeButton.test.tsx` to follow the rendering pattern (which testing-library setup, prop shapes).

- [ ] **Step 2: Add tests for the paused branch**

Append to `ConversationModeButton.test.tsx`:

```ts
describe('paused lifecycle', () => {
  it('renders amber Paused pill when active && lifecycle=paused', () => {
    const { getByRole, queryByText } = render(
      <ConversationModeButton
        active={true}
        available={true}
        lifecycle="paused"
        onResume={() => {}}
        onToggle={() => {}}
      />,
    )
    const btn = getByRole('button')
    expect(btn).toHaveTextContent(/paused/i)
    expect(btn).not.toHaveTextContent(/^Live$/i)
  })

  it('calls onResume (not onToggle) when clicked while paused', () => {
    const onResume = vi.fn()
    const onToggle = vi.fn()
    const { getByRole } = render(
      <ConversationModeButton
        active={true}
        available={true}
        lifecycle="paused"
        onResume={onResume}
        onToggle={onToggle}
      />,
    )
    fireEvent.click(getByRole('button'))
    expect(onResume).toHaveBeenCalledOnce()
    expect(onToggle).not.toHaveBeenCalled()
  })

  it('renders Live pill when active && lifecycle=active (existing path unchanged)', () => {
    const { getByRole } = render(
      <ConversationModeButton
        active={true}
        available={true}
        lifecycle="active"
        onResume={() => {}}
        onToggle={() => {}}
      />,
    )
    expect(getByRole('button')).toHaveTextContent(/^Live$/i)
  })
})
```

- [ ] **Step 3: Run tests to verify failure**

Run: `cd frontend && pnpm vitest run src/features/voice/components/ConversationModeButton.test.tsx`
Expected: tests fail (props `lifecycle` / `onResume` not accepted).

- [ ] **Step 4: Update `ConversationModeButton.tsx`**

In `frontend/src/features/voice/components/ConversationModeButton.tsx`:

1. Add the import: `import type { VoiceLifecycle } from '@/features/voice-commands'`
2. Extend `ConversationModeButtonProps`:

```ts
interface ConversationModeButtonProps {
  active?: boolean
  available?: boolean
  phase?: ConversationPhase
  onToggle?: () => void
  /** Current voice-lifecycle state. When 'paused', click invokes `onResume`. */
  lifecycle?: VoiceLifecycle
  /** Invoked when the button is clicked while `lifecycle === 'paused'`. */
  onResume?: () => void
  persona?: PersonaVoiceShape | null
  onConfigure?: () => void
}
```

3. Insert the paused branch **before** the existing `if (active)` block, after the `if (!available)` and persona-not-configured branches:

```tsx
if (active && lifecycle === 'paused') {
  return (
    <button
      type="button"
      onClick={onResume}
      className={`${baseClass} border-amber-400/55 bg-amber-400/15 text-amber-400 animate-pulse shadow-[0_0_16px_rgba(251,191,36,0.35)]`}
      title='Voice paused — click to resume'
      aria-label="Resume voice"
      aria-pressed="true"
    >
      <ConvIcon muted />
      <span className="hidden sm:inline">Paused</span>
    </button>
  )
}
```

4. Update the existing `ConvIcon` to take an optional `muted` prop and render the strikethrough when set:

```tsx
function ConvIcon({ muted }: { muted?: boolean } = {}) {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="6" y="2" width="4" height="7" rx="2" />
      <path d="M3.5 7.5C3.5 10 5.5 11.5 8 11.5C10.5 11.5 12.5 10 12.5 7.5" />
      <line x1="8" y1="11.5" x2="8" y2="13.5" />
      <path d="M1.5 5.5C1.5 5.5 1 7 1 8C1 9 1.5 10.5 1.5 10.5" />
      <path d="M14.5 5.5C14.5 5.5 15 7 15 8C15 9 14.5 10.5 14.5 10.5" />
      {muted && <path d="M2 2 14 14" strokeWidth="1.4" />}
    </svg>
  )
}
```

`baseClass` already exists in the component; if it lives inside the `if (active)` branch only, lift it to function scope so the new branch can use the same definition. Otherwise duplicate the literal.

- [ ] **Step 5: Run tests**

Run: `cd frontend && pnpm vitest run src/features/voice/components/ConversationModeButton.test.tsx`
Expected: pass.

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm run build`
Expected: succeeds (call sites without `lifecycle` still build because the prop is optional).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice/components/ConversationModeButton.tsx \
        frontend/src/features/voice/components/ConversationModeButton.test.tsx
git commit -m "ConversationModeButton: amber Paused pill + click-to-resume

New props lifecycle + onResume. When active && paused, render amber
pulsing pill with strikethrough mic and label 'Paused'; click invokes
onResume instead of onToggle. Active path unchanged."
```

---

### Task 8: ChatView wiring — HoldToKeepTalking gate + top-bar lifecycle

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Add the lifecycle hook in `ChatView.tsx`**

Near the other `useXStore` calls in `ChatView`, add:

```ts
import { useVoiceLifecycleStore } from '@/features/voice-commands'

// inside the component:
const voiceLifecycle = useVoiceLifecycleStore((s) => s.state)
const setVoiceActive = useVoiceLifecycleStore((s) => s.setActive)
```

- [ ] **Step 2: Gate `HoldToKeepTalking`**

At the existing render block (lines ~1345–1352), extend the condition:

```tsx
{conversationActive
  && !conversationMicMuted
  && voiceLifecycle === 'active'                      // ← new gate
  && (conversationPhase === 'user-speaking' || conversationPhase === 'held') && (
  <HoldToKeepTalking
    isHolding={conversationIsHolding}
    onHoldStart={() => setConversationHolding(true)}
    onHoldEnd={() => setConversationHolding(false)}
  />
)}
```

- [ ] **Step 3: Wire the top-bar pill**

Locate the `ConversationModeButton` render in `ChatView` (or in the top-bar component it delegates to — find by `ConversationModeButton` reference). Pass the new props:

```tsx
<ConversationModeButton
  active={conversationActive}
  available={liveAvailability.available}
  phase={conversationPhase}
  lifecycle={voiceLifecycle}
  onToggle={...}
  onResume={setVoiceActive}
  persona={persona}
  onConfigure={...}
/>
```

If `ConversationModeButton` is rendered in a separate top-bar component, propagate `voiceLifecycle` and `setVoiceActive` through that component's props (or have it read the store directly — pick the simpler integration).

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm run build`
Expected: succeeds.

- [ ] **Step 5: Run all frontend tests**

Run: `cd frontend && pnpm vitest run`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
# add the top-bar component file too if it lives elsewhere and was modified
git commit -m "ChatView: wire voice lifecycle into Hold gate + top-bar pill

HoldToKeepTalking now requires voiceLifecycle === 'active'; top-bar
ConversationModeButton receives lifecycle + onResume so click while
paused resumes instead of exiting live mode."
```

---

### Task 9: Final build + manual verification

This task runs against a real device. Tasks 1–8 must be merged-into / cherry-picked-onto the working tree before this task starts.

- [ ] **Step 1: Final build**

Run: `cd frontend && pnpm run build`
Expected: clean build, no warnings beyond pre-existing.

- [ ] **Step 2: Final test run**

Run: `cd frontend && pnpm vitest run`
Expected: all pass.

- [ ] **Step 3: Start the dev server**

Run: `cd frontend && pnpm dev` (or whatever the project's dev command is — check `package.json`).

- [ ] **Step 4: Walk through spec §9.1 — Trigger word + synonyms**

Follow the spec table. For each of the 8 phrases, verify the correct toast string, cue (acoustic), and final lifecycle state. Record any failure with the exact spoken phrase, the actual toast, and the resulting state.

- [ ] **Step 5: Walk through spec §9.2 — Strict-reject**

Say `Voice nope`. Verify: persona does not respond as if to a chat message; browser console shows `[VoiceCommand] Rejected 2-token "voice <unknown>"`; the dispatcher source carries the `// TODO: add error toast and audible feedback with error sound` comment.

- [ ] **Step 6: Walk through spec §9.3 — voice as content word**

Say `Voice mode is great`. Verify: the persona answers it as a chat message; no reject log; lifecycle unchanged.

- [ ] **Step 7: Walk through spec §9.4 — Paused-mode Vosk path**

Enter paused mode, then test phrases 1–7 from §9.4 individually. For phrase 7 (any non-command sentence), confirm via Network tab that no audio leaves the browser.

- [ ] **Step 8: Walk through spec §9.5 — UI indicators**

In paused mode, visually confirm: cockpit button (amber, pulse, strikethrough mic), top-bar pill (amber, pulse, label `Paused`, strikethrough mic), HoldToKeepTalking not rendered.

- [ ] **Step 9: Walk through spec §9.6 — Click-to-resume**

Click each of the two buttons (cockpit + top-bar pill) while paused; both must resume.

- [ ] **Step 10: Walk through spec §9.7 — Lifecycle reset**

Pause → resume → exit live mode → re-enter live mode. Verify lifecycle starts as `active`.

- [ ] **Step 11: Walk through spec §9.8 — Trailing punctuation**

Observe during normal use; no specific action required beyond watching for `Voice off.` transcripts and confirming the dispatch log shows `body=off` (no period).

- [ ] **Step 12: Record the verification result**

If all steps pass, the redesign is ready for merge to master. If any step fails, file a fix task referencing the failing spec section and re-run the affected step.

---

## Self-review notes

- Spec coverage: each section of `2026-05-01-voice-commands-redesign-design.md` maps to one or more tasks (§4 → Task 1; §5.1–5.2 → Task 2; §5.3 → Task 3; §5.5 → existing normaliser, no task; §6 → Task 4; §7.1 → Tasks 5+6; §7.2 → Task 7; §7.3 → Task 8; §9 → Task 9).
- No placeholders remain. The two genuine "look it up at implementation time" notes (CockpitButton state discriminator in Task 6 Step 1, top-bar caller location in Task 8 Step 3) are intentional code-reading instructions, not blanks.
- Type consistency verified: `VoiceLifecycle = 'active' | 'paused'` is the same string across Tasks 1, 5, 7, 8. `setActive`/`setPause`/`reset` consistent across Tasks 1–8.

---

## Execution

After this plan is approved, dispatch via subagent-driven-development. Each subagent dispatch must:

1. Carry the explicit constraint: *do not merge, do not push, do not switch branches*.
2. Reference the specific Task by number.
3. Receive only the spec + this plan + the project CLAUDE.md as context (no broader codebase tour).
