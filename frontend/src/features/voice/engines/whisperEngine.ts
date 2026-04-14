import type { STTEngine, STTOptions, STTResult } from '../types'
import { voiceWorker } from '../workers/voiceWorkerClient'
import { modelManager } from '../infrastructure/modelManager'

/**
 * Whisper STT engine — delegates to Web Worker for inference.
 * All heavy WASM computation runs off the main thread.
 */
class WhisperEngineImpl implements STTEngine {
  readonly id = 'whisper-tiny'
  readonly name = 'Whisper Tiny'
  readonly modelSize = 31_000_000
  readonly languages = ['en']

  private ready = false

  async init(): Promise<void> {
    const { resolved } = await voiceWorker.initSTT()
    console.log('[voice] stt ready: %s/%s (fromCache=%s)', resolved.device, resolved.dtype, resolved.fromCache)
    await modelManager.markDownloaded('whisper-tiny')
    this.ready = true
  }

  async transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult> {
    if (!this.ready) throw new Error('WhisperEngine not initialised')
    const result = await voiceWorker.transcribe(audio, options?.language)
    return {
      text: result.text,
      language: result.language,
    }
  }

  async dispose(): Promise<void> { this.ready = false }
  isReady(): boolean { return this.ready }
}

export const whisperEngine = new WhisperEngineImpl()
