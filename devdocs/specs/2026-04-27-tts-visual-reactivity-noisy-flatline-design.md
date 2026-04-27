# TTS Visual Reactivity Extension — Noisy Flatline

**Date:** 2026-04-27
**Status:** Draft, awaiting Chris's review
**Scope:** Frontend only. Extends the existing `VoiceVisualiser` with a second
data source (synthetic noise) and a new gating predicate. Also bundles one
purely cosmetic tweak: the bar field is clamped to 90% of the viewport
width, centred. No new UI controls, no new settings fields, no backend or
DTO changes.

Builds on `devdocs/specs/2026-04-26-tts-voice-visualiser-design.md`.

---

## 1. Problem

The TTS Voice Visualiser ships in two visible states only: full spectrum bars
when audio plays, and completely invisible otherwise. This is sharp and clean
during continuous speech, but it leaves perceptual holes in two situations:

1. **Pre-audio waiting** — between user input and the first TTS chunk, the
   user has no ambient cue that the assistant is preparing to speak. In live
   mode, the LiveButton's mic pulse already conveys "I'm listening to you",
   but once the user stops speaking and the assistant's pipeline takes over
   there is silence on the screen until audio starts.
2. **Inter-chunk gaps** — between sentences, between buffered TTS chunks, or
   when synthesis stalls briefly, the bars cut to completely invisible. The
   abrupt disappearance reads as "something broke" rather than "natural
   pause".

The fix is one unified concept: when TTS is *expected*, show a quiet,
breathing baseline of bars instead of nothing. When real audio plays, the
bars dance to the FFT data as today. The transition between the two is
smoothed implicitly by the existing exponential per-bar smoother.

---

## 2. Goals and non-goals

### Goals

- Add a third visible state to the `VoiceVisualiser`: a low-amplitude,
  Perlin-style "noisy flatline" that breathes across the bars whenever TTS
  is expected but no audio is currently playing.
- Cover all three TTS-producing modes uniformly: continuous voice ("live"),
  manual read-aloud, and auto-read-aloud.
- Make the transition between noise and real-FFT seamless via the existing
  per-bar exponential smoother — no explicit cross-fade.
- Keep the existing render pipeline, style system, persona colour, opacity,
  bar count, master toggle, reduced-motion handling, and pause behaviour
  fully intact.

### Non-goals

- **No ECG / heartbeat overlay.** An earlier brainstorm direction (a
  separate ECG visual fading into the spectrum) was simplified away during
  design: the noisy flatline already conveys "system is alive, audio
  pending" without a second visual primitive.
- **No new UI controls** in the Voice settings tab. The existing master
  toggle plus `style` / `opacity` / `barCount` cover the noise state too.
- **No transcribing-state visualisation.** While the user's microphone is
  being processed by STT, no visualisation is added here. That belongs to a
  separate, future component.
- **No pause behaviour during noise.** Tap-to-pause is an audio-playback
  control; with no audio, there is nothing to pause. The HitStrip remains
  mounted but a tap during the noise state is a no-op.
- **No backend or DTO changes.** Pure frontend work.

---

## 3. Architecture overview

The existing `VoiceVisualiser` component owns one `requestAnimationFrame`
loop that, each frame, picks a *target* per-bar value and lets the existing
smoother (`value += (target - value) * 0.28`) interpolate towards it. Today
that target is either the FFT bins or nothing (loop pauses). The change
extends the target selection by one branch:

```
                          ┌─ playing? ──────────► FFT bins      (existing)
isTtsExpected ───────────►│
                          └─ otherwise ─────────► noise bins    (NEW)
not expected ────────────────────────────────────► fade out     (existing)
```

The noise branch is generated synthetically each frame from a tiny pure
function. The fade-out branch is unchanged: `activeRef` fades to 0, the
RAF loop terminates, and a new playback or expectation event resumes it.

### New files

