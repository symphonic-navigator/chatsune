import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

describe('cuePlayer', () => {
  let oscStartCalls: Array<{ freq: number; startAt: number }>
  let mockCtx: { currentTime: number; state: string; resume: () => void; createOscillator: () => unknown; createBiquadFilter: () => unknown; createGain: () => unknown; destination: object }

  beforeEach(() => {
    oscStartCalls = []
    mockCtx = {
      currentTime: 0,
      state: 'running',
      resume: vi.fn(),
      destination: {},
      createOscillator: () => {
        const osc = {
          type: '',
          frequency: { setValueAtTime: vi.fn((freq: number, startAt: number) => oscStartCalls.push({ freq, startAt })) },
          connect: vi.fn(() => osc),
          start: vi.fn(),
          stop: vi.fn(),
        }
        return osc
      },
      createBiquadFilter: () => ({
        type: '',
        Q: { setValueAtTime: vi.fn() },
        frequency: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
        connect: vi.fn(function (this: unknown) { return this }),
      }),
      createGain: () => ({
        gain: {
          setValueAtTime: vi.fn(),
          linearRampToValueAtTime: vi.fn(),
        },
        connect: vi.fn(function (this: unknown) { return this }),
      }),
    }
    vi.stubGlobal('AudioContext', vi.fn(function () { return mockCtx }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('playCue("on") schedules C4 then G4 (ascending fifth)', async () => {
    const { playCue } = await import('../cuePlayer')
    playCue('on')

    expect(oscStartCalls).toHaveLength(2)
    expect(oscStartCalls[0].freq).toBeCloseTo(261.63, 1)
    expect(oscStartCalls[1].freq).toBeCloseTo(392.00, 1)
    expect(oscStartCalls[1].startAt).toBeGreaterThan(oscStartCalls[0].startAt)
  })

  it('playCue("off") schedules G4 then C4 (descending fifth)', async () => {
    const { playCue } = await import('../cuePlayer')
    playCue('off')

    expect(oscStartCalls).toHaveLength(2)
    expect(oscStartCalls[0].freq).toBeCloseTo(392.00, 1)
    expect(oscStartCalls[1].freq).toBeCloseTo(261.63, 1)
  })

  it('resumes a suspended AudioContext defensively', async () => {
    mockCtx.state = 'suspended'
    const { playCue } = await import('../cuePlayer')
    playCue('on')

    expect(mockCtx.resume).toHaveBeenCalled()
  })
})
