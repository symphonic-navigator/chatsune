# Transcription Indicator — Design

Status: Draft (brainstormed 2026-04-27)
Author: Chris + Claude
Related: `devdocs/specs/2026-04-26-tts-voice-visualiser-design.md`,
`devdocs/specs/2026-04-27-spectrum-analyser-chat-layout-anchoring-design.md`

---

## Problem

When the user finishes speaking, the voice pipeline enters the `transcribing`
phase: the captured audio is sent to the STT provider and the frontend waits
for a transcript. Today, this window is **visually silent** — the spectrum
analyser canvas is empty, and the user gets no feedback that anything is
happening between releasing push-to-talk (or VAD end) and the first sign of
the assistant response.

The goal: a small, calm, on-brand indicator that fills exactly this gap, in
the same visual slot as the spectrum analyser, looking like it belongs to
the same family of visuals — "everything from one mould".

## Phase mapping

The voice pipeline today produces these visible states in the analyser slot:

| Phase | What is currently visible |
|---|---|
| `recording` (user speaks) | empty |
| `transcribing` (STT in flight) | **empty — this is the gap we are filling** |
| `waiting-for-llm` (LLM producing response) | "wave" (noisy fake bins via `ttsExpected` branch) |
| `speaking` (TTS playing back) | spectrum bars |

The new indicator runs **only in `transcribing`**. The wave already covers
`waiting-for-llm`; bars cover `speaking`. The three phases now form a
continuous chain of visuals: dots → wave → bars.

## Look & feel

Three pulsing circles, centred horizontally in the chat text column,
vertically on the canvas mid-line (same `cy` as the spectrum bars).

- Base diameter: **14 px**
- Centre-to-centre spacing: **22 px** (≈ diameter × 1.6)
- Animation: matches the existing `ThinkingBubble` "thinking dots" exactly:
  - Period 2 s, ease-in-out
  - Per-dot stagger 0.3 s
  - `scale ∈ [0.8, 1.2]`
  - `animOpacity ∈ [0.3, 1.0]`
- Colour: persona chakra colour, sourced via the same prop pipeline as the
  bars (`personaColourHex` → `rgb` and `rgbLight` via `brighten()`).
- Final alpha: `userOpacity × animOpacity`, so the user's analyser opacity
  slider (0.05–0.80) controls the dots in lock-step with the bars.
- Reduced motion (`prefers-reduced-motion: reduce`): no dots are drawn,
  matching the existing visualiser behaviour. (The canvas branch returns
  early before the dots branch is reached — see "Branching" below.)

### Style adaptation — "from one mould"

The dots reuse all four visualiser styles. Each is implemented as a small
draw function alongside the existing bar renderers:

- `sharp` — solid circle in `rgbLight`, flat alpha.
- `soft` — radial gradient: bright centre (`rgbLight` at full opacity),
  fading to `rgb` at mid-radius, transparent at the edge. Mirrors the
  vertical gradient of `drawSoft` for bars.
- `glow` — solid circle in `rgbLight` plus `ctx.shadowColor` / `ctx.shadowBlur`
  in `rgb`, exactly the technique used by `drawGlow` for bars.
- `glass` — milky white fill at low alpha plus a thin coloured ring,
  matching the cool/translucent feel of `drawGlass`.

The dispatcher mirrors `drawVisualiserFrame`:

```ts
export function drawTranscriptionDots(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  height: number,
  opts: RenderOpts,
  geometry: BarGeometry,
  t: number,            // performance.now() / 1000
): void
```

Per-dot animation phase. The CSS `thinkPulse` animation goes
`0% → 50% → 100%` as `0.8 → 1.2 → 0.8` for scale and `0.3 → 1.0 → 0.3`
for opacity — i.e. a single hump per 2-second period. The Canvas
equivalent is a raised cosine, not a sine wave (a sine would oscillate
through both half-spaces and produce a different rhythm):

```
phase_i = ((t - i * 0.3) / 2.0) mod 1     // 0..1, period 2 s
pulse   = (1 - cos(phase_i * 2π)) / 2     // 0..1..0 across the period
scale   = 0.8 + 0.4 * pulse               // 0.8 → 1.2 → 0.8
animOp  = 0.3 + 0.7 * pulse               // 0.3 → 1.0 → 0.3
```

The numeric constants live next to the existing `MAX_HEIGHT_FRACTION` and
`FADE_RATE` constants, so the bar/dot pair stays easy to tune together.

## Branching in `VoiceVisualiser.tsx`

A new selector reads the pipeline phase:

```ts
const phase = useVoicePipeline((s) => s.phase)
```

Inside `tick()`, after the existing `paused` branch and the
`playing || expected` branch, before the early-out, add:

```ts
const transcribing = phase === 'transcribing'
const dotsTarget = transcribing ? 1 : 0
dotsActiveRef.current += (dotsTarget - dotsActiveRef.current) * FADE_RATE

if (dotsActiveRef.current > 0.005) {
  const rgb = hexToRgb(personaColourHex)
  const rgbLight = brighten(rgb)
  drawTranscriptionDots(style, ctx, h, {
    rgb,
    rgbLight,
    opacity: opacity * dotsActiveRef.current,
    maxHeightFraction: MAX_HEIGHT_FRACTION, // unused for dots, passed for parity
  }, { chatview, textColumn }, performance.now() / 1000)
  rafRef.current = requestAnimationFrame(tick)
  return
}
```

Properties of this placement:

- The `paused` and `playing/expected` branches early-return, so they take
  precedence. Phases are mutually exclusive in the data model
  (`transcribing` implies no active group → `ttsExpected = false`), so the
  branches never co-render.
- `dotsActiveRef` mirrors the existing `activeRef` for bars: identical
  `FADE_RATE = 0.05` constant, identical `> 0.005` cutoff. Result: the
  dots fade in when `transcribing` starts, fade out when it ends, and
  the wave (bars-via-noise) takes over without a visible gap.
- The `reducedMotion` early-out at the top of `tick()` continues to work
  unchanged — no dots in reduced motion.
- The `enabled === false` early-out (which clears the canvas and exits the
  RAF loop entirely) also continues to work unchanged — no dots when the
  user disables the analyser.

## Geometry

Reuses `barLayout` from `visualiserRenderers.ts`:

- `cy` — vertical centre of the canvas.
- `xOffset`, `finalWidth` from `barLayout` — horizontal extent matches the
  bars, but for the dots we compute a single centre point:
  ```
  centreX = xOffset + finalWidth / 2
  ```
- The three dots are centred on `centreX` with `±22 px` offsets:
  ```
  dotXs = [centreX - 22, centreX, centreX + 22]
  ```

## Files touched

- `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
  - Add `drawTranscriptionDots` dispatcher and four `drawDots{Sharp,Soft,Glow,Glass}`
    helpers. Add a `dotLayout(geometry)` helper analogous to `barLayout` for
    the centre-X computation. `dotLayout` is exported (so it can be unit-tested
    directly); the four `drawDots…` helpers stay module-private and are only
    reachable through the dispatcher.
- `frontend/src/features/voice/components/VoiceVisualiser.tsx`
  - Add `phase` selector from `useVoicePipeline`.
  - Add `dotsActiveRef`.
  - Add the new RAF branch as shown above.
  - Extend the `useEffect` dependency array with `phase`.
- `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`
  - One test per style verifying that `drawTranscriptionDots` issues the
    expected canvas calls at the expected coordinates.

No changes to:
- Voice settings store / persisted shape.
- Voice pipeline store.
- Visualiser layout store.
- Any DTO, event, or backend code.

## Testing

### Unit (visualiserRenderers.test.ts)

For each style:

- Construct a mocked 2D context.
- Call `drawTranscriptionDots(style, ctx, h, opts, geometry, t=0.5)` (a fixed
  `t` so the animation phase is deterministic).
- Assert that the right primitive (`arc`, `fill`, gradient creation, shadow
  set, etc.) was used the expected number of times (3 dots × N primitives).
- Assert that the centre-x of the middle dot equals `xOffset + finalWidth / 2`.

### Manual verification

The test discipline from prior visualiser specs applies — run on the real
device with a real STT round-trip:

1. **Push-to-talk** — record a sentence, release. Dots appear, fade in
   smoothly, hold while STT is in flight, fade out as the wave begins.
2. **Continuous voice** — VAD detects end-of-utterance. Dots → wave → bars
   with no visible gap.
3. **Style switching** — cycle through `sharp`, `soft`, `glow`, `glass`
   in the Voice tab. Dots adopt each style; "glow" should visibly glow,
   "glass" should look milky.
4. **Opacity slider** — set to 0.05 → dots barely visible; set to 0.80 →
   dots clearly present.
5. **Visualiser toggle off** — dots do not appear. Toggle back on → dots
   appear in the next `transcribing` window.
6. **Reduced motion** — enable `prefers-reduced-motion: reduce` in the
   browser. No dots appear, matching the bars' behaviour.
7. **Persona switch** — switch to a persona with a different chakra colour
   mid-session. The next `transcribing` window shows dots in the new colour.

### Build verification

- `pnpm run build` clean (catches `tsc -b` strictness that
  `pnpm tsc --noEmit` misses).

## Out of scope

- Any change to the pulsing dots inside `ThinkingBubble` (those stay as
  they are; they live in a different visual context).
- Any change to the `TranscriptionOverlay` (the small text box that shows
  the transcribed sentence). The dots and the overlay are complementary:
  dots = "in flight"; overlay = "result". They never overlap because the
  overlay only appears once the transcript arrives.
- Any new user setting. The dots inherit `enabled`, `style`, `opacity`,
  and the persona chakra colour from the existing visualiser plumbing.
- Any backend or event change.
