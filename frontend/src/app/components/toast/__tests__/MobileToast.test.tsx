import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MobileToast } from '../MobileToast'
import { useNotificationStore } from '../../../../core/store/notificationStore'
import type { AppNotification } from '../../../../core/store/notificationStore'

function makeNotification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 'n1',
    level: 'info',
    title: 'Hello',
    message: 'World',
    dismissed: false,
    timestamp: Date.now(),
    ...overrides,
  }
}

describe('MobileToast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useNotificationStore.setState({ notifications: [] })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders title and message', () => {
    render(<MobileToast notification={makeNotification()} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('World')).toBeInTheDocument()
  })

  it('dismisses on tap', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    fireEvent.click(screen.getByRole('status'))
    // MobileToast delays actual store dismiss by the exit animation (200ms)
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).toHaveBeenCalledWith('n1')
  })

  it('dismisses on swipe-down past threshold', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    const el = screen.getByRole('status')
    fireEvent.pointerDown(el, { clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(el, { clientY: 160, pointerId: 1 })
    fireEvent.pointerUp(el, { clientY: 160, pointerId: 1 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).toHaveBeenCalledWith('n1')
  })

  it('does not dismiss on short swipe', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    const el = screen.getByRole('status')
    fireEvent.pointerDown(el, { clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(el, { clientY: 110, pointerId: 1 })
    fireEvent.pointerUp(el, { clientY: 110, pointerId: 1 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).not.toHaveBeenCalled()
  })

  it('does not dismiss on pointercancel even past swipe threshold', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    const el = screen.getByRole('status')
    fireEvent.pointerDown(el, { clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(el, { clientY: 160, pointerId: 1 })
    fireEvent.pointerCancel(el, { clientY: 160, pointerId: 1 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).not.toHaveBeenCalled()
  })

  it('auto-dismisses after duration', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification({ level: 'success' })} />)
    // success default duration is 4000ms; +200ms exit
    act(() => { vi.advanceTimersByTime(4500) })
    expect(dismissSpy).toHaveBeenCalledWith('n1')
  })
})
