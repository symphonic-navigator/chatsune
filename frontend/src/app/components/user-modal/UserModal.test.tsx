import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { UserModal } from './UserModal'
import type { TopTabId, SubTabId } from './userModalTree'

// Stub heavy child tabs so tests stay fast and isolated
vi.mock('./AboutMeTab', () => ({ AboutMeTab: () => <div>about-me-content</div> }))
vi.mock('./SettingsTab', () => ({ SettingsTab: () => <div>settings-display-content</div> }))
vi.mock('./HistoryTab', () => ({ HistoryTab: () => <div>history-content</div> }))
vi.mock('./ProjectsTab', () => ({ ProjectsTab: () => <div>projects-content</div> }))
vi.mock('./KnowledgeTab', () => ({ KnowledgeTab: () => <div>knowledge-content</div> }))
vi.mock('./LlmProvidersTab', () => ({ LlmProvidersTab: () => <div>llm-providers-content</div> }))

// Suppress async badge-fetch calls that are not under test here
vi.mock('../../../core/api/llm', () => ({
  llmApi: { listConnections: vi.fn().mockResolvedValue([]) },
}))
vi.mock('../../../core/websocket/eventBus', () => ({
  eventBus: { on: vi.fn().mockReturnValue(() => {}) },
}))

function renderModal(activeTop: TopTabId = 'about-me', activeSub?: SubTabId) {
  const onClose = vi.fn()
  const onTabChange = vi.fn()
  render(
    <MemoryRouter>
      <UserModal
        activeTop={activeTop}
        activeSub={activeSub}
        onClose={onClose}
        onTabChange={onTabChange}
        displayName="Chris"
        hasApiKeyProblem={false}
        onProvidersChanged={vi.fn()}
        onOpenPersonaOverlay={vi.fn()}
      />
    </MemoryRouter>,
  )
  return { onClose, onTabChange }
}

describe('UserModal', () => {
  it('renders the active top-tab content for a leaf-only top', () => {
    renderModal('about-me')
    expect(screen.getByText('about-me-content')).toBeInTheDocument()
  })

  it('renders the active sub-tab content when a sub is specified', () => {
    renderModal('settings', 'display')
    expect(screen.getByText('settings-display-content')).toBeInTheDocument()
  })

  it('renders sub-tab pills for tops that have children', () => {
    renderModal('settings', 'display')
    expect(screen.getByRole('tab', { name: /display/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /llm providers/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^integrations$/i })).toBeInTheDocument()
  })

  it('does not render sub-tab pills for leaf-only tops', () => {
    renderModal('about-me')
    // No sub-tabs exist for 'about-me'
    expect(screen.queryByLabelText(/about me sub-sections/i)).not.toBeInTheDocument()
  })

  it('calls onTabChange with correct top when a top-pill is clicked', () => {
    const { onTabChange } = renderModal('about-me')
    fireEvent.click(screen.getByRole('tab', { name: /^settings$/i }))
    expect(onTabChange).toHaveBeenCalledWith('settings')
  })

  it('calls onClose when close button is clicked', () => {
    const { onClose } = renderModal('about-me')
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows ! badge on Settings top-pill when llm-providers has no connection', async () => {
    const { llmApi } = await import('../../../core/api/llm')
    vi.mocked(llmApi.listConnections).mockResolvedValueOnce([])
    renderModal('about-me')
    // The badge span renders "!" with aria-label="Attention required".
    // Wait for the async connection-check to resolve and the badge to appear.
    const badgeSpan = await screen.findByLabelText('Attention required')
    expect(badgeSpan.textContent).toBe('!')
    // The badge must sit inside the Settings top-pill, not any other pill.
    // Query by id since the accessible name includes "Attention required" after the badge renders.
    const settingsTab = document.getElementById('user-tab-settings')
    expect(settingsTab).not.toBeNull()
    expect(settingsTab!.contains(badgeSpan)).toBe(true)
    // Other top-level tabs must not contain the badge
    const aboutMeTab = document.getElementById('user-tab-about-me')
    expect(aboutMeTab).not.toBeNull()
    expect(aboutMeTab!.contains(badgeSpan)).toBe(false)
  })

  it('clicking a top-pill with children calls onTabChange with top only (AppLayout resolves sub)', () => {
    const { onTabChange } = renderModal('about-me')
    fireEvent.click(screen.getByRole('tab', { name: /^chats$/i }))
    // onTabChange is called with top only — AppLayout picks remembered or first sub
    expect(onTabChange).toHaveBeenCalledWith('chats')
  })

  it('clicking a sub-pill calls onTabChange with both top and sub', () => {
    const { onTabChange } = renderModal('settings', 'display')
    fireEvent.click(screen.getByRole('tab', { name: /^models$/i }))
    expect(onTabChange).toHaveBeenCalledWith('settings', 'models')
  })
})
