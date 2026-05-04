// Behaviour tests for the desktop project picker. The picker is the
// busiest piece of UI in Phase 7 — it owns the project assignment
// flow and the entry point into the create-modal — so every row
// gets a dedicated assertion.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { ProjectDto } from '../types'

vi.mock('../projectsApi', () => ({
  projectsApi: {
    setSessionProject: vi.fn(),
  },
}))

const sanitisedState = { value: false }
vi.mock('../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: sanitisedState.value }),
}))

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: (sel: (s: { addNotification: () => void }) => unknown) =>
    sel({ addNotification: vi.fn() }),
}))

// The create-modal is exercised in its own test file; here we just
// verify the picker mounts it with the right props.
vi.mock('../ProjectCreateModal', () => ({
  ProjectCreateModal: ({
    isOpen,
    onCreated,
  }: {
    isOpen: boolean
    onCreated: (p: ProjectDto) => void
  }) =>
    isOpen ? (
      <div data-testid="create-modal">
        <button
          type="button"
          onClick={() =>
            onCreated({
              id: 'new-1',
              user_id: 'u1',
              title: 'New One',
              emoji: null,
              description: null,
              nsfw: false,
              pinned: false,
              sort_order: 0,
              knowledge_library_ids: [],
              created_at: '2026-05-04T00:00:00Z',
              updated_at: '2026-05-04T00:00:00Z',
            })
          }
        >
          create-mock
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
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  sanitisedState.value = false
  vi.clearAllMocks()
})

describe('ProjectPicker — list rendering', () => {
  it('renders the "— No project" row, the search input and the project list', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'a', title: 'Alpha' }))
    useProjectsStore.getState().upsert(makeProject({ id: 'b', title: 'Beta' }))

    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId={null} onClose={() => {}} />,
    )
    expect(screen.getByText('No project')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/search projects/i)).toBeInTheDocument()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
    expect(screen.getByText(/create new project/i)).toBeInTheDocument()
  })

  it('filters the project list by the search query (case-insensitive)', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'a', title: 'Star Trek' }))
    useProjectsStore.getState().upsert(makeProject({ id: 'b', title: 'Music' }))

    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId={null} onClose={() => {}} />,
    )
    const search = screen.getByPlaceholderText(/search projects/i)
    fireEvent.change(search, { target: { value: 'star' } })

    expect(screen.getByText('Star Trek')).toBeInTheDocument()
    expect(screen.queryByText('Music')).not.toBeInTheDocument()
  })

  it('hides NSFW projects when sanitised mode is on', async () => {
    sanitisedState.value = true
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'a', title: 'Tame', nsfw: false }))
    useProjectsStore.getState().upsert(makeProject({ id: 'b', title: 'Spicy', nsfw: true }))

    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId={null} onClose={() => {}} />,
    )
    expect(screen.getByText('Tame')).toBeInTheDocument()
    expect(screen.queryByText('Spicy')).not.toBeInTheDocument()
  })

  it('excludes the currently-active project from the picker if it is NSFW (§6.7)', async () => {
    // Spec: "What is already open stays open" — the chip shows the
    // active project (verified in ProjectSwitcher.test.tsx) but the
    // picker list is filtered.
    sanitisedState.value = true
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(
      makeProject({ id: 'p-spicy', title: 'Spicy', nsfw: true }),
    )
    useProjectsStore.getState().upsert(
      makeProject({ id: 'p-tame', title: 'Tame', nsfw: false }),
    )

    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker
        sessionId="s1"
        currentProjectId="p-spicy"
        onClose={() => {}}
      />,
    )
    expect(screen.queryByText('Spicy')).not.toBeInTheDocument()
    expect(screen.getByText('Tame')).toBeInTheDocument()
  })
})

describe('ProjectPicker — assignment', () => {
  it('calls setSessionProject(null) when "No project" is clicked', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.setSessionProject).mockResolvedValueOnce({ ok: true })

    const onClose = vi.fn()
    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId="p1" onClose={onClose} />,
    )
    fireEvent.click(screen.getByRole('option', { name: /no project/i }))

    // Microtask flush
    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.setSessionProject)).toHaveBeenCalledWith('s1', null)
    expect(onClose).toHaveBeenCalled()
  })

  it('calls setSessionProject with the chosen project id', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'p-x', title: 'X-Project' }))

    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.setSessionProject).mockResolvedValueOnce({ ok: true })

    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId={null} onClose={() => {}} />,
    )
    fireEvent.click(screen.getByRole('option', { name: /x-project/i }))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.setSessionProject)).toHaveBeenCalledWith('s1', 'p-x')
  })
})

describe('ProjectPicker — create flow', () => {
  it('opens the create-modal when "+ Create new project…" is clicked', async () => {
    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId={null} onClose={() => {}} />,
    )
    expect(screen.queryByTestId('create-modal')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText(/create new project/i))
    expect(screen.getByTestId('create-modal')).toBeInTheDocument()
  })

  it('auto-assigns the new project on create-success', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.setSessionProject).mockResolvedValueOnce({ ok: true })

    const onClose = vi.fn()
    const { ProjectPicker } = await import('../ProjectPicker')
    render(
      <ProjectPicker sessionId="s1" currentProjectId={null} onClose={onClose} />,
    )
    fireEvent.click(screen.getByText(/create new project/i))
    fireEvent.click(screen.getByText('create-mock'))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.setSessionProject)).toHaveBeenCalledWith('s1', 'new-1')
    expect(onClose).toHaveBeenCalled()
  })
})
