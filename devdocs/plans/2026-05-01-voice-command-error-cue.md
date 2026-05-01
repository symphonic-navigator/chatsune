# Voice Command Error Cue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user an audible (low G3 doppelton) and visual (red toast) signal when continuous voice hears `voice <unknown>` (a 2-token mis-recognition that the dispatcher already filters), so misheard commands are not silently swallowed in either paused or running mode.

**Architecture:** Pure additive change in the existing voice-commands module. Extend `CueKind` with a third value `'error'`, add a flat-G3 sequence to the cue player, and replace the dispatcher's silent strict-reject branch with a full `respondToUser()` call that carries both the new cue and an `error`-level toast. No new modules, no new contracts, no Vosk/STT changes.

**Tech Stack:** TypeScript, React, Vite, Vitest, Web Audio API (existing AudioContext infrastructure in `cuePlayer.ts`).

---

## File Structure

| File | Role | Change |
|---|---|---|
| `frontend/src/features/voice-commands/types.ts` | Public type contracts | Widen `CueKind` union |
| `frontend/src/features/voice-commands/cuePlayer.ts` | Audio cue scheduler | Add G3 constant + `'error'` branch |
| `frontend/src/features/voice-commands/dispatcher.ts` | Command-text router | Replace silent reject with `respondToUser` call |
| `frontend/src/features/voice-commands/__tests__/cuePlayer.test.ts` | Cue player unit tests | One new `it()` block |
| `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts` | Dispatcher unit tests | Two new assertions in existing describe blocks |

No other files touched. No backend, no shared contracts, no event bus.

---

## Reference: spec

Full spec at `devdocs/specs/2026-05-01-voice-command-error-cue-design.md`. Read it before starting Task 1 — it explains the *why* behind the audio choice (flat G3 vs. interval) and the side effects of `level: 'error'` (red toast, 10 s auto-dismiss, mobile haptic).

---

## Task 1: Add `'error'` cue to the audio layer

Adds the new cue kind end-to-end: type widening, audio implementation, and unit test. Self-contained — no consumer change yet.

**Files:**
- Modify: `frontend/src/features/voice-commands/types.ts:10`
- Modify: `frontend/src/features/voice-commands/cuePlayer.ts:16,83-92`
- Modify: `frontend/src/features/voice-commands/__tests__/cuePlayer.test.ts` (append new `it()` block before final `})`)

- [ ] **Step 1: Write the failing test**

Append this block inside the `describe('cuePlayer', ...)` block in `frontend/src/features/voice-commands/__tests__/cuePlayer.test.ts`, immediately after the existing `it('resumes a suspended AudioContext defensively', ...)` block:

```ts
  it('playCue("error") schedules G3 twice (flat repeated low note)', async () => {
    const { playCue } = await import('../cuePlayer')
    playCue('error')

    expect(oscStartCalls).toHaveLength(2)
    expect(oscStartCalls[0].freq).toBeCloseTo(196.00, 1)
    expect(oscStartCalls[1].freq).toBeCloseTo(196.00, 1)
    expect(oscStartCalls[1].startAt).toBeGreaterThan(oscStartCalls[0].startAt)
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands/__tests__/cuePlayer.test.ts
```

Expected: the new test fails. Either with a TypeScript error (`Argument of type '"error"' is not assignable to parameter of type 'CueKind'`) at the `playCue('error')` call, **or** with a runtime assertion failure because the current `playCue` switch falls through and schedules nothing for `'error'`. Both outcomes are acceptable failures — they confirm the feature does not yet exist.

- [ ] **Step 3: Widen `CueKind`**

In `frontend/src/features/voice-commands/types.ts`, change line 10 from:

```ts
export type CueKind = 'on' | 'off'
```

to:

```ts
export type CueKind = 'on' | 'off' | 'error'
```

- [ ] **Step 4: Add G3 constant and `'error'` cue branch**

In `frontend/src/features/voice-commands/cuePlayer.ts`, change line 16 from:

```ts
const NOTES = { C4: 261.63, G4: 392.00 } as const
```

to:

```ts
const NOTES = { C4: 261.63, G3: 196.00, G4: 392.00 } as const
```

Then change the `playCue` function (lines 83-92) from:

```ts
export function playCue(kind: CueKind): void {
  switch (kind) {
    case 'on':
      // Ascending perfect fifth — Bluetooth-style "connect" pattern.
      return playSequence([[NOTES.C4, 130], [NOTES.G4, 80]])
    case 'off':
      // Descending perfect fifth — mirror of 'on', "disconnect" pattern.
      return playSequence([[NOTES.G4, 130], [NOTES.C4, 80]])
  }
}
```

to:

