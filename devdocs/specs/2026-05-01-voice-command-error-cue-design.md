# Voice Command Error Cue — Design

**Date:** 2026-05-01
**Status:** Approved, ready for implementation plan
**Scope:** Frontend only (`frontend/src/features/voice-commands/`)

---

## Problem

When the user says something that begins with "voice" but is not a recognised
voice-command sub-action, the system currently swallows the input silently:

- **Dispatcher** (`dispatcher.ts:35-42`) detects the `voice <unknown>` 2-token
  case, logs a `console.warn`, and returns `{dispatched:true}` to suppress
  LLM dispatch. No toast. No tone. The user has no way to tell whether the
  input was even heard.
- The TODO `add error toast and audible feedback with error sound` already
  marks this gap.

Result: in continuous-voice mode, a misheard "voice on" (e.g. "force on",
"voice hello") looks identical to nothing happening, and the user repeats
themselves blindly.

The same gap exists in both lifecycle modes:

- **paused** — Vosk local recogniser dispatch path
- **running** — STT-upstream dispatch path

Both modes funnel through `tryDispatchCommand()`, so a single dispatcher-level
change covers both.

---

## Goal

Give the user a clear, hands-free signal that the input was heard but not
matched, **only** when the input was structurally a voice command but had
an unknown sub-action. Inputs that are plainly normal speech (`voice` alone,
or `voice` followed by 3+ tokens) must continue to fall through to the LLM.

Concretely:

| Input | Tokens | Behaviour |
|---|---|---|
| `voice on` | 2, known | Existing success cue |
| `voice off` | 2, known | Existing success cue |
| `voice hello` | 2, unknown | **NEW: error cue + error toast** |
| `voice` | 1 | Fall-through (no signal) |
| `voice hello liebe voice` | 4, unknown | Fall-through (no signal) |
| `voice off please now` | 4, known | Existing success cue |

The triggering rule is the existing strict-reject rule in the dispatcher
(`tokens[0] === 'voice' && tokens.length === 2 && !isKnownVoiceSub(tokens[1])`).
This spec does not change the rule — only the response.

---

## Non-Goals

- No changes to Vosk grammar or STT adapters.
- No new sub-action recognised by the voice command.
- No cleanup of the now-dead `handler/voice.ts:63-67` "Unknown voice command:"
  fallback path. The dispatcher's strict-reject means that path is
  unreachable from production code, but removing it is scope-creep — track
  separately.
- No retry/repeat affordance. Toast disappears on its own timer; user
  re-speaks if they want.

---

## Design

### 1. Cue audio: new `'error'` kind

A flat, repeated low note. Selected after evaluation of A/B/C/D variants
during brainstorming:

- **Pitch:** G3 (196.00 Hz) — exactly one octave below the existing G4 used
  in `'on'`/`'off'`.
- **Pattern:** two identical G3 notes, **no interval movement**. The flatness
  is deliberate — both existing cues are intervals (ascending fifth for
  `'on'`, descending fifth for `'off'`), so a non-interval cue cannot be
  confused with either.
- **Rhythm:** identical to success — 130 ms + 30 ms gap + 80 ms. Reuses the
  module's existing rhythmic vocabulary.
- **Filter / envelope / gain:** unchanged from the existing `CUE_OPTS`. The
  exponential lowpass sweep down to 300 Hz already darkens any tail; on G3
  it darkens further still, reinforcing the "error" semantics without
  introducing a new audio vocabulary.
- **AudioContext:** unchanged — same dedicated cue context, no ducking of
  persona TTS.

### 2. Type-schema extension

```ts
// types.ts
export type CueKind = 'on' | 'off' | 'error'
```

Additive only. No existing handler is invalidated. No call sites outside
this module use `CueKind` (verified via grep on `responseChannel.ts`,
`cuePlayer.ts`, `index.ts`, and `__tests__/`).

### 3. Dispatcher response

`dispatcher.ts:35-42` is rewritten from a bare `warn + return` to a full
response emission:

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

Notes:

- `onTriggerWhilePlaying: 'resume'` — a misheard input must never cancel a
  running persona reply. Same rationale as the existing `level: 'error'`
  path in the handler-throw branch (`dispatcher.ts:51-58`).
- Toast text quotes the offending token so the user can diagnose
  mishearings ("force" vs "voice"). Final period matches existing voice
  command toasts.