- `frontend/src/features/voice/infrastructure/visualiserNoise.ts` — pure
  noise-bin generator.
- `frontend/src/features/voice/infrastructure/useTtsExpected.ts` — small
  hook composing the four reactive sources into the gating predicate.

### Modified files

- `frontend/src/features/voice/components/VoiceVisualiser.tsx` — extend
  the RAF loop with the new branch.
- `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` —
  one-line change in `barLayout()` for the 90% width clamp (see §6a).

That's it. No other files need touching.

---

## 4. Gating predicate — `useTtsExpected`

A new hook in `frontend/src/features/voice/infrastructure/useTtsExpected.ts`:

```ts
export function useTtsExpected(): () => boolean
```

Returns a stable accessor function (not a state value) so the component can
read it inside its RAF loop without forcing per-frame React renders. The
accessor reads its sources via refs/store getters at call time:

```ts
function isTtsExpected(): boolean {
  if (audioPlayback.isActive()) return true                    // (a)
  if (isReadingAloud()) return true                            // (b)
  if (getActiveGroup() !== null) {                             // (c)
    if (conversationModeActive()) return true                  //   live
    if (currentPersonaAutoReadEnabled()) return true           //   auto-read
  }
  return false
}
```

| Branch | Source | Covers |
|---|---|---|
| (a) `audioPlayback.isActive()` | `audioPlayback` singleton | Any time real audio is playing — strongest signal, never a false negative. |
| (b) `isReadingAloud()` | exported from `ReadAloudButton.tsx` (already exists) | Manual read-aloud and auto-read once the read-aloud pipeline has taken over (synthesising or playing). |
| (c) `getActiveGroup()` + mode/persona check | `responseTaskGroup` registry + `conversationModeStore` + active-persona store | The early window: live mode is on, OR auto-read is enabled for the active persona, AND the LLM has begun producing a response that will end in TTS. This is the only branch that would otherwise be missed by (a) and (b). |

For (c), the live-mode check uses `useConversationModeStore.getState().active`.
The auto-read-per-persona check reads `persona.voice_config.auto_read` for
the currently active persona. Both are existing fields — no new state.

Hook implementation reuses the same pub-sub seam as `usePhase`:
`subscribeActiveGroup(...)` + zustand selector + a singletons-as-functions
pattern. The hook returns a *getter* rather than a value because the
`VoiceVisualiser` reads it inside RAF, not inside JSX. This avoids
re-running the RAF effect on every state change of any of the four
sources, and it avoids unnecessary re-renders.

---

## 5. Noise generator

New file `frontend/src/features/voice/infrastructure/visualiserNoise.ts`:

```ts
const BASELINE = 0.035                  // ~1% viewport at maxHeightFraction=0.28
const NOISE_AMP = 0.14                  // brings peak to ~5% viewport
const PHASE_STEP = 0.15                 // bar-to-bar phase offset
const PERIOD_S = 2.0                    // breathing period

export function fillNoiseBins(
  out: Float32Array,
  tSeconds: number,
): void {
  const omega = (2 * Math.PI) / PERIOD_S
  for (let i = 0; i < out.length; i++) {
    const wave = 0.5 + 0.5 * Math.sin(omega * tSeconds + i * PHASE_STEP)
    out[i] = BASELINE + NOISE_AMP * wave
  }
}
```

Why a single sine instead of true Perlin/value noise:

- The bars are already exponentially smoothed at 0.28 per frame. Any
  high-frequency noise component is smoothed out anyway.
- Visually, a phase-shifted sine reads as "wave wandering through the
  bars" — exactly the design goal. With 24–96 bars and `PHASE_STEP = 0.15`,
  we see ~3.6 wavelengths across a wide bar count, i.e. multiple sweeping
  crests at once. Perceptually indistinguishable from gentle Perlin in
  this regime.
- Pure function, no allocations after the initial `Float32Array`,
  cheaper than a hashed value-noise lookup.

