# Voice Commands — Companion Lifecycle Design

**Date:** 2026-05-01
**Status:** Approved (pre-implementation)
**Predecessor:** `2026-04-30-voice-commands-foundation-design.md` (Foundation, the trigger / matcher / dispatcher / responseChannel skeleton)
**Supersedes brief:** `_brief-voice-commands-part2-system-voice.md` — the brief proposed a TTS system-voice with cache for command responses; brainstorming revealed the better fit is short audio cues plus a privacy-preserving local STT for the OFF state, so the brief's TTS/cache plan is dropped (see "Relationship to the brief" below).
**Affected modules:** new files under `frontend/src/features/voice-commands/`; small touches to `frontend/src/features/voice/hooks/useConversationMode.ts`; one optional field added to Foundation's `CommandResponse` type.

---

## 1. Goal

Ship the three companion-lifecycle voice commands and the infrastructure they need:

- `companion off` — pause the assistant entirely. Persona stops talking, external STT is shut down (no microphone audio leaves the browser), only a local Vosk recogniser listens for the wake phrase.
- `companion on` — resume normal continuous-voice operation.
- `companion status` — speak the current state (as a tone cue), without disturbing whatever the persona is doing.

These are the first three real commands using the Foundation pipeline. They also define the audio-cue vocabulary the rest of the command system will inherit.

## 2. Why these three commands together, and why now

The original plan put system-voice playback (Brief Part 2) before the companion commands (Brief Part 3). Brainstorming showed the dependency is the other way round: the *responses* the system-voice would have spoken for these commands turn out to be better expressed as short Bluetooth-style tone cues — no synthesis, no cache, no voice picker. And the *real* hard problem is the OFF state itself, which needs a privacy-preserving local STT that wasn't on Part 2's radar at all.

Combining all three into one spec is honest: the cue vocabulary, the local-STT path, and the lifecycle state machine only make sense together. Splitting them across two specs would create a mid-state where the OFF command exists but cannot recover without sending audio upstream.

## 3. Relationship to the brief (`_brief-voice-commands-part2-system-voice.md`)

| Brief proposal | This spec |
|---|---|
| TTS system-voice playback for command responses | **Dropped.** Replaced by short tone cues. Companion responses don't need speech — Bluetooth-style "blip-blip" cues are clearer, latency-free, locale-independent, and cost zero infra. |
| `(voiceId, spokenText)` cache | **Dropped together with TTS.** Cues are computed in <1 ms from frequency tables; nothing to cache. |
| System-voice picker in `VoiceTab.tsx` | **Dropped.** No voice to pick. |
| Dedicated audio channel | **Kept conceptually** — cues play through their own `AudioContext`, completely separate from the persona's playback infrastructure. Implementation is now ~50 lines of Web Audio instead of a routed TTS pipeline. |
| Toast fallback when no system voice configured | **Reformulated.** Toast is no longer a fallback — it runs in parallel with the cue. Cue is the hands-free signal, toast is the look-at-the-screen signal. Both are cheap, both convey complementary information. |
| Backend-side caching out of scope | **Still out of scope.** No caching at all in this design. |

If a future command genuinely needs spoken-language output (multi-language confirmations, dynamic content, etc.), system-voice TTS gets its own design session at that time, with the actual requirements in hand. We are not building it speculatively.

## 4. Non-goals

- Companion-lifecycle commands beyond the three named here (no `companion mute`, `companion volume`, `companion sleep N minutes`, etc.). Scope creep from a working baseline is exactly how the foundation got into trouble in earlier prototypes.
- Multi-word triggers in the matcher. The single-token matcher from Foundation handles companion via one trigger + body switch.
- Custom wake phrases configurable per user. The wake phrase is `companion on` (and `companion status`) — the same way Alexa's wake phrase is `alexa`.
- Error tone cues. YAGNI — we don't have an error-cue design that respects the "signature" two-tone pattern, and command failures already surface via toast.
- Voice settings in `VoiceTab.tsx`. Volume (0.30), VAD sensitivity (existing user preset), and confidence threshold (0.95) are hard-coded with comments pointing at this spec. We add settings if and when a user complains.
- Persistence of `companionLifecycleStore` across page reloads. OFF state has no meaning outside an active continuous-voice session — every fresh page load starts in ON.
- Companion-state UI indicator (a visible widget showing ON/OFF). Out of scope here; if it turns out to be needed during testing, it gets added separately.

---

## 5. Design Decisions (Resolved during Brainstorming)

