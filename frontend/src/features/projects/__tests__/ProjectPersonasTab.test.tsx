// Tests for the Project-Detail-Overlay Personas tab. Covers spec
// invariants: alphabetical order, Start-chat-here side-effects (create
// session + assign + navigate), Remove-from-project PATCH,
// add-picker, switch-confirmation when picking a persona that already
// has a different default project.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ProjectDto } from '../types'
import type { PersonaDto } from '../../../core/types/persona'

const navigateMock = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}))

const updatePersonaMock = vi.fn(async () => undefined)
const personasState = { value: [] as PersonaDto[] }
vi.mock('../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({
    personas: personasState.value,
    update: updatePersonaMock,
  }),
}))

const projectsState = {
  value: {} as Record<string, ProjectDto>,
}
vi.mock('../useProjectsStore', () => ({
  useProjectsStore: (sel: (s: { projects: Record<string, ProjectDto> }) => unknown) =>
    sel({ projects: projectsState.value }),
}))

const sanitisedState = { value: false }
vi.mock('../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: sanitisedState.value }),
}))

const addNotificationMock = vi.fn()
vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: (sel: (s: { addNotification: typeof addNotificationMock }) => unknown) =>
    sel({ addNotification: addNotificationMock }),
}))

const createSessionMock = vi.fn(
  async (_personaId: string, _projectId?: string | null) => ({
    id: 'sess-new',
    persona_id: 'p-worf',
  }),
)
vi.mock('../../../core/api/chat', () => ({
  chatApi: {
    createSession: (personaId: string, projectId?: string | null) =>
      createSessionMock(personaId, projectId),
  },
}))

function makePersona(overrides: Partial<PersonaDto> = {}): PersonaDto {
  return {
    id: 'p-worf',
    user_id: 'u1',
    name: 'Mr. Worf',
    tagline: 'Klingon security officer',
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
    monogram: 'W',
    pinned: false,
    profile_image: null,
    profile_crop: null,
    mcp_config: null,
    integrations_config: null,
    voice_config: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-15T00:00:00Z',
    default_project_id: null,
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
    system_prompt: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  navigateMock.mockClear()
  updatePersonaMock.mockClear()
  createSessionMock.mockClear()
  personasState.value = []
  projectsState.value = {}
  sanitisedState.value = false
})

describe('ProjectPersonasTab — list', () => {
  it('renders default personas alphabetically', async () => {
    personasState.value = [
      makePersona({ id: 'p-worf', name: 'Mr. Worf', default_project_id: 'proj-trek' }),
      makePersona({
        id: 'p-schiller',
        name: 'Friedrich Schiller',
        default_project_id: 'proj-trek',
        monogram: 'F',
      }),
    ]
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={vi.fn()} />)

    const rows = screen.getAllByTestId(/^project-personas-row-/)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Friedrich Schiller')
    expect(rows[1]).toHaveTextContent('Mr. Worf')
  })

  it('shows the empty state when no personas default to this project', async () => {
    personasState.value = [makePersona({ default_project_id: 'other' })]
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={vi.fn()} />)
    expect(screen.getByText('No default personas yet')).toBeInTheDocument()
  })
})

describe('ProjectPersonasTab — start chat', () => {
  it('creates a session pre-attached to the project, navigates and closes', async () => {
    personasState.value = [
      makePersona({ id: 'p-worf', default_project_id: 'proj-trek' }),
    ]
    const onClose = vi.fn()
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={onClose} />)

    fireEvent.click(screen.getByTestId('project-personas-start-p-worf'))
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    // Single call — backend ``POST /api/chat/sessions`` accepts
    // ``project_id`` directly so the redundant ``setSessionProject``
    // follow-up is gone.
    expect(createSessionMock).toHaveBeenCalledWith('p-worf', 'proj-trek')
    expect(createSessionMock).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalled()
    expect(navigateMock).toHaveBeenCalledWith('/chat/p-worf/sess-new')
  })
})

describe('ProjectPersonasTab — remove', () => {
  it('clears the persona default-project pointer via update', async () => {
    personasState.value = [
      makePersona({ id: 'p-worf', default_project_id: 'proj-trek' }),
    ]
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={vi.fn()} />)

    fireEvent.click(screen.getByTestId('project-personas-remove-p-worf'))
    await Promise.resolve()
    await Promise.resolve()

    expect(updatePersonaMock).toHaveBeenCalledWith('p-worf', {
      default_project_id: null,
    })
  })
})

describe('ProjectPersonasTab — add picker', () => {
  it('shows candidates and assigns the picked persona without confirmation when free', async () => {
    personasState.value = [
      makePersona({ id: 'p-spock', name: 'Spock', default_project_id: null }),
    ]
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={vi.fn()} />)

    fireEvent.click(screen.getByTestId('project-personas-add'))
    fireEvent.click(screen.getByTestId('project-personas-pick-p-spock'))
    await Promise.resolve()
    await Promise.resolve()

    expect(updatePersonaMock).toHaveBeenCalledWith('p-spock', {
      default_project_id: 'proj-trek',
    })
  })

  it('hides NSFW personas in sanitised mode', async () => {
    sanitisedState.value = true
    personasState.value = [
      makePersona({ id: 'p-clean', name: 'Clean Persona' }),
      makePersona({ id: 'p-spicy', name: 'Spicy Persona', nsfw: true }),
    ]
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={vi.fn()} />)

    fireEvent.click(screen.getByTestId('project-personas-add'))
    expect(screen.queryByTestId('project-personas-pick-p-spicy')).toBeNull()
    expect(screen.getByTestId('project-personas-pick-p-clean')).toBeInTheDocument()
  })

  it('opens the switch-confirmation when the persona already has a different default', async () => {
    projectsState.value = {
      'proj-other': makeProject({ id: 'proj-other', title: 'Other Mindspace' }),
    }
    personasState.value = [
      makePersona({ id: 'p-spock', name: 'Spock', default_project_id: 'proj-other' }),
    ]
    const { ProjectPersonasTab } = await import('../tabs/ProjectPersonasTab')
    render(<ProjectPersonasTab projectId="proj-trek" onClose={vi.fn()} />)

    fireEvent.click(screen.getByTestId('project-personas-add'))
    fireEvent.click(screen.getByTestId('project-personas-pick-p-spock'))

    expect(screen.getByTestId('project-personas-switch-confirm')).toBeInTheDocument()
    expect(screen.getByText('Other Mindspace', { exact: false })).toBeInTheDocument()
    expect(updatePersonaMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('project-personas-switch-confirm-go'))
    await Promise.resolve()
    await Promise.resolve()
    expect(updatePersonaMock).toHaveBeenCalledWith('p-spock', {
      default_project_id: 'proj-trek',
    })
  })
})
