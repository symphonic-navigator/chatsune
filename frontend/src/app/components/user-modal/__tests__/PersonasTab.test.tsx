import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { PersonasTab } from '../PersonasTab'

const mockReorder = vi.fn()
const mockUpdate = vi.fn()
let mockPersonas: any[] = []
let mockSanitised = false

vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: mockPersonas, reorder: mockReorder, update: mockUpdate }),
}))
vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: any) => sel({ isSanitised: mockSanitised }),
}))

function makePersona(overrides: any = {}) {
  return {
    id: 'p1',
    name: 'Aria',
    monogram: 'AR',
    tagline: 'A kind voice',
    profile_image: false,
    profile_crop: null,
    colour_scheme: 'crown',
    model_unique_id: 'ollama_cloud:llama3.2',
    display_order: 0,
    pinned: false,
    nsfw: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

beforeEach(() => {
  mockReorder.mockReset()
  mockUpdate.mockReset()
  mockPersonas = []
  mockSanitised = false
})

describe('PersonasTab', () => {
  it('renders pinned personas first, preserving state order otherwise', () => {
    // State order from API is already sorted by display_order; we only partition by pinned.
    mockPersonas = [
      makePersona({ id: 'b', name: 'Beta', display_order: 0, pinned: false }),
      makePersona({ id: 'a', name: 'Alpha', display_order: 2, pinned: false }),
      makePersona({ id: 'c', name: 'Gamma', display_order: 5, pinned: true }),
    ]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} onCreatePersona={vi.fn()} />)
    const rows = screen.getAllByTestId('persona-row')
    expect(rows.map((r) => r.getAttribute('data-persona-id'))).toEqual(['c', 'b', 'a'])
  })

  it('hides nsfw personas in sanitised mode', () => {
    mockSanitised = true
    mockPersonas = [
      makePersona({ id: 'a', name: 'Alpha', nsfw: false }),
      makePersona({ id: 'b', name: 'Beta', nsfw: true }),
    ]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} onCreatePersona={vi.fn()} />)
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders model identifier in monospace', () => {
    mockPersonas = [makePersona({ model_unique_id: 'ollama_cloud:llama3.2' })]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} onCreatePersona={vi.fn()} />)
    expect(screen.getByText('llama3.2')).toBeInTheDocument()
  })

  it('row click opens overlay with persona id', () => {
    const onOpen = vi.fn()
    mockPersonas = [makePersona({ id: 'p1' })]
    render(<PersonasTab onOpenPersonaOverlay={onOpen} onCreatePersona={vi.fn()} />)
    fireEvent.click(screen.getByTestId('persona-row-body'))
    expect(onOpen).toHaveBeenCalledWith('p1')
  })

  it('pin toggle calls update with inverted pinned and does not trigger row click', () => {
    const onOpen = vi.fn()
    mockPersonas = [makePersona({ id: 'p1', pinned: false })]
    render(<PersonasTab onOpenPersonaOverlay={onOpen} onCreatePersona={vi.fn()} />)
    fireEvent.click(screen.getByTestId('persona-pin-toggle'))
    expect(mockUpdate).toHaveBeenCalledWith('p1', { pinned: true })
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('shows nsfw indicator when not sanitised and persona is nsfw', () => {
    mockPersonas = [makePersona({ id: 'p1', nsfw: true })]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} onCreatePersona={vi.fn()} />)
    expect(screen.getByTestId('persona-nsfw-indicator')).toBeInTheDocument()
  })

  it('reorder via drag-end calls reorder with new order', () => {
    mockPersonas = [
      makePersona({ id: 'a', name: 'Alpha', display_order: 0 }),
      makePersona({ id: 'b', name: 'Beta', display_order: 1 }),
      makePersona({ id: 'c', name: 'Gamma', display_order: 2 }),
    ]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} onCreatePersona={vi.fn()} />)
    const helper = (window as any).__personasTabTestHelper
    expect(helper).toBeDefined()
    helper.simulateReorder('a', 'c')
    expect(mockReorder).toHaveBeenCalledWith(['b', 'c', 'a'])
  })
})
