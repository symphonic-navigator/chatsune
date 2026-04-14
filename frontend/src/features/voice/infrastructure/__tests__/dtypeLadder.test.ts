import { describe, it, expect } from 'vitest'
import { filterLadder, WHISPER_LADDER, KOKORO_LADDER } from '../dtypeLadder'
import type { VoiceCapabilities } from '../capabilityProbe'

const baseCaps: VoiceCapabilities = {
  webgpu: true,
  shaderF16: true,
  adapterInfo: { vendor: 'test', architecture: 'arch' },
}

describe('filterLadder', () => {
  it('keeps every entry when both webgpu and shader-f16 are present', () => {
    expect(filterLadder(WHISPER_LADDER, baseCaps)).toEqual(WHISPER_LADDER)
  })

  it('strips shader-f16 entries when the feature is missing', () => {
    const caps = { ...baseCaps, shaderF16: false }
    const out = filterLadder(WHISPER_LADDER, caps)
    expect(out.some((e) => 'requires' in e && e.requires === 'shader-f16')).toBe(false)
    expect(out.some((e) => e.device === 'webgpu' && e.dtype === 'fp32')).toBe(true)
    expect(out.some((e) => e.device === 'webgpu' && e.dtype === 'q4')).toBe(true)
  })

  it('strips all webgpu entries when webgpu is unavailable', () => {
    const caps = { ...baseCaps, webgpu: false, shaderF16: false }
    const out = filterLadder(KOKORO_LADDER, caps)
    expect(out.every((e) => e.device === 'wasm')).toBe(true)
  })

  it('preserves the original ladder order', () => {
    const out = filterLadder(WHISPER_LADDER, baseCaps)
    expect(out[0]).toMatchObject({ device: 'webgpu', dtype: 'fp16' })
  })

  it('whisper ladder prefers fp16 over q4f16 (quality first)', () => {
    const fp16 = WHISPER_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'fp16')
    const q4f16 = WHISPER_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'q4f16')
    expect(fp16).toBeLessThan(q4f16)
  })

  it('kokoro ladder prefers q4f16 over fp16 (size first)', () => {
    const fp16 = KOKORO_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'fp16')
    const q4f16 = KOKORO_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'q4f16')
    expect(q4f16).toBeLessThan(fp16)
  })
})
