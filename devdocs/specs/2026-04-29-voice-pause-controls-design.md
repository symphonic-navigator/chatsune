# Continuous Voice — User-Tunable Pause Window with Countdown Pie

**Date:** 2026-04-29
**Status:** Design accepted, implementation pending
**Affected modules:** frontend voice feature only — no backend changes

---

## 1. Goal

In conversational mode (continuous voice) the VAD currently submits an
utterance after a fixed silence window of ~1 s. Two problems with the
current behaviour:

1. **The window is too short for thoughtful speakers** and there is no way
   for the user to lengthen it without hand-editing presets.
2. **The user gets no visual feedback** during the silence window — they
   simply see their utterance auto-send and have no way to anticipate it.

This design addresses both:

- A **slider** in the voice settings panel decouples the redemption window
  from the existing low/medium/high presets and lets the user dial it up to
  ~10× the current `high` value.
- A **countdown pie** appears centred on the existing visualiser rect for
  the duration of the redemption window, draining as silence elapses, and
  clears the moment the user resumes speech or the utterance is submitted.

## 2. Current state

`frontend/src/features/voice/infrastructure/vadPresets.ts` defines three
presets, each carrying four values:

| Preset  | positiveSpeechThreshold | negativeSpeechThreshold | minSpeechFrames | redemptionFrames |
|---------|-------------------------|-------------------------|-----------------|------------------|
| low     | 0.5                     | 0.35                    | 3               | 8                |
| medium  | 0.65                    | 0.5                     | 5               | 10               |
| high    | 0.8                     | 0.6                     | 8               | 12               |

`MS_PER_FRAME = 96` (audioCapture.ts:290), so `high.redemptionFrames = 12`
maps to ~1.15 s. The presets are surfaced in
`frontend/src/app/components/user-modal/VoiceTab.tsx` as three buttons
under the label *Voice Activation Threshold*.

The visualiser (Spectrum Analyzer) renders in four styles
(*sharp*, *soft*, *glow*, *glass*) — see `visualiserRenderers.ts`. It sits
as a global overlay over the layout, vertically centred,
`MAX_HEIGHT_FRACTION = 0.28`. There is no pause/redemption UI today.

VAD callbacks available from `@ricky0123/vad-web@0.0.30`:

- `onSpeechStart` / `onSpeechRealStart`
- `onSpeechEnd` (fires *after* the redemption window has elapsed)
- `onVADMisfire` (speech-start was a false positive, no `onSpeechEnd`)
- **`onFrameProcessed(probabilities, frame)`** — fires every frame
  (~96 ms) with the current speech probabilities. **Required for this
  design**: gives us the silence-began edge during the redemption window,
  before `onSpeechEnd` fires.

## 3. Decisions (settled in brainstorming)

### 3.1 Decoupled slider, single time scale

