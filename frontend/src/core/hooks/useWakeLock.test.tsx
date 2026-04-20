import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWakeLock } from './useWakeLock'

// A minimal fake WakeLockSentinel. `released` is flipped to true when
// `release()` is called, mirroring the real browser behaviour so the hook's
// "is the sentinel still held?" check works in tests.
type FakeSentinel = {
  released: boolean
  release: ReturnType<typeof vi.fn>
}

function createFakeSentinel(): FakeSentinel {
  const sentinel: FakeSentinel = {
    released: false,
    release: vi.fn(async () => {
      sentinel.released = true
    }),
  }
  return sentinel
}

// Track the sentinels the mock hands out so tests can inspect / mutate them.
let sentinels: FakeSentinel[] = []
let mockRequest: ReturnType<typeof vi.fn>

function installWakeLock(): void {
  mockRequest = vi.fn(async (_type: 'screen') => {
    const s = createFakeSentinel()
    sentinels.push(s)
    return s
  })
  Object.defineProperty(navigator, 'wakeLock', {
    configurable: true,
    value: { request: mockRequest },
  })
}

function uninstallWakeLock(): void {
  // `delete` requires the property to be configurable, which we set above.
  delete (navigator as unknown as { wakeLock?: unknown }).wakeLock
}

function setVisibility(state: 'visible' | 'hidden'): void {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value: state,
  })
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  sentinels = []
  setVisibility('visible')
  installWakeLock()
})

afterEach(() => {
  uninstallWakeLock()
  vi.restoreAllMocks()
})

describe('useWakeLock', () => {
  it('does not request the lock when shouldHold is false', () => {
    renderHook(() => useWakeLock(false))
    expect(mockRequest).not.toHaveBeenCalled()
  })

  it('requests the lock exactly once when shouldHold transitions false → true', async () => {
    const { rerender } = renderHook(({ hold }) => useWakeLock(hold), {
      initialProps: { hold: false },
    })
    expect(mockRequest).not.toHaveBeenCalled()

    await act(async () => {
      rerender({ hold: true })
    })

    expect(mockRequest).toHaveBeenCalledTimes(1)
    expect(mockRequest).toHaveBeenCalledWith('screen')
  })

  it('releases the sentinel when shouldHold transitions true → false', async () => {
    const { rerender } = renderHook(({ hold }) => useWakeLock(hold), {
      initialProps: { hold: true },
    })
    await act(async () => {}) // let the async acquire resolve

    expect(sentinels).toHaveLength(1)
    const first = sentinels[0]
    expect(first.released).toBe(false)

    await act(async () => {
      rerender({ hold: false })
    })

    expect(first.release).toHaveBeenCalledTimes(1)
    expect(first.released).toBe(true)
  })

  it('re-acquires on visibilitychange → visible when the sentinel was auto-released', async () => {
    renderHook(() => useWakeLock(true))
    await act(async () => {})

    expect(sentinels).toHaveLength(1)
    const first = sentinels[0]

    // Simulate the browser auto-releasing the lock when the tab was hidden.
    first.released = true
    setVisibility('hidden')

    // Now the user returns.
    await act(async () => {
      setVisibility('visible')
    })

    // A second request should have been made, handing out a fresh sentinel.
    expect(mockRequest).toHaveBeenCalledTimes(2)
    expect(sentinels).toHaveLength(2)
    expect(sentinels[1].released).toBe(false)
  })

  it('does nothing and throws nothing when navigator.wakeLock is unavailable', () => {
    uninstallWakeLock()
    expect(() => {
      renderHook(() => useWakeLock(true))
    }).not.toThrow()
  })

  it('releases the sentinel on unmount', async () => {
    const { unmount } = renderHook(() => useWakeLock(true))
    await act(async () => {})

    expect(sentinels).toHaveLength(1)
    const first = sentinels[0]

    await act(async () => {
      unmount()
    })

    expect(first.release).toHaveBeenCalledTimes(1)
    expect(first.released).toBe(true)
  })
})
