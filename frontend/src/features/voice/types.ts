/* -- Engine interfaces -- */
export interface STTOptions { language?: string }
export interface STTResult { text: string; language?: string; segments?: TranscriptSegment[] }
export interface TranscriptSegment { start: number; end: number; text: string }
export interface STTEngine {
  readonly id: string; readonly name: string; readonly modelSize: number; readonly languages: string[]
  init(): Promise<void>
  transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult>
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
  active(): T | undefined; setActive(id: string): Promise<void>
}
export interface SpeechSegment { type: 'voice' | 'narration'; text: string }
export type PipelinePhase = 'idle' | 'listening' | 'recording' | 'transcribing' | 'waiting-for-llm' | 'speaking'
export interface PipelineState { phase: PipelinePhase; segment?: number; total?: number }
export interface VoiceSettings { enabled: boolean; inputMode: 'push-to-talk' | 'continuous' }
export interface VoiceCapabilities { getUserMedia: boolean; webgpu: boolean; wasm: boolean; cacheStorage: boolean }
export interface ModelInfo { id: string; label: string; size: number; downloaded: boolean }
