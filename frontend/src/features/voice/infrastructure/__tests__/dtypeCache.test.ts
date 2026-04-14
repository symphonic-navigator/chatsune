import { describe, it, expect, beforeEach } from 'vitest'
import 'fake-indexeddb/auto'
import { getDecision, putDecision, _resetForTests } from '../dtypeCache'

describe('dtypeCache', () => {
  beforeEach(async () => {
    await _resetForTests()
  })

  it('returns null on cache miss', async () => {
    const d = await getDecision('whisper', 'webgpu/amd/rdna3/f16:true/v1')
    expect(d).toBeNull()
  })

  it('returns the stored decision on hit', async () => {
    await putDecision('whisper', 'webgpu/amd/rdna3/f16:true/v1', {
      device: 'webgpu',
      dtype: 'fp16',
    })
    const d = await getDecision('whisper', 'webgpu/amd/rdna3/f16:true/v1')
    expect(d).toMatchObject({ device: 'webgpu', dtype: 'fp16' })
    expect(typeof d?.decidedAt).toBe('string')
  })

  it('overwrites an existing entry for the same key', async () => {
    const key = 'webgpu/amd/rdna3/f16:true/v1'
    await putDecision('whisper', key, { device: 'webgpu', dtype: 'fp16' })
    await putDecision('whisper', key, { device: 'webgpu', dtype: 'q4' })
    const d = await getDecision('whisper', key)
    expect(d?.dtype).toBe('q4')
  })

  it('isolates decisions per model', async () => {
    const key = 'webgpu/amd/rdna3/f16:true/v1'
    await putDecision('whisper', key, { device: 'webgpu', dtype: 'fp16' })
    await putDecision('kokoro', key, { device: 'webgpu', dtype: 'q4f16' })
    expect((await getDecision('whisper', key))?.dtype).toBe('fp16')
    expect((await getDecision('kokoro', key))?.dtype).toBe('q4f16')
  })
})
