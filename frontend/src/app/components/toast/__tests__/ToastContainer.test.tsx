import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { ToastContainer } from '../ToastContainer'
import { useNotificationStore } from '../../../../core/store/notificationStore'

vi.mock('../../../../core/hooks/useViewport', () => ({
  useViewport: () => mockViewport,
}))

let mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }

describe('ToastContainer (desktop-only gating)', () => {
  beforeEach(() => {
    useNotificationStore.setState({
      notifications: [
        { id: 'a', level: 'info', title: 'Hi', message: '', dismissed: false, timestamp: 1 },
      ],
    })
  })

  it('returns null on mobile', () => {
    mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }
    const { container } = render(<ToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('renders toasts on desktop', () => {
    mockViewport = { isMobile: false, isDesktop: true, isTablet: false, isLandscape: false, isSm: true, isMd: true, isLg: true, isXl: false }
    const { container } = render(<ToastContainer />)
    expect(container.firstChild).not.toBeNull()
  })
})
