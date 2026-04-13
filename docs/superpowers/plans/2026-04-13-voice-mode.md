# Voice Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add client-side voice capabilities (STT, TTS, full voice mode) to Chatsune with zero third-party data sharing.

**Architecture:** Four-layer stack (Infrastructure → Engines → Orchestration → UI) under `frontend/src/features/voice/`. Backend changes limited to persisting `voice_config` on PersonaDto. All speech processing runs in-browser via WebGPU/WASM. Voice features are globally toggled off by default — zero UI impact when disabled.

**Tech Stack:** Transformers.js v3 (Whisper STT), kokoro-js (Kokoro TTS), @ricky0123/vad-web (Silero VAD), Web Audio API, Cache Storage API, Zustand (state), Vitest (tests)

**Spec:** `docs/superpowers/specs/2026-04-13-voice-mode-design.md`

---

## File Structure

```
frontend/src/features/voice/
  types.ts                          # All voice-related TypeScript interfaces
  stores/
    voiceSettingsStore.ts           # Global voice settings (localStorage)
    voicePipelineStore.ts           # Runtime pipeline state
  hooks/
    useVoiceCapabilities.ts         # Browser capability detection
    useCtrlSpace.ts                 # Ctrl+Space keyboard shortcut
  infrastructure/
    modelManager.ts                 # Model download, cache, device detection
    audioCapture.ts                 # getUserMedia, VAD, recording
    audioPlayback.ts                # Segment queue, interrupt, playback
  engines/
    registry.ts                     # Generic EngineRegistry<T>
    whisperEngine.ts                # Whisper tiny STT implementation
    kokoroEngine.ts                 # Kokoro TTS implementation
  pipeline/
    voicePipeline.ts                # Main orchestration (STT -> LLM -> TTS)
    audioParser.ts                  # Text preprocessing + role splitting
  components/
    VoiceButton.tsx                 # Unified mic/send/cancel/stop button
    ReadAloudButton.tsx             # Per-message speaker icon
    TranscriptionOverlay.tsx        # Transcribed text display
    SetupModal.tsx                  # First-use model download modal
    VoiceSettings.tsx               # Settings section for voice prefs
    PersonaVoiceConfig.tsx          # Persona overlay voice tab

backend changes:
  shared/dtos/persona.py            # Add VoiceConfigDto
  frontend/src/core/types/persona.ts # Add voice_config to PersonaDto
  backend/modules/persona/_models.py # Add voice_config field
  backend/modules/persona/_repository.py # Handle voice_config in to_dto

tests:
  frontend/src/features/voice/__tests__/audioParser.test.ts
```

---

### Task 1: Backend — VoiceConfig Persistence

**Files:**
- Modify: `shared/dtos/persona.py`
- Modify: `backend/modules/persona/_models.py`
- Modify: `backend/modules/persona/_repository.py`
- Modify: `frontend/src/core/types/persona.ts`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx:41-63` (DEFAULT_PERSONA)

**Why:** Voice settings per persona (which voice, auto-read, roleplay mode) must survive page reloads. The backend already persists persona config — we add one optional field.

- [ ] **Step 1: Add VoiceConfigDto to shared DTOs**

In `shared/dtos/persona.py`, add the new model and field:

```python
class VoiceConfigDto(BaseModel):
    dialogue_voice: str | None = None
    narrator_voice: str | None = None
    auto_read: bool = False
    roleplay_mode: bool = False
```

Add `voice_config: VoiceConfigDto | None = None` to `PersonaDto` (after `integrations_config`), `CreatePersonaDto`, and `UpdatePersonaDto`.

- [ ] **Step 2: Add voice_config to backend document model**

In `backend/modules/persona/_models.py`, add to `PersonaDocument`:

```python
voice_config: dict | None = None
```

After `mcp_config` (line 26).

- [ ] **Step 3: Update repository to_dto**

In `backend/modules/persona/_repository.py`, add to the `to_dto` method after `integrations_config`:

```python
voice_config=VoiceConfigDto(**doc["voice_config"]) if doc.get("voice_config") else None,
```

Add the import: `from shared.dtos.persona import PersonaDto, ProfileCropDto, VoiceConfigDto`

- [ ] **Step 4: Update frontend PersonaDto type**

In `frontend/src/core/types/persona.ts`, add to `PersonaDto` interface after `integrations_config`:

```typescript
voice_config: {
  dialogue_voice: string | null
  narrator_voice: string | null
  auto_read: boolean
  roleplay_mode: boolean
} | null
```

Add `voice_config?: PersonaDto['voice_config']` to `UpdatePersonaRequest`.

- [ ] **Step 5: Update DEFAULT_PERSONA**

In `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`, add to `DEFAULT_PERSONA` after `integrations_config`:

```typescript
voice_config: null,
```

- [ ] **Step 6: Verify backend compiles**

Run: `uv run python -m py_compile shared/dtos/persona.py && uv run python -m py_compile backend/modules/persona/_models.py && uv run python -m py_compile backend/modules/persona/_repository.py`

Expected: no output (clean compile)

- [ ] **Step 7: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean, no errors

- [ ] **Step 8: Commit**

```bash
git add shared/dtos/persona.py backend/modules/persona/_models.py backend/modules/persona/_repository.py frontend/src/core/types/persona.ts frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Add voice_config field to PersonaDto for voice mode persistence"
```

---

### Task 2: Install npm Dependencies

**Files:**
- Modify: `frontend/package.json`

**Why:** Voice mode requires three npm packages for STT, TTS, and VAD.

- [ ] **Step 1: Install voice dependencies**

```bash
cd frontend && pnpm add @huggingface/transformers kokoro-js @ricky0123/vad-web
```

- [ ] **Step 2: Verify build still works**

```bash
cd frontend && pnpm run build
```

Expected: clean build, no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add voice mode dependencies: transformers.js, kokoro-js, vad-web"
```

---

### Task 3: Voice Types and Settings Store

**Files:**
- Create: `frontend/src/features/voice/types.ts`
- Create: `frontend/src/features/voice/stores/voiceSettingsStore.ts`
- Create: `frontend/src/features/voice/stores/voicePipelineStore.ts`
- Create: `frontend/src/features/voice/hooks/useVoiceCapabilities.ts`

**Why:** Foundation types used by all other voice modules. Settings store provides the global toggle. Capability hook gates UI rendering.

- [ ] **Step 1: Create voice types**

Create `frontend/src/features/voice/types.ts`:

```typescript
/* -- Engine interfaces -- */

export interface STTOptions {
  language?: string
}

export interface STTResult {
  text: string
  language?: string
  segments?: TranscriptSegment[]
}

export interface TranscriptSegment {
  start: number
  end: number
  text: string
}

export interface STTEngine {
  readonly id: string
  readonly name: string
  readonly modelSize: number
  readonly languages: string[]
  init(device: 'webgpu' | 'wasm'): Promise<void>
  transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult>
  dispose(): Promise<void>
  isReady(): boolean
}

export interface VoicePreset {
  id: string
  name: string
  language: string
  gender?: 'male' | 'female' | 'neutral'
  preview?: string
}

export interface TTSEngine {
  readonly id: string
  readonly name: string
  readonly modelSize: number
  readonly voices: VoicePreset[]
  init(device: 'webgpu' | 'wasm'): Promise<void>
  synthesise(text: string, voice: VoicePreset): Promise<Float32Array>
  dispose(): Promise<void>
  isReady(): boolean
}

/* -- Engine registry -- */

export interface EngineRegistry<T extends STTEngine | TTSEngine> {
  register(engine: T): void
  get(id: string): T | undefined
  list(): T[]
  active(): T | undefined
  setActive(id: string): Promise<void>
}

/* -- Audio parser -- */

export interface SpeechSegment {
  type: 'voice' | 'narration'
  text: string
}

/* -- Pipeline -- */

export type PipelinePhase =
  | 'idle'
  | 'listening'
  | 'recording'
  | 'transcribing'
  | 'waiting-for-llm'
  | 'speaking'

export interface PipelineState {
  phase: PipelinePhase
  segment?: number
  total?: number
}

/* -- Settings -- */

export interface VoiceSettings {
  enabled: boolean
  inputMode: 'push-to-talk' | 'continuous'
}

/* -- Capabilities -- */

export interface VoiceCapabilities {
  getUserMedia: boolean
  webgpu: boolean
  wasm: boolean
  cacheStorage: boolean
}

export type VoiceDevice = 'webgpu' | 'wasm'

/* -- Model manager -- */

export interface ModelInfo {
  id: string
  label: string
  size: number
  downloaded: boolean
}
```

- [ ] **Step 2: Create voice settings store**

Create `frontend/src/features/voice/stores/voiceSettingsStore.ts`:

