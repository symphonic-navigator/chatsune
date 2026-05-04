// Tests for the Project-Detail-Overlay Overview tab. The tab is the
// busiest editing surface in Phase 9 — name, description, NSFW,
// libraries and the delete-stub all live here — so each editing
// affordance gets its own assertion.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ProjectDto } from '../types'
import type { KnowledgeLibraryDto } from '../../../core/types/knowledge'

// Stub the emoji picker — we only need to assert that picking one
// fires the right PATCH; the emoji-mart implementation is heavy.
vi.mock('../../chat/EmojiPickerPopover', () => ({
  EmojiPickerPopover: ({ onSelect }: { onSelect: (e: string) => void }) => (
    <div data-testid="emoji-picker">
      <button type="button" onClick={() => onSelect('🚀')}>
        pick-rocket
      </button>
    </div>
  ),
}))

const patchMock = vi.fn(
  async (_id: string, _body: Record<string, unknown>) => undefined,
)
const getMock = vi.fn(async (_id: string, _includeUsage?: boolean) => ({}))
const deleteMock = vi.fn(async (_id: string, _purgeData: boolean) => ({ ok: true }))
vi.mock('../projectsApi', () => ({
  projectsApi: {
    patch: (id: string, body: Record<string, unknown>) => patchMock(id, body),
    get: (id: string, includeUsage?: boolean) => getMock(id, includeUsage),
    delete: (id: string, purgeData: boolean) => deleteMock(id, purgeData),
  },
}))

const addNotificationMock = vi.fn()
vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: (sel: (s: { addNotification: typeof addNotificationMock }) => unknown) =>
    sel({ addNotification: addNotificationMock }),
}))

const sanitisedState = { value: false }
vi.mock('../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: sanitisedState.value }),
}))

const mockLibraries = { value: [] as KnowledgeLibraryDto[] }
const mockFetchLibraries = vi.fn(async () => {})
type KnowledgeStoreShape = {
  libraries: KnowledgeLibraryDto[]
  fetchLibraries: () => Promise<void>
}
vi.mock('../../../core/store/knowledgeStore', () => ({
  useKnowledgeStore: (sel: (s: KnowledgeStoreShape) => unknown) =>
    sel({
      libraries: mockLibraries.value,
      fetchLibraries: mockFetchLibraries,
    }),
}))

const projectsState = {
  value: makeProject(),
}

vi.mock('../useProjectsStore', () => ({
  useProjectsStore: (sel: (s: { projects: Record<string, ProjectDto> }) => unknown) =>
    sel({ projects: { [projectsState.value.id]: projectsState.value } }),
}))

const recentProjectEmojisState = { value: [] as string[] }
const setRecentProjectEmojisMock = vi.fn((emojis: string[]) => {
  recentProjectEmojisState.value = emojis
})
vi.mock('../recentProjectEmojisStore', () => {
  function useRecentProjectEmojisStore(
    sel: (s: { emojis: string[] }) => unknown,
  ): unknown {
    return sel({ emojis: recentProjectEmojisState.value })
  }
  // The component reads `.getState()` to push a freshly-picked emoji
  // to the LRU; mirror that path so the test can observe the call.
  ;(useRecentProjectEmojisStore as unknown as {
    getState: () => { set: typeof setRecentProjectEmojisMock }
  }).getState = () => ({ set: setRecentProjectEmojisMock })
  return { useRecentProjectEmojisStore }
})

