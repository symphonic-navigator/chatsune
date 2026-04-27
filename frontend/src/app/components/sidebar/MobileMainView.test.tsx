import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MobileMainView } from './MobileMainView'

const baseProps = {
  isAdmin: false,
  isInChat: false,
  hasLastSession: false,
  hasApiKeyProblem: false,
  isSanitised: false,
  displayName: 'Chris',
  role: 'user',
  initial: 'C',
  onAdmin: vi.fn(),
  onContinue: vi.fn(),
  onNewChat: vi.fn(),
  onPersonas: vi.fn(),
  onHistory: vi.fn(),
  onBookmarks: vi.fn(),
  onKnowledge: vi.fn(),
  onMyData: vi.fn(),
  onToggleSanitised: vi.fn(),
  onUserRow: vi.fn(),
  onLogout: vi.fn(),
}

function renderView(overrides: Partial<typeof baseProps> = {}) {
  return render(
    <MemoryRouter>
      <MobileMainView {...baseProps} {...overrides} />
    </MemoryRouter>
  )
}

describe('MobileMainView — conditional rows', () => {
  it('renders Admin row when isAdmin is true', () => {
    renderView({ isAdmin: true })
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('hides Admin row when isAdmin is false', () => {
    renderView({ isAdmin: false })
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })

  it('renders Continue row when not in chat AND last session exists', () => {
    renderView({ isInChat: false, hasLastSession: true })
    expect(screen.getByText('Continue')).toBeInTheDocument()
  })

  it('hides Continue row when in chat', () => {
    renderView({ isInChat: true, hasLastSession: true })
    expect(screen.queryByText('Continue')).not.toBeInTheDocument()
  })

  it('hides Continue row when no last session', () => {
    renderView({ isInChat: false, hasLastSession: false })
    expect(screen.queryByText('Continue')).not.toBeInTheDocument()
  })

  it('shows API-key alert dot on avatar when hasApiKeyProblem', () => {
    renderView({ hasApiKeyProblem: true })
    expect(screen.getByLabelText(/api key problem/i)).toBeInTheDocument()
  })

  it('omits the alert dot when no problem', () => {
    renderView({ hasApiKeyProblem: false })
    expect(screen.queryByLabelText(/api key problem/i)).not.toBeInTheDocument()
  })
})

describe('MobileMainView — fixed rows render unconditionally', () => {
  it('renders New Chat, Personas, History, Bookmarks', () => {
    renderView()
    expect(screen.getByText('New Chat')).toBeInTheDocument()
    expect(screen.getByText('Personas')).toBeInTheDocument()
    expect(screen.getByText('History')).toBeInTheDocument()
    expect(screen.getByText('Bookmarks')).toBeInTheDocument()
  })

  it('renders Knowledge, My Data, Sanitised, Log out', () => {
    renderView()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
    expect(screen.getByText('My Data')).toBeInTheDocument()
    expect(screen.getByText('Sanitised')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
  })
})

describe('MobileMainView — handler wiring', () => {
  it('calls onNewChat when New Chat row is tapped', async () => {
    const onNewChat = vi.fn()
    renderView({ onNewChat })
    await userEvent.click(screen.getByText('New Chat'))
    expect(onNewChat).toHaveBeenCalledOnce()
  })

  it('calls onHistory when History row is tapped', async () => {
    const onHistory = vi.fn()
    renderView({ onHistory })
    await userEvent.click(screen.getByText('History'))
    expect(onHistory).toHaveBeenCalledOnce()
  })

  it('calls onMyData when My Data row is tapped', async () => {
    const onMyData = vi.fn()
    renderView({ onMyData })
    await userEvent.click(screen.getByText('My Data'))
    expect(onMyData).toHaveBeenCalledOnce()
  })

  it('calls onToggleSanitised when Sanitised row is tapped', async () => {
    const onToggleSanitised = vi.fn()
    renderView({ onToggleSanitised })
    await userEvent.click(screen.getByText('Sanitised'))
    expect(onToggleSanitised).toHaveBeenCalledOnce()
  })

  it('calls onLogout when Log out row is tapped', async () => {
    const onLogout = vi.fn()
    renderView({ onLogout })
    await userEvent.click(screen.getByText('Log out'))
    expect(onLogout).toHaveBeenCalledOnce()
  })
})
