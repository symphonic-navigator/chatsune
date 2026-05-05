import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  startOverlayTransition,
  startRouteTransition,
  useBackButtonClose,
} from './useBackButtonClose'
import { useHistoryStackStore } from '../store/historyStackStore'

beforeEach(() => {
  useHistoryStackStore.getState().clear()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('useBackButtonClose', () => {
  it('does nothing while open is false', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    renderHook(() => useBackButtonClose(false, onClose, 'a'))
    expect(pushSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
  })

  it('pushes state and registers store entry on open=false→true', async () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: false } },
    )
    rerender({ open: true })
    await Promise.resolve()
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(pushSpy.mock.calls[0][0]).toEqual({ __overlayId: 'a' })
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('a')
  })

  it('pops store and calls history.back on programmatic open=true→false', async () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    rerender({ open: false })
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('does not call history.back if entry already absent (popstate path)', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    useHistoryStackStore.getState().clear()
    rerender({ open: false })
    expect(backSpy).not.toHaveBeenCalled()
  })

  it('treats unmount while open as programmatic close', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { unmount } = renderHook(() => useBackButtonClose(true, onClose, 'a'))
    await Promise.resolve()
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    unmount()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('ignores overlayId changes while open stays true', async () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ id }) => useBackButtonClose(true, onClose, id),
      { initialProps: { id: 'a' } },
    )
    await Promise.resolve()
    expect(pushSpy).toHaveBeenCalledTimes(1)
    rerender({ id: 'b' })
    await Promise.resolve()
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('a')
  })

  it('does not call history.back when own entry is not at the top of the stack', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    useHistoryStackStore.getState().clear()

    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'our'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    // Hook just pushed its 'our' entry. Now simulate another overlay sitting
    // on top by pushing directly.
    useHistoryStackStore.getState().push('other-on-top', () => {})

    rerender({ open: false })
    expect(backSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().stack.map((e) => e.overlayId)).toEqual(['other-on-top'])
  })

  it('uses replaceState (not pushState) when an overlay transition was marked', async () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    const onClose = vi.fn()

    startOverlayTransition('outgoing-overlay')
    renderHook(() => useBackButtonClose(true, onClose, 'incoming-overlay'))
    await Promise.resolve()

    expect(replaceSpy).toHaveBeenCalledTimes(1)
    expect(replaceSpy.mock.calls[0][0]).toEqual({ __overlayId: 'incoming-overlay' })
    expect(pushSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('incoming-overlay')
  })

  it('uses pushState normally when no overlay transition was marked', async () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const replaceSpy = vi.spyOn(window.history, 'replaceState')
    const onClose = vi.fn()

    renderHook(() => useBackButtonClose(true, onClose, 'a'))
    await Promise.resolve()

    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(replaceSpy).not.toHaveBeenCalled()
  })

  it('clears the transition marker via setTimeout(0) when no overlay claims it', async () => {
    vi.useFakeTimers()
    try {
      const pushSpy = vi.spyOn(window.history, 'pushState')
      const replaceSpy = vi.spyOn(window.history, 'replaceState')
      const onClose = vi.fn()

      // Mark a transition but never mount an overlay to consume it.
      startOverlayTransition('orphan-transition')

      // Flush the setTimeout(0) so the marker auto-clears.
      vi.advanceTimersByTime(0)

      // Now mount an overlay — it must use pushState because the previous
      // transition marker has been cleared.
      vi.useRealTimers()
      renderHook(() => useBackButtonClose(true, onClose, 'fresh'))
      await Promise.resolve()

      expect(pushSpy).toHaveBeenCalledTimes(1)
      expect(replaceSpy).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('skips history.back() on close when a route transition is pending for that overlay', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'route-overlay'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)

    // Caller about to navigate to a new route: mark the transition,
    // then close the overlay. The hook must NOT call history.back()
    // because react-router has already pushed a new entry, and an
    // extra back() would race and revert the URL.
    startRouteTransition('route-overlay')
    rerender({ open: false })

    expect(backSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
  })

  it('still calls history.back() on close when no route transition was marked', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'route-overlay-2'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    rerender({ open: false })

    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('only consumes the route transition when the overlay id matches', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'route-overlay-3'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()

    // Marker is for a DIFFERENT overlay — must not be consumed here.
    startRouteTransition('some-other-overlay')
    rerender({ open: false })

    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('self-clears the route transition marker via setTimeout(0)', async () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()

    // Mark a transition, but don't close anything before the
    // setTimeout(0) flushes — the marker must clear itself.
    startRouteTransition('route-overlay-4')
    await new Promise((r) => setTimeout(r, 5))

    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'route-overlay-4'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    rerender({ open: false })

    // Marker auto-cleared, so close must still go back.
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('does not push or call history.back when mount/cleanup/remount happens before microtask flushes (StrictMode-style)', async () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()

    // First mount: queues microtask but does not push yet.
    const { unmount: unmount1 } = renderHook(() => useBackButtonClose(true, onClose, 'a'))
    // Synchronously unmount before the microtask flushes.
    unmount1()
    // Re-mount synchronously, again before any microtask runs.
    renderHook(() => useBackButtonClose(true, onClose, 'a'))

    // Now flush microtasks — only the second mount's microtask should push.
    await Promise.resolve()

    expect(pushSpy).toHaveBeenCalledTimes(1)
    // Critically: history.back() must NOT have been called from the first
    // unmount, because that would fire a stale popstate.
    expect(backSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
  })
})
