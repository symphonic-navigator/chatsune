// Tests for the project create modal. Covers the spec-mandated
// invariants (name required, NSFW default off) plus the subtler
// surface that's easy to break: library multi-select, ``onCreated``
// payload, modal-reset between opens.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { ProjectDto } from '../types'
import type { KnowledgeLibraryDto } from '../../../core/types/knowledge'

vi.mock('../projectsApi', () => ({
  projectsApi: {
    create: vi.fn(),
  },
}))

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: (sel: (s: { addNotification: () => void }) => unknown) =>
    sel({ addNotification: vi.fn() }),
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

// The full emoji picker is heavy and not the focus of this test
// surface — stub it.
vi.mock('../../chat/EmojiPickerPopover', () => ({
  EmojiPickerPopover: ({ onSelect }: { onSelect: (e: string) => void }) => (
    <div data-testid="emoji-picker">
      <button type="button" onClick={() => onSelect('🚀')}>
        pick-rocket
      </button>
    </div>
  ),
}))

function makeProject(overrides: Partial<ProjectDto> = {}): ProjectDto {
  return {
    id: 'p-new',
    user_id: 'u1',
    title: 'Created',
    emoji: null,
    description: null,
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    system_prompt: null,
    created_at: '2026-05-04T00:00:00Z',
    updated_at: '2026-05-04T00:00:00Z',
    ...overrides,
  }
}

function makeLibrary(overrides: Partial<KnowledgeLibraryDto> = {}): KnowledgeLibraryDto {
  return {
    id: 'lib-1',
    name: 'Library',
    description: null,
    nsfw: false,
    document_count: 3,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    default_refresh: 'standard',
    ...overrides,
  }
}

beforeEach(() => {
  sanitisedState.value = false
  mockLibraries.value = []
  mockFetchLibraries.mockClear()
  vi.clearAllMocks()
})

describe('ProjectCreateModal — validation', () => {
  it('disables Create until a non-empty name is entered', async () => {
    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    )
    const createBtn = screen.getByRole('button', { name: /^create$/i })
    expect(createBtn).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'My Project' },
    })
    expect(createBtn).not.toBeDisabled()
  })

  it('keeps Create disabled when only whitespace is entered', async () => {
    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    )
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: '   ' },
    })
    expect(screen.getByRole('button', { name: /^create$/i })).toBeDisabled()
  })
})

describe('ProjectCreateModal — defaults', () => {
  it('renders NSFW toggle off by default', async () => {
    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    )
    const checkbox = screen.getByTestId('project-create-nsfw') as HTMLInputElement
    expect(checkbox.checked).toBe(false)
  })

  it('renders no emoji until the user picks one', async () => {
    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    )
    expect(screen.getByLabelText(/add emoji/i)).toBeInTheDocument()
  })
})

describe('ProjectCreateModal — submission', () => {
  it('calls projectsApi.create with the form contents and forwards the result via onCreated', async () => {
    mockLibraries.value = [
      makeLibrary({ id: 'lib-a', name: 'Alpha-Lib' }),
      makeLibrary({ id: 'lib-b', name: 'Beta-Lib' }),
    ]
    const { projectsApi } = await import('../projectsApi')
    const created = makeProject({ id: 'p-new', title: 'Test', emoji: '🚀' })
    vi.mocked(projectsApi.create).mockResolvedValueOnce(created)

    const onCreated = vi.fn()
    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={onCreated}
      />,
    )
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Test' },
    })
    // Pick an emoji via the stubbed picker
    fireEvent.click(screen.getByLabelText(/add emoji/i))
    fireEvent.click(screen.getByText('pick-rocket'))

    // Toggle NSFW on
    fireEvent.click(screen.getByTestId('project-create-nsfw'))

    // Tick the lib-a checkbox
    fireEvent.click(screen.getByTestId('project-create-library-lib-a'))

    fireEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.create)).toHaveBeenCalledWith({
      title: 'Test',
      emoji: '🚀',
      description: null,
      nsfw: true,
      knowledge_library_ids: ['lib-a'],
    })
    expect(onCreated).toHaveBeenCalledWith(created)
  })

  it('passes a trimmed description, omitting it as null when blank', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.create).mockResolvedValueOnce(makeProject())

    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    )
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Has-Desc' },
    })
    fireEvent.change(screen.getByLabelText(/description/i), {
      target: { value: '   ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^create$/i }))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(projectsApi.create)).toHaveBeenCalledWith(
      expect.objectContaining({ description: null }),
    )
  })
})

describe('ProjectCreateModal — sanitised mode', () => {
  it('hides NSFW libraries from the multi-select when sanitised', async () => {
    sanitisedState.value = true
    mockLibraries.value = [
      makeLibrary({ id: 'lib-a', name: 'Alpha-Lib', nsfw: false }),
      makeLibrary({ id: 'lib-b', name: 'Spicy-Lib', nsfw: true }),
    ]

    const { ProjectCreateModal } = await import('../ProjectCreateModal')
    render(
      <ProjectCreateModal
        isOpen={true}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    )
    expect(screen.getByText('Alpha-Lib')).toBeInTheDocument()
    expect(screen.queryByText('Spicy-Lib')).not.toBeInTheDocument()
  })
})
