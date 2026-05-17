import { transcribeNanoGptXai, synthesiseNanoGptXai } from './api'
import { nanoGptXaiVoices } from './voices'
import { useIntegrationsStore } from '../../store'
import type {
  CapturedAudio,
  STTEngine,
  STTOptions,
  STTResult,
  TTSEngine,
  VoicePreset,
} from '../../../voice/types'

const INTEGRATION_ID = 'nano_gpt_voice_xai'

function isIntegrationEnabled(): boolean {
  return useIntegrationsStore.getState().configs?.[INTEGRATION_ID]
    ?.effective_enabled === true
}

async function decodeAudioToMono(blob: Blob): Promise<Float32Array> {
  const buf = await blob.arrayBuffer()
  const ctx = new OfflineAudioContext(1, 1, 24_000)
  const decoded = await ctx.decodeAudioData(buf)
  return decoded.getChannelData(0)
}

export class NanoGptXaiSTTEngine implements STTEngine {
  readonly id = 'nano_gpt_voice_xai_stt'
  readonly name = 'xAI Speech-to-Text via nano-gpt'
  readonly modelSize = 0
  readonly languages = [
    'en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'ru', 'zh', 'ja', 'ko',
  ]

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  async transcribe(audio: CapturedAudio, options?: STTOptions): Promise<STTResult> {
    const text = await transcribeNanoGptXai({
      audio: audio.blob,
      mimeType: audio.mimeType,
      language: options?.language,
    })
    return { text }
  }
}

export class NanoGptXaiTTSEngine implements TTSEngine {
  readonly id = 'nano_gpt_voice_xai_tts'
  readonly name = 'xAI Text-to-Speech via nano-gpt'
  readonly modelSize = 0

  get voices(): VoicePreset[] { return nanoGptXaiVoices.current }

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  // Override hook for tests (OfflineAudioContext is not available in jsdom).
  private _decode = decodeAudioToMono

  async synthesise(_text: string, _voice: VoicePreset): Promise<Float32Array> {
    const blob = await synthesiseNanoGptXai({ text: _text, voiceId: _voice.id })
    return this._decode(blob)
  }
}
