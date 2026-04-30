import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { RisingEmojisEffect } from '../overlay/RisingEmojisEffect'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
})

describe('RisingEmojisEffect smoke', () => {
  it('mounts and spawns particles for the full profile', () => {
    const onDone = vi.fn()
    const { container } = render(
      <RisingEmojisEffect emojis={['💖', '🤘', '🔥']} reduced={false} onDone={onDone} />,
    )
    // Spawning happens inside useEffect on mount; jsdom executes it immediately.
    const spans = container.querySelectorAll('span.screen-effect-rising-emoji')
    expect(spans.length).toBe(40) // PROFILE_FULL.count
  })

  it('uses the reduced profile when reduced=true', () => {
    const onDone = vi.fn()
    const { container } = render(
      <RisingEmojisEffect emojis={['💖']} reduced onDone={onDone} />,
    )
    const spans = container.querySelectorAll('span.screen-effect-rising-emoji')
    expect(spans.length).toBe(4) // PROFILE_REDUCED.count
  })

  it('falls back to a sparkle when emojis is empty', () => {
    const onDone = vi.fn()
    const { container } = render(
      <RisingEmojisEffect emojis={[]} reduced onDone={onDone} />,
    )
    const spans = container.querySelectorAll('span.screen-effect-rising-emoji')
    expect(spans.length).toBeGreaterThan(0)
    Array.from(spans).forEach((s) => {
      expect(s.textContent).toBe('✨')
    })
  })

  it('calls onDone after the safety timeout elapses', () => {
    const onDone = vi.fn()
    render(<RisingEmojisEffect emojis={['💖']} reduced onDone={onDone} />)
    expect(onDone).not.toHaveBeenCalled()
    // Safety timeout = delay + duration + 500. Reduced profile worst case
    // is spawnMs (1200) + riseMsMax (2900) + 500 = 4600ms. Advance 6s.
    vi.advanceTimersByTime(6000)
    expect(onDone).toHaveBeenCalledTimes(1)
  })
})
