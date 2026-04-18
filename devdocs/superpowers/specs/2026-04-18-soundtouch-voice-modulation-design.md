# SoundTouch Voice Modulation — Design

**Date:** 2026-04-18
**Status:** Approved, awaiting implementation plan
**Scope:** Frontend (primary) + small backend schema extension

---

## Goal

Give each persona per-voice **speed** and **pitch** controls that are applied
to TTS audio at playback time via SoundTouch. A persona has up to two voices
(primary dialogue + optional narrator); each gets its own pair of sliders. A
user-editable test phrase allows verifying that difficult words survive the
chosen modulation.

## Non-Goals

- No live parameter changes while a preview is playing — "Preview" is always
  fire-and-forget with the values at click time. Avoids audio-thread parameter
  plumbing.
- No presets, no curated "Child / Demon / Robot" shortcuts.
- No persistence of the test phrase. Pure transient UI state.
- No server-side audio processing. Modulation is a purely frontend concern.

## User Experience

Within the persona voice configuration panel:

```
Auto-Read Toggle
Narrator Mode Dropdown
─────────────────────
Voice Selects (unchanged, via GenericConfigForm)
─────────────────────
Voice Modulation
  Primary voice
    Speed  [────●────]  1.00×
    Pitch  [────●────]  0 st
  Narrator voice                    (only when narrator_mode ≠ off)
    Speed  [────●────]  1.00×
    Pitch  [────●────]  0 st
─────────────────────
Test phrase: [ The quick brown fox jumps over the lazy dog. ]
[▶ Preview primary voice]
[▶ Preview narrator voice]         (only when narrator_mode ≠ off)
```

### Slider ranges

| Control | Range | Step |
|---|---|---|
| Speed | 0.75× – 1.50× | 0.05 |
| Pitch | −6 – +6 semitones | 1 |

Chosen conservatively — beyond these ranges SoundTouch artefacts become
distracting. Room to extend later if a real use case shows up.

### Persistence behaviour

- Slider changes persist with a **~400 ms debounce** — drag ends, save fires.
- Test phrase is purely local UI state; not sent to the backend.

## Data Model

### Persona `voice_config` gains four fields

```python
class PersonaVoiceConfig(BaseModel):
    dialogue_voice: str | None = None
    narrator_voice: str | None = None
    auto_read: bool = False
    narrator_mode: Literal['off', 'play', 'narrate'] = 'off'
    # New — post-synthesis modulation
    dialogue_speed: float = Field(default=1.0, ge=0.75, le=1.5)
    dialogue_pitch: int   = Field(default=0,   ge=-6,   le=6)
    narrator_speed: float = Field(default=1.0, ge=0.75, le=1.5)
    narrator_pitch: int   = Field(default=0,   ge=-6,   le=6)
```

Defaults make existing documents deserialise without migration — complies
with the *No More Wipes* rule (CLAUDE.md). `Field(ge=…, le=…)` clamps
server-side as defence-in-depth; the frontend is authoritative for the
range.

The frontend mirror in `core/types/persona.ts` is extended in parallel.

### Why `voice_config` and not `integration_configs[ttsProviderId]`

SoundTouch runs as a **post-synthesis stage**, after the TTS engine has
produced the Float32Array. It is orthogonal to which provider is active.
Storing the values per-persona in `voice_config` means the user keeps their
modulation preferences when switching TTS providers in the future.

## Playback Architecture

### Dependency

```
pnpm add @soundtouchjs/audio-worklet
```

Chosen over the plain `soundtouchjs` package because it runs on an
AudioWorklet rather than the deprecated ScriptProcessorNode. That keeps
audio generation off the main thread and avoids pipeline glitches.

### Routing

Current:
```
BufferSource ──► destination
```

New:
```
BufferSource ──► SoundTouchNode(tempo, pitchSemitones) ──► destination
```

The `SoundTouchNode` is created per segment and disconnected in `onended`,
matching the current `BufferSource` lifecycle exactly. The AudioWorklet
module itself is registered **once** on the first `AudioContext` via
`ctx.audioWorklet.addModule(...)`, cached for the session.

### Parameter plumbing

Modulation values travel **per segment** rather than via global state:

```ts
interface SpeechSegment {
  type: 'voice' | 'narration'
  text: string
  speed?: number   // new, defaults to 1.0 at playback
  pitch?: number   // new, defaults to 0
}
```

Callers responsible for providing values:

- **Auto-read / read-aloud buttons** — read from the persona `voice_config`
  and attach per-segment values based on `segment.type`.
- **Preview** — reads from the local slider state and passes it straight
  through, independent of persisted values. Enables dragging → preview →
  listen → continue dragging.

This mirrors how `segment.type` is already threaded through and keeps
`audioPlayback` a dumb scheduler — no global modulation state to manage,
no state leakage between previews and live playback.

### Fallback

If `audioWorklet.addModule` rejects (Safari quirks, offline cache miss),
playback falls back silently to direct BufferSource → destination routing
and logs a warning. Modulation becomes a no-op in that session; the rest
of the feature still works.

### Interaction with existing playback features

- **`stopAll`** disconnects the current SoundTouchNode alongside the
  BufferSource. No lingering worklet nodes.
- **`skipCurrent`** keeps the same `onended` chain.
- **Gap-handling** is untouched — SoundTouch is inside the segment, not
  around the queue.

## Backend

Apart from the schema fields above:

- `persona.updated` event automatically carries the new values because the
  whole `voice_config` object is in the payload. No new event type.
- No new Python dependencies. Both `pyproject.toml` files unchanged.

## Validation Plan

1. **Build** — `pnpm run build` in `frontend/` must succeed; `uv run python -m py_compile` on the touched backend file.
2. **Unit tests** — extend `audioPlayback.test.ts` for the new per-segment
   parameters (mock the worklet node, assert values applied). Extend the
   persona-voice-config component test if one exists.
3. **Manual** —
   - Set dialogue slider to `0.75×` / `−4 st`, preview — should sound slow and low.
   - Reset, set narrator to `1.3×` / `+3 st`, enable narrator mode, preview — should sound fast and high only on narration.
   - Run a real chat with auto-read enabled, verify both voices honour their settings.
   - Enter "Froschschenkel" in the test phrase with `0.75× / −6 st` and confirm it is still intelligible (or accept that it is not — validates the range choice).

## Out of scope / future work

- Live parameter sweeping while a preview is playing.
- Persona-level "voice mood" presets.
- Additional SoundTouch parameters (`rate` independent of `tempo`, quality
  knobs).
- Exposing speed/pitch to the TTS-provider level (only worth considering if
  a provider ships native prosody control that we want to prefer over
  post-processing).