```ts
export function playCue(kind: CueKind): void {
  switch (kind) {
    case 'on':
      // Ascending perfect fifth — Bluetooth-style "connect" pattern.
      return playSequence([[NOTES.C4, 130], [NOTES.G4, 80]])
    case 'off':
      // Descending perfect fifth — mirror of 'on', "disconnect" pattern.
      return playSequence([[NOTES.G4, 130], [NOTES.C4, 80]])
    case 'error':
      // Flat repeated low G — no interval movement signals "input not recognised",
      // distinct from both ascending/descending fifth cues.
      return playSequence([[NOTES.G3, 130], [NOTES.G3, 80]])
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands/__tests__/cuePlayer.test.ts
```

Expected: all four tests pass (three existing + the new `'error'` test).

- [ ] **Step 6: Run the full voice-commands suite to catch regressions**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands
```

Expected: all tests pass. The dispatcher tests in particular still pass — `CueKind` widening is additive and does not break consumers.

- [ ] **Step 7: TypeScript build check**

Run from `frontend/`:
```bash
pnpm run build
```

Expected: build succeeds without TypeScript errors. (Per global instructions, `pnpm run build` is required because `tsc -b` catches stricter errors than `pnpm tsc --noEmit`.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/voice-commands/types.ts \
        frontend/src/features/voice-commands/cuePlayer.ts \
        frontend/src/features/voice-commands/__tests__/cuePlayer.test.ts
git commit -m "Add error cue: flat G3 doppelton

Extends CueKind union with 'error' and schedules a non-interval pair of
G3 notes — distinct from the ascending/descending fifth used by 'on' and
'off'. No consumer change yet; the dispatcher integration follows in the
next commit."
```

---

## Task 2: Dispatcher emits error response on misheard `voice <unknown>`

Wires the new cue + a red toast into the existing strict-reject branch. Adds two assertions: a positive (cue + toast emitted on `voice nope`) and a negative (no emission on 1-token or 3+ token fall-through).

**Files:**
- Modify: `frontend/src/features/voice-commands/dispatcher.ts:35-42`
- Modify: `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts` (append assertion to existing strict-reject test, add new negative test)

- [ ] **Step 1: Write the failing positive assertion**

In `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts`, find the existing test at line ~154:

```ts
    it('rejects "voice nope" without dispatching to LLM', async () => {
      const r = await tryDispatchCommand('voice nope')
      expect(r.dispatched).toBe(true)
      if (r.dispatched) expect(r.onTriggerWhilePlaying).toBe('resume')
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Rejected 2-token'),
        expect.anything(),
      )
    })
```

Add a new `it()` block immediately after it, still inside the `describe('strict-reject (2-token unknown sub)', ...)` block:

```ts
    it('emits an error response with cue:error on "voice <unknown>" 2-token', async () => {
      await tryDispatchCommand('voice nope')
      expect(respondMock).toHaveBeenCalledWith(
        expect.objectContaining({
          level: 'error',
          cue: 'error',
          displayText: expect.stringContaining("'nope'"),
        }),
      )
    })
```

- [ ] **Step 2: Write the failing negative assertion**

In the same file, find the `describe('fall-through (1 token or 3+ tokens, unknown sub)', ...)` block (line ~171). Append this new `it()` block at the end of that describe block, after the existing `'falls through for 4-token "voice mode is great"'` test:

```ts
    it('does NOT call respondToUser on 1-token or 3+ token fall-through', async () => {
      respondMock.mockReset()
      await tryDispatchCommand('voice')
      await tryDispatchCommand('voice that is great')
      await tryDispatchCommand('voice mode is great')
      expect(respondMock).not.toHaveBeenCalled()
    })
```

- [ ] **Step 3: Run tests to verify the positive one fails**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands/__tests__/dispatcher.test.ts
```

Expected: the new `'emits an error response with cue:error ...'` test FAILS — `respondToUser` is not yet called by the strict-reject branch. The new negative `'does NOT call respondToUser ...'` test should already PASS (current behaviour is silent on those paths). The existing tests must still pass.

- [ ] **Step 4: Wire the dispatcher to call `respondToUser`**

In `frontend/src/features/voice-commands/dispatcher.ts`, change lines 35-42 from:

```ts
  if (tokens[0] === 'voice' && (tokens.length < 2 || !isKnownVoiceSub(tokens[1]))) {
    if (tokens.length === 2) {
      console.warn('[VoiceCommand] Rejected 2-token "voice <unknown>":', tokens)
      // TODO: add error toast and audible feedback with error sound
      return { dispatched: true, onTriggerWhilePlaying: 'resume' }
    }
    return { dispatched: false }
  }
```

to:

```ts
  if (tokens[0] === 'voice' && (tokens.length < 2 || !isKnownVoiceSub(tokens[1]))) {
    if (tokens.length === 2) {
      console.warn('[VoiceCommand] Rejected 2-token "voice <unknown>":', tokens)
      respondToUser({
        level: 'error',
        cue: 'error',
        displayText: `Voice command not recognised: '${tokens[1]}'.`,
      })
      return { dispatched: true, onTriggerWhilePlaying: 'resume' }
    }
    return { dispatched: false }
  }
