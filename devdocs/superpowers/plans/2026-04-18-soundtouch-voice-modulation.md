# SoundTouch Voice Modulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-voice speed and pitch sliders to a persona's voice config, applied to TTS audio at playback time via SoundTouch.

**Architecture:** The `VoiceConfigDto` on the backend gains four provider-agnostic numeric fields (dialogue + narrator × speed + pitch) with Pydantic `Field` clamps. Frontend mirrors the type, extends `SpeechSegment` with optional `speed`/`pitch`, and routes `BufferSource → SoundTouchNode → destination` in `audioPlayback`. A persistent AudioWorklet module is registered on first use; if worklet registration fails the playback falls back silently to direct routing. The `PersonaVoiceConfig` component grows a modulation block with sliders and a live test-phrase preview.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind, Vitest, Pydantic v2, FastAPI. New dependency: `@soundtouchjs/audio-worklet`.

**Spec:** `devdocs/superpowers/specs/2026-04-18-soundtouch-voice-modulation-design.md`

---

### Task 1: Install SoundTouch AudioWorklet dependency

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`

- [ ] **Step 1: Add the dependency**

```bash
cd frontend && pnpm add @soundtouchjs/audio-worklet
```

- [ ] **Step 2: Verify it installed cleanly**

```bash
cd frontend && pnpm list @soundtouchjs/audio-worklet
```

Expected: prints the installed version, no warnings.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add @soundtouchjs/audio-worklet for TTS voice modulation"
```

---

### Task 2: Extend `VoiceConfigDto` with modulation fields

**Files:**
- Modify: `shared/dtos/persona.py:21-40`
- Test: `tests/modules/persona/test_voice_config_modulation.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/modules/persona/test_voice_config_modulation.py`:

```python
import pytest
from pydantic import ValidationError

from shared.dtos.persona import VoiceConfigDto


def test_defaults_are_neutral():
    cfg = VoiceConfigDto()
    assert cfg.dialogue_speed == 1.0
    assert cfg.dialogue_pitch == 0
    assert cfg.narrator_speed == 1.0
    assert cfg.narrator_pitch == 0


def test_speed_clamped_to_range():
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_speed=0.5)
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_speed=2.0)
    # Boundary values accepted
    VoiceConfigDto(dialogue_speed=0.75, narrator_speed=1.5)


def test_pitch_clamped_to_range():
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_pitch=-12)
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_pitch=7)
    VoiceConfigDto(dialogue_pitch=-6, narrator_pitch=6)


def test_existing_document_without_modulation_loads():
    cfg = VoiceConfigDto.model_validate(
        {"dialogue_voice": "alice", "narrator_mode": "play"}
    )
    assert cfg.dialogue_speed == 1.0
    assert cfg.narrator_pitch == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune && uv run pytest tests/modules/persona/test_voice_config_modulation.py -v
```

Expected: all four tests fail — `AttributeError: 'VoiceConfigDto' object has no attribute 'dialogue_speed'`.

- [ ] **Step 3: Extend the DTO**

Replace the `VoiceConfigDto` class in `shared/dtos/persona.py` (currently lines 21-40) with:

```python
class VoiceConfigDto(BaseModel):
    dialogue_voice: str | None = None
    narrator_voice: str | None = None
    auto_read: bool = False
    narrator_mode: Literal["off", "play", "narrate"] = "off"
    # Post-synthesis modulation applied client-side via SoundTouch.
    dialogue_speed: float = Field(default=1.0, ge=0.75, le=1.5)
    dialogue_pitch: int = Field(default=0, ge=-6, le=6)
    narrator_speed: float = Field(default=1.0, ge=0.75, le=1.5)
    narrator_pitch: int = Field(default=0, ge=-6, le=6)

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_roleplay_mode(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "narrator_mode" in data:
            data.pop("roleplay_mode", None)
            return data
        legacy = data.pop("roleplay_mode", None)
        if legacy is True:
            data["narrator_mode"] = "play"
        elif legacy is False:
            data["narrator_mode"] = "off"
        return data
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/chris/workspace/chatsune && uv run pytest tests/modules/persona/test_voice_config_modulation.py -v
```

Expected: all four tests pass.

- [ ] **Step 5: Run the existing voice config tests to confirm no regression**

```bash
cd /home/chris/workspace/chatsune && uv run pytest tests/modules/persona/ -v
```