- The `console.warn` line is preserved unchanged — it is part of the
  diagnostic story (cf. the `dispatch entry:` info line at `dispatcher.ts:29`).

### 4. Side effects of `level: 'error'`

Inherited from the existing notification system, not new behaviour, but
worth surfacing because they are now triggered by misheard voice input:

- **Colour:** red (`rgb(248,113,113)`, red-400) with `✗` icon — see
  `app/components/toast/Toast.tsx:5-19`.
- **Duration:** 10 000 ms auto-dismiss (longer than success/info to give
  the user time to read the offending token) —
  `Toast.tsx:19-23`.
- **Haptics:** `hapticError()` fires on mobile — `notificationStore.ts:35-37`.
  This was added so the user feels failures even with the screen off.
  It is now reachable via voice mishearing too. Acceptable: a misheard
  command **is** an error from the user's perspective, and a single short
  vibration is consistent with the audible cue.

If the haptic is undesirable for this specific case, we would need to add
an opt-out flag to `addNotification()` — out of scope for this spec.

### 5. Mode reach (paused / running)

No mode-specific code touched. Both Vosk and STT-upstream funnel through
`tryDispatchCommand()` (verified in the dispatcher's own comment at
`dispatcher.ts:26-28`). The single-point change therefore covers both.

---

## Tests

### `cuePlayer.test.ts` — new case

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

### `dispatcher.test.ts` — extend strict-reject suite

Two assertions added to the existing `strict-reject (2-token unknown sub)`
describe block:

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

And a regression-protection negative in the `fall-through` block:

```ts
it('does NOT emit a response on 1-token or 3+ token fall-through', async () => {
  respondMock.mockReset()
  await tryDispatchCommand('voice')
  await tryDispatchCommand('voice that is great')
  expect(respondMock).not.toHaveBeenCalled()
})
```

The existing tests in both blocks remain unchanged and still pass.

---

## Manual verification

These steps must be run on a real device after merge — TypeScript build and
unit tests do not exercise the audio pipeline.

1. **Pre-flight:** `pnpm run build` clean. `pnpm vitest run` green for the
   `voice-commands` suite.
2. **Continuous voice — running mode:**
   - Start continuous voice (`voice on` or UI button).
   - Say `voice on` → existing ascending-fifth cue + "Listening" toast.
   - Say `voice hello` → **expected: low G3 doppelton + red "Voice command
     not recognised: 'hello'" toast.** Persona TTS, if running, must keep
     playing.
   - Say `voice hello liebe voice` → no cue, no toast, falls through to
     normal LLM dispatch.
   - Say `voice` alone → no cue, no toast, falls through.
3. **Continuous voice — paused mode:**
   - Say `voice off` → descending-fifth cue + "Paused" toast.
   - Say `voice nope` → **expected: low G3 doppelton + red toast.**
   - Say something normal like `voice please come back` → no cue, no toast.
4. **Audio sanity:**
   - The G3 doppelton must clearly read as "lower than" the on/off cues.
   - The two G3 notes must be discernibly two notes, not one long note —
     the 30 ms gap is the audible separator.
   - Volume must match on/off cues (same `CUE_OPTS.volume`).

---

## Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| G3 too low to hear over persona TTS on small phone speakers | Medium | Identical envelope/gain as on/off cues, which are field-tested. Manual verification step covers this. |
| `CueKind` widening breaks an external consumer | Low | Grep confirms no external uses. Additive change. |
| Toast spam if STT goes haywire | Low | Toast auto-dismisses; the underlying problem would already be visible via the existing `dispatch entry:` info logs. |
| User mistakes the cue for something else (notification, error elsewhere) | Low | Doppelton on G3 is distinct from any other tone in the app. |

---

## Files touched

- `frontend/src/features/voice-commands/types.ts` — extend `CueKind`.
- `frontend/src/features/voice-commands/cuePlayer.ts` — add `G3` constant
  and `'error'` branch.
- `frontend/src/features/voice-commands/dispatcher.ts` — replace
  warn-only branch with `respondToUser` call.
- `frontend/src/features/voice-commands/__tests__/cuePlayer.test.ts` —
  one new test.
- `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts` —
  two new assertions.

No backend, no shared contracts, no event bus, no Vosk grammar, no STT
adapter touched.
