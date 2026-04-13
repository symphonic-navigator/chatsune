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
    // q4f16 may not work on all WASM runtimes; fp32 is safest fallback
    const dtype = device === 'webgpu' ? 'fp32' : 'fp32'
    this.tts = await KokoroTTS.from_pretrained(
      'onnx-community/Kokoro-82M-v1.0-ONNX',
      { dtype },
    )
    await modelManager.markDownloaded('kokoro-tts')
  }

  async synthesise(text: string, voice: VoicePreset): Promise<Float32Array> {
    if (!this.tts) throw new Error('KokoroEngine not initialised')
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const result = await this.tts.generate(text, { voice: voice.id as any })
    return result.audio as unknown as Float32Array
  }

  async dispose(): Promise<void> { this.tts = null }
  isReady(): boolean { return this.tts !== null }
}

export const kokoroEngine = new KokoroEngineImpl()