| # | Decision | Rationale |
|---|---|---|
| 1 | TTS / cache / voice picker from the brief are all dropped; cues replace them. | The three concrete commands do not need speech. A signature audio vocabulary (two-tone, two-octave range, ascending = on / descending = off) is clearer hands-free than spoken confirmations. |
| 2 | Toast stays alongside the cue, both fire in parallel. | Cue is the hands-free signal, toast is the visual confirmation when the user happens to look. Cheap, complementary. |
| 3 | OFF-state STT runs locally via Vosk + constrained grammar. | Privacy: in the OFF state the user may be on the phone, talking to family, watching TV. No audio of any kind leaves the browser. Vosk's confidence-filtered constrained grammar keeps false positives manageable while needing zero network. |
| 4 | Vosk lifecycle: model + recogniser stay warm during continuous-voice mode; audio only fed when state is OFF. | Zero CPU during ON (no `acceptWaveform` calls), no cold-start penalty when transitioning OFF→ON repeatedly within one session. Recogniser reuse is mandatory per the VOSK-STT spike notes — fresh `KaldiRecognizer` per call would cost 2–3 s of grammar-graph recompilation each time. |
| 5 | Existing VAD (vad-web Silero in `audioCapture.ts`) is reused, no second VAD pipeline. | The VAD already produces 16 kHz Float32 PCM, exactly Vosk's expected input format. Adding a parallel VAD would double CPU for nothing. |
| 6 | OFF-state is a single boolean in a dedicated `companionLifecycleStore`, not a derived state from existing voice stores. | Lifecycle is conceptually separate from "is continuous voice active" — putting it in `conversationModeStore` would mix concerns. Default 'on'; reset on continuous-voice stop. |
| 7 | Idempotent commands: `companion on` while already ON / `companion off` while already OFF play their cue + show an info-level toast, do not change state. | Hands-free user experience principle: the system audibly acknowledges that it heard the command, even when the action is a no-op. "I heard you, you're already there." The toast level (info vs success) is the audit trail. |
| 8 | If the user issues `companion off` before the Vosk model is loaded, the OFF transition still happens immediately. External STT is shut down, persona is abandoned, cue plays — Vosk just isn't listening yet. The user simply waits a few seconds before the wake phrase works. | Privacy must not be compromised by load timing. The 2–3-second blackout once per session is acceptable. The alternative — leaving external STT alive while waiting for Vosk to load — would be a privacy leak. |
| 9 | Per-execution override of `onTriggerWhilePlaying` (Foundation Decision #7 extension). | `companion status` while persona speaks must not interrupt her; `companion off` must. Three sub-commands under one trigger means the static-only flag from Foundation no longer fits. Solution: keep static flag as **default**, add optional override on `CommandResponse`. Three lines in the dispatcher. |
| 10 | Vosk grammar contains `companion on` and `companion status`, plus phonetic distractors, but **not** `companion off`. | In the OFF state, hearing "companion off" again would be a no-op. Adding it to the grammar only gives the decoder more competing paths and increases false-positive risk on the accept set. |
| 11 | Vosk model is hosted in the frontend Docker image, fetched at build time via a setup script. | Geopolitical resilience — the Vosk project's CDN is operated by a small Russian organisation; we do not want a runtime dependency on it. Build-time download keeps the choice but makes a deploy-time failure obvious instead of a runtime one. |
| 12 | Cue audio uses its own `AudioContext`, separate from the audioCapture VAD context and the persona TTS pipeline. | Cues must overlay the persona without ducking, must not be subject to the persona's playback queue, must be lazy-initialised inside a user-gesture handler (cooperatively achieved because cues only fire after a user-initiated continuous-voice start). Separate context guarantees these properties without coordination. |
| 13 | Foundation Spec (`2026-04-30-voice-commands-foundation-design.md`) is left unchanged. The dispatcher patch is documented here. | Specs are an audit trail of how decisions were taken at the time, not living documents. The new spec extends Decision #7; it does not rewrite it. |

---

## 6. Architecture

### 6.1 Module layout

```
frontend/src/features/voice-commands/
  cuePlayer.ts                    (NEW)  Web Audio cue synthesis (~80 lines)
  vosk/                           (NEW)
    grammar.ts                           constrained-grammar JSON, distractor list
    modelLoader.ts                       40 MB model load, idempotent, singleton
    recogniser.ts                        public API: init, feed, dispose, getState
  companionLifecycleStore.ts      (NEW)  zustand store: 'on' | 'off' + setters + reset
  handlers/
    debug.ts                      (mod)  remove `spokenText`
    companion.ts                  (NEW)  one CommandSpec, switch on body for off/on/status
  responseChannel.ts              (mod)  add cue-playing branch
  types.ts                        (mod)  remove spokenText, add CueKind, add optional onTriggerWhilePlaying override
  dispatcher.ts                   (mod)  three lines: prefer response.onTriggerWhilePlaying when set
  index.ts                        (mod)  registerCoreBuiltins now also registers companionCommand
  __tests__/
    cuePlayer.test.ts             (NEW)
    companionLifecycleStore.test.ts (NEW)
    vosk/recogniser.test.ts       (NEW)
    vosk/grammar.test.ts          (NEW)
    handlers/companion.test.ts    (NEW)
    dispatcher.test.ts            (mod)  add override test
    responseChannel.test.ts       (NEW)

frontend/src/features/voice/hooks/useConversationMode.ts (mod)
  - transcribeAndSend: branch to vosk.feed when companion state is 'off'
  - startContinuous path: void vosk.init() (fire-and-forget)
  - stopContinuous path: vosk.dispose() + companionLifecycleStore.reset()

frontend/vendor/vosk-model/                                     (NEW, gitignored)
frontend/scripts/download-vosk-model.{sh,mjs}                   (NEW)
frontend/package.json                            (mod)  pnpm run vosk:download
frontend/Dockerfile                              (mod)  pnpm run vosk:download before pnpm build
frontend/vite.config.ts                          (mod)  vite-plugin-static-copy mirrors vendor/vosk-model
.gitignore                                       (mod)  frontend/vendor/vosk-model
README.md                                        (mod)  one-time dev-setup note
```

### 6.2 Data flow — ON state (unchanged from Foundation)

```
mic → vad-web (audioCapture) → onSpeechEnd(pcm)
                                       ↓
                         transcribeAndSend(audio)
                                       ↓
                          state === 'on' → external STT
                                       ↓
                          tryDispatchCommand(text)
                                       ├─ no match  → controller.commit(barge, text)
                                       └─ matched   → controller.resume / abandon
                                                       per dispatch result
```

### 6.3 Data flow — OFF state (NEW)

```
mic → vad-web (audioCapture) → onSpeechEnd(pcm)   (same VAD, same callback)
                                       ↓
                         transcribeAndSend(audio)
                                       ↓
                          state === 'off' → vosk.feed(pcm)
                                                ↓
                                  pcm.length / 16000 > 4 ?
                                       ├─ yes → drop (CPU guard)
                                       └─ no  → recogniser.acceptWaveform
                                                  ↓
                                          finalResult { text, words[].conf }
                                                  ↓
                                        text exact-match in accept set
                                        AND every conf >= 0.95 ?
                                                  ├─ no  → drop, console.debug rejection
                                                  └─ yes → tryDispatchCommand(text)
                                                              ↓
                                                       handler runs, response renders
                                                              ↓
                                                       (no controller call — nothing playing in OFF)
```

The OFF branch never calls `controller.commit / resume / abandon`. The controller has nothing to act on: persona is silenced, no Group is open. The Vosk path talks exclusively to the command dispatcher.

### 6.4 State machine

```
companionLifecycleStore.state: 'on' | 'off'    (default: 'on')

  ┌─────────────────────────────────────────────────────────────┐
  │   ON                                                        │
  │   - external STT routes to stt.transcribe                   │
  │   - vosk recogniser warm but not fed                        │
  │   - persona TTS pipeline operates normally                  │
  └─────────────────────────────────────────────────────────────┘
                │                                ▲
        companion off                            │
   (handler.execute → store.setOff)        companion on
   + dispatcher resolves                   (handler.execute → store.setOn)
   onTriggerWhilePlaying='abandon'         + dispatcher resolves
   → controller.abandonAll()               onTriggerWhilePlaying='abandon' (default;
                │                            no-op in OFF since nothing is playing)
                ▼                                │
  ┌─────────────────────────────────────────────────────────────┐
  │   OFF                                                       │
  │   - external STT receives no audio (transcribeAndSend       │
  │     short-circuits to vosk.feed)                            │
  │   - vosk recogniser is fed, listens for "companion on"      │
  │     and "companion status"                                  │
  │   - persona is silent (was abandoned on transition)         │
  └─────────────────────────────────────────────────────────────┘

Reset to ON happens automatically on continuous-voice stop.
```

`companion status` does **not** transition state in either direction. Idempotent calls (`on` while ON, `off` while OFF — the latter unreachable under normal flow because Vosk grammar excludes `companion off`) also do not transition; they emit an info-level cue + toast acknowledging the no-op.

---

## 7. Type contracts

### 7.1 Foundation patch — `voice-commands/types.ts`

```typescript
// REMOVE
//   spokenText: string

// ADD
export type CueKind = 'on' | 'off'

export interface CommandResponse {
  level: 'success' | 'info' | 'error'
  /** Tone cue to play through the dedicated cue audio channel. Optional —
   *  responses without a cue still surface as a toast. */
  cue?: CueKind
  /** Toast message. Always rendered, regardless of cue. */
  displayText: string
  /**
   * Per-execution override of CommandSpec.onTriggerWhilePlaying. When set,
   * takes precedence over the static default registered with the spec.
   *
   * Use case: a single trigger that branches behaviour by body content
   * (e.g. `companion off` must abandon the playing Group, but
   * `companion status` must not). The static default still required on
   * the spec — this only overrides per call.
   */
  onTriggerWhilePlaying?: 'abandon' | 'resume'
}
```

### 7.2 Foundation patch — `voice-commands/dispatcher.ts`

The success branch of `tryDispatchCommand`:

```typescript
respondToUser(response)
return {
  dispatched: true,
  onTriggerWhilePlaying: response.onTriggerWhilePlaying ?? handler.onTriggerWhilePlaying,
}
```

The catch branch (handler threw) is unchanged: `'resume'` is always forced regardless of any override the broken handler may have tried to emit. A buggy handler must not be able to abandon a playing Group.

### 7.3 New — `cuePlayer.ts` public API

```typescript
export type CueKind = 'on' | 'off'   // re-exported from types.ts for convenience
export function playCue(kind: CueKind): void
```

### 7.4 New — `companionLifecycleStore.ts`

```typescript
import { create } from 'zustand'

type CompanionLifecycle = 'on' | 'off'

interface CompanionLifecycleStore {
  state: CompanionLifecycle
  setOff: () => void
  setOn: () => void
  reset: () => void
}

export const useCompanionLifecycleStore = create<CompanionLifecycleStore>((set) => ({
  state: 'on',
  setOff: () => set({ state: 'off' }),
  setOn:  () => set({ state: 'on'  }),
  reset:  () => set({ state: 'on'  }),
}))
```

The store is intentionally inert: data only, no side effects. Side-effecting consumers (audio routing, Vosk feeding) read the current state at the right callsite. This keeps test fixtures simple — a fresh store per test, no need to mock side effects.

### 7.5 New — `vosk/recogniser.ts` public API

```typescript
type VoskState = 'idle' | 'loading' | 'ready' | 'error'

export const vosk: {
  init(): Promise<void>            // idempotent
  feed(pcm: Float32Array): void    // sync wrapper; recognition is internal
  dispose(): void                  // recogniser only; model singleton survives
  getState(): VoskState
}
```

`feed` is `void`-returning to its caller because match results route through `tryDispatchCommand` asynchronously, not via return value. Internal flow:

```typescript
function feed(pcm: Float32Array): void {
  if (state !== 'ready') return                         // Decision #8: drop, don't buffer
  if (pcm.length / 16_000 > 4) {                        // VOSK-STT.md MAX_SEGMENT_SECONDS
    console.debug('[Vosk] dropping segment > 4s')
    return
  }
  recogniser.acceptWaveform(pcm)
  const result = recogniser.finalResult()
  if (!ACCEPT_TEXTS.has(result.text)) {                 // exact match in {'companion on', 'companion status'}
    console.debug('[Vosk] rejected (text):', result.text)
    return
  }
  if (!result.result.every((w) => w.conf >= 0.95)) {    // VOSK-STT.md WAKE_CONF_THRESHOLD
    console.debug('[Vosk] rejected (conf):', result)
    return
  }
  void tryDispatchCommand(result.text)
}
```

---

## 8. Vosk module

### 8.1 Grammar

```typescript
// vosk/grammar.ts

export const VOSK_GRAMMAR: readonly string[] = [
  // Accept set
  'companion on',
  'companion status',

  // Phonetic distractors (standalone) — VOSK-STT.md pitfall #6
  'campaign', 'champion', 'company', 'compass', 'common', 'complete', 'complain',

  // Phonetic distractors with second word — VOSK-STT.md pitfall #7
  // Without these, the second word collapses onto the accept set when the
  // first word is misheard as 'companion'
  'campaign on',  'champion on',  'company on',  'compass on',  'common on',  'complete on',  'complain on',
  'campaign status', 'champion status', 'company status', 'compass status',
  'common status', 'complete status', 'complain status',

  // Garbage model — required to give Viterbi a "this isn't a wake phrase" path
  '[unk]',
]

export const ACCEPT_TEXTS: ReadonlySet<string> = new Set(['companion on', 'companion status'])
```

`companion off` is deliberately not in the grammar (Decision #10).

If false positives appear in production with words not on this list, **add them** to the standalone *and* second-word sections. Do not skip the second-word entries — pitfall #7 in the spike notes documents how that mistake plays out.

### 8.2 Recogniser lifecycle

| Event | Action |
|---|---|
| `vosk.init()` first call | Load model from `/vosk-model/...` into `Model` singleton (~3 s WASM JIT warmup once per page load). Construct `KaldiRecognizer(model, 16000, JSON.stringify(VOSK_GRAMMAR))`. State → `'ready'`. |
| `vosk.init()` subsequent calls | No-op when state ∈ {`'loading'`, `'ready'`}. Construct fresh recogniser when state is `'idle'` (after a previous dispose). Model singleton is reused. |
| `vosk.feed(pcm)` while state ∈ {`'idle'`, `'loading'`, `'error'`} | Drop silently. |
| `vosk.feed(pcm)` while state is `'ready'` | See §7.5 internal flow. |
| `vosk.dispose()` | `recogniser.remove()`, recogniser reference cleared. Model singleton **kept** (rebuilding the recogniser with grammar is cheap; reloading the model is not). State → `'idle'`. |

### 8.3 Model hosting and download

The model is the standard `vosk-model-small-en-us-0.15` (~40 MB, the only available small en-US model from the Vosk project at time of writing).

Build-time download workflow:

1. `frontend/vendor/vosk-model/` — gitignored (40 MB binary should not enter Git history).
2. `frontend/scripts/download-vosk-model.mjs` — Node script that:
   - checks if `frontend/vendor/vosk-model/am/final.mdl` already exists (idempotency probe);
   - if not, downloads `https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip`;
   - unzips into `frontend/vendor/vosk-model/`, flattening the top-level versioned folder so files live directly under that path.
3. `frontend/package.json` — `"vosk:download": "node scripts/download-vosk-model.mjs"` script entry.
4. `frontend/Dockerfile` — `RUN pnpm run vosk:download` after `pnpm install`, before `pnpm run build`.
5. `frontend/vite.config.ts` — `vite-plugin-static-copy` adds:
   ```ts
   targets: [
     { src: 'vendor/vosk-model/**/*', dest: 'vosk-model' },
     // existing entries unchanged
   ]
   ```
   so the model files end up at `/vosk-model/...` in the served output.
6. `modelLoader.ts` constructs `new Model('/vosk-model/')`.
7. `README.md` adds a one-line dev-setup note: "Run `pnpm run vosk:download` once after first checkout."

If `alphacephei.com` becomes unreachable (sanctions, outage, project disappears), running containers keep working — the model is already in the image. Future builds will fail; the fix is to host a mirror somewhere we control (Hetzner storage bucket, etc.) and update the URL in the script. We do not pre-emptively mirror; this is reactive.

---

## 9. Cue player

### 9.1 Module

```typescript
// cuePlayer.ts

const NOTES = { C4: 261.63, G4: 392.00 } as const

const CUE_OPTS = {
  waveform: 'square' as const,
  volume: 0.30,                           // STATE-CUE.md default
  filter: { startHz: 7000, endHz: 300, Q: 1 },  // exponential lowpass sweep
  envelopeMs: 12,                         // attack/release, capped at duration/4
  gapMs: 30,
} as const

let ctx: AudioContext | null = null

function audio(): AudioContext {
  if (!ctx) ctx = new AudioContext()
  // STATE-CUE.md: iOS/background-tab guard, idempotent and cheap
  if (ctx.state === 'suspended') void ctx.resume()
  return ctx
}

function scheduleBlip(startAt: number, freq: number, durationMs: number): void {
  const c = audio()
  const osc = c.createOscillator()
  const filter = c.createBiquadFilter()
  const gain = c.createGain()

  osc.type = CUE_OPTS.waveform
  osc.frequency.setValueAtTime(freq, startAt)

  filter.type = 'lowpass'
  filter.Q.setValueAtTime(CUE_OPTS.filter.Q, startAt)
  filter.frequency.setValueAtTime(CUE_OPTS.filter.startHz, startAt)
  filter.frequency.exponentialRampToValueAtTime(
    CUE_OPTS.filter.endHz,
    startAt + durationMs / 1000,
  )

  const env = Math.min(CUE_OPTS.envelopeMs, durationMs / 4) / 1000
  gain.gain.setValueAtTime(0, startAt)
  gain.gain.linearRampToValueAtTime(CUE_OPTS.volume, startAt + env)
  gain.gain.linearRampToValueAtTime(CUE_OPTS.volume, startAt + durationMs / 1000 - env)
  gain.gain.linearRampToValueAtTime(0, startAt + durationMs / 1000)

  osc.connect(filter).connect(gain).connect(c.destination)
  osc.start(startAt)
  osc.stop(startAt + durationMs / 1000 + 0.01)
}

function playSequence(notes: ReadonlyArray<readonly [number, number]>): void {
  const c = audio()
  let t = c.currentTime
  for (const [freq, durMs] of notes) {
    scheduleBlip(t, freq, durMs)
    t += durMs / 1000 + CUE_OPTS.gapMs / 1000
  }
}

export type CueKind = 'on' | 'off'

export function playCue(kind: CueKind): void {
  switch (kind) {
    case 'on':  return playSequence([[NOTES.C4, 130], [NOTES.G4, 80]])  // ascending fifth
    case 'off': return playSequence([[NOTES.G4, 130], [NOTES.C4, 80]])  // descending fifth
  }
}
```

Vocabulary discipline: every cue is at most two notes, drawn from a two-octave range, square-wave through a swept lowpass. New cues added later (errors etc.) must respect this signature so the system stays sonically coherent.

### 9.2 `responseChannel.ts` change

```typescript
import { useNotificationStore } from '../../core/store/notificationStore'
import { playCue } from './cuePlayer'
import type { CommandResponse } from './types'

export function respondToUser(response: CommandResponse): void {
  console.debug('[VoiceCommand] response:', response)
  if (response.cue) playCue(response.cue)
  useNotificationStore.getState().addNotification({
    level: response.level,
    title: 'Voice command',
    message: response.displayText,
  })
}
```

Cue and toast both fire unconditionally when the response includes them — no fallback logic, no priority. They are complementary, not alternatives.

---

## 10. Companion handler

```typescript
// handlers/companion.ts

import { useCompanionLifecycleStore } from '../companionLifecycleStore'
import type { CommandSpec, CommandResponse } from '../types'

export const companionCommand: CommandSpec = {
  trigger: 'companion',
  // Default: 'abandon' — `companion off` must stop the persona. Sub-commands
  // that should not abandon (`status`, idempotent `on`) override per-call.
  onTriggerWhilePlaying: 'abandon',
  source: 'core',
  execute: async (body): Promise<CommandResponse> => {
    const lifecycle = useCompanionLifecycleStore.getState()
    switch (body.trim()) {
      case 'off':
        if (lifecycle.state === 'off') {
          // Idempotent: acknowledge but don't re-trigger transition.
          // No override needed — in OFF the external STT path is dead, so
          // this branch is only reachable through Vosk (which doesn't carry
          // 'companion off' in its grammar), making it effectively unreachable
          // under normal flow. Defensive coverage is the only purpose.
          return {
            level: 'info',
            cue: 'off',
            displayText: 'Companion already off.',
          }
        }
        lifecycle.setOff()
        return {
          level: 'success',
          cue: 'off',
          displayText: 'Companion off.',
        }

      case 'on':
        if (lifecycle.state === 'on') {
          return {
            level: 'info',
            cue: 'on',
            displayText: 'Companion already on.',
            onTriggerWhilePlaying: 'resume',  // don't interrupt the persona for an idempotent ack
          }
        }
        lifecycle.setOn()
        return {
          level: 'success',
          cue: 'on',
          displayText: 'Companion on.',
        }
        // No override on the success branch: in OFF→ON the persona is already
        // silent (was abandoned on entering OFF), so 'abandon' is a no-op.

      case 'status':
        return {
          level: 'info',
          cue: lifecycle.state === 'off' ? 'off' : 'on',
          displayText: `Companion is ${lifecycle.state}.`,
          onTriggerWhilePlaying: 'resume',  // status must never interrupt the persona
        }

      default:
        return {
          level: 'error',
          displayText: `Unknown companion command: '${body}'.`,
          onTriggerWhilePlaying: 'resume',  // an error must not abandon the persona
        }
    }
  },
}
```

---

## 11. Bootstrap

`voice-commands/index.ts` — extend `registerCoreBuiltins` and its symmetric counterpart:

```typescript
import { companionCommand } from './handlers/companion'
import { debugCommand } from './handlers/debug'
import { registerCommand, unregisterCommand } from './registry'

export function registerCoreBuiltins(): void {
  registerCommand(debugCommand)
  registerCommand(companionCommand)
}

export function unregisterCoreBuiltins(): void {
  unregisterCommand(debugCommand.trigger)
  unregisterCommand(companionCommand.trigger)
}
```

The bootstrap callsite (already present from Foundation merge) does not change.

---

## 12. Audio routing in `useConversationMode.ts`

Three small changes, all in the existing hook.

### 12.1 Branch in `transcribeAndSend` (line ~279)

At the very top of `transcribeAndSend`, before any STT-in-flight tracking:

```typescript
const transcribeAndSend = useCallback(async (audio: CapturedAudio): Promise<void> => {
  // OFF-state branch — route audio to local Vosk recogniser instead of
  // upstream STT. Vosk handles match detection and dispatch internally.
  // No controller call: in OFF there's no Group to commit/resume/abandon.
  if (useCompanionLifecycleStore.getState().state === 'off') {
    vosk.feed(audio.pcm)
    return
  }

  // Existing path follows unchanged...
}, [/* existing deps */])
```

Direct store read (not a subscription hook) — `transcribeAndSend` is a callback invoked imperatively, atomic with the audio bundle it receives. A subscription would only trigger unwanted re-renders.

### 12.2 Vosk init at continuous-voice start (line ~546 area)

After the existing `audioCapture.startContinuous` call:

```typescript
audioCapture.startContinuous({ onSpeechEnd: handleSpeechEnd, /* existing options */ })
void vosk.init()  // fire-and-forget; first call loads model + builds recogniser
```

Fire-and-forget so the user does not wait 2–3 s of WASM warmup before continuous-voice is responsive. If the user issues `companion off` before Vosk is ready, the OFF transition still happens — Vosk just isn't listening yet (Decision #8).

### 12.3 Vosk dispose and lifecycle reset at continuous-voice stop (line ~493 area)

```typescript
try { audioCapture.stopContinuous() } catch { /* not active */ }
vosk.dispose()
useCompanionLifecycleStore.getState().reset()
```

Reset is essential: a continuous-voice session left in OFF would leave the store stuck there, and the next session would launch with no Vosk recogniser yet vosk-routed audio. Always boot fresh sessions in ON.

---

## 13. Foundation patch summary

Two files in Foundation need surgical edits:

| File | Change | Lines |
|---|---|---|
| `voice-commands/types.ts` | Remove `spokenText` from `CommandResponse`. Add `cue?: CueKind`, `onTriggerWhilePlaying?: 'abandon' \| 'resume'`. Export `CueKind`. | ~6 |
| `voice-commands/dispatcher.ts` | In the success branch, prefer `response.onTriggerWhilePlaying` when set; fall back to `handler.onTriggerWhilePlaying`. Catch branch unchanged. | ~3 |
| `voice-commands/handlers/debug.ts` | Remove `spokenText` from the response. | ~1 |

That's the entire Foundation impact. No dispatcher logic restructuring, no matcher changes, no registry changes.

---

## 14. Settings

**No settings changes.** All tuneable values are hard-coded with comments referencing this spec and the source notes (`VOSK-STT.md`, `STATE-CUE.md`):

- Cue volume: `0.30`
- Vosk per-word confidence floor: `0.95`
- Vosk max segment length: `4 s`
- VAD sensitivity: existing user preset, unchanged.

If users start asking, settings get added then. Building configurability speculatively for any of these values would mean shipping UI for problems that don't exist yet.

---

## 15. Testing

### 15.1 Unit tests

**`cuePlayer.test.ts`** (new)
- `vi.spyOn(globalThis, 'AudioContext')` to capture the constructor.
- `playCue('on')` → 2 oscillators created, frequencies are C4 then G4 in that order.
- `playCue('off')` → 2 oscillators, G4 then C4.
- Both cues use square wave, lowpass filter, gain envelope (verify by inspecting the spied `connect` calls).

**`companionLifecycleStore.test.ts`** (new)
- Default state is `'on'`.
- `setOff()` → `'off'`. `setOn()` → `'on'`. `reset()` → `'on'` from any prior state.
- Each test gets a fresh store via `useCompanionLifecycleStore.setState({ state: 'on' })` in `beforeEach`.

**`vosk/grammar.test.ts`** (new)
- Snapshot of `VOSK_GRAMMAR` so accidental edits surface in review.
- Asserts `'companion on'` and `'companion status'` are in `ACCEPT_TEXTS`.
- Asserts `'companion off'` is **not** in the grammar at all.
- All standalone distractors also appear in their `<word> on` and `<word> status` two-word forms.

**`vosk/recogniser.test.ts`** (new)
- Mock the vosk-browser `Model` and `KaldiRecognizer` classes.
- `feed` with `pcm.length / 16000 > 4` → no `acceptWaveform` call.
- `feed` while state is `'loading'` → no `acceptWaveform` call.
- `feed` with mocked `finalResult` returning `text='companion on'`, all confs ≥ 0.95 → `tryDispatchCommand` called with `'companion on'`.
- Same with one conf at 0.94 → `tryDispatchCommand` not called.
- Same with `text='campaign on'` (in distractors but not accept set) → `tryDispatchCommand` not called.
- `dispose()` → recogniser disposed, model singleton retained, state `'idle'`.

**`handlers/companion.test.ts`** (new)
- `body='off'` while ON → calls `setOff`, response has `cue='off'`, `level='success'`, no `onTriggerWhilePlaying` override (uses static `'abandon'`).
- `body='off'` while already OFF → does **not** call `setOff` again, response has `level='info'`, `cue='off'`.
- `body='on'` while OFF → calls `setOn`, `cue='on'`, `level='success'`.
- `body='on'` while already ON → response has `level='info'`, `cue='on'`, override `onTriggerWhilePlaying='resume'`.
- `body='status'` while ON → `cue='on'`, override `'resume'`.
- `body='status'` while OFF → `cue='off'`, override `'resume'`.
- `body='nonsense'` → `level='error'`, no cue, override `'resume'`.

**`dispatcher.test.ts`** (extend)
- Existing tests untouched.
- Add: handler returns response with `onTriggerWhilePlaying: 'resume'` while spec has `'abandon'` → DispatchResult carries `'resume'`.
- Add: handler returns response without `onTriggerWhilePlaying` → DispatchResult carries the spec's static value.
- Add: handler throws → catch branch forces `'resume'` regardless.

**`responseChannel.test.ts`** (new)
- Mock `playCue` and the notification store.
- Response with `cue: 'on'` → `playCue('on')` called once, toast emitted once.
- Response without `cue` → `playCue` not called, toast emitted once.

### 15.2 Integration tests

Extend `useConversationMode` tests (or new file `useConversationMode.companionLifecycle.test.tsx`):
- With companion state `'off'`, audio captured by VAD goes to `vosk.feed` — `stt.transcribe` is **not** called.
- With companion state `'on'`, audio goes to `stt.transcribe` — `vosk.feed` is **not** called.
- Continuous-voice stop in OFF state resets the store back to ON.

### 15.3 Manual verification

Continuous voice on, persona busy with a long answer (e.g. asked it to summarise something):

1. **OFF→ON cycle.** Mid-sentence: say `"companion off"`. Persona stops, cue-off (G4→C4) plays, toast "Companion off." Console shows `[VoiceCommand] response: { level: 'success', cue: 'off', ... }`.
2. **Wake from OFF.** In OFF for ~3 s, then say `"companion on"`. Cue-on (C4→G4) plays, toast "Companion on." Then say something normal — STT works, persona answers.
3. **Status while persona speaks.** Persona speaking, say `"companion status"`. Cue-on plays *over* the persona, persona keeps talking, toast "Companion is on."
4. **Status in OFF state.** In OFF, say `"companion status"`. Cue-off plays (heard via Vosk). Toast "Companion is off." State remains OFF.
5. **Idempotent on while ON.** Persona speaking, say `"companion on"`. Cue-on parallel, persona does **not** stop, info-toast "Companion already on."
6. **Distractor sanity.** In OFF, say `"campaign on"`, `"champion on"`, `"company on"` — clearly enunciated. Each must produce **no** cue, **no** toast, **no** state change. Console shows `[Vosk] rejected (text): ...` lines. If any false-positive triggers, the distractor list in `grammar.ts` needs more entries — code is fine.
7. **>4 s pre-filter.** In OFF, talk for 5–6 seconds (count, recite). Console: `[Vosk] dropping segment > 4s`. CPU stays calm.
8. **Model-load race.** Hard-refresh (clear browser cache for the Vosk model) → start continuous voice → **immediately** say `"companion off"`. Persona stops, cue plays. Immediately say `"companion on"` — likely swallowed (model still loading). Wait 3 s, say it again — works. Console shows `[Vosk] model loading…`, then `[Vosk] model ready`.
9. **Stop in OFF, restart.** In OFF, stop continuous voice. Console shows Vosk dispose. Restart continuous voice — back in ON, STT works immediately. Say `"companion off"` — works.
10. **Audio overlap sanity.** Persona speaking loudly, say `"companion status"`. Cue-on must be audible **simultaneously** with the persona without either dropping or distorting.
11. **iOS Safari (if testing on iPhone).** First `playCue` after entering continuous voice must not be silent. If it is, the `audio()` helper's `ctx.resume()` defensive call is the fix per `STATE-CUE.md`.

---

## 16. Out of scope and follow-ups

### Out of this spec
- A visible UI indicator showing companion ON/OFF (status pill, mic icon variant, etc.). Likely useful, but the cue + toast already cover the immediate feedback need; let real testing decide if a persistent indicator is needed.
- System-voice TTS playback for command responses generally. If a future command needs spoken output, design it then.
- Wake-phrase configurability. Add when a user explicitly asks.
- Companion volume slider. Add when 0.30 turns out to be wrong for someone.
- Multi-language Vosk grammar. Current grammar is en-US. German wake phrases would need a different model (vosk-model-small-de) and a different grammar. Out of scope; chatsune testers are en-US-comfortable for now.

### Pre-existing code touched
- `voice-commands/types.ts`, `dispatcher.ts`, `handlers/debug.ts`, `responseChannel.ts`, `index.ts` — small surgical edits per §13.
- `voice/hooks/useConversationMode.ts` — three additions per §12.

Nothing else changes. Existing inline-trigger plumbing, response-task-group, barge controller, audio-capture VAD, all remain untouched.
