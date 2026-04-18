import { transcribe as apiTranscribe, synthesise as apiSynthesise } from './api'
import { mistralVoices } from './voices'
import { useSecretsStore } from '../../secretsStore'
import type { STTEngine, STTOptions, STTResult, TTSEngine, VoicePreset } from '../../../voice/types'

const INTEGRATION_ID = 'mistral_voice'
const API_KEY_FIELD = 'api_key'

function getApiKey(): string | undefined {
  return useSecretsStore.getState().getSecret(INTEGRATION_ID, API_KEY_FIELD)
}

// Converts a Float32Array of PCM audio (mono, 16 kHz) to a WAV Blob
// suitable for sending to the Mistral transcription API.
function float32ToWavBlob(samples: Float32Array, sampleRate = 16_000): Blob {
  const numSamples = samples.length
  const bytesPerSample = 2 // 16-bit PCM
  const dataLength = numSamples * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)

  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }
  const writeU32 = (offset: number, v: number) => view.setUint32(offset, v, true)
  const writeU16 = (offset: number, v: number) => view.setUint16(offset, v, true)

  writeStr(0, 'RIFF')
  writeU32(4, 36 + dataLength)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  writeU32(16, 16)                          // PCM chunk size
  writeU16(20, 1)                            // PCM format
  writeU16(22, 1)                            // mono
  writeU32(24, sampleRate)
  writeU32(28, sampleRate * bytesPerSample)  // byte rate
  writeU16(32, bytesPerSample)               // block align
  writeU16(34, 16)                           // bits per sample
  writeStr(36, 'data')
  writeU32(40, dataLength)

  let offset = 44
  for (let i = 0; i < numSamples; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
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
    return !!getApiKey()
  }

  async transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult> {
    const key = getApiKey()
    if (!key) throw new Error('Mistral API key not configured')

    const wavBlob = float32ToWavBlob(audio)
    const text = await apiTranscribe({ apiKey: key, audio: wavBlob, language: options?.language })
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
    return !!getApiKey()
  }

  async synthesise(text: string, voice: VoicePreset): Promise<Float32Array> {
    const key = getApiKey()
    if (!key) throw new Error('Mistral API key not configured')

    const blob = await apiSynthesise({ apiKey: key, text, voiceId: voice.id })
    // Diagnostic log — pair with [TTS-http] lines in api.ts. Remove with them.
    const preview = text.slice(0, 40).replace(/\s+/g, ' ')
    const decodeStart = performance.now()
    const pcm = await blobToFloat32(blob)
    console.log(`[TTS-decode] done "${preview}" ${Math.round(performance.now() - decodeStart)}ms`)
    return pcm
  }
}
