import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MobileNewChatView } from './MobileNewChatView'
import type { PersonaDto } from '../../../core/types/persona'

const aria = {
  id: 'aria', name: 'Aria', monogram: 'A',
  pinned: true, nsfw: false,
  colour_scheme: 'root',
} as unknown as PersonaDto

const lyra = {
  id: 'lyra', name: 'Lyra', monogram: 'L',
  pinned: true, nsfw: true,
  colour_scheme: 'crown',
} as unknown as PersonaDto

const marcus = {
  id: 'marcus', name: 'Marcus the Stoic', monogram: 'M',
  pinned: false, nsfw: false,
  colour_scheme: 'heart',
} as unknown as PersonaDto

const thorne = {
  id: 'thorne', name: 'Thorne', monogram: 'T',
  pinned: false, nsfw: true,
  colour_scheme: 'root',
} as unknown as PersonaDto

let mockIsSanitised = false
vi.mock('../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) => sel({ isSanitised: mockIsSanitised }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  mockIsSanitised = false
})

function renderView(personas: PersonaDto[], onSelect: (p: PersonaDto) => void = () => {}) {
  return render(
    <MemoryRouter>
      <MobileNewChatView personas={personas} onSelect={onSelect} />
    </MemoryRouter>
  )
}

describe('MobileNewChatView — sections', () => {
  it('renders Pinned section header only when pinned personas exist', () => {
    renderView([aria, marcus])
    expect(screen.getByText('Pinned')).toBeInTheDocument()
    expect(screen.getByText('Other')).toBeInTheDocument()
  })

  it('omits Pinned header when no pinned personas', () => {
    renderView([marcus, thorne])
    expect(screen.queryByText('Pinned')).not.toBeInTheDocument()
    expect(screen.getByText('Other')).toBeInTheDocument()
  })

  it('omits Other header when no unpinned personas', () => {
    renderView([aria, lyra])
    expect(screen.getByText('Pinned')).toBeInTheDocument()
    expect(screen.queryByText('Other')).not.toBeInTheDocument()
  })

  it('renders empty-state when no personas at all', () => {
    renderView([])
    expect(screen.getByText(/no personas yet/i)).toBeInTheDocument()
  })
})

describe('MobileNewChatView — NSFW pill', () => {
  it('renders the NSFW pill for NSFW personas', () => {
    renderView([aria, lyra])
    const pills = screen.getAllByText('NSFW')
    expect(pills).toHaveLength(1)
  })

  it('does not render NSFW pill for non-NSFW personas', () => {
    renderView([aria, marcus])
    expect(screen.queryByText('NSFW')).not.toBeInTheDocument()
  })
})

describe('MobileNewChatView — sanitised mode', () => {
  it('hides NSFW personas from the list when sanitised mode is on', () => {
    mockIsSanitised = true
    renderView([aria, lyra, marcus, thorne])
    expect(screen.getByText('Aria')).toBeInTheDocument()
    expect(screen.getByText('Marcus the Stoic')).toBeInTheDocument()
    expect(screen.queryByText('Lyra')).not.toBeInTheDocument()
    expect(screen.queryByText('Thorne')).not.toBeInTheDocument()
    expect(screen.queryByText('NSFW')).not.toBeInTheDocument()
  })
})

describe('MobileNewChatView — selection', () => {
  it('calls onSelect with the persona when a row is tapped', async () => {
    const onSelect = vi.fn()
    renderView([aria, marcus], onSelect)
    await userEvent.click(screen.getByText('Marcus the Stoic'))
    expect(onSelect).toHaveBeenCalledWith(marcus)
  })
})
