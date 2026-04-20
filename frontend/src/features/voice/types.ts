/* -- Engine interfaces -- */
export interface STTOptions { language?: string }
export interface STTResult { text: string; language?: string; segments?: TranscriptSegment[] }
export interface TranscriptSegment { start: number; end: number; text: string }

/**
 * A captured audio utterance, ready for hand-off to an STT engine.
 *
 * Cloud STT engines upload `blob` directly (saves ~10x bytes over WAV for
 * webm/opus, ~5x for mp4/aac). Engines that still need raw PCM (future local
 * STT, debug paths) can fall back to `pcm`.
 *
 * `mimeType === 'audio/wav'` indicates the Tier-3 fallback path where no
 * MediaRecorder was available — the blob was derived from the PCM via
 * `float32ToWavBlob`. Downstream code should treat all three MIME types as
 * equivalent uploads; only the bytes-on-the-wire differ.
 */
export interface CapturedAudio {
  pcm: Float32Array
  blob: Blob
  mimeType: string
  sampleRate: number
  durationMs: number
}

export interface STTEngine {
  readonly id: string; readonly name: string; readonly modelSize: number; readonly languages: string[]
  init(): Promise<void>
  transcribe(audio: CapturedAudio, options?: STTOptions): Promise<STTResult>
  dispose(): Promise<void>
  isReady(): boolean
}
export interface VoicePreset { id: string; name: string; language: string; gender?: 'male' | 'female' | 'neutral'; preview?: string }
export interface TTSEngine {
  readonly id: string; readonly name: string; readonly modelSize: number; readonly voices: VoicePreset[]
  init(): Promise<void>
  synthesise(text: string, voice: VoicePreset): Promise<Float32Array>
  dispose(): Promise<void>
  isReady(): boolean
}
export interface EngineRegistry<T extends STTEngine | TTSEngine> {
  register(engine: T): void; get(id: string): T | undefined; list(): T[]
}
export interface SpeechSegment {
  type: 'voice' | 'narration'
  text: string
  speed?: number   // default 1.0 at playback
  pitch?: number   // semitones; default 0
}
export type PipelinePhase = 'idle' | 'listening' | 'recording' | 'transcribing' | 'waiting-for-llm' | 'speaking'
export interface PipelineState { phase: PipelinePhase; segment?: number; total?: number }
export interface VoiceCapabilities { getUserMedia: boolean; webgpu: boolean; wasm: boolean; cacheStorage: boolean }
export interface ModelInfo { id: string; label: string; size: number; downloaded: boolean }
export type NarratorMode = 'off' | 'play' | 'narrate'