```typescript
import { create } from 'zustand'
import type { VoiceSettings } from '../types'

const STORAGE_KEY = 'chatsune_voice_settings'

const DEFAULT_SETTINGS: VoiceSettings = {
  enabled: false,
  inputMode: 'push-to-talk',
}

function load(): VoiceSettings {
  try {
    if (typeof localStorage === 'undefined') return { ...DEFAULT_SETTINGS }
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

function save(settings: VoiceSettings): void {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  }
}

interface VoiceSettingsState {
  settings: VoiceSettings
  update: (patch: Partial<VoiceSettings>) => void
}

export const useVoiceSettings = create<VoiceSettingsState>((set, get) => ({
  settings: load(),
  update: (patch) => {
    const next = { ...get().settings, ...patch }
    set({ settings: next })
    save(next)
  },
}))
```

- [ ] **Step 3: Create pipeline state store**

Create `frontend/src/features/voice/stores/voicePipelineStore.ts`:

```typescript
import { create } from 'zustand'
import type { PipelineState } from '../types'

interface VoicePipelineState {
  state: PipelineState
  setState: (state: PipelineState) => void
}

export const useVoicePipeline = create<VoicePipelineState>((set) => ({
  state: { phase: 'idle' },
  setState: (state) => set({ state }),
}))
```

- [ ] **Step 4: Create voice capabilities hook**

Create `frontend/src/features/voice/hooks/useVoiceCapabilities.ts`:

```typescript
import { useMemo } from 'react'
import type { VoiceCapabilities, VoiceDevice } from '../types'

export function detectVoiceCapabilities(): VoiceCapabilities {
  return {
    getUserMedia: typeof navigator !== 'undefined'
      && !!navigator.mediaDevices?.getUserMedia,
    webgpu: typeof navigator !== 'undefined' && 'gpu' in navigator,
    wasm: typeof WebAssembly !== 'undefined'
      && typeof WebAssembly.validate === 'function',
    cacheStorage: typeof caches !== 'undefined',
  }
}

export function detectDevice(caps: VoiceCapabilities): VoiceDevice | null {
  if (caps.webgpu) return 'webgpu'
  if (caps.wasm) return 'wasm'
  return null
}

export function useVoiceCapabilities() {
  return useMemo(() => {
    const caps = detectVoiceCapabilities()
    const device = detectDevice(caps)
    const supported = device !== null && caps.cacheStorage
    const sttSupported = supported && caps.getUserMedia
    return { caps, device, supported, sttSupported }
  }, [])
}
```

- [ ] **Step 5: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/types.ts frontend/src/features/voice/stores/ frontend/src/features/voice/hooks/useVoiceCapabilities.ts
git commit -m "Add voice types, settings store, pipeline store and capability detection"
```

---

### Task 4: AudioParser with Tests

**Files:**
- Create: `frontend/src/features/voice/pipeline/audioParser.ts`
- Create: `frontend/src/features/voice/__tests__/audioParser.test.ts`

**Why:** AudioParser converts LLM output text into speech segments, stripping markdown/code and splitting dialogue from narration. This is pure logic — highly testable.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/voice/__tests__/audioParser.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { parseForSpeech } from '../pipeline/audioParser'

describe('parseForSpeech', () => {
  describe('roleplay mode', () => {
    it('splits quoted dialogue from narration', () => {
      const result = parseForSpeech(
        '*walks over* "Hello there!" *waves*',
        true,
      )
      expect(result).toEqual([
        { type: 'narration', text: 'walks over' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'narration', text: 'waves' },
      ])
    })

    it('treats unmarked text as narration', () => {
      const result = parseForSpeech('She looked away quietly.', true)
      expect(result).toEqual([
        { type: 'narration', text: 'She looked away quietly.' },
      ])
    })

    it('handles consecutive dialogue segments', () => {
      const result = parseForSpeech('"Hi!" "How are you?"', true)
      expect(result).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
      ])
    })
  })

  describe('non-roleplay mode', () => {
    it('treats everything as voice', () => {
      const result = parseForSpeech('Hello, how are you?', false)
      expect(result).toEqual([
        { type: 'voice', text: 'Hello, how are you?' },
      ])
    })
  })

  describe('pre-processing', () => {
    it('strips code blocks', () => {
      const input = 'Here is some code:\n' + '```js\nconsole.log("hi")\n```' + '\nDone.'
      const result = parseForSpeech(input, false)
      expect(result).toEqual([
        { type: 'voice', text: 'Here is some code:\nDone.' },
      ])
    })

    it('strips inline code', () => {
      const result = parseForSpeech(
        'Use the `console.log` function.',
        false,
      )
      expect(result).toEqual([
        { type: 'voice', text: 'Use the  function.' },
      ])
    })

    it('strips OOC markers', () => {
      const result = parseForSpeech(
        '"Hello!" (( this is OOC )) *smiles*',
        true,
      )
      expect(result).toEqual([
        { type: 'voice', text: 'Hello!' },
        { type: 'narration', text: 'smiles' },
      ])
    })

    it('strips markdown bold and italic', () => {
      const result = parseForSpeech('This is **bold** and __also bold__.', false)
      expect(result).toEqual([
        { type: 'voice', text: 'This is bold and also bold.' },
      ])
    })

    it('strips markdown headings', () => {
      const result = parseForSpeech('## Section Title\nSome text.', false)
      expect(result).toEqual([
        { type: 'voice', text: 'Section Title\nSome text.' },
      ])
    })

    it('strips markdown links', () => {
      const result = parseForSpeech('Click [here](https://example.com) now.', false)
      expect(result).toEqual([
        { type: 'voice', text: 'Click here now.' },
      ])
    })

    it('strips URLs', () => {
      const result = parseForSpeech('Visit https://example.com for details.', false)
      expect(result).toEqual([
        { type: 'voice', text: 'Visit  for details.' },
      ])
    })

    it('strips list markers', () => {
      const result = parseForSpeech('- First item\n- Second item\n1. Numbered', false)
      expect(result).toEqual([
        { type: 'voice', text: 'First item\nSecond item\nNumbered' },
      ])
    })

    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', false)).toEqual([])
    })

    it('returns empty array for code-only input', () => {
      const input = '```js\ncode\n```'
      expect(parseForSpeech(input, false)).toEqual([])
    })
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/voice/__tests__/audioParser.test.ts`

Expected: FAIL — module not found

- [ ] **Step 3: Implement audioParser**

Create `frontend/src/features/voice/pipeline/audioParser.ts`:

```typescript
import type { SpeechSegment } from '../types'

/**
 * Pre-process raw LLM output for TTS consumption:
 * strip code blocks, inline code, OOC markers, markdown formatting, URLs.
 */
function preprocess(text: string): string {
  let s = text
  // 1. Fenced code blocks
  s = s.replace(/```[\s\S]*?```/g, '')
  // 2. Inline code
  s = s.replace(/`[^`]+`/g, '')
  // 3. OOC markers: (( ... ))
  s = s.replace(/\(\([\s\S]*?\)\)/g, '')
  // 4. Markdown links: [text](url) -> text
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  // 5. Standalone URLs
  s = s.replace(/https?:\/\/\S+/g, '')
  // 6. Headings: ## Title -> Title
  s = s.replace(/^#{1,6}\s+/gm, '')
  // 7. Bold/italic (non-roleplay asterisks handled later)
  s = s.replace(/\*\*(.+?)\*\*/g, '$1')
  s = s.replace(/__(.+?)__/g, '$1')
  // 8. List markers
  s = s.replace(/^[-*+]\s+/gm, '')
  s = s.replace(/^\d+\.\s+/gm, '')
  // 9. Blockquotes
  s = s.replace(/^>\s?/gm, '')
  return s.trim()
}

/**
 * Parse roleplay text into voice/narration segments.
 * Quoted text -> voice, asterisk-wrapped text -> narration, unmarked -> narration.
 */
function parseRoleplay(text: string): SpeechSegment[] {
  const segments: SpeechSegment[] = []
  // Match: "dialogue" or \u201cdialogue\u201d or *narration*
  const pattern = /"([^"]+)"|\u201c([^\u201d]+)\u201d|\*([^*]+)\*/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    // Unmarked text before this match -> narration
    if (match.index > lastIndex) {
      const unmarked = text.slice(lastIndex, match.index).trim()
      if (unmarked) segments.push({ type: 'narration', text: unmarked })
    }

    if (match[1] !== undefined) {
      // "straight quote" dialogue
      segments.push({ type: 'voice', text: match[1] })
    } else if (match[2] !== undefined) {
      // curly quote dialogue
      segments.push({ type: 'voice', text: match[2] })
    } else if (match[3] !== undefined) {
      // *narration*
      segments.push({ type: 'narration', text: match[3] })
    }

    lastIndex = pattern.lastIndex
  }

  // Trailing unmarked text -> narration
  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex).trim()
    if (trailing) segments.push({ type: 'narration', text: trailing })
  }

  return segments
}

