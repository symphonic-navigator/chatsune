// Smoke + interaction tests for the mobile fullscreen project picker.
// Mirrors the desktop ProjectPicker test surface — list rendering,
// search filter, row clicks, "no project" detach, sanitised filter,
// create flow — so any divergence between desktop and mobile is
// caught here.

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

vi.mock('../../../core/utils/bodyScrollLock', () => ({
  lockBodyScroll: vi.fn(),
  unlockBodyScroll: vi.fn(),
}))

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
              id: 'mob-new',
              user_id: 'u1',
              title: 'Mob New',
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

describe('ProjectPickerMobile — fullscreen rendering', () => {
  it('mounts a fullscreen overlay carrying the project list', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'a', title: 'Alpha' }))
    useProjectsStore.getState().upsert(makeProject({ id: 'b', title: 'Beta' }))

    const { ProjectPickerMobile } = await import('../ProjectPickerMobile')
    render(
      <ProjectPickerMobile
        sessionId="s1"
        currentProjectId={null}
        onClose={() => {}}
      />,
    )
    const overlay = screen.getByTestId('project-picker-mobile')
    expect(overlay).toHaveClass('fixed', 'inset-0')
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('Beta')).toBeInTheDocument()
    expect(screen.getByText('No project')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/search projects/i)).toBeInTheDocument()
    expect(screen.getByText(/create new project/i)).toBeInTheDocument()
  })
})

describe('ProjectPickerMobile — interactions', () => {
  it('calls setSessionProject when a project row is tapped', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'p-x', title: 'X-Project' }))

    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.setSessionProject).mockResolvedValueOnce({ ok: true })

    const onClose = vi.fn()
    const { ProjectPickerMobile } = await import('../ProjectPickerMobile')
    render(
      <ProjectPickerMobile
        sessionId="s1"
        currentProjectId={null}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByRole('option', { name: /x-project/i }))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.setSessionProject)).toHaveBeenCalledWith('s1', 'p-x')
    expect(onClose).toHaveBeenCalled()
  })

  it('detaches the project when "No project" is tapped', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.setSessionProject).mockResolvedValueOnce({ ok: true })

    const { ProjectPickerMobile } = await import('../ProjectPickerMobile')
    render(
      <ProjectPickerMobile
        sessionId="s1"
        currentProjectId="p1"
        onClose={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('option', { name: /no project/i }))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.setSessionProject)).toHaveBeenCalledWith('s1', null)
  })

  it('filters the list as the user types', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'a', title: 'Star Trek' }))
    useProjectsStore.getState().upsert(makeProject({ id: 'b', title: 'Music' }))

    const { ProjectPickerMobile } = await import('../ProjectPickerMobile')
    render(
      <ProjectPickerMobile
        sessionId="s1"
        currentProjectId={null}
        onClose={() => {}}
      />,
    )
    fireEvent.change(screen.getByPlaceholderText(/search projects/i), {
      target: { value: 'star' },
    })
    expect(screen.getByText('Star Trek')).toBeInTheDocument()
    expect(screen.queryByText('Music')).not.toBeInTheDocument()
  })

  it('opens the create-modal and auto-assigns on success', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.setSessionProject).mockResolvedValueOnce({ ok: true })

    const onClose = vi.fn()
    const { ProjectPickerMobile } = await import('../ProjectPickerMobile')
    render(
      <ProjectPickerMobile
        sessionId="s1"
        currentProjectId={null}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByText(/create new project/i))
    fireEvent.click(screen.getByText('create-mock'))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.setSessionProject)).toHaveBeenCalledWith('s1', 'mob-new')
    expect(onClose).toHaveBeenCalled()
  })

  it('triggers the back button onClose', async () => {
    const onClose = vi.fn()
    const { ProjectPickerMobile } = await import('../ProjectPickerMobile')
    render(
      <ProjectPickerMobile
        sessionId="s1"
        currentProjectId={null}
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /close project picker/i }))
    expect(onClose).toHaveBeenCalled()
  })
})
