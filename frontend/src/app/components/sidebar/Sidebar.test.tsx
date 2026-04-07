import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Sidebar } from './Sidebar'

const mockNavigate = vi.fn()

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

const defaults = {
  personas: [],
  sessions: [],
  activePersonaId: null,
  activeSessionId: null,
  onOpenModal: vi.fn(),
  onCloseModal: vi.fn(),
  activeModalTab: null as null,
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
})

describe('Sidebar — overlay close on navigation', () => {
  it('calls onOpenAdmin when Admin banner is clicked', async () => {
    const onOpenAdmin = vi.fn()
    renderSidebar({ onOpenAdmin })
    await userEvent.click(screen.getByText('Admin'))
    expect(onOpenAdmin).toHaveBeenCalledOnce()
  })

  it('calls onCloseModal when Personas NavRow is clicked', async () => {
    const onCloseModal = vi.fn()
    renderSidebar({ onCloseModal })
    await userEvent.click(screen.getByText('Personas'))
    expect(onCloseModal).toHaveBeenCalledOnce()
  })
})