Expected: all persona tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && git add shared/dtos/persona.py tests/modules/persona/test_voice_config_modulation.py
git commit -m "Extend VoiceConfigDto with dialogue/narrator speed and pitch"
```

---

### Task 3: Mirror the new fields in the frontend persona type

**Files:**
- Modify: `frontend/src/core/types/persona.ts:39-44`

- [ ] **Step 1: Update the type**

In `frontend/src/core/types/persona.ts`, replace the `voice_config` block (lines 39-44) with:

```ts
  voice_config?: {
    dialogue_voice: string | null
    narrator_voice: string | null
    auto_read: boolean
    narrator_mode: 'off' | 'play' | 'narrate'
    dialogue_speed: number
    dialogue_pitch: number
    narrator_speed: number
    narrator_pitch: number
  } | null;
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/core/types/persona.ts
git commit -m "Mirror voice modulation fields in PersonaDto type"
```

---

### Task 4: Extend `SpeechSegment` with optional modulation

**Files:**
- Modify: `frontend/src/features/voice/types.ts:24`

- [ ] **Step 1: Update the type**

In `frontend/src/features/voice/types.ts`, replace line 24 with:

```ts
export interface SpeechSegment {
  type: 'voice' | 'narration'
  text: string
  speed?: number   // default 1.0 at playback
  pitch?: number   // semitones; default 0
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors — the fields are optional, all existing call sites stay valid.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/types.ts
git commit -m "Add optional speed and pitch to SpeechSegment"
```

---

### Task 5: SoundTouch worklet loader

**Files:**
- Create: `frontend/src/features/voice/infrastructure/soundTouchLoader.ts`

- [ ] **Step 1: Write the loader**

Create `frontend/src/features/voice/infrastructure/soundTouchLoader.ts`:

```ts
// Lazy, memoised registration of the SoundTouch AudioWorklet module.
// Returns a factory that builds a node connected to its destination.
// If module registration fails, `isAvailable` is false and callers should
// pass audio through unmodified.

import { SoundTouchNode } from '@soundtouchjs/audio-worklet'
// The package ships the worklet source as a URL import under ?worker-url.
// Vite resolves this at build time; at runtime the URL is fetched once.
import workletUrl from '@soundtouchjs/audio-worklet/dist/soundtouch-worklet.js?url'

interface LoaderState {
  initialised: boolean
  available: boolean
  error: string | null
}

const state: LoaderState = { initialised: false, available: false, error: null }
let currentContext: AudioContext | null = null

export async function ensureSoundTouchReady(ctx: AudioContext): Promise<boolean> {
  // Each AudioContext needs its own addModule call. If the caller gives us a
  // fresh context, re-register.
  if (currentContext !== ctx) {
    state.initialised = false
    currentContext = ctx
  }
  if (state.initialised) return state.available

  try {
    await ctx.audioWorklet.addModule(workletUrl)
    state.available = true
    state.error = null
  } catch (err) {
    state.available = false
    state.error = err instanceof Error ? err.message : String(err)
    console.warn('[SoundTouch] Worklet registration failed, modulation disabled:', err)
  } finally {
    state.initialised = true
  }
  return state.available
}

/**
 * Create a SoundTouchNode configured for the given speed and pitch.
 * Returns null if the worklet is not available — caller must fall back to
 * direct routing.
 */
export function createModulationNode(
  ctx: AudioContext,
  speed: number,
  pitchSemitones: number,
): SoundTouchNode | null {
  if (!state.initialised || !state.available) return null
  const node = new SoundTouchNode(ctx)
  node.tempo = speed
  node.pitchSemitones = pitchSemitones
  return node
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors. If the `?url` import errors because of missing Vite types, add the import path to the top of the file's module resolution via `/// <reference types="vite/client" />` — but the repo already has this set globally, so this should not be needed.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/infrastructure/soundTouchLoader.ts
git commit -m "Add SoundTouch AudioWorklet loader"
```

---

### Task 6: Route `audioPlayback` through the modulation node

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`

- [ ] **Step 1: Extend the playback test**

Append to `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`:

```ts
import type { SpeechSegment } from '../../types'

// Track how audio graph nodes were connected per segment
const connections: Array<{ from: string; to: string }> = []

class FakeModulationNode {
  tempo = 1
  pitchSemitones = 0
  connect = vi.fn((dest: unknown) => {
    connections.push({ from: 'soundtouch', to: (dest as { _name?: string })._name ?? 'destination' })
  })
  disconnect = vi.fn()
}

// We test the opt-in shape without actually loading the worklet. Loader is
// mocked so createModulationNode returns a stub when available.
vi.mock('../soundTouchLoader', () => ({
  ensureSoundTouchReady: vi.fn().mockResolvedValue(true),
  createModulationNode: vi.fn(() => new FakeModulationNode()),
}))

describe('audioPlayback — modulation', () => {
  it('routes segment audio through a modulation node when speed or pitch set', async () => {
    connections.length = 0
    const seg: SpeechSegment = { type: 'voice', text: 'x', speed: 0.9, pitch: 2 }
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), seg)
    await Promise.resolve() // let the async playNext settle
    expect(connections.some((c) => c.from === 'soundtouch')).toBe(true)
  })

  it('skips the modulation node when speed and pitch are both neutral', async () => {
    connections.length = 0
    const seg: SpeechSegment = { type: 'voice', text: 'x' } // no speed/pitch
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), seg)
    await Promise.resolve()
    expect(connections.some((c) => c.from === 'soundtouch')).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
```

Expected: the two new tests fail — the modulation routing does not exist yet.

- [ ] **Step 3: Implement modulation routing**

Replace the body of `AudioPlaybackImpl.playNext` in `frontend/src/features/voice/infrastructure/audioPlayback.ts` (currently lines 69-107) with:

```ts
  private async playNext(): Promise<void> {
    const entry = this.queue.shift()
    if (!entry) {
      this.playing = false
      if (this.streamClosed) this.callbacks?.onFinished()
      return
    }

    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)

    try {
      if (!this.ctx || this.ctx.state === 'closed') {
        this.ctx = new AudioContext({ sampleRate: 24_000 })
      }
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume()
      }

      const buffer = this.ctx.createBuffer(1, entry.audio.length, 24_000)
      buffer.getChannelData(0).set(entry.audio)

      const source = this.ctx.createBufferSource()
      source.buffer = buffer

      const speed = entry.segment.speed ?? 1.0
      const pitch = entry.segment.pitch ?? 0
      const needsModulation = speed !== 1.0 || pitch !== 0

      let modNode: AudioNode | null = null
      if (needsModulation) {
        const ready = await ensureSoundTouchReady(this.ctx)
        if (ready) {
          modNode = createModulationNode(this.ctx, speed, pitch)
        }
      }

      if (modNode) {
        source.connect(modNode)
        modNode.connect(this.ctx.destination)
      } else {
        source.connect(this.ctx.destination)
      }

      this.currentSource = source

      source.onended = () => {
        this.currentSource = null
        if (modNode) {
          try { modNode.disconnect() } catch { /* ignore */ }
        }
        this.scheduleNext()
      }

      source.start()
    } catch (err) {
      console.error('[AudioPlayback] Failed to play segment:', err)
      this.currentSource = null
      this.scheduleNext()
    }
  }
```

Add the import at the top of the file (after the existing `import type`):

```ts
import { ensureSoundTouchReady, createModulationNode } from './soundTouchLoader'
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
```

Expected: all audioPlayback tests pass, including the two new modulation tests.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/infrastructure/audioPlayback.ts frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
git commit -m "Route playback through SoundTouch node when speed or pitch set"
```

---

### Task 7: Thread modulation through `ReadAloudButton`

**Files:**
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Plumb values into `runReadAloud` and `triggerReadAloud`**

In `ReadAloudButton.tsx`, extend `runReadAloud` (around line 96) to accept modulation values and attach them to each segment before enqueueing. Replace the signature and the enqueue loop:

```ts
async function runReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
  gapMs: number,
  modulation: {
    dialogue_speed: number
    dialogue_pitch: number
    narrator_speed: number
    narrator_pitch: number
  },
): Promise<void> {
  // ... existing early returns, cache lookup, setCallbacks unchanged ...

  // Replace the cached-enqueue loop:
  if (cached) {
    setActiveReader(messageId, 'playing')
    for (const { audio, segment } of cached.segments) {
      audioPlayback.enqueue(audio, applyModulation(segment, modulation))
    }
    audioPlayback.closeStream()
    return
  }

  // ... parse + setActiveReader synthesising unchanged ...

  try {
    const results: CachedAudio['segments'] = []
    for (const segment of parsed) {
      if (activeMessageId !== messageId) return
      const voice = segment.type === 'voice' ? primary : narrator
      const audio = await tts.synthesise(segment.text, voice)
      if (activeMessageId !== messageId) return
      results.push({ audio, segment })
      audioPlayback.enqueue(audio, applyModulation(segment, modulation))
    }
    cachePut(cacheKey, { segments: results })
    audioPlayback.closeStream()
  } catch (err) {
    // ... unchanged ...
  }
}

function applyModulation(
  segment: SpeechSegment,
  mod: {
    dialogue_speed: number
    dialogue_pitch: number
    narrator_speed: number
    narrator_pitch: number
  },
): SpeechSegment {
  const speed = segment.type === 'voice' ? mod.dialogue_speed : mod.narrator_speed
  const pitch = segment.type === 'voice' ? mod.dialogue_pitch : mod.narrator_pitch
  if (speed === 1.0 && pitch === 0) return segment
  return { ...segment, speed, pitch }
}
```

**Important:** the cache stores the raw synthesised audio **without modulation** (modulation is a pure playback-time effect). `applyModulation` decorates the segment freshly on every enqueue, so changing sliders never forces a re-synthesis.

Update `triggerReadAloud` (around line 164) to accept and forward modulation:

```ts
export async function triggerReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
  gapMs: number,
  modulation: {
    dialogue_speed: number
    dialogue_pitch: number
    narrator_speed: number
    narrator_pitch: number
  },
): Promise<void> {
  audioPlayback.stopAll()
  setActiveReader(messageId, 'synthesising')
  await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, mode, gapMs, modulation)
}
```

- [ ] **Step 2: Resolve modulation inside the component and pass it**

In the component body (currently around lines 193-231), after `const gapMs = ...` resolve modulation from the persona:

```ts
  const modulation = {
    dialogue_speed: persona?.voice_config?.dialogue_speed ?? 1.0,
    dialogue_pitch: persona?.voice_config?.dialogue_pitch ?? 0,
    narrator_speed: persona?.voice_config?.narrator_speed ?? 1.0,
    narrator_pitch: persona?.voice_config?.narrator_pitch ?? 0,
  }
