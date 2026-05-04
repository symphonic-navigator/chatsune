// Tests for the Mindspace projectFilter / include-project-chats
// extensions to HistoryTab. Other history-tab behaviour (search,
// pin, rename, delete) is covered by indirect renders elsewhere.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ChatSessionDto } from '../../../../core/api/chat'
import type { PersonaDto } from '../../../../core/types/persona'
import type { ProjectDto } from '../../../../features/projects/types'

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

const listSessionsMock = vi.fn(
  async (_params?: {
    project_id?: string
    include_project_chats?: boolean
  }): Promise<ChatSessionDto[]> => [],
)
const updateSessionPinnedMock = vi.fn(
  async (_sessionId: string, _pinned: boolean) => undefined,
)
const searchSessionsMock = vi.fn(
  async (_params: {
    q: string
    persona_id?: string
    exclude_persona_ids?: string[]
  }): Promise<ChatSessionDto[]> => [],
)
vi.mock('../../../../core/api/chat', () => ({
  chatApi: {
    listSessions: (params?: {
      project_id?: string
      include_project_chats?: boolean
    }) => listSessionsMock(params),
    searchSessions: (params: { q: string; persona_id?: string; exclude_persona_ids?: string[] }) =>
      searchSessionsMock(params),
    updateSessionPinned: (sessionId: string, pinned: boolean) =>
      updateSessionPinnedMock(sessionId, pinned),
  },
}))

const defaultSessionsState = { value: [] as ChatSessionDto[], loading: false }
vi.mock('../../../../core/hooks/useChatSessions', () => ({
  useChatSessions: () => ({
    sessions: defaultSessionsState.value,
    isLoading: defaultSessionsState.loading,
  }),
}))

const personasState = { value: [] as PersonaDto[] }
vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: personasState.value }),
}))

const drawerState = { open: false }
vi.mock('../../../../core/store/drawerStore', () => ({
  useDrawerStore: Object.assign(
    (sel: (s: { sidebarOpen: boolean }) => unknown) =>
      sel({ sidebarOpen: drawerState.open }),
    { getState: () => ({ sidebarOpen: drawerState.open }) },
  ),
}))

const sanitisedState = { value: false }
vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: sanitisedState.value }),
}))

const projectsState = {
  value: {} as Record<string, ProjectDto>,
}
vi.mock('../../../../features/projects/useProjectsStore', () => ({
  useProjectsStore: (sel: (s: { projects: Record<string, ProjectDto> }) => unknown) =>
    sel({ projects: projectsState.value }),
}))

vi.mock('../../../../core/websocket/eventBus', () => ({
  eventBus: { on: () => () => undefined },
}))

const safeStorageState: Record<string, string> = {}
vi.mock('../../../../core/utils/safeStorage', () => ({
  safeLocalStorage: {
    getItem: (k: string) => safeStorageState[k] ?? null,
    setItem: (k: string, v: string) => {
      safeStorageState[k] = v
    },
    removeItem: (k: string) => {
      delete safeStorageState[k]
    },
    hasItem: (k: string) => k in safeStorageState,
  },
}))

