import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useBackButtonClose } from './useBackButtonClose'
import { useHistoryStackStore } from '../store/historyStackStore'

beforeEach(() => {
  useHistoryStackStore.getState().clear()
  vi.restoreAllMocks()
})

describe('useBackButtonClose', () => {
  it('does nothing while open is false', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    renderHook(() => useBackButtonClose(false, onClose, 'a'))
    expect(pushSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
  })

  it('pushes state and registers store entry on open=false→true', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: false } },
    )
    rerender({ open: true })
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(pushSpy.mock.calls[0][0]).toEqual({ __overlayId: 'a' })
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('a')
  })

  it('pops store and calls history.back on programmatic open=true→false', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: true } },
    )
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    rerender({ open: false })
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('does not call history.back if entry already absent (popstate path)', () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: true } },
    )
    useHistoryStackStore.getState().clear()
    rerender({ open: false })
    expect(backSpy).not.toHaveBeenCalled()
  })

  it('treats unmount while open as programmatic close', () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { unmount } = renderHook(() => useBackButtonClose(true, onClose, 'a'))
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    unmount()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('ignores overlayId changes while open stays true', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ id }) => useBackButtonClose(true, onClose, id),
      { initialProps: { id: 'a' } },
    )
    expect(pushSpy).toHaveBeenCalledTimes(1)
    rerender({ id: 'b' })
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('a')
  })
})
