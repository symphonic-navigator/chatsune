# Chatsune Voice Mode — Design Spec

## Overview

Voice capabilities for Chatsune, a persona-oriented LLM chat client in React/TSX.
All speech processing runs client-side in the browser (WebGPU with WASM fallback).
No voice data is sent to third-party services.

### Three Independent Features

- **Transcription Mode**: STT only. User dictates, text appears in the input field.
- **Read Aloud**: TTS only. Any LLM response can be read aloud on demand or automatically.
- **Voice Mode**: STT + TTS combined. Full spoken conversation.

Each feature is independently toggleable. Engines are loaded lazily — only when needed.

### Scope v1

- English only (Whisper tiny + Kokoro)
- Architecture is multilingual-ready and engine-pluggable
- Disclaimer: "Chatsune is English only for now in voice mode, this is a principal limitation of currently available technology"

## Architecture

Four layers with strict top-down dependency:

```
┌─────────────────────────────────────────────────┐
│  UI Layer                                       │
│  VoiceButton, TranscriptionOverlay,             │
│  ReadAloudButton, VoiceSettings,                │
│  PersonaVoiceConfig, SetupModal                 │
├─────────────────────────────────────────────────┤
│  Orchestration Layer                            │
│  VoicePipeline (coordinates STT/TTS/Playback)   │
│  AudioParser (separates dialogue / narration)   │
├─────────────────────────────────────────────────┤
│  Engine Layer                                   │
│  STTRegistry          TTSRegistry               │
│  ├─ WhisperEngine     ├─ KokoroEngine           │
│  └─ (future engines)  └─ (future engines)       │
├─────────────────────────────────────────────────┤
│  Infrastructure Layer                           │
│  ModelManager (download, cache, device detect)  │
│  AudioCapture (getUserMedia, VAD, echo cancel)  │
│  AudioPlayback (segment queue, interrupt)       │
└─────────────────────────────────────────────────┘
```

No upward dependencies. UI knows only the Pipeline. Pipeline knows the Registries.
Registries know the Engines. Engines use Infrastructure.

Integration with Chatsune: The voice layer wraps input and output of the existing
chat flow. The LLM call itself remains unchanged. Messages appear in the chat
history as normal text.

## Global Voice Toggle

Voice features are gated behind a per-user toggle in the settings UI.
This toggle is stored client-side in `voiceSettingsStore` (localStorage).

**When disabled (default):**
- No microphone button appears in the chat input
- No read-aloud button appears on messages
- No "Voice" tab in persona configuration
- No voice-related settings visible
- Zero impact on existing UI — as if voice mode does not exist

**When enabled:**
- Microphone button replaces send button when text field is empty
- Read-aloud buttons appear on assistant messages (on hover)
- "Voice" tab appears in persona overlay
- Voice settings section appears in settings

The toggle is per-user, not admin-controlled. Since all processing is
client-side, there is no server-side resource implication.

## Browser Capability Detection

At app startup (if voice is enabled), detect browser support:

```typescript
interface VoiceCapabilities {
  getUserMedia: boolean;        // navigator.mediaDevices.getUserMedia
  webgpu: boolean;              // navigator.gpu
  wasm: boolean;                // WebAssembly.validate
  cacheStorage: boolean;        // caches (for model storage)
}
```

**Behaviour:**
- If `getUserMedia` is unavailable: hide all STT/Voice Mode features, TTS-only still works
- If neither `webgpu` nor `wasm`: hide all voice features, show toast explaining why
- If `cacheStorage` unavailable: hide all voice features (cannot store models)
- Toast message: "Voice features are not available in this browser. WebGPU or WebAssembly support is required."

No voice UI elements are rendered if the browser cannot support them.

## First-Use Setup Modal

On first activation of any voice feature, a setup modal appears
showing model download progress:

```
┌─ Voice Mode Setup ───────────────────────┐
│                                          │
│  The following models will be downloaded  │
│  and stored locally in your browser:     │
│                                          │
│  [====····] Speech Recognition    31 MB  │
│  [========] Voice Detection        1 MB  │  ← done
│  [········] Speech Synthesis      40 MB  │  ← waiting
│                                          │
│  Total: ~73 MB                           │
│  Runtime: WebGPU / CPU (WASM)            │
│                                          │
│             [Cancel]                     │
└──────────────────────────────────────────┘
```

User-facing labels (not technical names):
- "Speech Recognition" (Whisper tiny)
- "Voice Detection" (Silero VAD)
- "Speech Synthesis" (Kokoro)

