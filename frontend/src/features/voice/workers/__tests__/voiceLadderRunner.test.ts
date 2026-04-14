import { describe, it, expect, vi } from 'vitest'
import { walkLadder } from '../voiceLadderRunner'
import type { DtypeEntry } from '../../infrastructure/dtypeLadder'

const LADDER: DtypeEntry[] = [
  { device: 'webgpu', dtype: 'fp16',  requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'fp32' },
  { device: 'wasm',   dtype: 'fp32' },
]

describe('walkLadder', () => {
  it('returns the first successful step', async () => {
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entry).toEqual(LADDER[0])
      expect(result.model).toBe('model')
      expect(result.attempts).toHaveLength(1)
      expect(result.attempts[0]?.outcome).toBe('ok')
    }
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('advances when load throws', async () => {
    const load = vi.fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entry).toEqual(LADDER[1])
      expect(result.attempts).toHaveLength(2)
      expect(result.attempts[0]?.outcome).toBe('load-failed')
    }
  })

  it('advances when warmup throws', async () => {
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn()
      .mockRejectedValueOnce(new Error('warmup-boom'))
      .mockResolvedValueOnce(undefined)

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(true)
    if (result.ok) expect(result.entry).toEqual(LADDER[1])
  })

  it('advances when collectGpuErrors returns a non-empty array', async () => {
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    const calls: number[] = []
    const collectGpuErrors = vi.fn(async () => {
      calls.push(calls.length)
      return calls.length === 1 ? ['GPUValidationError: Add'] : []
    })

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors,
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entry).toEqual(LADDER[1])
      expect(result.attempts[0]?.outcome).toBe('gpu-error')
    }
  })

  it('returns ok=false when every step fails', async () => {
    const load = vi.fn().mockRejectedValue(new Error('boom'))
    const warmup = vi.fn()

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.attempts).toHaveLength(LADDER.length)
      expect(result.attempts.every((a) => a.outcome !== 'ok')).toBe(true)
    }
  })

  it('invokes a logger for every attempt', async () => {
    const logs: string[] = []
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
      log: (line) => logs.push(line),
    })

    expect(logs.some((l) => l.includes('webgpu/fp16'))).toBe(true)
    expect(logs.some((l) => l.includes('OK'))).toBe(true)
  })
})
