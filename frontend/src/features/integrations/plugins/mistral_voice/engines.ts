import { transcribe as apiTranscribe, synthesise as apiSynthesise } from './api'
import { mistralVoices } from './voices'
import { useIntegrationsStore } from '../../store'
import type { CapturedAudio, STTEngine, STTOptions, STTResult, TTSEngine, VoicePreset } from '../../../voice/types'

const INTEGRATION_ID = 'mistral_voice'

function isIntegrationEnabled(): boolean {
  return useIntegrationsStore.getState().configs?.[INTEGRATION_ID]?.enabled === true
}

// Decodes an audio Blob (MP3) to a mono Float32Array via the browser's
// Web Audio API for handoff to the existing AudioContext-based playback pipeline.
async function blobToFloat32(blob: Blob): Promise<Float32Array> {
  const arrayBuffer = await blob.arrayBuffer()
  const ctx = new OfflineAudioContext(1, 1, 24_000)
  const decoded = await ctx.decodeAudioData(arrayBuffer)
  // Mix down to mono if necessary
  return decoded.getChannelData(0)
}

export class MistralSTTEngine implements STTEngine {
  readonly id = 'mistral_stt'
  readonly name = 'Mistral Voxtral'
  readonly modelSize = 0
  readonly languages = ['en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'ru', 'zh', 'ja', 'ko']

  async init(): Promise<void> { /* no-op — cloud API, no local model to load */ }
  async dispose(): Promise<void> { /* no-op */ }

  isReady(): boolean {
    return isIntegrationEnabled()
  }

  async transcribe(audio: CapturedAudio, options?: STTOptions): Promise<STTResult> {
    const text = await apiTranscribe({
      audio: audio.blob,
      mimeType: audio.mimeType,
      language: options?.language,
    })
    return { text }
  }
}

export class MistralTTSEngine implements TTSEngine {
  readonly id = 'mistral_tts'
  readonly name = 'Mistral Voice'
  readonly modelSize = 0

  get voices(): VoicePreset[] {
    return mistralVoices.current
  }

  async init(): Promise<void> { /* no-op — cloud API, no local model to load */ }
  async dispose(): Promise<void> { /* no-op */ }

  isReady(): boolean {
    return isIntegrationEnabled()
  }

  // Override hook for tests (OfflineAudioContext is not available in jsdom).
  private _decode = blobToFloat32

  async synthesise(text: string, voice: VoicePreset): Promise<Float32Array> {
    const blob = await apiSynthesise({ text, voiceId: voice.id })
    // Diagnostic log — pair with [TTS-http] lines in api.ts. Remove with them.
    const preview = text.slice(0, 40).replace(/\s+/g, ' ')
    const decodeStart = performance.now()
    const pcm = await this._decode(blob)
    console.log(`[TTS-decode] done "${preview}" ${Math.round(performance.now() - decodeStart)}ms`)
    return pcm
  }
}