Downloads are sequential. The modal closes automatically when all
downloads complete. The user can cancel at any time — partial downloads
are cleaned up.

After initial setup, models are loaded from Cache Storage on subsequent
uses — no network required.

## Engine Interfaces

### STTEngine

```typescript
interface STTEngine {
  readonly id: string;              // "whisper-tiny", "whisper-turbo", ...
  readonly name: string;            // Display name for settings
  readonly modelSize: number;       // Bytes, for UI display
  readonly languages: string[];     // ["en"], ["en","de","fr",...]

  init(device: "webgpu" | "wasm"): Promise<void>;
  transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult>;
  dispose(): Promise<void>;
  isReady(): boolean;
}

interface STTOptions {
  language?: string;                // Force language, or auto-detect
}

interface STTResult {
  text: string;
  language?: string;                // Detected language
  segments?: TranscriptSegment[];   // Timestamped segments
}

interface TranscriptSegment {
  start: number;                    // Seconds
  end: number;
  text: string;
}
```

### TTSEngine

```typescript
interface TTSEngine {
  readonly id: string;              // "kokoro", "piper-de", ...
  readonly name: string;
  readonly modelSize: number;
  readonly voices: VoicePreset[];

  init(device: "webgpu" | "wasm"): Promise<void>;
  synthesise(text: string, voice: VoicePreset): Promise<Float32Array>;
  dispose(): Promise<void>;
  isReady(): boolean;
}

interface VoicePreset {
  id: string;                       // "af_heart", "am_adam", ...
  name: string;                     // Display name
  language: string;
  gender?: "male" | "female" | "neutral";
  preview?: string;                 // URL to sample audio
}
```

### Engine Registry

```typescript
interface EngineRegistry<T extends STTEngine | TTSEngine> {
  register(engine: T): void;
  get(id: string): T | undefined;
  list(): T[];
  active(): T | undefined;           // Currently loaded engine
  setActive(id: string): Promise<void>;  // Load & switch
}
```

Registries are singletons in the frontend, following the same pattern as
backend registries for tools and inference providers.

## AudioParser — Voice/Narrator Separation

### Segment Types

```typescript
interface SpeechSegment {
  type: "voice" | "narration";
  text: string;
}

function parseRoleplayOutput(text: string): SpeechSegment[];
```

### Parsing Rules

**Roleplay mode active:**
- Text in `"quotation marks"` → `voice`
- Text in `*asterisks*` → `narration`
- Unmarked text → `narration` (default, as action descriptions are often unmarked)

**Roleplay mode inactive:**
- Everything → `voice`

### Pre-Processing (before parsing)

Before splitting into segments, the raw text is cleaned for TTS:

1. **Code blocks** (`` ``` ... ``` ``) → stripped entirely (not spoken)
2. **Inline code** (`` `code` ``) → stripped (not spoken)
3. **Markdown formatting** → stripped to plain text:
   - `**bold**` / `*italic*` → text only (after roleplay parsing, so `*action*` is handled first)
   - `# headings` → text only
   - `[link text](url)` → "link text" only
   - `> blockquotes` → text only
4. **OOC markers** (`(( text ))`) → stripped (not spoken)
5. **Lists** (`- item` / `1. item`) → spoken as plain text without markers
6. **URLs** → stripped (not spoken)

Order: code blocks → OOC → roleplay parse → markdown strip → TTS

### Example

Input:
```
*walks over to the fridge* "Want something to drink?" *opens the door and peers inside*
```

Output:
```typescript
[
  { type: "narration", text: "walks over to the fridge" },
  { type: "voice",     text: "Want something to drink?" },
  { type: "narration", text: "opens the door and peers inside" }
]
```

### Synthesis Flow

Each segment is synthesised with the persona's assigned voice:
- `narration` segments → `persona.voice_config.narrator_voice`
- `voice` segments → `persona.voice_config.dialogue_voice`

Segments are synthesised sentence-by-sentence and enqueued for playback.
Playback begins as soon as the first segment is ready; remaining segments
are prepared in parallel.

## Voice Pipeline

### Interface