function makeSession(overrides: Partial<ChatSessionDto> = {}): ChatSessionDto {
  return {
    id: 's1',
    user_id: 'u1',
    persona_id: 'p1',
    state: 'idle',
    title: 'Session title',
    tools_enabled: false,
    auto_read: false,
    reasoning_override: null,
    pinned: false,
    project_id: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

function makePersona(overrides: Partial<PersonaDto> = {}): PersonaDto {
  return {
    id: 'p1',
    user_id: 'u1',
    name: 'Persona One',
    tagline: '',
    model_unique_id: null,
    system_prompt: '',
    temperature: 0.8,
    reasoning_enabled: false,
    soft_cot_enabled: false,
    vision_fallback_model: null,
    nsfw: false,
    use_memory: true,
    colour_scheme: 'heart',
    display_order: 0,
    monogram: 'P',
    pinned: false,
    profile_image: null,
    profile_crop: null,
    mcp_config: null,
    integrations_config: null,
    voice_config: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-15T00:00:00Z',
    ...overrides,
  }
}

function makeProject(overrides: Partial<ProjectDto> = {}): ProjectDto {
  return {
    id: 'proj-trek',
    user_id: 'u1',
    title: 'Star Trek Fan Fiction',
    emoji: '🖖',
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
  vi.clearAllMocks()
  for (const key of Object.keys(safeStorageState)) delete safeStorageState[key]
  defaultSessionsState.value = []
  personasState.value = [makePersona()]
  projectsState.value = {}
  sanitisedState.value = false
  listSessionsMock.mockReset()
  listSessionsMock.mockResolvedValue([])
})

describe('HistoryTab — projectFilter', () => {
  it('hides the include-project-chats toggle when scoped to a single project', async () => {
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} projectFilter="proj-trek" />)
    expect(
      screen.queryByTestId('history-include-project-chats'),
    ).toBeNull()
  })

  it('fetches the project-scoped list when projectFilter is set', async () => {
    listSessionsMock.mockResolvedValue([
      makeSession({ id: 's-trek', project_id: 'proj-trek' }),
    ])
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} projectFilter="proj-trek" />)
    // Allow the useEffect-driven fetch to settle.
    await Promise.resolve()
    await Promise.resolve()
    expect(listSessionsMock).toHaveBeenCalledWith({
      project_id: 'proj-trek',
      include_project_chats: false,
    })
  })

  it('does NOT render the project pill when scoped to a single project', async () => {
    listSessionsMock.mockResolvedValue([
      makeSession({ id: 's-trek', project_id: 'proj-trek' }),
    ])
    projectsState.value = { 'proj-trek': makeProject() }
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} projectFilter="proj-trek" />)
    await Promise.resolve()
    await Promise.resolve()
    expect(screen.queryByTestId('history-project-pill')).toBeNull()
  })
})

describe('HistoryTab — global UserModal context', () => {
  it('shows the toggle and defaults it to off', async () => {
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} />)
    const toggle = screen.getByTestId(
      'history-include-project-chats',
    ) as HTMLInputElement
    expect(toggle.checked).toBe(false)
  })

  it('persists the toggle state via safeLocalStorage', async () => {
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} />)
    fireEvent.click(screen.getByTestId('history-include-project-chats'))
    expect(safeStorageState['chatsune.history.includeProjectChats']).toBe('true')
  })

  it('reads the toggle state back from safeLocalStorage on next mount', async () => {
    safeStorageState['chatsune.history.includeProjectChats'] = 'true'
    listSessionsMock.mockResolvedValue([])
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} />)
    const toggle = screen.getByTestId(
      'history-include-project-chats',
    ) as HTMLInputElement
    expect(toggle.checked).toBe(true)
    // Allow the fetch to fire — when toggle is on we hit listSessions.
    await Promise.resolve()
    await Promise.resolve()
    expect(listSessionsMock).toHaveBeenCalledWith({
      project_id: undefined,
      include_project_chats: true,
    })
  })

  it('renders the project pill on project-bound sessions when toggle is on', async () => {
    safeStorageState['chatsune.history.includeProjectChats'] = 'true'
    projectsState.value = { 'proj-trek': makeProject() }
    listSessionsMock.mockResolvedValue([
      makeSession({ id: 's-trek', project_id: 'proj-trek' }),
    ])
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} />)
    expect(
      await screen.findByTestId('history-project-pill'),
    ).toHaveTextContent('Star Trek Fan Fiction')
  })

  it('hides chats whose project is NSFW in sanitised mode', async () => {
    safeStorageState['chatsune.history.includeProjectChats'] = 'true'
    sanitisedState.value = true
    projectsState.value = {
      'proj-spicy': makeProject({ id: 'proj-spicy', nsfw: true }),
    }
    listSessionsMock.mockResolvedValue([
      makeSession({ id: 's-spicy', project_id: 'proj-spicy', title: 'Spicy chat' }),
    ])
    const { HistoryTab } = await import('../HistoryTab')
    render(<HistoryTab onClose={vi.fn()} />)
    // No project-bound session is expected — wait for the fetch then
    // verify the spicy chat title isn't there.
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByText('Spicy chat')).toBeNull()
  })
})