```

Pass `modulation` into the `runReadAloud(...)` call at the end of `handleClick` and add it to `useCallback`'s deps array.

- [ ] **Step 3: Update all `triggerReadAloud` callers**

Find callers of `triggerReadAloud`:

```bash
cd frontend && rg "triggerReadAloud" src/
```

At each call site, add a `modulation` object derived from the persona's `voice_config`. Commonly this is in `ChatView.tsx` and in the streaming auto-read path — update each to resolve the persona's voice_config and pass the same shape.

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Run voice tests**

```bash
cd frontend && pnpm vitest run src/features/voice/
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/components/ReadAloudButton.tsx frontend/src/features/chat/
git commit -m "Thread modulation values through read-aloud synthesis path"
```

---

### Task 8: Thread modulation through `voicePipeline.speakResponse`

**Files:**
- Modify: `frontend/src/features/voice/pipeline/voicePipeline.ts:107-130`
- Modify: all callers of `speakResponse`

- [ ] **Step 1: Extend the signature**

In `voicePipeline.ts`, replace `speakResponse` (currently lines 107-130) with:

```ts
  async speakResponse(
    text: string,
    dialogueVoice: VoicePreset,
    narratorVoice: VoicePreset,
    mode: NarratorMode,
    modulation: {
      dialogue_speed: number
      dialogue_pitch: number
      narrator_speed: number
      narrator_pitch: number
    },
  ): Promise<void> {
    const tts = ttsRegistry.active()
    if (!tts) return
    const segments = parseForSpeech(text, mode)
    if (segments.length === 0) return
    this.setState({ phase: 'speaking', segment: 0, total: segments.length })
    audioPlayback.setCallbacks({
      onSegmentStart: (seg) => {
        const idx = segments.findIndex((s) => s === seg)
        this.setState({ phase: 'speaking', segment: idx, total: segments.length })
      },
      onFinished: () => {
        if (this.mode === 'continuous') this.setState({ phase: 'listening' })
        else this.setState({ phase: 'idle' })
      },
    })
    for (const segment of segments) {
      const voice = segment.type === 'voice' ? dialogueVoice : narratorVoice
      const audio = await tts.synthesise(segment.text, voice)
      const speed = segment.type === 'voice' ? modulation.dialogue_speed : modulation.narrator_speed
      const pitch = segment.type === 'voice' ? modulation.dialogue_pitch : modulation.narrator_pitch
      const modulated = speed === 1.0 && pitch === 0 ? segment : { ...segment, speed, pitch }
      audioPlayback.enqueue(audio, modulated)
    }
  }
