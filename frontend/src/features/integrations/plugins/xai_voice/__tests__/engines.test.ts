import { describe, it, expect, vi, beforeEach } from 'vitest'
import { XaiSTTEngine, XaiTTSEngine } from '../engines'

vi.mock('../api', () => ({
  transcribeXai: vi.fn(),
  synthesiseXai: vi.fn(),
  listXaiVoices: vi.fn(),
  toVoicePreset: (v: { id: string; name: string }) => ({
    id: v.id, name: v.name, language: 'en',
  }),
}))

// Path: from __tests__/ it's one deeper than from engines.ts
vi.mock('../../../store', () => ({
  useIntegrationsStore: {
    getState: () => ({ configs: { xai_voice: { enabled: true } } }),
  },
}))

import { transcribeXai, synthesiseXai } from '../api'

describe('XaiSTTEngine', () => {
  beforeEach(() => vi.clearAllMocks())

  it('transcribe packs Float32Array into a WAV Blob and returns the text', async () => {
    ;(transcribeXai as ReturnType<typeof vi.fn>).mockResolvedValueOnce('hello')
    const engine = new XaiSTTEngine()
    const res = await engine.transcribe(new Float32Array([0.1, -0.2, 0.3]))
    expect(res.text).toBe('hello')
    const args = (transcribeXai as ReturnType<typeof vi.fn>).mock.calls[0][0] as { audio: Blob }
    expect(args.audio).toBeInstanceOf(Blob)
    expect(args.audio.type).toBe('audio/wav')
  })

  it('isReady reflects integration store state', () => {
    const engine = new XaiSTTEngine()
    expect(engine.isReady()).toBe(true)
  })
})

describe('XaiTTSEngine', () => {
  beforeEach(() => vi.clearAllMocks())

  it('synthesise returns a Float32Array via the decode hook', async () => {
    // OfflineAudioContext is not available in jsdom; inject a fake decoder
    ;(synthesiseXai as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Blob([new Uint8Array([0xff, 0xfb])], { type: 'audio/mpeg' }),
    )
    const engine = new XaiTTSEngine()
    ;(engine as unknown as { _decode: (blob: Blob) => Promise<Float32Array> })._decode =
      async () => new Float32Array([0.0])
    const pcm = await engine.synthesise('hi', { id: 'v1', name: 'V', language: 'en' })
    expect(pcm).toBeInstanceOf(Float32Array)
  })
})