```

Note: `respondToUser` is already imported at the top of the file (line 4 — used by the handler-throw branch). No new import needed.

- [ ] **Step 5: Run tests to verify both new assertions pass**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands/__tests__/dispatcher.test.ts
```

Expected: all dispatcher tests pass. Both new tests green. The existing `'rejects "voice nope" without dispatching to LLM'` test must still pass — it does not assert on `respondMock` so the new emission does not break it.

- [ ] **Step 6: Run the full voice-commands suite**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands
```

Expected: all tests pass — cuePlayer tests from Task 1, dispatcher tests including the two new ones, plus all other voice-commands tests (matcher, normaliser, registry, vosk, handlers).

- [ ] **Step 7: TypeScript build check**

Run from `frontend/`:
```bash
pnpm run build
```

Expected: build succeeds without TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/voice-commands/dispatcher.ts \
        frontend/src/features/voice-commands/__tests__/dispatcher.test.ts
git commit -m "Voice dispatcher: emit error cue + toast on misheard voice <unknown>

Replaces the silent strict-reject branch with a respondToUser() call
carrying the new 'error' cue (flat G3 doppelton) and a red error toast
quoting the offending token. Covers both paused (Vosk) and running
(STT-upstream) modes since both funnel through tryDispatchCommand.

The 1-token and 3+ token fall-through paths remain silent — those are
ordinary speech and must continue to LLM dispatch."
```

---

## Task 3: Manual verification on real device

Build/test passing does not exercise the audio pipeline. This task is the human-loop verification step from the spec, before the work is considered done.

**Files:** none (manual session).

- [ ] **Step 1: Pre-flight green**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands
pnpm run build
```

Expected: both green. If anything fails, fix before proceeding.

- [ ] **Step 2: Boot the dev server**

Run from `frontend/`:
```bash
pnpm dev
```

Open the app on a real device (phone preferred so the haptic side effect is exercised) or in a browser tab.

- [ ] **Step 3: Continuous voice — running mode**

- Start continuous voice (say `voice on` or use the UI button).
- Say `voice on` again → expect: existing ascending-fifth cue + "Listening" toast.
- Say `voice hello` → **expected: low G3 doppelton + red "Voice command not recognised: 'hello'." toast.** Persona TTS, if running, must keep playing — the cue overlays without ducking.
- Say `voice hello liebe voice` (4 tokens) → no cue, no toast, falls through to normal LLM dispatch.
- Say `voice` alone → no cue, no toast, falls through.

- [ ] **Step 4: Continuous voice — paused mode**

- Say `voice off` → descending-fifth cue + "Paused" toast.
- Say `voice nope` → **expected: low G3 doppelton + red toast.** (Vosk path, separate from the STT-upstream path tested in Step 3.)
- Say something normal like `voice please come back` → no cue, no toast.

- [ ] **Step 5: Audio sanity**

- The G3 doppelton must clearly read as "lower than" the on/off cues.
- The two G3 notes must be discernibly two notes, not one long note — the 30 ms gap is the audible separator.
- Volume must match on/off cues (they share `CUE_OPTS.volume`).

- [ ] **Step 6: Mobile haptic check (if on phone)**

The error toast triggers `hapticError()` on mobile. A short vibration on `voice hello` is expected and acceptable per the spec.

- [ ] **Step 7: Sign-off**

If all of the above behave as expected, the feature is done. If any step misbehaves, file the symptom against the spec and the matching task — do not patch in place.

---

## Self-review notes

- **Spec coverage:** every spec section is mapped:
  - Cue audio (spec §1) → Task 1.
  - Type-schema extension (spec §2) → Task 1 step 3.
  - Dispatcher response (spec §3) → Task 2.
  - Side effects of `level: 'error'` (spec §4) → no code task — inherited from existing notification system; surfaced in Task 3 step 6 as a manual check.
  - Mode reach paused/running (spec §5) → Task 3 steps 3 and 4.
  - Tests (spec "Tests" section) → Task 1 step 1 and Task 2 steps 1-2.
  - Manual verification (spec section) → Task 3.
- **Out of scope (per spec):** dead-code cleanup in `handler/voice.ts:63-67` is **not** included. Confirmed: no task touches that file.
- **No placeholders:** every step has a concrete file path, a concrete code block, or a concrete command.
- **Type consistency:** `CueKind` is the only new type symbol introduced — used identically in `types.ts`, `cuePlayer.ts`, and the assertions in both test files.

---

## Constraints for the executing agent

- **Do not merge to master.** The user merges manually after verification.
- **Do not push to remote.** The user pushes manually.
- **Do not switch branches.** Stay on the current branch (master at time of plan).
- **Do not modify any file outside the five listed in the file-structure table.** If a step seems to require it, stop and report — do not improvise.
- **Do not add new dependencies.** No `pnpm add`. Everything used is already imported.
