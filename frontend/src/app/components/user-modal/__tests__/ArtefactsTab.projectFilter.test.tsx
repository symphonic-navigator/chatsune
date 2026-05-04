// Mindspace projectFilter wiring for ArtefactsTab. Verifies that
// artefactApi.listAll is invoked with project_id when the prop is set.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { ArtefactListItem } from '../../../../core/types/artefact'
import type { PersonaDto } from '../../../../core/types/persona'

const listAllMock = vi.fn(
  async (): Promise<ArtefactListItem[]> => [],
)
vi.mock('../../../../core/api/artefact', () => ({
  artefactApi: {
    listAll: (...args: unknown[]) => listAllMock(...args),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

vi.mock('../../../../core/websocket/eventBus', () => ({
  eventBus: { on: () => () => undefined },
}))

const personasState = { value: [] as PersonaDto[] }
vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: personasState.value }),
}))

vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: () => ({ isSanitised: false }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  personasState.value = []
})

describe('ArtefactsTab — projectFilter', () => {
  it('passes project_id to artefactApi.listAll when filter is set', async () => {
    const { ArtefactsTab } = await import('../ArtefactsTab')
    render(<ArtefactsTab onClose={vi.fn()} projectFilter="proj-trek" />)
    await Promise.resolve()
    await Promise.resolve()
    expect(listAllMock).toHaveBeenCalledWith({ project_id: 'proj-trek' })
  })

  it('passes no params when filter is unset', async () => {
    const { ArtefactsTab } = await import('../ArtefactsTab')
    render(<ArtefactsTab onClose={vi.fn()} />)
    await Promise.resolve()
    await Promise.resolve()
    expect(listAllMock).toHaveBeenCalledWith(undefined)
  })
})
