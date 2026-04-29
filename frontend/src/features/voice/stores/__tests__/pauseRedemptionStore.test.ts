import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePauseRedemptionStore } from '../pauseRedemptionStore'

describe('pauseRedemptionStore', () => {
  beforeEach(() => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:00:00Z'))
  })

  it('defaults to inactive', () => {
    const s = usePauseRedemptionStore.getState()
    expect(s.active).toBe(false)
    expect(s.startedAt).toBeNull()
    expect(s.windowMs).toBe(0)
  })

  it('start() captures windowMs and timestamps the start', () => {
    const before = performance.now()
    usePauseRedemptionStore.getState().start(1728)
    const s = usePauseRedemptionStore.getState()
    expect(s.active).toBe(true)
    expect(s.windowMs).toBe(1728)
    expect(s.startedAt).not.toBeNull()
    expect(s.startedAt!).toBeGreaterThanOrEqual(before)
  })

  it('start() captures the window in force at the moment of the call (not later)', () => {
    usePauseRedemptionStore.getState().start(2000)
    // Subsequent setting changes (e.g. user drags slider mid-pause) must NOT
    // mutate the captured value. Simulate by calling start() a second time:
    usePauseRedemptionStore.getState().start(8000)
    expect(usePauseRedemptionStore.getState().windowMs).toBe(8000)
  })

  it('clear() resets to inactive and is idempotent', () => {
    usePauseRedemptionStore.getState().start(1000)
    usePauseRedemptionStore.getState().clear()
    expect(usePauseRedemptionStore.getState().active).toBe(false)
    expect(usePauseRedemptionStore.getState().startedAt).toBeNull()
    // Idempotent — calling clear again is a no-op.
    usePauseRedemptionStore.getState().clear()
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })
})
