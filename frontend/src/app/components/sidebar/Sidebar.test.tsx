import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useDrawerStore } from '../../../core/store/drawerStore'
import type { TopTabId, SubTabId } from '../user-modal/userModalTree'

const mockNavigate = vi.fn()
const mockUseViewport = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('../../../core/store/authStore', () => ({
  useAuthStore: (sel: (s: Record<string, unknown>) => unknown) =>
    sel({ user: { role: 'admin', display_name: 'Test Admin', username: 'admin' } }),
}))

vi.mock('../../../core/hooks/useAuth', () => ({
  useAuth: () => ({ logout: vi.fn() }),
}))

vi.mock('../../../core/hooks/useViewport', () => ({
  useViewport: () => mockUseViewport(),
}))

const DESKTOP_VIEWPORT = {
  isDesktop: true, isMobile: false, isTablet: false, isLandscape: false,
  isSm: true, isMd: true, isLg: true, isXl: false,
}

const MOBILE_VIEWPORT = {
  isDesktop: false, isMobile: true, isTablet: false, isLandscape: false,
  isSm: true, isMd: false, isLg: false, isXl: false,
}

const defaults = {
  personas: [],
  sessions: [],
  activePersonaId: null,
  activeSessionId: null,
  onOpenModal: vi.fn(),
  onCloseModal: vi.fn(),
  activeModalTop: null as TopTabId | null,
  activeModalSub: null as SubTabId | null,
  onOpenAdmin: vi.fn(),
  isAdminOpen: false,
  hasApiKeyProblem: false,
}

function renderSidebar(overrides: Partial<typeof defaults> = {}) {
  return render(
    <MemoryRouter>
      <Sidebar {...defaults} {...overrides} />
    </MemoryRouter>
  )
}

beforeEach(() => {
  mockNavigate.mockClear()
  // Reset drawer store to closed on each test
  useDrawerStore.setState({ sidebarOpen: false })
})

describe('Sidebar — overlay close on navigation', () => {
  beforeEach(() => {
    mockUseViewport.mockReturnValue(DESKTOP_VIEWPORT)
  })

  it('calls onOpenAdmin when Admin banner is clicked', async () => {
    const onOpenAdmin = vi.fn()
    renderSidebar({ onOpenAdmin })
    await userEvent.click(screen.getByText('Admin'))
    expect(onOpenAdmin).toHaveBeenCalledOnce()
  })

})

describe('Sidebar — isTabActive sub-tab highlight', () => {
  beforeEach(() => {
    mockUseViewport.mockReturnValue(DESKTOP_VIEWPORT)
  })

  it('highlights the Bookmarks nav row when activeModalTop=chats and activeModalSub=bookmarks', () => {
    renderSidebar({ activeModalTop: 'chats', activeModalSub: 'bookmarks' })
    // NavRow renders a div[role="button"] containing the label text.
    // When isActive, NavRow sets aria-current="page".
    // getByText finds the label span inside NavRow; .closest finds the row element.
    const labelSpan = screen.getByText('Bookmarks')
    const navRow = labelSpan.closest('[role="button"]')
    expect(navRow).not.toBeNull()
    expect(navRow).toHaveAttribute('aria-current', 'page')
  })
})

describe('Sidebar — mobile stack', () => {
  beforeEach(() => {
    mockUseViewport.mockReturnValue(MOBILE_VIEWPORT)
    useDrawerStore.setState({ sidebarOpen: true })
    mockNavigate.mockClear()
  })

  it('starts on the main view', () => {
    renderSidebar()
    expect(screen.getByText('Chatsune')).toBeInTheDocument()
    expect(screen.getByText('New Chat')).toBeInTheDocument()
  })

  it('navigates to new-chat overlay when New Chat row is tapped', async () => {
    renderSidebar()
    await userEvent.click(screen.getByText('New Chat'))
    expect(screen.getByRole('button', { name: /back to main/i })).toBeInTheDocument()
  })

  it('returns to main view when back button is tapped', async () => {
    renderSidebar()
    await userEvent.click(screen.getByText('New Chat'))
    await userEvent.click(screen.getByRole('button', { name: /back to main/i }))
    expect(screen.getByRole('button', { name: /close sidebar/i })).toBeInTheDocument()
  })

  it('closes the drawer when ✕ is tapped (state goes false)', async () => {
    renderSidebar()
    await userEvent.click(screen.getByRole('button', { name: /close drawer/i }))
    expect(useDrawerStore.getState().sidebarOpen).toBe(false)
  })
})
