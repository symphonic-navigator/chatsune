import { beforeEach, describe, expect, it } from 'vitest'

import {
  selectActiveBatchesForPersona,
  selectFirstActiveBatchForPersona,
  selectBatchByImportAndPersona,
  useMemoryBatchStore,
} from './memoryBatchStore'
import type { MemoryBatchDto } from '../api/chatGptImportApi'

function reset() {
  useMemoryBatchStore.setState({ batches: {} })
}

function dto(overrides: Partial<MemoryBatchDto> = {}): MemoryBatchDto {
  return {
    import_id: 'imp-1',
    persona_id: 'persona-1',
    state: 'running',
    target_count: 5,
    conversations_imported: 5,
    permanent_failures: 0,
    session_ids: ['s1', 's2', 's3', 's4', 's5'],
    paused_at: null,
    total_entries_created: 0,
    created_at: '2026-05-12T10:00:00Z',
    updated_at: '2026-05-12T10:00:00Z',
    ...overrides,
  }
}

describe('memoryBatchStore', () => {
  beforeEach(reset)

  describe('setBatch', () => {
    it('inserts a new batch entry with null progress fields', () => {
      useMemoryBatchStore.getState().setBatch(dto())
      const entry = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(entry).toBeDefined()
      expect(entry!.state).toBe('running')
      expect(entry!.current_session_index).toBeNull()
      expect(entry!.current_session_title).toBeNull()
    })

    it('preserves live progress fields when re-setting from the server snapshot', () => {
      const s = useMemoryBatchStore.getState()
      s.handleProgressEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        session_id: 's2',
        session_title: 'Second',
        session_index: 2,
        total: 5,
        state: 'extracting',
        entries_created: null,
      })
      s.setBatch(dto({ total_entries_created: 7 }))
      const entry = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(entry!.current_session_index).toBe(2)
      expect(entry!.current_session_title).toBe('Second')
      expect(entry!.total_entries_created).toBe(7)
    })
  })

  describe('handleProgressEvent', () => {
    it('updates current_session_index / title from extracting event', () => {
      useMemoryBatchStore.getState().setBatch(dto())
      useMemoryBatchStore.getState().handleProgressEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        session_id: 's3',
        session_title: 'Third conversation',
        session_index: 3,
        total: 5,
        state: 'extracting',
        entries_created: null,
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e!.current_session_index).toBe(3)
      expect(e!.current_session_title).toBe('Third conversation')
      expect(e!.state).toBe('running')
    })

    it('increments total_entries_created on session-done progress', () => {
      useMemoryBatchStore.getState().setBatch(dto({ total_entries_created: 4 }))
      useMemoryBatchStore.getState().handleProgressEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        session_id: 's3',
        session_title: 'Third',
        session_index: 3,
        total: 5,
        state: 'done',
        entries_created: 2,
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e!.total_entries_created).toBe(6)
    })

    it('clears paused_at when progress fires after a paused snapshot', () => {
      useMemoryBatchStore.getState().setBatch(
        dto({
          state: 'paused',
          paused_at: {
            session_index: 2,
            session_id: 's2',
            reason: 'provider_unavailable',
            user_message: 'down',
            detail: null,
            at: '2026-05-12T10:00:00Z',
          },
        }),
      )
      useMemoryBatchStore.getState().handleProgressEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        session_id: 's2',
        session_title: 'Second',
        session_index: 2,
        total: 5,
        state: 'extracting',
        entries_created: null,
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e!.state).toBe('running')
      expect(e!.paused_at).toBeNull()
    })
  })

  describe('handlePausedEvent', () => {
    it('sets paused_at and state=paused', () => {
      useMemoryBatchStore.getState().setBatch(dto())
      useMemoryBatchStore.getState().handlePausedEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        paused_at_session_index: 3,
        paused_at_session_id: 's3',
        total: 5,
        reason: 'budget_exhausted',
        user_message: 'Daily budget exhausted',
        detail: null,
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e!.state).toBe('paused')
      expect(e!.paused_at!.session_index).toBe(3)
      expect(e!.paused_at!.reason).toBe('budget_exhausted')
    })

    it('synthesises a row if none exists yet (race with rehydrate)', () => {
      useMemoryBatchStore.getState().handlePausedEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        paused_at_session_index: 1,
        paused_at_session_id: 's1',
        total: 4,
        reason: 'provider_unavailable',
        user_message: 'Connection refused',
        detail: 'ECONNREFUSED',
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e).toBeDefined()
      expect(e!.state).toBe('paused')
      expect(e!.target_count).toBe(4)
    })
  })

  describe('handleDoneEvent', () => {
    it('clears paused_at and sets state to done', () => {
      useMemoryBatchStore.getState().setBatch(
        dto({
          state: 'paused',
          paused_at: {
            session_index: 2,
            session_id: 's2',
            reason: 'provider_unavailable',
            user_message: 'down',
            detail: null,
            at: '2026-05-12T10:00:00Z',
          },
        }),
      )
      useMemoryBatchStore.getState().handleDoneEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        total: 5,
        total_entries_created: 12,
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e!.state).toBe('done')
      expect(e!.paused_at).toBeNull()
      expect(e!.total_entries_created).toBe(12)
    })

    it('preserves discarded state when the server already marked it so', () => {
      useMemoryBatchStore.getState().setBatch(dto({ state: 'discarded' }))
      useMemoryBatchStore.getState().handleDoneEvent({
        import_id: 'imp-1',
        persona_id: 'persona-1',
        total: 5,
        total_entries_created: 3,
      })
      const e = selectBatchByImportAndPersona(
        'imp-1',
        'persona-1',
      )(useMemoryBatchStore.getState())
      expect(e!.state).toBe('discarded')
      expect(e!.total_entries_created).toBe(3)
    })
  })

  describe('selectActiveBatchesForPersona', () => {
    it('filters to running and paused only', () => {
      const s = useMemoryBatchStore.getState()
      s.setBatch(dto({ import_id: 'a', state: 'running' }))
      s.setBatch(dto({ import_id: 'b', state: 'paused', paused_at: {
        session_index: 1, session_id: 's1', reason: 'other',
        user_message: 'x', detail: null, at: 't',
      } }))
      s.setBatch(dto({ import_id: 'c', state: 'done' }))
      s.setBatch(dto({ import_id: 'd', state: 'discarded' }))
      s.setBatch(dto({ import_id: 'e', state: 'pending' }))
      // Different persona — should be ignored
      s.setBatch(dto({ import_id: 'f', persona_id: 'persona-2', state: 'running' }))
      const active = selectActiveBatchesForPersona('persona-1')(
        useMemoryBatchStore.getState(),
      )
      const ids = active.map((b) => b.import_id).sort()
      expect(ids).toEqual(['a', 'b'])
    })
  })

  describe('selectFirstActiveBatchForPersona', () => {
    it('prefers running over paused', () => {
      const s = useMemoryBatchStore.getState()
      s.setBatch(dto({ import_id: 'p', state: 'paused', paused_at: {
        session_index: 1, session_id: 's1', reason: 'other',
        user_message: 'x', detail: null, at: 't',
      } }))
      s.setBatch(dto({ import_id: 'r', state: 'running' }))
      const first = selectFirstActiveBatchForPersona('persona-1')(
        useMemoryBatchStore.getState(),
      )
      expect(first?.import_id).toBe('r')
    })

    it('falls back to paused when no running', () => {
      const s = useMemoryBatchStore.getState()
      s.setBatch(dto({ import_id: 'p', state: 'paused', paused_at: {
        session_index: 1, session_id: 's1', reason: 'other',
        user_message: 'x', detail: null, at: 't',
      } }))
      const first = selectFirstActiveBatchForPersona('persona-1')(
        useMemoryBatchStore.getState(),
      )
      expect(first?.import_id).toBe('p')
    })

    it('returns null when no active batch exists', () => {
      const s = useMemoryBatchStore.getState()
      s.setBatch(dto({ state: 'done' }))
      const first = selectFirstActiveBatchForPersona('persona-1')(
        useMemoryBatchStore.getState(),
      )
      expect(first).toBeNull()
    })

    // Regression: the original selectActiveBatchesForPersona allocated
    // a fresh array on every call, triggering an infinite render loop
    // when subscribed via useMemoryBatchStore. selectFirstActiveBatchForPersona
    // must return the same entry reference when state has not changed.
    it('returns identical reference on repeated reads when state unchanged', () => {
      useMemoryBatchStore.getState().setBatch(dto({ state: 'running' }))
      const selector = selectFirstActiveBatchForPersona('persona-1')
      const a = selector(useMemoryBatchStore.getState())
      const b = selector(useMemoryBatchStore.getState())
      expect(a).toBe(b)
      expect(a).not.toBeNull()
    })

    it('returns null reference identity stably across reads', () => {
      const selector = selectFirstActiveBatchForPersona('persona-1')
      const a = selector(useMemoryBatchStore.getState())
      const b = selector(useMemoryBatchStore.getState())
      expect(a).toBe(b)
      expect(a).toBeNull()
    })
  })

  describe('removeBatch', () => {
    it('deletes the keyed entry', () => {
      useMemoryBatchStore.getState().setBatch(dto())
      useMemoryBatchStore.getState().removeBatch('imp-1', 'persona-1')
      expect(
        selectBatchByImportAndPersona('imp-1', 'persona-1')(
          useMemoryBatchStore.getState(),
        ),
      ).toBeUndefined()
    })
  })
})
