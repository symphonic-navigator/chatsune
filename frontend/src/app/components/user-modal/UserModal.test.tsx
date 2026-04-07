import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { UserModal } from './UserModal'

// Stub heavy child tabs so tests stay fast and isolated
vi.mock('./AboutMeTab', () => ({ AboutMeTab: () => <div>about-me-content</div> }))
vi.mock('./SettingsTab', () => ({ SettingsTab: () => <div>settings-content</div> }))
vi.mock('./HistoryTab', () => ({ HistoryTab: () => <div>history-content</div> }))
vi.mock('./ProjectsTab', () => ({ ProjectsTab: () => <div>projects-content</div> }))
vi.mock('./KnowledgeTab', () => ({ KnowledgeTab: () => <div>knowledge-content</div> }))

function renderModal(activeTab = 'about-me' as const) {
  const onClose = vi.fn()
  const onTabChange = vi.fn()
  render(
    <MemoryRouter>
      <UserModal activeTab={activeTab} onClose={onClose} onTabChange={onTabChange} displayName="Chris" hasApiKeyProblem={false} onProvidersChanged={vi.fn()} />
    </MemoryRouter>,
  )
  return { onClose, onTabChange }
}

describe('UserModal', () => {
  it('renders the active tab content', () => {
    renderModal('about-me')
    expect(screen.getByText('about-me-content')).toBeInTheDocument()
  })

  it('switches tab on click', () => {
    const { onTabChange } = renderModal('about-me')
    fireEvent.click(screen.getByRole('tab', { name: /settings/i }))
    expect(onTabChange).toHaveBeenCalledWith('settings')
  })

  it('calls onClose when close button is clicked', () => {
    const { onClose } = renderModal('about-me')
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
