import { fireEvent, render, screen } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMemoryBatchStore } from '../../core/store/memoryBatchStore'
import type {
  MemoryBatchDto,
  MemoryBatchPausedAtDto,
} from '../../core/api/chatGptImportApi'
import { MemoryBatchProgressPanel } from './MemoryBatchProgressPanel'

// Mock the API module before the panel imports it.
vi.mock('../../core/api/chatGptImportApi', async () => {
  const actual = await vi.importActual<object>(
    '../../core/api/chatGptImportApi',
  )
  return {
    ...actual,
    chatGptImportApi: {
      resumeMemoryBatch: vi.fn(),
      discardMemoryBatch: vi.fn(),
      getMemoryBatch: vi.fn(),
    },
  }
})

import { chatGptImportApi } from '../../core/api/chatGptImportApi'

function baseDto(overrides: Partial<MemoryBatchDto> = {}): MemoryBatchDto {
  return {
    import_id: 'imp-1',
    persona_id: 'persona-1',
    state: 'running',
    target_count: 7,
    conversations_imported: 7,
    permanent_failures: 0,
    session_ids: ['s1', 's2', 's3', 's4', 's5', 's6', 's7'],
    paused_at: null,
    total_entries_created: 0,
    created_at: '2026-05-12T10:00:00Z',
    updated_at: '2026-05-12T10:00:00Z',
    ...overrides,
  }
}

function pausedAt(reason: MemoryBatchPausedAtDto['reason']): MemoryBatchPausedAtDto {
  return {
    session_index: 3,
    session_id: 's3',
    reason,
    user_message:
      reason === 'budget_exhausted'
        ? 'Daily budget exhausted'
        : 'Provider not reachable',
    detail: null,
    at: '2026-05-12T10:05:00Z',
  }
}

beforeEach(() => {
  useMemoryBatchStore.setState({ batches: {} })
  vi.clearAllMocks()
})

afterEach(() => {
  useMemoryBatchStore.setState({ batches: {} })
})