```

- [ ] **Step 2: Update `speakResponse` callers**

```bash
cd frontend && rg "\.speakResponse\(" src/
```

At each call site (likely in `useConversationMode.ts` and `streamingAutoReadControl.ts`), pass a `modulation` object derived from the active persona's `voice_config` with the same shape as Task 7.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/
git commit -m "Thread modulation through conversational speakResponse"
```

---

### Task 9: Add reusable slider component

**Files:**
- Create: `frontend/src/features/voice/components/ModulationSlider.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/voice/components/ModulationSlider.tsx`:

```tsx
import type { ChakraPaletteEntry } from '../../../core/types/chakra'

interface Props {
  label: string
  value: number
  min: number
  max: number
  step: number
  format: (v: number) => string
  chakra: ChakraPaletteEntry
  onChange: (v: number) => void
}

export function ModulationSlider({ label, value, min, max, step, format, chakra, onChange }: Props) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 text-[10px] uppercase tracking-[0.15em] text-white/50 font-mono">
        {label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number.parseFloat(e.target.value))}
        className="flex-1 h-1 appearance-none bg-white/10 rounded-full cursor-pointer accent-current"
        style={{ color: chakra.hex }}
      />
      <span className="w-12 text-right text-[11px] font-mono text-white/70 tabular-nums">
        {format(value)}
      </span>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/components/ModulationSlider.tsx
git commit -m "Add ModulationSlider component"
```

