// Behaviour tests for the UserModal Projects sub-tab. Covers the four
// surfaces the tab is responsible for per spec §6.4: client-side
// search, the all/pinned filter pill, the "+ New Project" → modal
// hand-off, and the sanitised-mode NSFW filter. Empty-state copy is
// asserted too because that is the only feedback users see when no
// projects match.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { ProjectDto } from '../../../../features/projects/types'

// projectsApi is touched directly by the per-row pin toggle, and
// indirectly by the create-modal stub.
vi.mock('../../../../features/projects/projectsApi', () => ({
  projectsApi: {
    create: vi.fn(),
    list: vi.fn().mockResolvedValue([]),
    setPinned: vi.fn().mockResolvedValue({ ok: true }),
  },
}))

const sanitisedState = { value: false }
vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: sanitisedState.value }),
}))

// Stub the create-modal — the tab's only contract with it is "mount
// when the trigger is clicked" and "unmount when onClose fires".
vi.mock('../../../../features/projects/ProjectCreateModal', () => ({
  ProjectCreateModal: ({
    isOpen,
    onClose,
  }: {
    isOpen: boolean
    onClose: () => void
  }) =>
    isOpen ? (
      <div data-testid="create-modal">
        <button type="button" onClick={onClose}>
          close-mock
        </button>
      </div>
    ) : null,
}))

function makeProject(overrides: Partial<ProjectDto> = {}): ProjectDto {
  return {
    id: 'p1',
    user_id: 'u1',
    title: 'Alpha',
    emoji: null,
    description: null,
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    system_prompt: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(async () => {
  sanitisedState.value = false
  vi.clearAllMocks()
  // Reset the projects store so cross-test state cannot leak.
  const { useProjectsStore } = await import(
    '../../../../features/projects/useProjectsStore'
  )
  useProjectsStore.setState({ projects: {}, loaded: false, loading: false })
})

describe('ProjectsTab — list rendering', () => {
  it('renders all visible projects with name, emoji and description', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore
      .getState()
      .upsert(
        makeProject({
          id: 'a',
          title: 'Star Trek Fan Fiction',
          emoji: '✨',
          description: 'Fanfic with Mr. Worf about romulan diplomacy.',
        }),
      )
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'b', title: 'Music Theory Notes', emoji: '🎼' }))

    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    expect(screen.getByText('Star Trek Fan Fiction')).toBeInTheDocument()
    expect(screen.getByText('Music Theory Notes')).toBeInTheDocument()
    expect(
      screen.getByText('Fanfic with Mr. Worf about romulan diplomacy.'),
    ).toBeInTheDocument()
  })

  it('shows the friendly empty-state copy when there are no projects', async () => {
    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    expect(screen.getByText('No projects yet')).toBeInTheDocument()
    expect(screen.getByText(/Projects let you group/i)).toBeInTheDocument()
  })

  it('renders a pinned badge for pinned projects', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'a', title: 'Pinned Project', pinned: true }))
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'b', title: 'Other Project', pinned: false }))

    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    const badges = screen.getAllByTestId('project-pinned-badge')
    expect(badges).toHaveLength(1)
  })
})

describe('ProjectsTab — search & filter', () => {
  it('filters by the search query (case-insensitive) on the project name', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'a', title: 'Star Trek' }))
    useProjectsStore.getState().upsert(makeProject({ id: 'b', title: 'Music' }))

    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    const search = screen.getByPlaceholderText(/search projects/i)
    fireEvent.change(search, { target: { value: 'STAR' } })

    expect(screen.getByText('Star Trek')).toBeInTheDocument()
    expect(screen.queryByText('Music')).not.toBeInTheDocument()
  })

  it('restricts the list to pinned projects when the "Pinned only" filter is active', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'a', title: 'Pinned Project', pinned: true }))
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'b', title: 'Loose Project', pinned: false }))

    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    // Both visible by default
    expect(screen.getByText('Pinned Project')).toBeInTheDocument()
    expect(screen.getByText('Loose Project')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /pinned only/i }))

    expect(screen.getByText('Pinned Project')).toBeInTheDocument()
    expect(screen.queryByText('Loose Project')).not.toBeInTheDocument()
  })

  it('hides NSFW projects when sanitised mode is on', async () => {
    sanitisedState.value = true
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'a', title: 'Tame', nsfw: false }))
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'b', title: 'Spicy', nsfw: true }))

    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    expect(screen.getByText('Tame')).toBeInTheDocument()
    expect(screen.queryByText('Spicy')).not.toBeInTheDocument()
  })

  it('shows a "no matches" empty state when the search clears the list', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore.getState().upsert(makeProject({ id: 'a', title: 'Alpha' }))

    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    fireEvent.change(screen.getByPlaceholderText(/search projects/i), {
      target: { value: 'zzz' },
    })

    expect(screen.getByText(/no matching projects/i)).toBeInTheDocument()
  })
})

describe('ProjectsTab — create modal hand-off', () => {
  it('mounts ProjectCreateModal when the "+ New Project" button is clicked', async () => {
    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    expect(screen.queryByTestId('create-modal')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /create new project/i }))

    expect(screen.getByTestId('create-modal')).toBeInTheDocument()
  })

  it('unmounts the create-modal again on close', async () => {
    const { ProjectsTab } = await import('../ProjectsTab')
    render(<ProjectsTab />)

    fireEvent.click(screen.getByRole('button', { name: /create new project/i }))
    fireEvent.click(screen.getByText('close-mock'))

    expect(screen.queryByTestId('create-modal')).not.toBeInTheDocument()
  })
})
