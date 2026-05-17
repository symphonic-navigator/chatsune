import { describe, it, expect, vi, beforeEach } from 'vitest'
import { NanoGptXaiSTTEngine, NanoGptXaiTTSEngine } from '../engines'
import type { CapturedAudio } from '../../../../voice/types'

vi.mock('../api', () => ({
  transcribeNanoGptXai: vi.fn(),
  synthesiseNanoGptXai: vi.fn(),
  listNanoGptXaiVoices: vi.fn(),
  toVoicePreset: (v: { id: string; name: string }) => ({
    id: v.id, name: v.name, language: 'en',
  }),
}))

// Path: from __tests__/ it's one deeper than from engines.ts
vi.mock('../../../store', () => ({
  useIntegrationsStore: {
    getState: () => ({ configs: { nano_gpt_voice_xai: { enabled: true, effective_enabled: true } } }),
  },
}))

import { transcribeNanoGptXai, synthesiseNanoGptXai } from '../api'

function fakeBundle(): CapturedAudio {
  return {
    pcm: new Float32Array([0.1, -0.2, 0.3]),
    blob: new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm;codecs=opus' }),
    mimeType: 'audio/webm;codecs=opus',
    sampleRate: 0,
    durationMs: 500,
  }
}

describe('NanoGptXaiSTTEngine', () => {
  beforeEach(() => vi.clearAllMocks())

  it('transcribe forwards the captured blob + mimeType to transcribeNanoGptXai', async () => {
    ;(transcribeNanoGptXai as ReturnType<typeof vi.fn>).mockResolvedValueOnce('hello')
    const engine = new NanoGptXaiSTTEngine()
    const res = await engine.transcribe(fakeBundle())
    expect(res.text).toBe('hello')
    const args = (transcribeNanoGptXai as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      audio: Blob
      mimeType: string
    }
    expect(args.audio).toBeInstanceOf(Blob)
    expect(args.mimeType).toBe('audio/webm;codecs=opus')
  })

  it('isReady reflects integration store state for nano-gpt xAI STT', () => {
    const engine = new NanoGptXaiSTTEngine()
    expect(engine.isReady()).toBe(true)
  })
})

describe('NanoGptXaiTTSEngine', () => {
  beforeEach(() => vi.clearAllMocks())

  it('synthesise returns a Float32Array via the decode hook for nano-gpt xAI TTS', async () => {
    // OfflineAudioContext is not available in jsdom; inject a fake decoder
    ;(synthesiseNanoGptXai as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Blob([new Uint8Array([0xff, 0xfb])], { type: 'audio/mpeg' }),
    )
    const engine = new NanoGptXaiTTSEngine()
    ;(engine as unknown as { _decode: (blob: Blob) => Promise<Float32Array> })._decode =
      async () => new Float32Array([0.0])
    const pcm = await engine.synthesise('hi', { id: 'v1', name: 'V', language: 'en' })
    expect(pcm).toBeInstanceOf(Float32Array)
  })
})
