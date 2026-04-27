import { describe, expect, it } from 'vitest'
import { computeTtsExpected, type TtsExpectedInput } from '../ttsExpected'

const baseInput: TtsExpectedInput = {
  audioActive: false,
  isReadingAloud: false,
  hasActiveGroup: false,
  liveModeActive: false,
  autoReadEnabledForActiveGroup: false,
}

describe('computeTtsExpected', () => {
  it('returns false when nothing is happening', () => {
    expect(computeTtsExpected(baseInput)).toBe(false)
  })

  it('returns true when audio is actively playing', () => {
    expect(computeTtsExpected({ ...baseInput, audioActive: true })).toBe(true)
  })

  it('returns true when read-aloud is in flight', () => {
    expect(computeTtsExpected({ ...baseInput, isReadingAloud: true })).toBe(true)
  })

  it('returns true when an active group runs in live mode', () => {
    expect(
      computeTtsExpected({
        ...baseInput,
        hasActiveGroup: true,
        liveModeActive: true,
      }),
    ).toBe(true)
  })

  it('returns true when an active group runs with auto-read on', () => {
    expect(
      computeTtsExpected({
        ...baseInput,
        hasActiveGroup: true,
        autoReadEnabledForActiveGroup: true,
      }),
    ).toBe(true)
  })

  it('returns false when an active group runs without live mode or auto-read', () => {
    expect(
      computeTtsExpected({ ...baseInput, hasActiveGroup: true }),
    ).toBe(false)
  })

  it('returns false when live mode is on but no group is active', () => {
    expect(
      computeTtsExpected({ ...baseInput, liveModeActive: true }),
    ).toBe(false)
  })

  it('returns false when auto-read is on but no group is active', () => {
    expect(
      computeTtsExpected({
        ...baseInput,
        autoReadEnabledForActiveGroup: true,
      }),
    ).toBe(false)
  })
})
