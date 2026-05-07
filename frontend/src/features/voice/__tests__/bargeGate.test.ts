import { describe, it, expect } from 'vitest'
import { shouldSuppressBarge } from '../bargeGate'

describe('shouldSuppressBarge', () => {
  it('returns false when barging is enabled, regardless of group state', () => {
    expect(shouldSuppressBarge({ enabled: true, groupState: null })).toBe(false)
    expect(shouldSuppressBarge({ enabled: true, groupState: 'streaming' })).toBe(false)
    expect(shouldSuppressBarge({ enabled: true, groupState: 'tailing' })).toBe(false)
    expect(shouldSuppressBarge({ enabled: true, groupState: 'before-first-delta' })).toBe(false)
  })

  it('returns true when disabled and group is in speaking phase', () => {
    expect(shouldSuppressBarge({ enabled: false, groupState: 'streaming' })).toBe(true)
    expect(shouldSuppressBarge({ enabled: false, groupState: 'tailing' })).toBe(true)
  })

  it('returns false when disabled but group is not yet speaking', () => {
    // before-first-delta = phase 'thinking'. Mic suppression here would
    // be misleading — the user can still speak normally, the mic is just
    // closed by the natural pipeline (STT just sent its bundle).
    expect(shouldSuppressBarge({ enabled: false, groupState: 'before-first-delta' })).toBe(false)
  })

  it('returns false when disabled and there is no active group', () => {
    // Phase listening — barging-off must not suppress fresh speech.
    expect(shouldSuppressBarge({ enabled: false, groupState: null })).toBe(false)
  })
})