Output values are in the same `[0, 1]`-normalised space as
`useTtsFrequencyData`'s smoothed bins. They are not double-smoothed: the
caller writes `out[i]` directly into the smoother's `target` slot, and the
existing smoother does the per-frame interpolation as it does for FFT
bins. This gives a continuous, slightly lazy response — exactly the
"breathing" feel.

---

## 6. Renderer integration

The change to `VoiceVisualiser.tsx` is local to the `tick()` function
inside the main `useEffect`. Today (simplified):

```ts
const playing = accessors.isActive()
const target = playing ? 1 : 0
activeRef.current += (target - activeRef.current) * FADE_RATE

if (activeRef.current > 0.005) {
  const bins = accessors.getBins()
  if (bins) drawVisualiserFrame(...)
  rafRef.current = requestAnimationFrame(tick)
} else if (playing) {
  rafRef.current = requestAnimationFrame(tick)
} else {
  rafRef.current = null
}
```

After:

```ts
const playing  = audioPlayback.isActive()
const expected = ttsExpectedRef.current()        // from useTtsExpected
const visible  = playing || expected
const target   = visible ? 1 : 0
activeRef.current += (target - activeRef.current) * FADE_RATE

if (activeRef.current > 0.005) {
  let bins: Float32Array | null = null
  if (playing) {
    bins = accessors.getBins()                   // FFT
  } else if (expected) {
    fillNoiseBins(noiseBufferRef.current, performance.now() / 1000)
    bins = noiseBufferRef.current
  }
  if (bins) drawVisualiserFrame(...)
  rafRef.current = requestAnimationFrame(tick)
} else if (visible) {
  rafRef.current = requestAnimationFrame(tick)
} else {
  rafRef.current = null
}
```

The smoothing handover from noise to FFT and back is handled invisibly:
both sources write into the same exponentially-smoothed target, and the
smoother's 0.28 coefficient bridges the discontinuity in 4–5 frames
(~70 ms), which reads as a soft handover rather than a hard switch.

The component's existing additional concerns each map cleanly:

- **Pause snapshot freeze.** The existing `paused` branch freezes the
  current bins and breathes opacity. This is preserved unchanged. Pause
  during the noise state is intentionally inactive (no audio to pause), so
  in practice the `paused` branch will only be entered when bins are FFT-
  derived. This is consistent with the current behaviour and needs no
  special handling for the noise state — but a defensive `if (!playing)`
  guard around setting `paused=true` already lives in the pause flow
  upstream of the visualiser.
- **Reduced-motion short-circuit.** The existing
  `reducedMotionRef.current` check sits *before* both the playing and the
  expected branches, so noise is suppressed for reduced-motion users for
  free.
- **Persona colour, style, opacity, bar count.** Read identically for
  both bin sources; no branching required.
- **RAF resume on play.** The existing `audioPlayback.subscribe()`
  callback already restarts the loop on the next play event. We
  additionally subscribe to the active-group registry and to
  `conversationModeStore` from the `useTtsExpected` accessor's underlying
  pub-sub so that *expectation* changes (e.g. user submits a message in
  live mode) also restart the loop without waiting for audio. The
  cleanest place for this restart hook is inside `useTtsExpected` itself:
  the hook accepts an optional `onExpectedChange` callback that fires
  when the predicate transitions false→true. The visualiser passes a
  RAF-restart function.

The new ref allocations are small and stable for the component's
lifetime: one `Float32Array(barCount)` for the noise output buffer, and
one accessor function from `useTtsExpected`. The noise buffer is
re-allocated together with the existing smoothed-bin buffer when
`barCount` changes.

---

## 6a. Bundled cosmetic tweak — 90% width clamp

The bar field currently spans the full viewport width. Edges of the chat
column or modal hit the outermost bars too snugly, especially at low
`barCount` where each bar slot is wide. The fix is a one-line clamp in
`barLayout()` inside `visualiserRenderers.ts`:

