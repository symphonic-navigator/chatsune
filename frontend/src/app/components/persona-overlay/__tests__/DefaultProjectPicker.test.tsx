// Behaviour tests for the persona Overview tab default-project picker.
// The picker is the single new affordance in Phase 10 / Task 39 — it
// PATCHes ``personas/{id}.default_project_id`` and renders the
// chosen project as a chip; the rest of the Overview tab is
// unaffected.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { PersonaDto } from '../../../../core/types/persona'
import type { ProjectDto } from '../../../../features/projects/types'
import { CHAKRA_PALETTE } from '../../../../core/types/chakra'

vi.mock('../../../../core/api/personas', () => ({
  personasApi: {
    update: vi.fn(),
  },
}))

const sanitisedState = { value: false }
vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: sanitisedState.value }),
}))

vi.mock('../../../../core/store/notificationStore', () => ({
  useNotificationStore: (sel: (s: { addNotification: () => void }) => unknown) =>
    sel({ addNotification: vi.fn() }),
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

function makePersona(overrides: Partial<PersonaDto> = {}): PersonaDto {
  return {
    id: 'persona-1',
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
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    default_project_id: null,
    ...overrides,
  }
}

beforeEach(() => {
  sanitisedState.value = false
  vi.clearAllMocks()
})

describe('DefaultProjectPicker — rendering', () => {
  it('renders a "No default" chip when persona has no default project', async () => {
    const { DefaultProjectPicker } = await import('../DefaultProjectPicker')
    render(
      <DefaultProjectPicker
        persona={makePersona()}
        chakra={CHAKRA_PALETTE.heart}
      />,
    )
    expect(screen.getByText('Default project')).toBeInTheDocument()
    expect(screen.getByText('No default')).toBeInTheDocument()
  })

  it('renders the assigned project chip when persona has a default', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore.getState().upsert(
      makeProject({ id: 'p-trek', title: 'Star Trek', emoji: '✨' }),
    )

    const { DefaultProjectPicker } = await import('../DefaultProjectPicker')
    render(
      <DefaultProjectPicker
        persona={makePersona({ default_project_id: 'p-trek' })}
        chakra={CHAKRA_PALETTE.heart}
      />,
    )
    expect(screen.getByText('Star Trek')).toBeInTheDocument()
    expect(screen.getByText('✨')).toBeInTheDocument()
  })

  it('opens the picker dropdown on trigger click', async () => {
    const { DefaultProjectPicker } = await import('../DefaultProjectPicker')
    render(
      <DefaultProjectPicker
        persona={makePersona()}
        chakra={CHAKRA_PALETTE.heart}
      />,
    )
    expect(
      screen.queryByTestId('persona-default-project-picker'),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('persona-default-project-trigger'))

    expect(
      screen.getByTestId('persona-default-project-picker'),
    ).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/search projects/i)).toBeInTheDocument()
  })

  it('hides NSFW projects from the picker list when sanitised mode is on', async () => {
    sanitisedState.value = true
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore.getState().upsert(
      makeProject({ id: 'p-tame', title: 'Tame', nsfw: false }),
    )
    useProjectsStore.getState().upsert(
      makeProject({ id: 'p-spicy', title: 'Spicy', nsfw: true }),
    )

    const { DefaultProjectPicker } = await import('../DefaultProjectPicker')
    render(
      <DefaultProjectPicker
        persona={makePersona()}
        chakra={CHAKRA_PALETTE.heart}
      />,
    )
    fireEvent.click(screen.getByTestId('persona-default-project-trigger'))

    expect(screen.getByText('Tame')).toBeInTheDocument()
    expect(screen.queryByText('Spicy')).not.toBeInTheDocument()
  })
})

describe('DefaultProjectPicker — assignment', () => {
  it('PATCHes the persona with the picked project id', async () => {
    const { useProjectsStore } = await import(
      '../../../../features/projects/useProjectsStore'
    )
    useProjectsStore.getState().upsert(
      makeProject({ id: 'p-trek', title: 'Star Trek' }),
    )

    const { personasApi } = await import('../../../../core/api/personas')
    vi.mocked(personasApi.update).mockResolvedValueOnce(makePersona())

    const { DefaultProjectPicker } = await import('../DefaultProjectPicker')
    render(
      <DefaultProjectPicker
        persona={makePersona()}
        chakra={CHAKRA_PALETTE.heart}
      />,
    )
    fireEvent.click(screen.getByTestId('persona-default-project-trigger'))
    fireEvent.click(screen.getByTestId('persona-default-project-pick-p-trek'))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(personasApi.update)).toHaveBeenCalledWith(
      'persona-1',
      { default_project_id: 'p-trek' },
    )
  })

  it('PATCHes default_project_id=null when "No default" is clicked', async () => {
    const { personasApi } = await import('../../../../core/api/personas')
    vi.mocked(personasApi.update).mockResolvedValueOnce(makePersona())

    const { DefaultProjectPicker } = await import('../DefaultProjectPicker')
    render(
      <DefaultProjectPicker
        persona={makePersona({ default_project_id: 'p-old' })}
        chakra={CHAKRA_PALETTE.heart}
      />,
    )
    fireEvent.click(screen.getByTestId('persona-default-project-trigger'))
    fireEvent.click(screen.getByTestId('persona-default-project-clear'))

    await new Promise((r) => setTimeout(r, 0))
    expect(vi.mocked(personasApi.update)).toHaveBeenCalledWith(
      'persona-1',
      { default_project_id: null },
    )
  })
})
