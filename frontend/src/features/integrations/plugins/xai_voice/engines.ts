import { transcribeXai, synthesiseXai } from './api'
import { xaiVoices } from './voices'
import { useIntegrationsStore } from '../../store'
import type { STTEngine, STTOptions, STTResult, TTSEngine, VoicePreset } from '../../../voice/types'

const INTEGRATION_ID = 'xai_voice'

function isIntegrationEnabled(): boolean {
  return useIntegrationsStore.getState().configs?.[INTEGRATION_ID]?.enabled === true
}

// Converts a Float32Array of PCM audio (mono, 16 kHz) to a WAV Blob
// suitable for sending to the STT proxy.
function float32ToWavBlob(samples: Float32Array, sampleRate = 16_000): Blob {
  const numSamples = samples.length
  const bytesPerSample = 2
  const dataLength = numSamples * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)
  const writeStr = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i))
  }
  const writeU32 = (off: number, v: number) => view.setUint32(off, v, true)
  const writeU16 = (off: number, v: number) => view.setUint16(off, v, true)
  writeStr(0, 'RIFF'); writeU32(4, 36 + dataLength); writeStr(8, 'WAVE')
  writeStr(12, 'fmt '); writeU32(16, 16); writeU16(20, 1); writeU16(22, 1)
  writeU32(24, sampleRate); writeU32(28, sampleRate * bytesPerSample)
  writeU16(32, bytesPerSample); writeU16(34, 16)
  writeStr(36, 'data'); writeU32(40, dataLength)
  let off = 44
  for (let i = 0; i < numSamples; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(off, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    off += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

async function decodeAudioToMono(blob: Blob): Promise<Float32Array> {
  const buf = await blob.arrayBuffer()
  const ctx = new OfflineAudioContext(1, 1, 24_000)
  const decoded = await ctx.decodeAudioData(buf)
  return decoded.getChannelData(0)
}

export class XaiSTTEngine implements STTEngine {
  readonly id = 'xai_stt'
  readonly name = 'xAI Speech-to-Text'
  readonly modelSize = 0
  readonly languages = ['en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'ru', 'zh', 'ja', 'ko']

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  async transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult> {
    const wav = float32ToWavBlob(audio)
    const text = await transcribeXai({ audio: wav, language: options?.language })
    return { text }
  }
}

export class XaiTTSEngine implements TTSEngine {
  readonly id = 'xai_tts'
  readonly name = 'xAI Text-to-Speech'
  readonly modelSize = 0

  get voices(): VoicePreset[] { return xaiVoices.current }

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  // Override hook for tests (OfflineAudioContext is not available in jsdom).
  private _decode = decodeAudioToMono

  async synthesise(_text: string, _voice: VoicePreset): Promise<Float32Array> {
    const blob = await synthesiseXai({ text: _text, voiceId: _voice.id })
    return this._decode(blob)
  }
}