describe('MemoryBatchProgressPanel', () => {
  it('renders nothing when no batch is present', () => {
    const { container } = render(
      <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when state is discarded', () => {
    useMemoryBatchStore.getState().setBatch(baseDto({ state: 'discarded' }))
    const { container } = render(
      <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  describe('running state', () => {
    beforeEach(() => {
      useMemoryBatchStore.getState().setBatch(baseDto())
      useMemoryBatchStore.getState().handleProgressEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        session_id: 's3',
        session_title: 'Hühnerbrust Geschnetzeltes',
        session_index: 3,
        total: 7,
        state: 'extracting',
        entries_created: null,
      })
    })

    it('shows progress bar and currently-processing title', () => {
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      expect(screen.getByText(/Memory extraction/)).toBeInTheDocument()
      // "2 / 7" — current_session_index is 3, so 3-1=2 done
      expect(screen.getByText('2 / 7')).toBeInTheDocument()
      expect(screen.getByText(/Currently processing/)).toBeInTheDocument()
      expect(
        screen.getByText(/Hühnerbrust Geschnetzeltes/),
      ).toBeInTheDocument()
      const bar = screen.getByRole('progressbar')
      expect(bar).toHaveAttribute('aria-valuenow', '29') // 2/7 rounded
    })
  })

  describe('paused — provider_unavailable', () => {
    beforeEach(() => {
      useMemoryBatchStore.getState().setBatch(
        baseDto({ state: 'paused', paused_at: pausedAt('provider_unavailable') }),
      )
    })

    it('renders Resume + Discard buttons, no force-budget variant', () => {
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      expect(screen.getByText(/Memory extraction paused/)).toBeInTheDocument()
      expect(screen.getByText(/Provider not reachable/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Discard remaining/i }),
      ).toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: /Resume tomorrow/i }),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByRole('button', { name: /exceed budget/i }),
      ).not.toBeInTheDocument()
    })

    it('Resume button calls API with force_budget=false', async () => {
      const next = baseDto({ state: 'running' })
      vi.mocked(chatGptImportApi.resumeMemoryBatch).mockResolvedValue(next)
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
      })
      expect(chatGptImportApi.resumeMemoryBatch).toHaveBeenCalledWith(
        'imp-1',
        'persona-1',
        false,
      )
    })
  })

  describe('paused — budget_exhausted', () => {
    beforeEach(() => {
      useMemoryBatchStore.getState().setBatch(
        baseDto({ state: 'paused', paused_at: pausedAt('budget_exhausted') }),
      )
    })

    it('shows two Resume variants and Discard', () => {
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      expect(screen.getByText(/Daily budget exhausted/)).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Resume tomorrow/i }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /exceed budget/i }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /Discard remaining/i }),
      ).toBeInTheDocument()
    })

    it('"Resume now — exceed budget" calls API with force_budget=true', async () => {
      vi.mocked(chatGptImportApi.resumeMemoryBatch).mockResolvedValue(
        baseDto({ state: 'running' }),
      )
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      await act(async () => {
        fireEvent.click(
          screen.getByRole('button', { name: /exceed budget/i }),
        )
      })
      expect(chatGptImportApi.resumeMemoryBatch).toHaveBeenCalledWith(
        'imp-1',
        'persona-1',
        true,
      )
    })

    it('"Resume tomorrow" does not call the API', async () => {
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      await act(async () => {
        fireEvent.click(
          screen.getByRole('button', { name: /Resume tomorrow/i }),
        )
      })
      expect(chatGptImportApi.resumeMemoryBatch).not.toHaveBeenCalled()
    })
  })

  describe('discard confirmation', () => {
    beforeEach(() => {
      useMemoryBatchStore.getState().setBatch(
        baseDto({ state: 'paused', paused_at: pausedAt('provider_unavailable') }),
      )
    })

    it('opens a confirmation block before calling the API', async () => {
      vi.mocked(chatGptImportApi.discardMemoryBatch).mockResolvedValue(
        baseDto({ state: 'discarded' }),
      )
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      fireEvent.click(
        screen.getByRole('button', { name: /Discard remaining/i }),
      )
      // Confirmation appears; API not yet called
      expect(
        screen.getByRole('button', { name: /Yes, discard/i }),
      ).toBeInTheDocument()
      expect(chatGptImportApi.discardMemoryBatch).not.toHaveBeenCalled()
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: /Yes, discard/i }))
      })
      expect(chatGptImportApi.discardMemoryBatch).toHaveBeenCalledWith(
        'imp-1',
        'persona-1',
      )
    })

    it('Cancel closes the confirmation without an API call', () => {
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      fireEvent.click(
        screen.getByRole('button', { name: /Discard remaining/i }),
      )
      fireEvent.click(screen.getByRole('button', { name: /Cancel/i }))
      expect(
        screen.queryByRole('button', { name: /Yes, discard/i }),
      ).not.toBeInTheDocument()
      expect(chatGptImportApi.discardMemoryBatch).not.toHaveBeenCalled()
    })
  })

  describe('done state', () => {
    it('renders the success summary with memories count', () => {
      useMemoryBatchStore.getState().setBatch(
        baseDto({ state: 'done', total_entries_created: 24 }),
      )
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      expect(
        screen.getByText(/Memory extraction complete/),
      ).toBeInTheDocument()
      expect(screen.getByText('7 / 7')).toBeInTheDocument()
      expect(screen.getByText(/24 memories created/)).toBeInTheDocument()
    })

    it('uses singular "memory" when exactly one entry was created', () => {
      useMemoryBatchStore.getState().setBatch(
        baseDto({ state: 'done', total_entries_created: 1 }),
      )
      render(
        <MemoryBatchProgressPanel importId="imp-1" personaId="persona-1" />,
      )
      expect(screen.getByText(/1 memory created/)).toBeInTheDocument()
    })
  })
})