---

### Task 10: Add modulation block + test phrase to `PersonaVoiceConfig`

**Files:**
- Modify: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`

- [ ] **Step 1: Extend local state with modulation values + test phrase**

In `PersonaVoiceConfig.tsx`, after the existing `useState` hooks (around line 46), add:

```tsx
  const [testPhrase, setTestPhrase] = useState(PREVIEW_PHRASE)

  const [modulation, setModulation] = useState(() => ({
    dialogue_speed: persona.voice_config?.dialogue_speed ?? 1.0,
    dialogue_pitch: persona.voice_config?.dialogue_pitch ?? 0,
    narrator_speed: persona.voice_config?.narrator_speed ?? 1.0,
    narrator_pitch: persona.voice_config?.narrator_pitch ?? 0,
  }))
```

- [ ] **Step 2: Debounced persistence for modulation**

Add this helper inside the component, after the existing `persistVoiceConfig` callback:

```tsx
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const scheduleModulationSave = useCallback((next: typeof modulation) => {
    setModulation(next)
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      persistVoiceConfig(next)
    }, 400)
  }, [persistVoiceConfig])

  useEffect(() => {
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [])
```

Add `useRef, useEffect` to the imports from `react`.

Update `persistVoiceConfig` so it accepts modulation fields too. Replace the existing body (currently around lines 60-78) with:

```tsx
  const persistVoiceConfig = useCallback(
    async (patch: Partial<{
      auto_read: boolean
      narrator_mode: NarratorMode
      dialogue_speed: number
      dialogue_pitch: number
      narrator_speed: number
      narrator_pitch: number
    }>) => {
      setSaving(true)
      try {
        await onSave(persona.id, {
          voice_config: {
            dialogue_voice: persona.voice_config?.dialogue_voice ?? null,
            narrator_voice: persona.voice_config?.narrator_voice ?? null,
            auto_read: autoRead,
            narrator_mode: narratorMode,
            dialogue_speed: modulation.dialogue_speed,
            dialogue_pitch: modulation.dialogue_pitch,
            narrator_speed: modulation.narrator_speed,
            narrator_pitch: modulation.narrator_pitch,
            ...patch,
          },
        })
      } finally {
        setSaving(false)
      }
    },
    [persona.id, persona.voice_config, onSave, autoRead, narratorMode, modulation],
  )
```

- [ ] **Step 3: Update `playPreview` to use current slider values**

Replace the existing `playPreview` (around lines 99-113) with:

```tsx
  const playPreview = useCallback(async (voiceId: string, isNarrator: boolean) => {
    const tts = ttsRegistry.active()
    if (!tts?.isReady()) return
    const voice = tts.voices.find((v) => v.id === voiceId)
    if (!voice) return
    audioPlayback.stopAll()
    setActiveReader(null, 'idle')
    try {
      const audio = await tts.synthesise(testPhrase, voice)
      audioPlayback.setCallbacks({ onSegmentStart: () => {}, onFinished: () => {} })
      const speed = isNarrator ? modulation.narrator_speed : modulation.dialogue_speed
      const pitch = isNarrator ? modulation.narrator_pitch : modulation.dialogue_pitch
      const segment: SpeechSegment =
        speed === 1.0 && pitch === 0
          ? { type: isNarrator ? 'narration' : 'voice', text: testPhrase }
          : { type: isNarrator ? 'narration' : 'voice', text: testPhrase, speed, pitch }
      audioPlayback.enqueue(audio, segment)
    } catch (err) {
      console.error('[PersonaVoiceConfig] Preview failed:', err)
    }
  }, [testPhrase, modulation])
```

Add `SpeechSegment` to the imports from `../types`.

- [ ] **Step 4: Render the modulation block + test phrase input**

Find the `<div className="flex flex-col gap-2 mt-1">` block holding the preview buttons inside `VoiceFormWithPreview` (around lines 231-238). Replace the whole `VoiceFormWithPreview` signature to accept modulation + handlers, and render the modulation UI before the preview buttons.

Replace the existing `VoiceFormWithPreview` (currently lines 189-241) with:

```tsx
function VoiceFormWithPreview({
  activeTTS, persona, optionsProvider, onSave, playPreview, showNarratorField,
  modulation, onModulationChange, chakra, testPhrase, onTestPhraseChange,
}: {
  activeTTS: IntegrationDefinition
  persona: PersonaDto
  optionsProvider: (fieldKey: string) => Option[] | Promise<Option[]>
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
  playPreview: (voiceId: string, isNarrator: boolean) => Promise<void>
  showNarratorField: boolean
  modulation: {
    dialogue_speed: number
    dialogue_pitch: number
    narrator_speed: number
    narrator_pitch: number
  }
  onModulationChange: (next: typeof modulation) => void
  chakra: ChakraPaletteEntry
  testPhrase: string
  onTestPhraseChange: (s: string) => void
}) {
  const initial = (persona.integration_configs?.[activeTTS.id] ?? {}) as Record<string, unknown>
  const primaryId = initial.voice_id as string | undefined
  const narratorId = initial.narrator_voice_id as string | null | undefined

  const fields = activeTTS.persona_config_fields.filter(
    (f) => f.key !== 'narrator_voice_id' || showNarratorField,
  )

  const fmtSpeed = (v: number) => `${v.toFixed(2)}×`
  const fmtPitch = (v: number) => (v === 0 ? '0 st' : `${v > 0 ? '+' : ''}${v} st`)

  return (
    <div className="flex flex-col gap-4">
      <GenericConfigForm
        fields={fields}
        initialValues={initial}
        onSubmit={async (values) => {
          const normalised: Record<string, unknown> = { ...values }
          if ('narrator_voice_id' in normalised && normalised.narrator_voice_id === '') {
            normalised.narrator_voice_id = null
          }
          await onSave(persona.id, {
            integration_configs: {
              ...(persona.integration_configs ?? {}),
              [activeTTS.id]: normalised,
            },
          })
        }}
        optionsProvider={optionsProvider}
        submitLabel="Save voice"
        autoSubmit
      />

      <div className="flex flex-col gap-3 pt-2 border-t border-white/10">
        <label className={LABEL}>Voice Modulation</label>

        <div className="flex flex-col gap-3">
          <div className="text-[11px] text-white/55 font-mono">Primary voice</div>
          <ModulationSlider
            label="Speed" value={modulation.dialogue_speed} min={0.75} max={1.5} step={0.05}
            format={fmtSpeed} chakra={chakra}
            onChange={(v) => onModulationChange({ ...modulation, dialogue_speed: Math.round(v * 20) / 20 })}
          />
          <ModulationSlider
            label="Pitch" value={modulation.dialogue_pitch} min={-6} max={6} step={1}
            format={fmtPitch} chakra={chakra}
            onChange={(v) => onModulationChange({ ...modulation, dialogue_pitch: Math.round(v) })}
          />
        </div>

        {showNarratorField && (
          <div className="flex flex-col gap-3 mt-2">
            <div className="text-[11px] text-white/55 font-mono">Narrator voice</div>
            <ModulationSlider
              label="Speed" value={modulation.narrator_speed} min={0.75} max={1.5} step={0.05}
              format={fmtSpeed} chakra={chakra}
              onChange={(v) => onModulationChange({ ...modulation, narrator_speed: Math.round(v * 20) / 20 })}
            />
            <ModulationSlider
              label="Pitch" value={modulation.narrator_pitch} min={-6} max={6} step={1}
              format={fmtPitch} chakra={chakra}
              onChange={(v) => onModulationChange({ ...modulation, narrator_pitch: Math.round(v) })}
            />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 pt-2 border-t border-white/10">
        <label className={LABEL}>Test phrase</label>
        <input
          type="text"
          value={testPhrase}
          onChange={(e) => onTestPhraseChange(e.target.value)}
          className="bg-white/5 text-[12px] font-mono text-white/80 rounded px-2 py-1.5 border border-white/10 focus:border-white/30 focus:outline-none"
        />
        {primaryId && (
          <PreviewButton label="Preview primary voice" onClick={() => playPreview(primaryId, false)} />
        )}
        {showNarratorField && narratorId && (
          <PreviewButton label="Preview narrator voice" onClick={() => playPreview(narratorId, true)} />
        )}
      </div>
    </div>
  )
}
```

Update the `<VoiceFormWithPreview .../>` callsite in the outer `PersonaVoiceConfig` render to pass the new props:

```tsx
          <VoiceFormWithPreview
            activeTTS={activeTTS}
            persona={persona}
            optionsProvider={optionsProvider}
            onSave={onSave}
            playPreview={playPreview}
            showNarratorField={showNarratorField}
            modulation={modulation}
            onModulationChange={scheduleModulationSave}
            chakra={chakra}
            testPhrase={testPhrase}
            onTestPhraseChange={setTestPhrase}
          />
```

Also import `ModulationSlider` at the top:

```tsx
import { ModulationSlider } from './ModulationSlider'
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/components/PersonaVoiceConfig.tsx
git commit -m "Add voice modulation sliders and test phrase to persona voice config"
```

---

### Task 11: Build verification

**Files:** none modified

- [ ] **Step 1: Full TypeScript check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 2: Full test suite (frontend)**

```bash
cd frontend && pnpm vitest run
```

Expected: all tests pass.

- [ ] **Step 3: Production build**

```bash
cd frontend && pnpm run build
```

Expected: clean build, no warnings about unresolved imports.

- [ ] **Step 4: Backend compile check**

```bash
cd /home/chris/workspace/chatsune && uv run python -m py_compile shared/dtos/persona.py
```

Expected: silent success.

- [ ] **Step 5: Backend test suite**

```bash
cd /home/chris/workspace/chatsune && uv run pytest tests/modules/persona/ -v
```

Expected: all persona tests pass.

---

### Task 12: Manual verification

**Files:** none modified — this is a human test.

- [ ] **Step 1: Run the stack**

```bash
cd /home/chris/workspace/chatsune && docker compose up -d
cd frontend && pnpm run dev
```

- [ ] **Step 2: Verify existing personas keep working**

Open a persona whose `voice_config` was created before this change. Its modulation block should show `1.00×` / `0 st` for both voices. Preview plays normally.

- [ ] **Step 3: Slow + low dialogue**

Drag dialogue Speed to `0.75×`, Pitch to `−4 st`. Click "Preview primary voice" — should sound noticeably slower and lower. Wait ≥400 ms, refresh the page, reopen: sliders retain the values.

- [ ] **Step 4: Fast + high narrator**

Enable narrator mode, drag narrator Speed to `1.3×`, Pitch to `+3 st`. Preview narrator — should sound fast and high. Preview primary should still reflect the dialogue settings, not the narrator's.

- [ ] **Step 5: Test phrase for difficult words**

Replace the test phrase with "Froschschenkel fressen friedliche Frösche freitags" and preview with dialogue at `0.75× / −6 st`. Assess intelligibility — this validates the chosen slider range.

- [ ] **Step 6: Real chat with auto-read**

Enable auto-read, send a message, verify both voices honour the persona's modulation during streaming read-aloud.

- [ ] **Step 7: Merge to master**

```bash
cd /home/chris/workspace/chatsune && git checkout master && git merge --no-ff <worktree-branch>
```

(Per project default in CLAUDE.md: always merge to master after implementation.)
