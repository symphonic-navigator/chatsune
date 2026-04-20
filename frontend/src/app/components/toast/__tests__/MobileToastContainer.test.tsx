import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MobileToastContainer } from '../MobileToastContainer'
import { useNotificationStore } from '../../../../core/store/notificationStore'

vi.mock('../../../../core/hooks/useViewport', () => ({
  useViewport: () => mockViewport,
}))

let mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }

function seed(ns: Array<{ id: string; title: string }>) {
  // notificationStore prepends new notifications, so the first entry is the
  // newest. Seed in the same order: first element = most recent.
  useNotificationStore.setState({
    notifications: ns.map((n, i) => ({
      id: n.id,
      level: 'info' as const,
      title: n.title,
      message: '',
      dismissed: false,
      timestamp: Date.now() - i,
    })),
  })
}

describe('MobileToastContainer', () => {
  beforeEach(() => {
    mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }
    useNotificationStore.setState({ notifications: [] })
  })

  it('renders nothing when not mobile', () => {
    mockViewport = { isMobile: false, isDesktop: true, isTablet: false, isLandscape: false, isSm: true, isMd: true, isLg: true, isXl: false }
    seed([{ id: 'a', title: 'First' }])
    const { container } = render(<MobileToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when there are no notifications', () => {
    const { container } = render(<MobileToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('renders only the most recent notification when mobile', () => {
    // First in array = newest (store prepends).
    seed([
      { id: 'c', title: 'Third' },
      { id: 'b', title: 'Second' },
      { id: 'a', title: 'First' },
    ])
    render(<MobileToastContainer />)
    expect(screen.queryByText('First')).not.toBeInTheDocument()
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
    expect(screen.getByText('Third')).toBeInTheDocument()
  })

  it('skips dismissed notifications', () => {
    // Newest (dismissed) first, older (visible) second.
    useNotificationStore.setState({
      notifications: [
        { id: 'b', level: 'info', title: 'Second', message: '', dismissed: true, timestamp: 2 },
        { id: 'a', level: 'info', title: 'First', message: '', dismissed: false, timestamp: 1 },
      ],
    })
    render(<MobileToastContainer />)
    expect(screen.getByText('First')).toBeInTheDocument()
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
  })
})