```typescript
interface VoicePipeline {
  start(mode: "push-to-talk" | "continuous"): void;
  stop(): void;

  // Playback control
  stopPlayback(): void;             // Cancel everything, clear queue
  skipSegment(): void;              // Skip current segment, play next

  // State
  state: PipelineState;
  onStateChange: (state: PipelineState) => void;
}

type PipelineState =
  | { phase: "idle" }
  | { phase: "listening" }          // Mic open, waiting for speech
  | { phase: "recording" }          // VAD detected speech
  | { phase: "transcribing" }       // Whisper working
  | { phase: "waiting-for-llm" }    // Text sent, waiting for response
  | { phase: "speaking"; segment: number; total: number };
```

### Push-to-Talk Flow

1. User presses Ctrl+Space (or taps mic button) → mic on, state: `recording`
2. User releases → mic off, state: `transcribing`
3. Whisper transcribes → text appears in input field
4. User can edit, then sends
5. LLM responds → state: `speaking`
6. AudioParser segments, TTS synthesises, queue plays
7. Finished → state: `idle`

### Continuous Listening Flow

1. User activates mode → mic on, state: `listening`
2. VAD detects speech → state: `recording`
3. VAD detects silence (~1.5s) → state: `transcribing`
4. Whisper transcribes → text briefly shown, then auto-sent
5. LLM responds → TTS playback
6. Finished → back to `listening`

### Interrupt Behaviour

| Trigger | Action |
|---|---|
| Stop button / Escape | `stopPlayback()` — immediate silence, queue cleared |
| Skip button | `skipSegment()` — jump to next segment |
| User speaks (VAD, continuous mode) | `stopPlayback()` + start new recording |
| User starts typing | `stopPlayback()` — switch to text input |

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Space` (hold) | Push-to-talk: record while held, transcribe on release |
| `Ctrl+Space` (tap) | Toggle continuous listening mode |
| `Escape` | Stop all playback, cancel recording |

Hold vs. tap detection: If Ctrl+Space is held for >300ms, treat as PTT.
If released within 300ms, toggle continuous mode.

## Infrastructure Layer

### ModelManager

```typescript
interface ModelManager {
  download(modelId: string, onProgress: (pct: number) => void): Promise<void>;
  isDownloaded(modelId: string): boolean;
  delete(modelId: string): Promise<void>;
  getStorageUsage(): Promise<{ used: number; models: ModelInfo[] }>;
  detectDevice(): "webgpu" | "wasm";
}
```

- Models stored in **Cache Storage** (browser API) — persistent across sessions
- First use: download with progress indicator via setup modal
- Subsequent uses: loaded from cache, no network required
- `detectDevice()` checks WebGPU availability once at startup

### AudioCapture

```typescript
interface AudioCapture {
  start(): Promise<void>;
  stop(): void;
  onSpeechStart: () => void;                      // VAD callback
  onSpeechEnd: (audio: Float32Array) => void;      // Complete audio segment
  onVolumeChange: (level: number) => void;         // For UI visualisation
}
```

- Uses `getUserMedia` + `AudioWorklet` for recording
- **Echo cancellation enabled** via `getUserMedia` constraints:
  ```typescript
  { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }
  ```
- Silero VAD (~1.5 MB) runs in the AudioWorklet
- `onVolumeChange` provides data for a simple level meter in the UI
- Only one tab may hold the microphone at a time (browser-enforced via
  `getUserMedia` — second tab gets a permission prompt or error)

### AudioPlayback

```typescript
interface AudioPlayback {
  enqueue(audio: Float32Array, segment: SpeechSegment): void;
  play(): void;
  stopAll(): void;
  skipCurrent(): void;
  onSegmentStart: (segment: SpeechSegment) => void;  // For UI highlighting
  onFinished: () => void;
}
```

- Internal queue of audio segments
- `onSegmentStart` allows the UI to highlight the currently spoken text
- Seamless playback between segments

### WebGPU/WASM Strategy

```
App start
  → detectDevice()
  → WebGPU available?
       yes → initialise all engines with "webgpu"
       no  → WASM available?
              yes → initialise all engines with "wasm"
              no  → disable voice features, show toast
  → User sees: "Voice mode running on GPU" / "...on CPU (slower)"