```ts
const WIDTH_FRACTION = 0.9                 // 90%, centred

function barLayout(width: number, height: number, n: number, frac: number) {
  const usableWidth = width * WIDTH_FRACTION
  const xOffset = (width - usableWidth) / 2
  const cy = height / 2
  const slot = usableWidth / n
  const barW = slot * 0.62
  const maxDy = (height * frac) / 2
  return { cy, slot, barW, maxDy, xOffset }
}
```

All four renderer functions (`drawSharp`, `drawSoft`, `drawGlow`,
`drawGlass`) currently compute their bar's x-coordinate as
`i * slot + (slot - barW) / 2`. Each becomes
`xOffset + i * slot + (slot - barW) / 2` — a single one-token addition
per renderer.

The clamp applies to both the FFT spectrum and the noisy flatline (they
share `barLayout`), so the new feature is consistent with the existing
visualiser cosmetically too. No setting; the constant lives in the
renderer file.

The live preview strip in `VoiceTab.tsx` re-uses the same renderers and
therefore inherits the clamp automatically. Visually it remains correct
because the preview is not full-viewport-wide — its 90% within its own
container is still well-proportioned.

---

## 7. Settings / UI

No new controls. The existing Voice settings tab stays exactly as is.

The live preview strip in `VoiceTab.tsx` continues to use the existing
`visualiserSpeechSimulator`. We do *not* alternate the preview between
noise and simulated speech — that would risk the user calibrating their
opacity slider against a dim noise frame and being surprised by full-
amplitude speech later. The simulator's amplitude profile is the right
calibration target.

---

## 8. Accessibility

No change. The canvas remains `aria-hidden`; reduced-motion fully
suppresses the new noise state too.

---

## 9. Performance

Per frame, when in the noise branch:

- One `fillNoiseBins` call: `barCount` × (one sin, two muls, one add).
  At `barCount = 96` this is ~96 sin evaluations, well under 0.05 ms on
  any device of the last decade.
- One `drawVisualiserFrame` call as today.
- No additional allocations.

Per frame, when fading out:

- RAF terminates as today. Resumes on next playback OR next expectation
  edge.

The new `useTtsExpected` subscribes to four reactive sources but emits
predicate-edge callbacks only when the boolean flips, not on every
underlying state change. The visualiser does not re-render on
expectation changes; it only restarts the RAF loop if it had paused.

---

## 10. Implementation order

Each step is independently mergeable and verifiable.

1. **Width clamp.** Apply the 90% width clamp in `barLayout()` and the
   four renderer functions. Ship in isolation: the visible spectrum
   becomes a touch narrower; everything else identical. Easy to revert
   if the proportions feel wrong.
2. **Noise generator.** Add `visualiserNoise.ts` with `fillNoiseBins` and
   a unit test confirming output is in `[BASELINE, BASELINE + NOISE_AMP]`
   and that adjacent bars differ by the expected phase step.
3. **Expectation hook.** Add `useTtsExpected.ts`, wire to the four
   sources, expose the getter and the optional edge callback. Unit-test
   the predicate as a pure function over the four input signals.
4. **Renderer integration.** Extend `VoiceVisualiser.tsx`'s RAF loop.
   Verify visually with each TTS path: live mode, manual read-aloud,
   auto-read-aloud, plain text-only chat (must remain invisible).
5. **Manual verification pass** (next section).

---

## 11. Manual verification

To be performed against a running dev frontend (`pnpm dev`, default
`http://localhost:5173`) on a real device, with at least one persona
configured and a TTS-capable LLM connection. Tester is Chris.

- [ ] **Live mode, fresh request.** Enter live mode, speak a question.
  After VAD ends, the visualiser shows the noisy flatline before the
  first audio chunk arrives, transitions smoothly to the spectrum when
  audio starts, returns to flatline during inter-sentence gaps, and
  fades out cleanly when the response ends and the listening phase
  begins.