function makeProject(overrides: Partial<ProjectDto> = {}): ProjectDto {
  return {
    id: 'p1',
    user_id: 'u1',
    title: 'Star Trek Fan Fiction',
    emoji: '🖖',
    description: 'About Captain Kirk',
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

function makeLibrary(overrides: Partial<KnowledgeLibraryDto> = {}): KnowledgeLibraryDto {
  return {
    id: 'lib-trek',
    name: 'Star Trek Lore',
    description: null,
    document_count: 42,
    nsfw: false,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-15T00:00:00Z',
    default_refresh: 'standard',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  patchMock.mockClear()
  addNotificationMock.mockClear()
  setRecentProjectEmojisMock.mockClear()
  projectsState.value = makeProject()
  mockLibraries.value = []
  recentProjectEmojisState.value = []
  sanitisedState.value = false
})

describe('ProjectOverviewTab — name', () => {
  it('saves the trimmed name on blur via projectsApi.patch', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    const input = screen.getByTestId('project-overview-name')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '  New Title  ' } })
    fireEvent.blur(input)

    expect(patchMock).toHaveBeenCalledWith('p1', { title: 'New Title' })
  })

  it('reverts an empty name and shows a warning notification', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    const input = screen.getByTestId('project-overview-name') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.blur(input)

    expect(patchMock).not.toHaveBeenCalled()
    expect(addNotificationMock).toHaveBeenCalledWith(
      expect.objectContaining({ level: 'warning' }),
    )
    expect(input.value).toBe('Star Trek Fan Fiction')
  })

  it('skips the patch when the trimmed name is unchanged', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    const input = screen.getByTestId('project-overview-name')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'Star Trek Fan Fiction' } })
    fireEvent.blur(input)

    expect(patchMock).not.toHaveBeenCalled()
  })
})

describe('ProjectOverviewTab — description', () => {
  it('saves the trimmed description on blur', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    const input = screen.getByTestId('project-overview-description')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '  Updated description  ' } })
    fireEvent.blur(input)

    expect(patchMock).toHaveBeenCalledWith('p1', { description: 'Updated description' })
  })

  it('clears the description when emptied', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    const input = screen.getByTestId('project-overview-description')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.blur(input)

    expect(patchMock).toHaveBeenCalledWith('p1', { description: null })
  })
})

describe('ProjectOverviewTab — NSFW', () => {
  it('toggles NSFW on click', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    fireEvent.click(screen.getByTestId('project-overview-nsfw'))
    expect(patchMock).toHaveBeenCalledWith('p1', { nsfw: true })
  })
})

describe('ProjectOverviewTab — libraries', () => {
  it('lists assigned libraries and removes one on ✕ click', async () => {
    mockLibraries.value = [makeLibrary({ id: 'lib-trek', name: 'Trek Lore' })]
    projectsState.value = makeProject({ knowledge_library_ids: ['lib-trek'] })
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    expect(
      screen.getByTestId('project-overview-library-lib-trek'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Remove Trek Lore'))
    expect(patchMock).toHaveBeenCalledWith('p1', {
      knowledge_library_ids: [],
    })
  })

  it('opens the picker dropdown and assigns a library on click', async () => {
    mockLibraries.value = [
      makeLibrary({ id: 'lib-trek', name: 'Trek Lore' }),
      makeLibrary({ id: 'lib-rom', name: 'Romulan Notes' }),
    ]
    projectsState.value = makeProject({ knowledge_library_ids: ['lib-trek'] })
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    fireEvent.click(screen.getByTestId('project-overview-add-library'))
    fireEvent.click(screen.getByTestId('project-overview-add-library-lib-rom'))
    expect(patchMock).toHaveBeenCalledWith('p1', {
      knowledge_library_ids: ['lib-trek', 'lib-rom'],
    })
  })
})

describe('ProjectOverviewTab — danger zone', () => {
  it('opens the DeleteProjectModal when delete is clicked', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    expect(screen.queryByTestId('delete-project-modal')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('project-overview-delete'))
    expect(screen.getByTestId('delete-project-modal')).toBeInTheDocument()
  })
})

describe('ProjectOverviewTab — emoji', () => {
  it('saves a picked emoji and pushes it to the recent LRU', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab projectId="p1" />)

    fireEvent.click(screen.getByTestId('project-overview-emoji'))
    fireEvent.click(screen.getByText('pick-rocket'))
    // The handler awaits the PATCH before pushing to the LRU; flush
    // pending microtasks before asserting on the LRU mutation.
    await Promise.resolve()
    await Promise.resolve()

    expect(patchMock).toHaveBeenCalledWith('p1', { emoji: '🚀' })
    expect(setRecentProjectEmojisMock).toHaveBeenCalledWith(['🚀'])
  })
})