`redemptionFrames` is removed from each preset. The three presets retain
`positiveSpeechThreshold`, `negativeSpeechThreshold`, `minSpeechFrames` —
i.e. they continue to control microphone *sensitivity* (how loud is "loud
enough"). The redemption window becomes its own user setting, persisted as
**absolute milliseconds** (not a percentage — resilient against future
scale changes).

**Default:** 1728 ms (= 18 frames). This is intentionally roomier than
the previous `high` preset (1152 ms) since user feedback was that the
old `high` already felt "stressy enough". On the conceptual 0–11 520 ms
time scale this sits at ~15 %; on the live slider's [576, 11 520]
range it sits at ~10.5 % — the slider's left edge is the safety floor,
not a "zero-time" sentinel.

**Range:** 576 ms to 11 520 ms (= 6 to 120 frames).

- Lower bound 576 ms ≈ ½ × old `high`; below this the VAD becomes too
  twitchy and atomises utterances around natural pauses for breath.
  The slider is hard-floored here — there is no UI affordance to go
  lower, because no useful value lives below it.
- Upper bound = 10 × old `high`. ~11 s is generous enough for
  reflective speakers; beyond this the cost of a misfire (waiting 11 s
  to discover you have to repeat yourself) outweighs the benefit.

The slider is **linear** with `step={96}` so values snap to whole
frames.

### 3.2 Countdown pie

- **Style** matches the user's chosen visualiser style
  (sharp / soft / glow / glass) and the active persona's accent colour.
- **Form**: a wedge that drains from full disc (just-paused) to empty
  (utterance about to submit). No numeric countdown — the requirement
  was explicit: reading a number while pausing is itself stressful.
- **Position**: centred horizontally, vertically centred on the existing
  visualiser rect. Diameter ~120 px on desktop, scales down on narrow
  viewports.
- **Trigger**: appears once VAD speech-probability has stayed below
  `negativeSpeechThreshold` for at least **4 consecutive frames**
  (384 ms grace period) while inside a confirmed speech segment. This
  grace prevents the pie from flickering on natural intra-sentence
  micro-pauses (breathing, hesitation between words). Frame-grained
  rather than wall-clock-grained, so it's robust against jitter in the
  VAD's frame cadence.
- **Dismiss**: clears immediately on either of:
  - Speech resumes (probability rises above `positiveSpeechThreshold`).
  - `onSpeechEnd` fires (utterance submitted; pie has done its job).
  - `onVADMisfire` fires (speech-start was a false positive — but in
    practice the pie never appeared in this case, since misfire means
    no confirmed speech segment ever existed).

### 3.3 Replace, don't overlay

When the pie appears, the bars **fade out** (~120 ms ease-out); when the
pie clears, the bars **fade back in** (~120 ms ease-in). This was chosen
over an overlay or a contracting animation because the brief reads
unambiguously: "different mode now — something else is happening". It
also keeps the rendering simple: bars and pie never compete for the same
pixels at the same time.

## 4. Architecture

```
                       ┌──────────────────────────────────┐
  audioCapture.ts ───► │ onFrameProcessed → derives edge: │
                       │ "redemption started" / "ended"   │
                       └──────────────┬───────────────────┘
                                      │ store updates
                                      ▼
                       ┌──────────────────────────────────┐
                       │ pauseRedemptionStore             │
                       │   active: boolean                │
                       │   startedAt: number | null       │
                       │   windowMs: number               │
                       └──────────────┬───────────────────┘
                                      │ subscriptions
                       ┌──────────────┴────────────┐
                       ▼                           ▼
              VoiceVisualiser              VoiceCountdownPie
              (fade-out while              (canvas-based,
               redemption active)           same renderer family
                                            as visualiser)
```

### 4.1 New store: `pauseRedemptionStore`

`frontend/src/features/voice/stores/pauseRedemptionStore.ts`

```ts
interface PauseRedemptionState {
  // True while the redemption window is open (silence detected, pie visible).
  active: boolean
  // performance.now() value when redemption started, or null.
  startedAt: number | null
  // The redemption window currently in force (mirrored from voiceSettings
  // at the moment the speech-pause edge fires).
  windowMs: number
  start(windowMs: number): void
  clear(): void
}
```

Two transitions are valid:

- `start()` — called by audioCapture when the silence-began edge is
  detected. Captures the current `windowMs` from voice settings so that
  the pie's fill is computed against a stable target even if the user
  drags the slider mid-pause.
- `clear()` — called when speech resumes, on `onSpeechEnd`, or on
  `onVADMisfire`. Idempotent.

The pie computes `remaining = max(0, startedAt + windowMs - now)` per
RAF frame; the wedge angle is `360° × remaining / windowMs`.

### 4.2 `voiceSettingsStore` additions

```ts
// new field
redemptionMs: number   // default 1728, clamped [576, 11520]

// new setter
setRedemptionMs(ms: number): void
```

Migration in `merge`:

```ts
redemptionMs: clamp(p.redemptionMs ?? 1728, 576, 11520),
```

This is a pure-add to the persisted shape; existing users get the
default on first load and can adjust from there. **No data wipe and no
migration script needed.**

### 4.3 `vadPresets.ts` change

`redemptionFrames` is removed from `VadPreset`. The three presets keep
their other three fields. Existing tests that assert on the shape need
updating (`__tests__/vadPresets.test.ts`).

### 4.4 `audioCapture.ts` changes

`startContinuous()` already takes a `threshold` (which selects the
preset). Add `redemptionMs: number` to its options:

```ts
this.vad = await MicVAD.new({
  // ... existing fields, but redemptionMs no longer derived from preset:
  redemptionMs,                           // from caller
  positiveSpeechThreshold: preset.positiveSpeechThreshold,
  negativeSpeechThreshold: preset.negativeSpeechThreshold,
  minSpeechMs: preset.minSpeechFrames * MS_PER_FRAME,
  // new callback:
  onFrameProcessed: (probs) => this.handleVadFrame(probs),
  // existing callbacks unchanged
})
```

`handleVadFrame` is a small state machine with a frame-counted grace:

```ts
private static readonly GRACE_FRAMES = 4   // 384 ms at 96 ms/frame
private inSpeech = false                   // mirrors VAD's confirmed segment
private silenceFrames = 0                  // consecutive low-prob frames
private redemptionOpen = false             // pie should be visible

private handleVadFrame(probs: { isSpeech: number }): void {
  if (!this.inSpeech) return

  if (probs.isSpeech < preset.negativeSpeechThreshold) {
    this.silenceFrames += 1
    if (!this.redemptionOpen && this.silenceFrames >= AudioCapture.GRACE_FRAMES) {
      this.redemptionOpen = true
      pauseRedemptionStore.getState().start(currentRedemptionMs)
    }
    return
  }

  // Probability rose again. Reset the silence counter and close the pie if
  // it had been opened.
  this.silenceFrames = 0
  if (this.redemptionOpen
      && probs.isSpeech > preset.positiveSpeechThreshold) {
    this.redemptionOpen = false
    pauseRedemptionStore.getState().clear()
  }
}
```

`handleVadSpeechStart` sets `inSpeech = true` and `silenceFrames = 0`.
`handleVadSpeechEnd` and `handleVadMisfire` set `inSpeech = false`,
`silenceFrames = 0`, `redemptionOpen = false`, and call
`pauseRedemptionStore.clear()` (idempotent if already cleared).

### 4.5 `VoiceCountdownPie` component

`frontend/src/features/voice/components/VoiceCountdownPie.tsx`

Canvas-based, sized and positioned from `visualiserLayoutStore.chatview`
(same source-of-truth as the visualiser, so they always agree on the
rect). Subscribes to `pauseRedemptionStore` for active state and
windowMs, to `voiceSettingsStore` for style/persona-colour.

Renderer functions live in
`frontend/src/features/voice/infrastructure/pieRenderers.ts` and follow
the existing `visualiserRenderers.ts` pattern: one `drawPieFrame` entry
point that switches on style and dispatches to per-style helpers
(`drawPieSharp`, `drawPieSoft`, `drawPieGlow`, `drawPieGlass`). Each
helper draws a wedge (full circle minus the elapsed angle) using the
same colour-and-effect conventions as the bar renderers — solid fill,
linear gradient, shadow-blur, milky+stroke respectively.

Reduced-motion: the pie does **not** pulse or shimmer. The wedge angle
still updates per frame (it's functional, not decorative).

### 4.6 `VoiceVisualiser` change

The visualiser already manages its own RAF loop and opacity envelope.
Add a `redemptionActive` subscription from `pauseRedemptionStore`; when
true, target opacity for bars goes to zero with a 120 ms ease-out;
when false, opacity returns to its normal envelope with a 120 ms
ease-in. The pie component independently mounts / unmounts on the same
edge.

### 4.7 `useConversationMode` change

Where `audioCapture.startContinuous()` is called, also pass the current
`redemptionMs` from `voiceSettingsStore`. If the user changes the slider
mid-session, the new value affects the **next** redemption window — we
don't restart VAD on every slider tick.

### 4.8 `VoiceTab.tsx` UI addition

A new range input directly under *Voice Activation Threshold*, matching
the existing visualiser sliders (Deckkraft / Anzahl Säulen) in markup
and styling:

```tsx
<label className={LABEL} htmlFor="redemption-ms">
  Pause-Toleranz <span className="text-white/85">{(redemptionMs / 1000).toFixed(1)}s</span>
</label>
<p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
  How long the conversation waits in silence before sending what you've
  said. Longer = more time to think between sentences.
</p>
<input
  id="redemption-ms"
  type="range"
  min={576}
  max={11520}
  step={96}
  value={redemptionMs}
  onChange={(e) => setRedemptionMs(Number(e.target.value))}
  className="w-full mb-4 accent-white/70"
/>
```

`step={96}` snaps to whole frames, which keeps the rendered value clean
and matches the underlying VAD frame quantisation.

## 5. Edge cases

| Situation | Behaviour |
|---|---|
| User speaks with brief intra-sentence micro-pauses (breathing, hesitation < 384 ms) | Pie does **not** appear. Silence counter resets on the next high-probability frame. Bars stay live. |
| User speaks, then a pause longer than the 384 ms grace but shorter than `redemptionMs` | Pie appears after grace, drains partway, clears when speech resumes; no submit. |
| User speaks, then full redemption window elapses | Pie drains to empty; `onSpeechEnd` fires; utterance submits; pie disappears. |
| User pauses, then closes laptop / loses focus | Pie keeps draining (RAF still runs while page is visible). On hidden tab, `requestAnimationFrame` pauses; redemption window resumes when tab returns. Acceptable: same behaviour as the visualiser today. |
| `onVADMisfire` (speech-start false positive) | `inSpeech` was set to `true` briefly. Pie may have appeared if the probability dipped fast. `clear()` is called on misfire, pie disappears. |
| User drags slider during a live pause | New value applies to the **next** pause. Current pie keeps draining against the captured `windowMs`. |
| Reduced-motion preference set | Bars don't fade (they swap instantly), pie wedge updates per frame but no pulsing. |
| Multiple barge / supersede events | Pie is tied to the live audio capture, not to the chat group. Bargecontroller paths don't need to know about the pie. |

## 6. Testing

### 6.1 Automated

- `vadPresets.test.ts` — update fixture (no `redemptionFrames` field).
- `voiceSettingsStore` migration test — old payload without
  `redemptionMs` hydrates to default 1728, clamps out-of-range values.
- `pauseRedemptionStore.test.ts` (new) — `start()` / `clear()`
  transitions, idempotency, captured `windowMs` survives slider drag.
- `audioCapture` frame-state-machine test (new) — drives a sequence of
  `onFrameProcessed` calls and asserts on store transitions.
- `pieRenderers.test.ts` (new) — happy-path render smoke test per style,
  mirroring `visualiserRenderers.test.ts`.

### 6.2 Manual verification on real device

These steps are **required** before merging — Chris runs them on
his phone with a real persona session:

1. **Default behaviour unchanged-ish.** With slider untouched, start a
   conversational session. Confirm utterances submit roughly 1.7 s after
   the last syllable (vs. ~1 s previously). Pie appears, drains, ends
   cleanly with submit.
2. **Slider extreme — long.** Drag slider to maximum (~11.5 s). Speak a
   sentence, pause, count to 10, see the pie still draining; resume
   speaking and watch the pie clear. Then pause and let it complete —
   utterance submits at the end.
3. **Slider extreme — short.** Drag slider to minimum (~576 ms). Confirm
   the pie still appears (briefly) — does not feel broken on the lowest
   setting.
4. **Visualiser style coupling.** Cycle through sharp / soft / glow /
   glass while a redemption is in flight. Confirm pie style swaps to
   match. Cycle through personas; confirm pie colour matches new
   persona's accent.
5. **Resume mid-pause.** Speak, pause briefly, resume, pause briefly,
   resume, pause to completion. Pie should appear and clear cleanly on
   each silence/resume edge with no visual glitch on the bars.
6. **Misfire.** Brief noise (cough, key click). The bars should not
   fade out and the pie should not flicker.
7. **Intra-sentence micro-pauses.** Speak a longer sentence with short
   natural pauses (breathing between clauses, hesitating on a word).
   Pie must **not** appear during these — only the cleaner end-of-thought
   pause should trigger it.
8. **Reduced-motion.** Enable OS-level reduced-motion preference.
   Confirm pie wedge still updates but does not pulse; bars swap
   instantly without crossfade.
9. **Tab background.** Start a redemption, switch to another tab,
   switch back. No frozen pie / orphaned overlay.
10. **Slider during pause.** Start a redemption, drag the slider while
    the pie is visible — confirm the *current* pie does not jump; the
    *next* pause uses the new value.

## 7. Out of scope

- Changing the *sensitivity* presets (`positiveSpeechThreshold` etc.).
- Reworking the visualiser style palette.
- Backend changes — this is a frontend-only feature.
- Push-to-talk mode — the redemption window is meaningless there.

## 8. Open questions

None at design time. The Implementation plan will be authored in a
follow-up step (`writing-plans`).