- [ ] **Live mode, long inference.** Trigger a request with a model that
  takes a while to produce its first token. The flatline persists
  visibly throughout the wait — no flicker, no momentary disappearance.
- [ ] **Live mode, mid-response gap.** During a multi-sentence reply,
  observe that the visualiser drops to flatline between sentences
  rather than cutting to invisible.
- [ ] **Manual read-aloud.** Click the read-aloud button on a message.
  Visualiser shows flatline during synthesis, transitions to spectrum
  when audio plays, returns to flatline between TTS chunks, fades out
  at the end.
- [ ] **Auto-read-aloud, enabled persona.** Configure a persona with
  `auto_read = true`. Send a text message. Visualiser shows flatline
  from the moment LLM inference begins (before any audio is queued),
  transitions to spectrum when auto-read kicks in, fades out at the end.
- [ ] **Auto-read-aloud, disabled persona.** Same persona but
  `auto_read = false`, no live mode. Send a message. **No visualiser
  appears at any point** — neither flatline nor spectrum.
- [ ] **Persona switch during flatline.** Switch to a persona with a
  different chakra colour while the flatline is showing. The bars'
  colour follows on the next frame.
- [ ] **Master toggle off.** Disable the visualiser in Voice settings.
  Neither flatline nor spectrum appears in any of the above scenarios.
- [ ] **Reduced motion on.** Enable OS-level reduced motion. Neither
  flatline nor spectrum animates. Disable again — both resume on next
  expectation edge or playback.
- [ ] **Tap-to-pause during flatline.** Tap the HitStrip while the
  flatline is showing. Nothing audible changes (no audio playing) and
  the flatline keeps wandering — no freeze, no opacity breath.
- [ ] **Tap-to-pause during spectrum.** Existing freeze + breath
  behaviour still works — verify no regression.
- [ ] **Style switch during flatline.** Cycle Scharf / Weich / Glühend /
  Glas while the flatline is showing. Each renders distinctly without
  needing to wait for audio.
- [ ] **Opacity slider during flatline.** Drag the opacity slider while
  the flatline is showing. The flatline's intensity tracks immediately.
- [ ] **Bar count slider during flatline.** Drag the bar-count slider.
  The flatline re-allocates without flicker; the wandering wave looks
  smooth at every count.
- [ ] **No regression in audio quality.** Listen to a passage with the
  noise feature both enabled and disabled. No audible difference.
- [ ] **Width clamp.** With TTS playing, verify the bar field spans
  exactly 90% of the viewport width and is horizontally centred —
  ~5% margin on each side. The flatline obeys the same clamp. The
  live preview strip in Voice settings looks correctly proportioned
  inside its container.

---

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The flatline is too prominent and visually competes with the chat content | Amplitudes are deliberately small (~5% viewport peak vs. ~28% for spectrum). Opacity slider gives the user the same escape hatch as for the spectrum. If it still feels loud at the default style, the constants `BASELINE` and `NOISE_AMP` are single-line tuneable. |
| The flatline is too quiet and reads as a rendering bug | Inverse of the above. Same constants, same easy tuning. Real-device testing during manual verification is the deciding step. |
| `useTtsExpected` subscribes too eagerly and pegs CPU | Predicate is a four-source `||`-chain reading already-existing pub-sub seams; no polling, no per-frame work outside the RAF. Edge callbacks fire on boolean flips only. |
| Auto-read setting read at the wrong scope | We read `voice_config.auto_read` from the *currently active* persona at predicate-evaluation time. If no persona is active (login screen), the predicate's (c) branch returns false. |
| A future TTS path is added that doesn't go through `audioPlayback` or `useIsReadingAloud` | The predicate would miss it. Mitigation: the visualiser's data plane is `audioPlayback`'s `AnalyserNode` — anything that wants the spectrum *must* go through `audioPlayback`, which means (a) catches it. The expectation-only branches are best-effort for the pre-audio window only. |