/**
 * Main entry point: preprocess text, then split into speech segments.
 *
 * @param text     Raw LLM output (markdown, roleplay markers, etc.)
 * @param roleplay Whether roleplay mode is active (splits dialogue/narration)
 */
export function parseForSpeech(text: string, roleplay: boolean): SpeechSegment[] {
  const cleaned = preprocess(text)
  if (!cleaned) return []

  if (!roleplay) {
    return [{ type: 'voice', text: cleaned }]
  }

  return parseRoleplay(cleaned)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/features/voice/__tests__/audioParser.test.ts`

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/pipeline/audioParser.ts frontend/src/features/voice/__tests__/audioParser.test.ts
git commit -m "Add AudioParser with text preprocessing and roleplay segment splitting"
```

---

### Task 5: ModelManager

**Files:**
- Create: `frontend/src/features/voice/infrastructure/modelManager.ts`

**Why:** Manages downloading, caching, and deleting ML models using the browser Cache Storage API. All other voice infrastructure depends on this to check whether models are available.

- [ ] **Step 1: Implement ModelManager**

Create `frontend/src/features/voice/infrastructure/modelManager.ts`:

```typescript
import type { ModelInfo } from '../types'

const CACHE_NAME = 'chatsune-voice-models'

const MODEL_URLS: Record<string, { url: string; label: string; size: number }> = {
  'whisper-tiny': {
    url: 'onnx-community/whisper-tiny',
    label: 'Speech Recognition',
    size: 31_000_000,
  },
  'silero-vad': {
    url: '@ricky0123/vad-web',
    label: 'Voice Detection',
    size: 1_500_000,
  },
  'kokoro-tts': {
    url: 'onnx-community/Kokoro-82M-v1.0-ONNX',
    label: 'Speech Synthesis',
    size: 40_000_000,
  },
}

class ModelManagerImpl {
  private cache: Cache | null = null

  private async getCache(): Promise<Cache> {
    if (!this.cache) {
      this.cache = await caches.open(CACHE_NAME)
    }
    return this.cache
  }

  async isDownloaded(modelId: string): Promise<boolean> {
    const cache = await this.getCache()
    const response = await cache.match(modelId)
    return response !== null
  }

  async markDownloaded(modelId: string): Promise<void> {
    const cache = await this.getCache()
    await cache.put(modelId, new Response('ok'))
  }

  async delete(modelId: string): Promise<void> {
    const cache = await this.getCache()
    await cache.delete(modelId)
  }

  async getStorageUsage(): Promise<{ used: number; models: ModelInfo[] }> {
    const models: ModelInfo[] = []
    let used = 0

    for (const [id, meta] of Object.entries(MODEL_URLS)) {
      const downloaded = await this.isDownloaded(id)
      models.push({ id, label: meta.label, size: meta.size, downloaded })
      if (downloaded) used += meta.size
    }

    return { used, models }
  }

  getModelList(): ModelInfo[] {
    return Object.entries(MODEL_URLS).map(([id, meta]) => ({
      id,
      label: meta.label,
      size: meta.size,
      downloaded: false,
    }))
  }

  detectDevice(): 'webgpu' | 'wasm' {
    if (typeof navigator !== 'undefined' && 'gpu' in navigator) return 'webgpu'
    return 'wasm'
  }
}

export const modelManager = new ModelManagerImpl()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/modelManager.ts
git commit -m "Add ModelManager for voice model download and cache management"
```

---

### Task 6: AudioCapture

**Files:**
- Create: `frontend/src/features/voice/infrastructure/audioCapture.ts`

**Why:** Wraps getUserMedia with echo cancellation + noise suppression. Integrates Silero VAD for speech detection. Provides volume level data for UI visualisation.

- [ ] **Step 1: Implement AudioCapture**

Create `frontend/src/features/voice/infrastructure/audioCapture.ts`:

```typescript
import { MicVAD } from '@ricky0123/vad-web'

export interface AudioCaptureCallbacks {
  onSpeechStart: () => void
  onSpeechEnd: (audio: Float32Array) => void
  onVolumeChange: (level: number) => void
}

class AudioCaptureImpl {
  private vad: MicVAD | null = null
  private callbacks: AudioCaptureCallbacks | null = null
  private analyser: AnalyserNode | null = null
  private animFrameId: number | null = null
  private audioContext: AudioContext | null = null

  async start(callbacks: AudioCaptureCallbacks): Promise<void> {
    this.callbacks = callbacks

    this.vad = await MicVAD.new({
      additionalAudioConstraints: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      onSpeechStart: () => {
        this.callbacks?.onSpeechStart()
      },
      onSpeechEnd: (audio: Float32Array) => {
        this.callbacks?.onSpeechEnd(audio)
      },
    })

    // Set up volume meter from the VAD's stream
    const stream = (this.vad as unknown as { stream: MediaStream }).stream
    if (stream) {
      this.audioContext = new AudioContext()
      const source = this.audioContext.createMediaStreamSource(stream)
      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = 256
      source.connect(this.analyser)
      this.startVolumeMeter()
    }

    this.vad.start()
  }

  stop(): void {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId)
      this.animFrameId = null
    }
    this.vad?.pause()
    this.vad?.destroy()
    this.vad = null
    this.audioContext?.close()
    this.audioContext = null
    this.analyser = null
    this.callbacks = null
  }

  private startVolumeMeter(): void {
    if (!this.analyser || !this.callbacks) return

    const dataArray = new Uint8Array(this.analyser.frequencyBinCount)

    const tick = () => {
      if (!this.analyser) return
      this.analyser.getByteFrequencyData(dataArray)
      // Normalise to 0-1
      const sum = dataArray.reduce((a, b) => a + b, 0)
      const level = sum / (dataArray.length * 255)
      this.callbacks?.onVolumeChange(level)
      this.animFrameId = requestAnimationFrame(tick)
    }

    this.animFrameId = requestAnimationFrame(tick)
  }
}

export const audioCapture = new AudioCaptureImpl()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioCapture.ts
git commit -m "Add AudioCapture with VAD, echo cancellation and volume metering"
```

---

### Task 7: AudioPlayback

**Files:**
- Create: `frontend/src/features/voice/infrastructure/audioPlayback.ts`

**Why:** Manages a queue of audio segments for seamless playback. Supports stopping all playback or skipping the current segment.

- [ ] **Step 1: Implement AudioPlayback**

Create `frontend/src/features/voice/infrastructure/audioPlayback.ts`:

```typescript
import type { SpeechSegment } from '../types'

interface QueueEntry {
  audio: Float32Array
  segment: SpeechSegment
}

export interface AudioPlaybackCallbacks {
  onSegmentStart: (segment: SpeechSegment) => void
  onFinished: () => void
}

class AudioPlaybackImpl {
  private queue: QueueEntry[] = []
  private ctx: AudioContext | null = null
  private currentSource: AudioBufferSourceNode | null = null
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false

  setCallbacks(callbacks: AudioPlaybackCallbacks): void {
    this.callbacks = callbacks
  }

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing) this.playNext()
  }

  stopAll(): void {
    this.queue = []
    this.currentSource?.stop()
    this.currentSource = null
    this.playing = false
  }

  skipCurrent(): void {
    this.currentSource?.stop()
    this.currentSource = null
    // playNext will be called by the onended handler
  }

  private playNext(): void {
    const entry = this.queue.shift()
    if (!entry) {
      this.playing = false
      this.callbacks?.onFinished()
      return
    }

    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)

    if (!this.ctx) {
      this.ctx = new AudioContext()
    }

    const buffer = this.ctx.createBuffer(1, entry.audio.length, 24_000)
    buffer.getChannelData(0).set(entry.audio)

    const source = this.ctx.createBufferSource()
    source.buffer = buffer
    source.connect(this.ctx.destination)
    this.currentSource = source

    source.onended = () => {
      this.currentSource = null
      this.playNext()
    }

    source.start()
  }

  isPlaying(): boolean {
    return this.playing
  }

  dispose(): void {
    this.stopAll()
    this.ctx?.close()
    this.ctx = null
    this.callbacks = null
  }
}

export const audioPlayback = new AudioPlaybackImpl()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioPlayback.ts
git commit -m "Add AudioPlayback with segment queue, stop and skip support"
```

---

### Task 8: Engine Registry

**Files:**
- Create: `frontend/src/features/voice/engines/registry.ts`

**Why:** Generic registry for STT/TTS engines. Follows the same singleton registry pattern used in the backend for tools and inference providers.

- [ ] **Step 1: Implement EngineRegistry**

Create `frontend/src/features/voice/engines/registry.ts`:

```typescript
import type { STTEngine, TTSEngine, EngineRegistry } from '../types'

class EngineRegistryImpl<T extends STTEngine | TTSEngine> implements EngineRegistry<T> {
  private engines = new Map<string, T>()
  private activeEngine: T | undefined = undefined

  register(engine: T): void {
    this.engines.set(engine.id, engine)
  }

  get(id: string): T | undefined {
    return this.engines.get(id)
  }

  list(): T[] {
    return Array.from(this.engines.values())
  }

  active(): T | undefined {
    return this.activeEngine
  }

  async setActive(id: string): Promise<void> {
    const engine = this.engines.get(id)
    if (!engine) throw new Error(`Engine "${id}" not registered`)

    if (this.activeEngine && this.activeEngine.id !== id) {
      await this.activeEngine.dispose()
    }

    this.activeEngine = engine
  }
}

export const sttRegistry = new EngineRegistryImpl<STTEngine>()
export const ttsRegistry = new EngineRegistryImpl<TTSEngine>()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/engines/registry.ts
git commit -m "Add generic engine registry for STT and TTS engines"
```

---

### Task 9: WhisperEngine (STT)

**Files:**
- Create: `frontend/src/features/voice/engines/whisperEngine.ts`

**Why:** Implements STTEngine using Whisper tiny via Transformers.js. Handles model loading and transcription.

- [ ] **Step 1: Implement WhisperEngine**

Create `frontend/src/features/voice/engines/whisperEngine.ts`:

```typescript
import { pipeline } from '@huggingface/transformers'
import type { STTEngine, STTOptions, STTResult } from '../types'
import { modelManager } from '../infrastructure/modelManager'

class WhisperEngineImpl implements STTEngine {
  readonly id = 'whisper-tiny'
  readonly name = 'Whisper Tiny'
  readonly modelSize = 31_000_000
  readonly languages = ['en']

  private pipe: Awaited<ReturnType<typeof pipeline>> | null = null

  async init(device: 'webgpu' | 'wasm'): Promise<void> {
    this.pipe = await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
      device: device === 'webgpu' ? 'webgpu' : 'wasm',
      dtype: 'q8',
    })
    await modelManager.markDownloaded('whisper-tiny')
  }

  async transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult> {
    if (!this.pipe) throw new Error('WhisperEngine not initialised')

    const result = await this.pipe(audio, {
      language: options?.language ?? 'en',
      return_timestamps: true,
    })

    // Transformers.js returns { text, chunks? }
    const output = result as { text: string; chunks?: Array<{ text: string; timestamp: [number, number] }> }

    return {
      text: output.text.trim(),
      language: options?.language ?? 'en',
      segments: output.chunks?.map((c) => ({
        text: c.text,
        start: c.timestamp[0],
        end: c.timestamp[1],
      })),
    }
  }

  async dispose(): Promise<void> {
    this.pipe = null
  }

  isReady(): boolean {
    return this.pipe !== null
  }
}

export const whisperEngine = new WhisperEngineImpl()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean (may need type adjustments for Transformers.js API — fix as needed)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/engines/whisperEngine.ts
git commit -m "Add WhisperEngine STT implementation using Transformers.js"
```

---

### Task 10: KokoroEngine (TTS)

**Files:**
- Create: `frontend/src/features/voice/engines/kokoroEngine.ts`

**Why:** Implements TTSEngine using Kokoro via kokoro-js. Handles model loading and speech synthesis with multiple voice presets.

- [ ] **Step 1: Implement KokoroEngine**

Create `frontend/src/features/voice/engines/kokoroEngine.ts`:

```typescript
import { KokoroTTS } from 'kokoro-js'
import type { TTSEngine, VoicePreset } from '../types'
import { modelManager } from '../infrastructure/modelManager'

const KOKORO_VOICES: VoicePreset[] = [
  { id: 'af_heart', name: 'Heart (Female)', language: 'en', gender: 'female' },
  { id: 'af_bella', name: 'Bella (Female)', language: 'en', gender: 'female' },
  { id: 'af_sarah', name: 'Sarah (Female)', language: 'en', gender: 'female' },
  { id: 'af_nicole', name: 'Nicole (Female)', language: 'en', gender: 'female' },
  { id: 'af_sky', name: 'Sky (Female)', language: 'en', gender: 'female' },
  { id: 'am_adam', name: 'Adam (Male)', language: 'en', gender: 'male' },
  { id: 'am_michael', name: 'Michael (Male)', language: 'en', gender: 'male' },
  { id: 'bf_emma', name: 'Emma (British F)', language: 'en', gender: 'female' },
  { id: 'bf_isabella', name: 'Isabella (British F)', language: 'en', gender: 'female' },
  { id: 'bm_george', name: 'George (British M)', language: 'en', gender: 'male' },
  { id: 'bm_lewis', name: 'Lewis (British M)', language: 'en', gender: 'male' },
]

class KokoroEngineImpl implements TTSEngine {
  readonly id = 'kokoro'
  readonly name = 'Kokoro'
  readonly modelSize = 40_000_000
  readonly voices = KOKORO_VOICES

  private tts: KokoroTTS | null = null

  async init(device: 'webgpu' | 'wasm'): Promise<void> {
    this.tts = await KokoroTTS.from_pretrained(
      'onnx-community/Kokoro-82M-v1.0-ONNX',
      { dtype: device === 'webgpu' ? 'fp32' : 'q8f16' },
    )
    await modelManager.markDownloaded('kokoro-tts')
  }

  async synthesise(text: string, voice: VoicePreset): Promise<Float32Array> {
    if (!this.tts) throw new Error('KokoroEngine not initialised')
    const result = await this.tts.generate(text, { voice: voice.id })
    return result.audio
  }

  async dispose(): Promise<void> {
    this.tts = null
  }

  isReady(): boolean {
    return this.tts !== null
  }
}

export const kokoroEngine = new KokoroEngineImpl()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean (may need type adjustments for kokoro-js API — fix as needed)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/engines/kokoroEngine.ts
git commit -m "Add KokoroEngine TTS implementation with voice presets"
```

---

### Task 11: VoicePipeline

**Files:**
- Create: `frontend/src/features/voice/pipeline/voicePipeline.ts`

**Why:** Orchestrates the full voice flow: mic -> STT -> text -> TTS -> playback. Manages pipeline state transitions and interrupt handling.

- [ ] **Step 1: Implement VoicePipeline**

Create `frontend/src/features/voice/pipeline/voicePipeline.ts`:

```typescript
import type { PipelineState, VoicePreset } from '../types'
import { audioCapture } from '../infrastructure/audioCapture'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { sttRegistry, ttsRegistry } from '../engines/registry'
import { parseForSpeech } from './audioParser'

export interface VoicePipelineCallbacks {
  onStateChange: (state: PipelineState) => void
  onTranscription: (text: string) => void
}

class VoicePipelineImpl {
  private callbacks: VoicePipelineCallbacks | null = null
  private mode: 'push-to-talk' | 'continuous' = 'push-to-talk'
  private state: PipelineState = { phase: 'idle' }

  setCallbacks(callbacks: VoicePipelineCallbacks): void {
    this.callbacks = callbacks
  }

  private setState(state: PipelineState): void {
    this.state = state
    this.callbacks?.onStateChange(state)
  }

  async startRecording(mode: 'push-to-talk' | 'continuous'): Promise<void> {
    this.mode = mode
    this.stopPlayback()

    this.setState({ phase: mode === 'continuous' ? 'listening' : 'recording' })

    await audioCapture.start({
      onSpeechStart: () => {
        this.setState({ phase: 'recording' })
      },
      onSpeechEnd: async (audio) => {
        this.setState({ phase: 'transcribing' })
        await this.handleAudio(audio)
      },
      onVolumeChange: () => {
        // Volume data is consumed by UI via the pipeline store
      },
    })
  }

  stopRecording(): void {
    audioCapture.stop()
    if (this.state.phase === 'recording' || this.state.phase === 'listening') {
      this.setState({ phase: 'idle' })
    }
  }

  private async handleAudio(audio: Float32Array): Promise<void> {
    const stt = sttRegistry.active()
    if (!stt) {
      this.setState({ phase: 'idle' })
      return
    }

    const result = await stt.transcribe(audio)
    this.callbacks?.onTranscription(result.text)

    if (this.mode === 'continuous') {
      this.setState({ phase: 'listening' })
    } else {
      this.setState({ phase: 'idle' })
    }
  }

  async speakResponse(
    text: string,
    dialogueVoice: VoicePreset,
    narratorVoice: VoicePreset,
    roleplayMode: boolean,
  ): Promise<void> {
    const tts = ttsRegistry.active()
    if (!tts) return

    const segments = parseForSpeech(text, roleplayMode)
    if (segments.length === 0) return

    this.setState({ phase: 'speaking', segment: 0, total: segments.length })

    audioPlayback.setCallbacks({
      onSegmentStart: (seg) => {
        const idx = segments.findIndex((s) => s === seg)
        this.setState({ phase: 'speaking', segment: idx, total: segments.length })
      },
      onFinished: () => {
        if (this.mode === 'continuous') {
          this.setState({ phase: 'listening' })
        } else {
          this.setState({ phase: 'idle' })
        }
      },
    })

    // Synthesise and enqueue each segment
    for (const segment of segments) {
      const voice = segment.type === 'voice' ? dialogueVoice : narratorVoice
      const audio = await tts.synthesise(segment.text, voice)
      audioPlayback.enqueue(audio, segment)
    }
  }

  stopPlayback(): void {
    audioPlayback.stopAll()
  }

  skipSegment(): void {
    audioPlayback.skipCurrent()
  }

  getPhase(): PipelineState['phase'] {
    return this.state.phase
  }

  dispose(): void {
    this.stopRecording()
    this.stopPlayback()
    audioPlayback.dispose()
    this.callbacks = null
    this.setState({ phase: 'idle' })
  }
}

export const voicePipeline = new VoicePipelineImpl()
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/pipeline/voicePipeline.ts
git commit -m "Add VoicePipeline orchestrating STT, TTS and playback"
```

---

### Task 12: SetupModal

**Files:**
- Create: `frontend/src/features/voice/components/SetupModal.tsx`

**Why:** First-use experience: download ~73 MB of models with progress indication. Shown when user first enables voice mode but models are not cached.

- [ ] **Step 1: Implement SetupModal**

Create `frontend/src/features/voice/components/SetupModal.tsx`:

```typescript
import { useCallback, useEffect, useState } from 'react'
import { modelManager } from '../infrastructure/modelManager'
import { whisperEngine } from '../engines/whisperEngine'
import { kokoroEngine } from '../engines/kokoroEngine'
import { sttRegistry, ttsRegistry } from '../engines/registry'

interface SetupModalProps {
  onComplete: () => void
  onCancel: () => void
}

interface StepState {
  label: string
  size: number
  status: 'waiting' | 'downloading' | 'done' | 'error'
  error?: string
}

export function SetupModal({ onComplete, onCancel }: SetupModalProps) {
  const [steps, setSteps] = useState<StepState[]>([
    { label: 'Speech Recognition', size: 31, status: 'waiting' },
    { label: 'Voice Detection', size: 1.5, status: 'waiting' },
    { label: 'Speech Synthesis', size: 40, status: 'waiting' },
  ])

  const updateStep = useCallback((idx: number, patch: Partial<StepState>) => {
    setSteps((prev) => prev.map((s, i) => i === idx ? { ...s, ...patch } : s))
  }, [])

  useEffect(() => {
    let cancelled = false

    async function run() {
      const device = modelManager.detectDevice()

      // Step 0: Whisper (STT)
      updateStep(0, { status: 'downloading' })
      try {
        await whisperEngine.init(device)
        sttRegistry.register(whisperEngine)
        await sttRegistry.setActive('whisper-tiny')
        if (cancelled) return
        updateStep(0, { status: 'done' })
      } catch (err) {
        if (cancelled) return
        updateStep(0, { status: 'error', error: String(err) })
        return
      }

      // Step 1: VAD (downloaded as part of audioCapture, just mark done)
      updateStep(1, { status: 'downloading' })
      try {
        await modelManager.markDownloaded('silero-vad')
        if (cancelled) return
        updateStep(1, { status: 'done' })
      } catch (err) {
        if (cancelled) return
        updateStep(1, { status: 'error', error: String(err) })
        return
      }

      // Step 2: Kokoro (TTS)
      updateStep(2, { status: 'downloading' })
      try {
        await kokoroEngine.init(device)
        ttsRegistry.register(kokoroEngine)
        await ttsRegistry.setActive('kokoro')
        if (cancelled) return
        updateStep(2, { status: 'done' })
      } catch (err) {
        if (cancelled) return
        updateStep(2, { status: 'error', error: String(err) })
        return
      }

      if (!cancelled) onComplete()
    }

    run()
    return () => { cancelled = true }
  }, [onComplete, updateStep])

  const totalSize = steps.reduce((a, s) => a + s.size, 0)
  const hasError = steps.some((s) => s.status === 'error')

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60" onClick={onCancel} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-md rounded-xl border border-white/10 bg-surface p-6 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <h2 className="mb-1 text-[14px] font-semibold text-white/85">
            Voice Mode Setup
          </h2>
          <p className="mb-5 text-[11px] text-white/45 font-mono">
            The following models will be downloaded and stored locally in your browser.
          </p>

          <div className="flex flex-col gap-3 mb-5">
            {steps.map((step, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="w-5 flex items-center justify-center">
                  {step.status === 'done' && (
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M3 7L6 10L11 4" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                  {step.status === 'downloading' && (
                    <div className="h-3 w-3 animate-spin rounded-full border-2 border-white/20 border-t-gold" />
                  )}
                  {step.status === 'waiting' && (
                    <div className="h-2 w-2 rounded-full bg-white/15" />
                  )}
                  {step.status === 'error' && (
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M4 4L10 10M10 4L4 10" stroke="#ef4444" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                  )}
                </div>
                <div className="flex-1">
                  <div className="flex items-baseline justify-between">
                    <span className={'text-[12px] ' + (step.status === 'done' ? 'text-white/60' : 'text-white/80')}>
                      {step.label}
                    </span>
                    <span className="text-[10px] text-white/35 font-mono">
                      {step.size} MB
                    </span>
                  </div>
                  {step.status === 'error' && (
                    <p className="text-[10px] text-red-400 mt-0.5">{step.error}</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between border-t border-white/8 pt-4">
            <span className="text-[10px] text-white/35 font-mono">
              Total: ~{totalSize.toFixed(0)} MB
            </span>
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-white/60 transition-colors hover:bg-white/10 hover:text-white/80"
            >
              {hasError ? 'Close' : 'Cancel'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/components/SetupModal.tsx
git commit -m "Add SetupModal for first-use voice model download with progress"
```

---

### Task 13: VoiceButton (Unified Action Button)

**Files:**
- Create: `frontend/src/features/voice/components/VoiceButton.tsx`
- Modify: `frontend/src/features/chat/ChatInput.tsx`

**Why:** The core UX innovation: the send button morphs into mic/send/cancel/stop depending on state. Zero additional UI clutter.

- [ ] **Step 1: Create VoiceButton component**

Create `frontend/src/features/voice/components/VoiceButton.tsx`:

```typescript
import type { PipelinePhase } from '../types'

interface VoiceButtonProps {
  phase: PipelinePhase
  hasText: boolean
  isStreaming: boolean
  disabled: boolean
  hasPendingUploads: boolean
  volumeLevel: number
  onSend: () => void
  onCancel: () => void
  onMicPress: () => void
  onMicRelease: () => void
  onStopRecording: () => void
}

export function VoiceButton({
  phase, hasText, isStreaming, disabled, hasPendingUploads,
  volumeLevel, onSend, onCancel, onMicPress, onMicRelease, onStopRecording,
}: VoiceButtonProps) {
  // Streaming -> cancel button
  if (isStreaming) {
    return (
      <button
        type="button"
        data-testid="cancel-button"
        onClick={onCancel}
        title="Cancel response"
        aria-label="Cancel response"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 transition-colors hover:bg-red-500/20"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // Recording -> stop button with volume glow
  if (phase === 'recording') {
    const glowOpacity = 0.1 + volumeLevel * 0.3
    return (
      <button
        type="button"
        onClick={onStopRecording}
        onMouseUp={onMicRelease}
        title="Stop recording"
        aria-label="Stop recording"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-red-500/40 text-red-400 transition-colors"
        style={{ background: `rgba(239, 68, 68, ${glowOpacity})` }}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // Transcribing -> spinner
  if (phase === 'transcribing') {
    return (
      <button
        type="button"
        disabled
        title="Transcribing..."
        aria-label="Transcribing"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-white/40"
      >
        <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
      </button>
    )
  }

  // Speaking -> stop playback button
  if (phase === 'speaking') {
    return (
      <button
        type="button"
        onClick={onStopRecording}
        title="Stop playback"
        aria-label="Stop playback"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-gold/40 bg-gold/10 text-gold transition-colors hover:bg-gold/20"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // Has text -> send button
  if (hasText) {
    return (
      <button
        type="button"
        data-testid="send-button"
        onClick={onSend}
        disabled={disabled || hasPendingUploads}
        title="Send message"
        aria-label="Send message"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85 disabled:opacity-30 disabled:hover:bg-white/6"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M2 14L14.5 8L2 2V6.5L10 8L2 9.5V14Z" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // No text -> mic button
  return (
    <button
      type="button"
      onMouseDown={onMicPress}
      onMouseUp={onMicRelease}
      onTouchStart={onMicPress}
      onTouchEnd={onMicRelease}
      disabled={disabled}
      title="Hold to record (Ctrl+Space)"
      aria-label="Record voice message"
      className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85 disabled:opacity-30"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <rect x="5" y="1" width="4" height="8" rx="2" stroke="currentColor" strokeWidth="1.2" />
        <path d="M3 6.5C3 9 5 11 7 11C9 11 11 9 11 6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M7 11V13M5.5 13H8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    </button>
  )
}
```

- [ ] **Step 2: Modify ChatInput to accept voice props**

In `frontend/src/features/chat/ChatInput.tsx`, add new optional props to `ChatInputProps`:

```typescript
voiceEnabled?: boolean
voicePhase?: PipelinePhase
volumeLevel?: number
onMicPress?: () => void
onMicRelease?: () => void
onStopRecording?: () => void
```

Add imports at the top:
```typescript
import { VoiceButton } from '../voice/components/VoiceButton'
import type { PipelinePhase } from '../voice/types'
```

Destructure the new props in the component function signature.

Replace the existing send/cancel button ternary (the block starting with `{isStreaming ? (` around lines 206-233) with:

```typescript
{voiceEnabled ? (
  <VoiceButton
    phase={voicePhase ?? 'idle'}
    hasText={!!text.trim()}
    isStreaming={isStreaming}
    disabled={disabled}
    hasPendingUploads={hasPendingUploads}
    volumeLevel={volumeLevel ?? 0}
    onSend={handleSend}
    onCancel={onCancel}
    onMicPress={onMicPress ?? (() => {})}
    onMicRelease={onMicRelease ?? (() => {})}
    onStopRecording={onStopRecording ?? (() => {})}
  />
) : (
  <>
    {isStreaming ? (
      <button
        type="button"
        data-testid="cancel-button"
        onClick={onCancel}
        title="Cancel response"
        aria-label="Cancel response"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 transition-colors hover:bg-red-500/20"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
    ) : (
      <button
        type="button"
        data-testid="send-button"
        onClick={handleSend}
        disabled={!text.trim() || disabled || hasPendingUploads}
        title="Send message"
        aria-label="Send message"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85 disabled:opacity-30 disabled:hover:bg-white/6"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M2 14L14.5 8L2 2V6.5L10 8L2 9.5V14Z" fill="currentColor" />
        </svg>
      </button>
    )}
  </>
)}
```

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/components/VoiceButton.tsx frontend/src/features/chat/ChatInput.tsx
git commit -m "Add VoiceButton: unified mic/send/cancel/stop action button"
```

---

### Task 14: TranscriptionOverlay

**Files:**
- Create: `frontend/src/features/voice/components/TranscriptionOverlay.tsx`

**Why:** Shows transcribed text near the input field before sending. In PTT mode, user can edit; in continuous mode, briefly displayed then auto-sent.

- [ ] **Step 1: Implement TranscriptionOverlay**

Create `frontend/src/features/voice/components/TranscriptionOverlay.tsx`:

```typescript
interface TranscriptionOverlayProps {
  text: string
  mode: 'push-to-talk' | 'continuous'
}

export function TranscriptionOverlay({ text, mode }: TranscriptionOverlayProps) {
  if (!text) return null

  return (
    <div className="mx-auto mb-2 max-w-3xl rounded-lg border border-white/10 bg-white/5 px-3 py-2">
      <div className="flex items-center gap-2 mb-1">
        <svg width="12" height="12" viewBox="0 0 14 14" fill="none" className="text-white/40">
          <rect x="5" y="1" width="4" height="8" rx="2" stroke="currentColor" strokeWidth="1.2" />
          <path d="M3 6.5C3 9 5 11 7 11C9 11 11 9 11 6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <span className="text-[10px] uppercase tracking-[0.15em] text-white/40 font-mono">
          {mode === 'continuous' ? 'Sending...' : 'Transcribed'}
        </span>
      </div>
      <p className="text-[13px] text-white/70">{text}</p>
    </div>
  )
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/components/TranscriptionOverlay.tsx
git commit -m "Add TranscriptionOverlay for displaying transcribed speech"
```

---

### Task 15: ReadAloudButton

**Files:**
- Create: `frontend/src/features/voice/components/ReadAloudButton.tsx`
- Modify: `frontend/src/features/chat/AssistantMessage.tsx`

**Why:** Per-message speaker icon allowing any assistant message to be read aloud on demand. Only visible when voice features are globally enabled.

- [ ] **Step 1: Create ReadAloudButton**

Create `frontend/src/features/voice/components/ReadAloudButton.tsx`:

```typescript
import { useCallback, useState } from 'react'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { parseForSpeech } from '../pipeline/audioParser'
import type { VoicePreset } from '../types'

interface ReadAloudButtonProps {
  content: string
  dialogueVoice?: VoicePreset
  narratorVoice?: VoicePreset
  roleplayMode?: boolean
}

export function ReadAloudButton({
  content, dialogueVoice, narratorVoice, roleplayMode = false,
}: ReadAloudButtonProps) {
  const [playing, setPlaying] = useState(false)

  const handleClick = useCallback(async () => {
    if (playing) {
      audioPlayback.stopAll()
      setPlaying(false)
      return
    }

    const tts = ttsRegistry.active()
    if (!tts) return

    const fallbackVoice = tts.voices[0]
    const dVoice = dialogueVoice ?? fallbackVoice
    const nVoice = narratorVoice ?? fallbackVoice

    const segments = parseForSpeech(content, roleplayMode)
    if (segments.length === 0) return

    setPlaying(true)

    audioPlayback.setCallbacks({
      onSegmentStart: () => {},
      onFinished: () => setPlaying(false),
    })

    for (const segment of segments) {
      const voice = segment.type === 'voice' ? dVoice : nVoice
      const audio = await tts.synthesise(segment.text, voice)
      audioPlayback.enqueue(audio, segment)
    }
  }, [content, dialogueVoice, narratorVoice, roleplayMode, playing])

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${
        playing
          ? 'text-gold'
          : 'text-white/25 hover:text-white/50'
      }`}
      title={playing ? 'Stop reading' : 'Read aloud'}
    >
      {playing ? (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
      )}
      {playing ? 'Stop' : 'Read'}
    </button>
  )
}
```

- [ ] **Step 2: Add ReadAloudButton to AssistantMessage**

In `frontend/src/features/chat/AssistantMessage.tsx`:

Add `voiceEnabled?: boolean` to `AssistantMessageProps` interface.

Add import: `import { ReadAloudButton } from '../voice/components/ReadAloudButton'`

Add `voiceEnabled` to the destructured props.

In the button row (line 109, inside `<div className="mt-2.5 flex gap-3 ...">`) add after the Bookmark button block (after the closing `)}` of the bookmark conditional, before the regenerate conditional):

```typescript
{voiceEnabled && (
  <ReadAloudButton content={effectiveContent} />
)}
```

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/components/ReadAloudButton.tsx frontend/src/features/chat/AssistantMessage.tsx
git commit -m "Add ReadAloudButton for per-message text-to-speech playback"
```

---

### Task 16: VoiceSettings

**Files:**
- Create: `frontend/src/features/voice/components/VoiceSettings.tsx`
- Modify: `frontend/src/app/components/user-modal/SettingsTab.tsx`

**Why:** Master toggle and voice preferences in the existing settings UI. Follows the exact same ButtonGroup + label pattern.

- [ ] **Step 1: Create VoiceSettings component**

Create `frontend/src/features/voice/components/VoiceSettings.tsx`:

```typescript
import { useVoiceSettings } from '../stores/voiceSettingsStore'
import { useVoiceCapabilities } from '../hooks/useVoiceCapabilities'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

export function VoiceSettings() {
  const { settings, update } = useVoiceSettings()
  const { supported, sttSupported, device } = useVoiceCapabilities()

  if (!supported) {
    return (
      <div>
        <label className={LABEL}>Voice Mode</label>
        <p className="text-[11px] text-white/40 font-mono leading-relaxed">
          Voice features are not available in this browser.
          WebGPU or WebAssembly support is required.
        </p>
      </div>
    )
  }

  return (
    <>
      <div>
        <label className={LABEL}>Voice Mode</label>
        <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
          Enable speech recognition and text-to-speech.
          All processing runs locally in your browser.
        </p>
        <button
          type="button"
          onClick={() => update({ enabled: !settings.enabled })}
          className={[
            'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            settings.enabled
              ? 'border-gold/60 bg-gold/12 text-gold'
              : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}
        >
          {settings.enabled ? 'On' : 'Off'}
        </button>
      </div>

      {settings.enabled && (
        <>
          <div>
            <label className={LABEL}>Input Mode</label>
            {!sttSupported && (
              <p className="text-[11px] text-amber-400/70 font-mono mb-2 leading-relaxed">
                Microphone access is not available. Text-to-speech still works.
              </p>
            )}
            {sttSupported && (
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() => update({ inputMode: 'push-to-talk' })}
                  className={[
                    'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
                    settings.inputMode === 'push-to-talk'
                      ? 'border-gold/60 bg-gold/12 text-gold'
                      : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
                  ].join(' ')}
                >
                  Push-to-Talk
                </button>
                <button
                  type="button"
                  onClick={() => update({ inputMode: 'continuous' })}
                  className={[
                    'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
                    settings.inputMode === 'continuous'
                      ? 'border-gold/60 bg-gold/12 text-gold'
                      : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
                  ].join(' ')}
                >
                  Continuous
                </button>
              </div>
            )}
          </div>

          <div>
            <label className={LABEL}>Runtime</label>
            <p className="text-[11px] text-white/40 font-mono leading-relaxed">
              Voice mode running on {device === 'webgpu' ? 'GPU (WebGPU)' : 'CPU (WASM)'}.
              {device === 'wasm' && ' Performance may be slower than GPU mode.'}
            </p>
          </div>
        </>
      )}
    </>
  )
}
```

- [ ] **Step 2: Add VoiceSettings to SettingsTab**

In `frontend/src/app/components/user-modal/SettingsTab.tsx`:

Add import: `import { VoiceSettings } from '../../../features/voice/components/VoiceSettings'`

Add at the end of the settings container div (after the Vibration section, before the closing `</div>` on what is currently line 152):

```typescript
<div className="border-t border-white/8 pt-6">
  <VoiceSettings />
</div>
```

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/components/VoiceSettings.tsx frontend/src/app/components/user-modal/SettingsTab.tsx
git commit -m "Add VoiceSettings with master toggle, input mode and runtime info"
```

---

### Task 17: PersonaVoiceConfig Tab

**Files:**
- Create: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

**Why:** Per-persona voice settings: dialogue voice, narrator voice, roleplay mode, auto-read. Appears as a new tab in the persona overlay, only when voice is globally enabled.

- [ ] **Step 1: Create PersonaVoiceConfig component**

Create `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`:

```typescript
import { useCallback, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { ChakraEntry } from '../../../core/types/chakra'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import type { VoicePreset } from '../types'

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

interface PersonaVoiceConfigProps {
  persona: PersonaDto
  chakra: ChakraEntry
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
}

export function PersonaVoiceConfig({ persona, chakra, onSave }: PersonaVoiceConfigProps) {
  const tts = ttsRegistry.active()
  const voices = tts?.voices ?? []

  const config = persona.voice_config ?? {
    dialogue_voice: null,
    narrator_voice: null,
    auto_read: false,
    roleplay_mode: false,
  }

  const [dialogueVoice, setDialogueVoice] = useState(config.dialogue_voice ?? '')
  const [narratorVoice, setNarratorVoice] = useState(config.narrator_voice ?? '')
  const [autoRead, setAutoRead] = useState(config.auto_read)
  const [roleplayMode, setRoleplayMode] = useState(config.roleplay_mode)
  const [previewing, setPreviewing] = useState(false)

  const save = useCallback(async (patch: Record<string, unknown>) => {
    const next = {
      dialogue_voice: dialogueVoice || null,
      narrator_voice: narratorVoice || null,
      auto_read: autoRead,
      roleplay_mode: roleplayMode,
      ...patch,
    }
    await onSave(persona.id, { voice_config: next })
  }, [persona.id, dialogueVoice, narratorVoice, autoRead, roleplayMode, onSave])

  const handlePreview = useCallback(async (voiceId: string) => {
    if (!tts || previewing) return
    const voice = voices.find((v: VoicePreset) => v.id === voiceId)
    if (!voice) return

    setPreviewing(true)
    const audio = await tts.synthesise('Hello! This is how I sound.', voice)
    audioPlayback.setCallbacks({
      onSegmentStart: () => {},
      onFinished: () => setPreviewing(false),
    })
    audioPlayback.enqueue(audio, { type: 'voice', text: 'preview' })
  }, [tts, voices, previewing])

  const inputBorder = `1px solid ${chakra.hex}26`
  const inputBorderFocus = `${chakra.hex}66`

  const selectStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.03)',
    border: inputBorder,
    borderRadius: 8,
    color: 'rgba(255,255,255,0.85)',
    fontSize: '13px',
    padding: '6px 10px',
    width: '100%',
    outline: 'none',
  }

  const toggleBase = 'relative inline-flex items-center h-[20px] w-[44px] rounded-full transition-colors cursor-pointer flex-shrink-0'

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl">
      {voices.length === 0 ? (
        <p className="text-[12px] text-white/50">
          Voice engines are not loaded yet. Enable voice mode in Settings and complete the setup first.
        </p>
      ) : (
        <>
          {/* Dialogue voice */}
          <div>
            <label className="block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono">
              Dialogue Voice
            </label>
            <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
              Voice used for spoken dialogue in quotes.
            </p>
            <div className="flex gap-2">
              <select
                value={dialogueVoice}
                onChange={(e) => { setDialogueVoice(e.target.value); save({ dialogue_voice: e.target.value || null }) }}
                style={selectStyle}
                onFocus={(e) => { e.currentTarget.style.borderColor = inputBorderFocus }}
                onBlur={(e) => { e.currentTarget.style.border = inputBorder }}
              >
                <option value="" style={OPTION_STYLE}>Default</option>
                {voices.map((v: VoicePreset) => (
                  <option key={v.id} value={v.id} style={OPTION_STYLE}>{v.name}</option>
                ))}
              </select>
              {dialogueVoice && (
                <button
                  type="button"
                  onClick={() => handlePreview(dialogueVoice)}
                  disabled={previewing}
                  className="flex-shrink-0 rounded-md border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-white/60 transition-colors hover:bg-white/10 disabled:opacity-30"
                >
                  Preview
                </button>
              )}
            </div>
          </div>

          {/* Narrator voice */}
          <div>
            <label className="block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono">
              Narrator Voice
            </label>
            <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
              Voice used for narration and action descriptions (text in *asterisks*).
            </p>
            <div className="flex gap-2">
              <select
                value={narratorVoice}
                onChange={(e) => { setNarratorVoice(e.target.value); save({ narrator_voice: e.target.value || null }) }}
                style={selectStyle}
                onFocus={(e) => { e.currentTarget.style.borderColor = inputBorderFocus }}
                onBlur={(e) => { e.currentTarget.style.border = inputBorder }}
              >
                <option value="" style={OPTION_STYLE}>Default</option>
                {voices.map((v: VoicePreset) => (
                  <option key={v.id} value={v.id} style={OPTION_STYLE}>{v.name}</option>
                ))}
              </select>
              {narratorVoice && (
                <button
                  type="button"
                  onClick={() => handlePreview(narratorVoice)}
                  disabled={previewing}
                  className="flex-shrink-0 rounded-md border border-white/10 bg-white/5 px-3 py-1 text-[11px] text-white/60 transition-colors hover:bg-white/10 disabled:opacity-30"
                >
                  Preview
                </button>
              )}
            </div>
          </div>

          {/* Roleplay mode toggle */}
          <div className="flex items-center justify-between">
            <div>
              <label className="block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-1 font-mono">
                Roleplay Mode
              </label>
              <p className="text-[11px] text-white/40 font-mono leading-relaxed">
                Split dialogue and narration into separate voices.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={roleplayMode}
              onClick={() => { setRoleplayMode(!roleplayMode); save({ roleplay_mode: !roleplayMode }) }}
              className={toggleBase}
              style={{ background: roleplayMode ? `${chakra.hex}cc` : 'rgba(255,255,255,0.12)' }}
            >
              <span
                className="absolute left-[2px] h-[16px] w-[16px] rounded-full bg-white transition-transform"
                style={{ transform: roleplayMode ? 'translateX(24px)' : 'translateX(0)' }}
              />
            </button>
          </div>

          {/* Auto-read toggle */}
          <div className="flex items-center justify-between">
            <div>
              <label className="block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-1 font-mono">
                Auto-Read Responses
              </label>
              <p className="text-[11px] text-white/40 font-mono leading-relaxed">
                Automatically read aloud every response from this persona.
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={autoRead}
              onClick={() => { setAutoRead(!autoRead); save({ auto_read: !autoRead }) }}
              className={toggleBase}
              style={{ background: autoRead ? `${chakra.hex}cc` : 'rgba(255,255,255,0.12)' }}
            >
              <span
                className="absolute left-[2px] h-[16px] w-[16px] rounded-full bg-white transition-transform"
                style={{ transform: autoRead ? 'translateX(24px)' : 'translateX(0)' }}
              />
            </button>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add voice tab to PersonaOverlay**

In `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`:

Add imports:
```typescript
import { useVoiceSettings } from '../../../features/voice/stores/voiceSettingsStore'
import { PersonaVoiceConfig } from '../../../features/voice/components/PersonaVoiceConfig'
```

Update the `PersonaOverlayTab` type to include `'voice'`:
```typescript
export type PersonaOverlayTab = 'overview' | 'edit' | 'knowledge' | 'memories' | 'history' | 'mcp' | 'integrations' | 'voice'
```

Add to `TABS` array (before `integrations`):
```typescript
{ id: 'voice', label: 'Voice', subtitle: 'sahasrara' },
```

Inside the `PersonaOverlay` function, add:
```typescript
const voiceEnabled = useVoiceSettings((s) => s.settings.enabled)
```

Update the tab filter (currently `.filter((tab) => !isCreating || tab.id === 'edit')`) to also hide voice when disabled:
```typescript
.filter((tab) => {
  if (isCreating && tab.id !== 'edit') return false
  if (tab.id === 'voice' && !voiceEnabled) return false
  return true
})
```

Add tab content rendering after the integrations block:
```typescript
{activeTab === 'voice' && !isCreating && (
  <PersonaVoiceConfig persona={resolved} chakra={chakra} onSave={onSave} />
)}
```

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/components/PersonaVoiceConfig.tsx frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Add PersonaVoiceConfig tab with voice selection, roleplay and auto-read toggles"
```

---

### Task 18: Ctrl+Space Keyboard Shortcut and Final Integration

**Files:**
- Create: `frontend/src/features/voice/hooks/useCtrlSpace.ts`
- Modify: `frontend/src/features/chat/ChatView.tsx` (wire everything together)

**Why:** Final integration: Ctrl+Space PTT shortcut, wiring the pipeline to ChatView, connecting VoiceButton props, and TranscriptionOverlay. This is the task that makes everything work together.

- [ ] **Step 1: Create useCtrlSpace hook**

Create `frontend/src/features/voice/hooks/useCtrlSpace.ts`:

```typescript
import { useEffect, useRef } from 'react'

const HOLD_THRESHOLD_MS = 300

interface UseCtrlSpaceOptions {
  enabled: boolean
  onHoldStart: () => void
  onHoldEnd: () => void
  onTap: () => void
}

export function useCtrlSpace({ enabled, onHoldStart, onHoldEnd, onTap }: UseCtrlSpaceOptions): void {
  const pressedAt = useRef<number | null>(null)
  const holdTriggered = useRef(false)

  useEffect(() => {
    if (!enabled) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.code !== 'Space' || !e.ctrlKey) return
      if (e.repeat) return
      e.preventDefault()

      pressedAt.current = Date.now()
      holdTriggered.current = false

      // Start hold after threshold
      setTimeout(() => {
        if (pressedAt.current !== null) {
          holdTriggered.current = true
          onHoldStart()
        }
      }, HOLD_THRESHOLD_MS)
    }

    function onKeyUp(e: KeyboardEvent) {
      if (e.code !== 'Space') return
      if (pressedAt.current === null) return

      e.preventDefault()

      if (holdTriggered.current) {
        onHoldEnd()
      } else {
        onTap()
      }

      pressedAt.current = null
      holdTriggered.current = false
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('keyup', onKeyUp)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('keyup', onKeyUp)
    }
  }, [enabled, onHoldStart, onHoldEnd, onTap])
}
```

- [ ] **Step 2: Wire voice into ChatView**

In `frontend/src/features/chat/ChatView.tsx`, add the voice integration. The exact changes depend on the current ChatView structure. Key additions:

Add imports at the top:
```typescript
import { useVoiceSettings } from '../voice/stores/voiceSettingsStore'
import { useVoicePipeline } from '../voice/stores/voicePipelineStore'
import { useCtrlSpace } from '../voice/hooks/useCtrlSpace'
import { voicePipeline } from '../voice/pipeline/voicePipeline'
import { TranscriptionOverlay } from '../voice/components/TranscriptionOverlay'
import { SetupModal } from '../voice/components/SetupModal'
import { sttRegistry } from '../voice/engines/registry'
```

Add state inside the ChatView component function:
```typescript
const voiceEnabled = useVoiceSettings((s) => s.settings.enabled)
const voiceInputMode = useVoiceSettings((s) => s.settings.inputMode)
const pipelineState = useVoicePipeline((s) => s.state)
const setPipelineState = useVoicePipeline((s) => s.setState)
const [transcription, setTranscription] = useState('')
const [showSetup, setShowSetup] = useState(false)
const [volumeLevel, setVolumeLevel] = useState(0)
```

Add voice pipeline effect (after other useEffect hooks):
```typescript
useEffect(() => {
  if (!voiceEnabled) return
  voicePipeline.setCallbacks({
    onStateChange: setPipelineState,
    onTranscription: (text) => {
      setTranscription(text)
      if (voiceInputMode === 'continuous' && text.trim()) {
        setTimeout(() => {
          // Use the existing send handler with the transcribed text
          handleSendMessage(text)
          setTranscription('')
        }, 800)
      }
    },
  })
  return () => voicePipeline.dispose()
}, [voiceEnabled, voiceInputMode])
```

Add mic handler callbacks:
```typescript
const handleMicPress = useCallback(() => {
  if (!sttRegistry.active()) {
    setShowSetup(true)
    return
  }
  voicePipeline.startRecording('push-to-talk')
}, [])

const handleMicRelease = useCallback(() => {
  voicePipeline.stopRecording()
}, [])

const handleStopVoice = useCallback(() => {
  voicePipeline.stopRecording()
  voicePipeline.stopPlayback()
}, [])

const handleToggleContinuous = useCallback(() => {
  if (pipelineState.phase === 'listening' || pipelineState.phase === 'recording') {
    voicePipeline.stopRecording()
  } else {
    if (!sttRegistry.active()) {
      setShowSetup(true)
      return
    }
    voicePipeline.startRecording('continuous')
  }
}, [pipelineState.phase])
```

Wire Ctrl+Space:
```typescript
useCtrlSpace({
  enabled: voiceEnabled,
  onHoldStart: handleMicPress,
  onHoldEnd: handleMicRelease,
  onTap: handleToggleContinuous,
})
```

Pass voice props to ChatInput (find the `<ChatInput` JSX element and add):
```typescript
voiceEnabled={voiceEnabled}
voicePhase={pipelineState.phase}
volumeLevel={volumeLevel}
onMicPress={handleMicPress}
onMicRelease={handleMicRelease}
onStopRecording={handleStopVoice}
```

Add TranscriptionOverlay above or inside the ChatInput toolbar area:
```typescript
{transcription && (
  <TranscriptionOverlay text={transcription} mode={voiceInputMode} />
)}
```

Add SetupModal (at the end of the component return, inside the outermost fragment):
```typescript
{showSetup && (
  <SetupModal
    onComplete={() => setShowSetup(false)}
    onCancel={() => setShowSetup(false)}
  />
)}
```

Pass `voiceEnabled` to AssistantMessage rendering — find where `<AssistantMessage` is rendered and add `voiceEnabled={voiceEnabled}`.

- [ ] **Step 3: Verify frontend compiles**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean

- [ ] **Step 4: Run all tests**

Run: `cd frontend && pnpm vitest run`

Expected: all tests pass

- [ ] **Step 5: Full build check**

Run: `cd frontend && pnpm run build`

Expected: clean build

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/hooks/useCtrlSpace.ts frontend/src/features/chat/ChatView.tsx
git commit -m "Wire voice pipeline into ChatView with Ctrl+Space shortcut and setup flow"
```

- [ ] **Step 7: Merge to master**

```bash
git checkout master && git merge <branch> && git push
```

---

## Dependency Graph

```
Task 1 (backend persistence)     -+
Task 2 (npm deps)                -+
Task 3 (types + stores + caps)   -+-- Foundation (independent)
Task 4 (AudioParser + tests)     -+

Task 5 (ModelManager)            -+
Task 6 (AudioCapture)            -+-- Infrastructure (needs Task 3 types)
Task 7 (AudioPlayback)           -+

Task 8 (Engine Registry)         --- Engine base (needs Task 3 types)

Task 9 (WhisperEngine)           -+-- Engines (needs Tasks 2, 5, 8)
Task 10 (KokoroEngine)           -+

Task 11 (VoicePipeline)          --- Orchestration (needs Tasks 4, 6, 7, 8)

Task 12 (SetupModal)             -+
Task 13 (VoiceButton + ChatInput)-+
Task 14 (TranscriptionOverlay)   -+-- UI (needs Tasks 3, 9, 10, 11)
Task 15 (ReadAloudButton)        -+
Task 16 (VoiceSettings)          -+
Task 17 (PersonaVoiceConfig)     -+

Task 18 (Ctrl+Space + wiring)    --- Final integration (needs all above)
```

**Parallelisable groups:**
- Tasks 1-4 are fully independent (4 parallel agents)
- Tasks 5-8 can run in parallel (4 parallel agents)
- Tasks 9-10 can run in parallel (2 parallel agents)
- Tasks 12-17 can mostly run in parallel (6 parallel agents)
- Task 11 must follow 4-8
- Task 18 must be last
