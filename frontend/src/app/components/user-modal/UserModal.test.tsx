import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { UserModal } from './UserModal'
import type { TopTabId, SubTabId } from './userModalTree'
import { useEnrichedModels } from '../../../core/hooks/useEnrichedModels'
import type {
  ConnectionModelGroup,
  UseEnrichedModels,
} from '../../../core/hooks/useEnrichedModels'

// Stub heavy child tabs so tests stay fast and isolated
vi.mock('./AboutMeTab', () => ({ AboutMeTab: () => <div>about-me-content</div> }))
vi.mock('./SettingsTab', () => ({ SettingsTab: () => <div>settings-display-content</div> }))
vi.mock('./HistoryTab', () => ({ HistoryTab: () => <div>history-content</div> }))
vi.mock('./ProjectsTab', () => ({ ProjectsTab: () => <div>projects-content</div> }))
vi.mock('./KnowledgeTab', () => ({ KnowledgeTab: () => <div>knowledge-content</div> }))
vi.mock('./LlmProvidersTab', () => ({ LlmProvidersTab: () => <div>llm-providers-content</div> }))

// The LLM-providers badge is driven entirely by useEnrichedModels. Mocking
// the hook directly keeps these tests insulated from the hub's internal
// plumbing (REST adapters, event-bus subscriptions, premium-provider merge
// logic). Each test overrides the return value to express the exact badge
// scenario under test.
vi.mock('../../../core/hooks/useEnrichedModels', () => ({
  useEnrichedModels: vi.fn(),
}))

const mockedUseEnrichedModels = vi.mocked(useEnrichedModels)

function hookReturn(
  overrides: Partial<UseEnrichedModels> = {},
): UseEnrichedModels {
  return {
    groups: [],
    loading: false,
    error: null,
    refresh: vi.fn().mockResolvedValue(undefined),
    findByUniqueId: vi.fn().mockReturnValue(null),
    ...overrides,
  }
}

/** Produce a minimally-shaped group with a single model. */
function groupWithOneModel(): ConnectionModelGroup {
  // The UserModal only checks `models.length > 0`, so the shape of the
  // connection/model payload is irrelevant — cast to the expected types.
  return {
    connection: { id: 'conn-1' } as ConnectionModelGroup['connection'],
    models: [{ unique_id: 'conn-1:m' } as ConnectionModelGroup['models'][number]],
  }
}

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
  beforeEach(() => {
    // Default: at least one usable model → badge suppressed. Individual
    // tests override this before calling renderModal().
    mockedUseEnrichedModels.mockReturnValue(
      hookReturn({ groups: [groupWithOneModel()] }),
    )
  })

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

  it('shows ! badge on Settings top-pill when the user has no usable models', () => {
    // Empty groups + settled hub → badge must appear.
    mockedUseEnrichedModels.mockReturnValue(
      hookReturn({ groups: [], loading: false }),
    )
    renderModal('about-me')

    const badgeSpan = screen.getByLabelText('Attention required')
    expect(badgeSpan.textContent).toBe('!')
    // The badge must sit inside the Settings top-pill, not any other pill.
    const settingsTab = document.getElementById('user-tab-settings')
    expect(settingsTab).not.toBeNull()
    expect(settingsTab!.contains(badgeSpan)).toBe(true)
    const aboutMeTab = document.getElementById('user-tab-about-me')
    expect(aboutMeTab).not.toBeNull()
    expect(aboutMeTab!.contains(badgeSpan)).toBe(false)
  })

  it('suppresses the badge when at least one group exposes a model', () => {
    // Default beforeEach already sets one group with a model, but be
    // explicit here so the intent is readable.
    mockedUseEnrichedModels.mockReturnValue(
      hookReturn({ groups: [groupWithOneModel()] }),
    )
    renderModal('about-me')
    expect(screen.queryByLabelText('Attention required')).not.toBeInTheDocument()
  })

  it('suppresses the badge while the models hub is still loading', () => {
    // Loading-state flash guard: groups are empty only because the hub
    // has not finished hydrating yet, so the badge must stay hidden.
    mockedUseEnrichedModels.mockReturnValue(
      hookReturn({ groups: [], loading: true }),
    )
    renderModal('about-me')
    expect(screen.queryByLabelText('Attention required')).not.toBeInTheDocument()
  })

  it('shows the badge when every group has zero models (all probes failed)', () => {
    // A premium account whose probe failed yields a group with models=[].
    // This must still count as "no usable LLM".
    const emptyGroup: ConnectionModelGroup = {
      connection: { id: 'premium:fake' } as ConnectionModelGroup['connection'],
      models: [],
    }
    mockedUseEnrichedModels.mockReturnValue(
      hookReturn({ groups: [emptyGroup], loading: false }),
    )
    renderModal('about-me')
    expect(screen.getByLabelText('Attention required')).toBeInTheDocument()
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