```

Single detection at startup, no runtime switching, no mixed mode.

## UI Components

### VoiceButton (Unified Action Button)

The send button in the chat input area serves four states — no additional
buttons are added to the input bar:

```
Text field empty + voice enabled:  [🎤 Mic]     → tap to start recording
Text field has content:            [➤ Send]     → tap to send message
LLM streaming:                     [⬛ Cancel]   → tap to cancel response
Recording (PTT):                   [⏹ Stop]     → tap to stop recording
```

**Visual states during voice activity:**
- **Idle** (mic icon): default styling, matches existing button pattern
- **Recording**: pulsing animation + level meter (from `onVolumeChange`),
  persona's chakra colour as glow
- **Transcribing**: spinner/loading indicator
- **Speaking**: waveform or speaker icon

The button uses the same `h-9 w-9` sizing and styling as the existing
send/cancel buttons for visual consistency.

### ReadAloudButton

A small speaker icon on each assistant message, visible on hover.
Only rendered when voice features are globally enabled.

- Appears in the message header area (near timestamp/bookmark controls)
- Click: synthesise and play the entire message via AudioParser + TTS
- While playing: icon changes to a stop icon, click to stop
- Uses the persona's configured dialogue/narrator voices

### TranscriptionOverlay

Appears in/near the chat input field.
- Shows transcribed text before sending
- Push-to-talk: user can edit before sending
- Continuous: briefly displayed, then auto-sent

### VoiceSettings

Integrated into Chatsune's existing settings system (SettingsTab).

- **Master toggle**: Enable/disable voice features (default: off)
- STT engine selection (v1: Whisper tiny only)
- TTS engine selection (v1: Kokoro only)
- Input mode preference: push-to-talk vs. continuous
- Default on mobile: continuous (PTT via touch is ergonomically poor)
- Model management: download status, storage usage, delete
- Device info: "Running on WebGPU" / "Running on CPU (WASM)"

### PersonaVoiceConfig

Per-persona settings within persona configuration overlay.
Only visible when voice features are globally enabled.

- **Dialogue voice**: dropdown from `TTSEngine.voices`
- **Narrator voice**: dropdown from `TTSEngine.voices`
- **Roleplay mode**: toggle (enables voice/narration splitting)
- **Preview button**: play a short sample with selected voice
- **Auto-read**: toggle to automatically read aloud responses for this persona

## Backend Persistence — PersonaDto Extension

Voice configuration is persisted per persona in the backend.
New optional field on `PersonaDto`:

```typescript
// Frontend type
voice_config: {
  dialogue_voice: string | null;    // Voice preset ID, e.g. "af_heart"
  narrator_voice: string | null;    // Voice preset ID, e.g. "am_adam"
  auto_read: boolean;               // Auto TTS for responses
  roleplay_mode: boolean;           // Enable voice/narration split
} | null;
```

```python
# Backend Pydantic model
class VoiceConfig(BaseModel):
    dialogue_voice: str | None = None
    narrator_voice: str | None = None
    auto_read: bool = False
    roleplay_mode: bool = False
```

`voice_config: null` = voice never configured for this persona (default).

**Future-proofing:** Engine-specific settings (which STT model, quantisation
level, etc.) will remain client-side when they become relevant. The backend
only stores semantic configuration (which voice, behaviour toggles) — not
engine internals. This keeps the backend stable as engines are added/removed.

Files to update:
- `shared/dtos/persona.py` — add `voice_config` field to DTO
- `frontend/src/core/types/persona.ts` — add `voice_config` to `PersonaDto`
- `backend/modules/persona/_models.py` — add `VoiceConfig` to document model
- `backend/modules/persona/_repository.py` — handle new field in CRUD

## Technology Stack (v1)

| Component | Technology | Size |
|---|---|---|
| STT | Whisper tiny via Transformers.js v4 | ~31 MB (q5) |
| TTS | Kokoro via kokoro-js | ~40 MB (q4f16) |
| VAD | Silero VAD | ~1.5 MB |
| Runtime | ONNX Runtime Web (WebGPU + WASM) | bundled |
| Total model download | | ~73 MB |

## Privacy

- All STT/TTS processing runs entirely client-side
- No voice data is sent to Apple, Google, or any other third party
- Audio data is processed in memory and never persisted
- Only the transcribed text leaves the browser (to the configured LLM provider)
- Trusted LLM providers: ollama (local), nano-gpt.com, openrouter

## Future Expansion

The pluggable architecture supports:
- Additional STT engines (Whisper turbo for multilingual, future distil-whisper variants)
- Additional TTS engines (Piper for German, future multilingual models)
- Per-engine language support, exposed in the UI
- Model size options per engine (tiny/base/small/turbo)
- Client-side storage of engine-specific configuration (model variant, quantisation)

No code changes needed to add engines — only new `STTEngine`/`TTSEngine`
implementations registered with the respective registry.
