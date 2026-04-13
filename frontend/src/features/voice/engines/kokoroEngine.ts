import type { TTSEngine, VoicePreset } from '../types'
import { voiceWorker } from '../workers/voiceWorkerClient'
import { modelManager } from '../infrastructure/modelManager'

/**
 * Kokoro TTS engine — delegates to Web Worker for inference.
 * All heavy WASM computation runs off the main thread.
 */
class KokoroEngineImpl implements TTSEngine {
  readonly id = 'kokoro'
  readonly name = 'Kokoro'
  readonly modelSize = 40_000_000
  voices: VoicePreset[] = []

  private ready = false

  async init(device: 'webgpu' | 'wasm'): Promise<void> {
    const voices = await voiceWorker.initTTS(device)
    this.voices = voices as VoicePreset[]
    await modelManager.markDownloaded('kokoro-tts')
    this.ready = true
  }

  async synthesise(text: string, voice: VoicePreset): Promise<Float32Array> {
    if (!this.ready) throw new Error('KokoroEngine not initialised')
    return voiceWorker.synthesise(text, voice.id)
  }

  async dispose(): Promise<void> { this.ready = false }
  isReady(): boolean { return this.ready }
}

export const kokoroEngine = new KokoroEngineImpl()
