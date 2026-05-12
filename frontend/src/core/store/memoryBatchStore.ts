/**
 * Zustand store for ChatGPT-import memory-batch state.
 *
 * One row per ``(import_id, persona_id)`` pair, keyed as
 * ``"${importId}:${personaId}"``. The store is populated three ways:
 *
 * 1. ``rehydrateForPersona`` — REST GET on persona-detail mount, so the
 *    UI is correct on reload / reconnect without depending on WS replay.
 * 2. ``handleProgressEvent`` / ``handlePausedEvent`` / ``handleDoneEvent``
 *    — live updates while the user has the import tab open.
 * 3. ``setBatch`` — direct upsert used by the REST resume / discard
 *    callers to fold the returned snapshot into the store before the
 *    WS event arrives.
 *
 * Selectors are exported as plain functions so callers can pass them
 * straight to ``useMemoryBatchStore(...)``. The Persona-header pill
 * relies on ``selectActiveBatchesForPersona`` which filters down to
 * "running" / "paused".
 */
import { create } from 'zustand'

import {
  chatGptImportApi,
  type MemoryBatchDto,
  type MemoryBatchPausedAtDto,
  type MemoryBatchReason,
} from '../api/chatGptImportApi'

function keyOf(importId: string, personaId: string): string {
  return `${importId}:${personaId}`
}

// --- Event payload shapes (mirror shared/events/chatgpt_import.py) ---------

export interface ChatGptImportMemoryProgressPayload {
  import_id: string
  persona_id: string
  session_id: string
  session_title: string
  session_index: number
  total: number
  state: 'extracting' | 'done'
  entries_created: number | null
}

export interface ChatGptImportMemoryPausedPayload {
  import_id: string
  persona_id: string
  paused_at_session_index: number
  paused_at_session_id: string
  total: number
  reason: MemoryBatchReason
  user_message: string
  detail: string | null
}

export interface ChatGptImportMemoryDonePayload {
  import_id: string
  persona_id: string
  total: number
  total_entries_created: number
}

// --- Store ----------------------------------------------------------------

// Augments the server-side ``MemoryBatchDto`` with the most-recent
// progress reported via WS — these fields are not on the DTO because
// they are live-only (the server doesn't snapshot the currently-running
// session into the batch row). They drive the "currently processing"
// label and progress-bar position.
export interface MemoryBatchEntry extends MemoryBatchDto {
  current_session_index: number | null
  current_session_title: string | null
}

interface MemoryBatchState {
  batches: Record<string, MemoryBatchEntry>

  setBatch: (batch: MemoryBatchDto) => void
  removeBatch: (importId: string, personaId: string) => void
  handleProgressEvent: (payload: ChatGptImportMemoryProgressPayload) => void
  handlePausedEvent: (payload: ChatGptImportMemoryPausedPayload) => void
  handleDoneEvent: (payload: ChatGptImportMemoryDonePayload) => void
  rehydrateForPersona: (importId: string, personaId: string) => Promise<void>
  reset: () => void
}

function dtoToEntry(
  dto: MemoryBatchDto,
  prior?: MemoryBatchEntry,
): MemoryBatchEntry {
  return {
    ...dto,
    current_session_index: prior?.current_session_index ?? null,
    current_session_title: prior?.current_session_title ?? null,
  }
}

export const useMemoryBatchStore = create<MemoryBatchState>((set, get) => ({
  batches: {},

  setBatch: (batch) =>
    set((s) => {
      const k = keyOf(batch.import_id, batch.persona_id)
      return {
        batches: { ...s.batches, [k]: dtoToEntry(batch, s.batches[k]) },
      }
    }),

  removeBatch: (importId, personaId) =>
    set((s) => {
      const k = keyOf(importId, personaId)
      if (!(k in s.batches)) return s
      const next = { ...s.batches }
      delete next[k]
      return { batches: next }
    }),

  handleProgressEvent: (payload) =>
    set((s) => {
      const k = keyOf(payload.import_id, payload.persona_id)
      const prior = s.batches[k]
      // If no prior batch is in the store, fall back to a synthetic row.
      // Counters / timestamps will be filled in on the next rehydrate or
      // setBatch; the goal here is to show progress in the UI immediately.
      const base: MemoryBatchEntry = prior ?? {
        import_id: payload.import_id,
        persona_id: payload.persona_id,
        state: 'running',
        target_count: payload.total,
        conversations_imported: 0,
        permanent_failures: 0,
        session_ids: [],
        paused_at: null,
        total_entries_created: 0,
        created_at: '',
        updated_at: '',
        current_session_index: null,
        current_session_title: null,
      }
      const isFinalForSession = payload.state === 'done'
      const entriesDelta =
        isFinalForSession && payload.entries_created != null
          ? payload.entries_created
          : 0
      // While progress events stream in, the batch is by definition not
      // paused or done — switch state to "running" so a stale snapshot
      // doesn't keep the paused UI on screen.
      return {
        batches: {
          ...s.batches,
          [k]: {
            ...base,
            state: 'running',
            paused_at: null,
            target_count: payload.total,
            current_session_index: payload.session_index,
            current_session_title: payload.session_title,
            total_entries_created:
              base.total_entries_created + entriesDelta,
          },
        },
      }
    }),

  handlePausedEvent: (payload) =>
    set((s) => {
      const k = keyOf(payload.import_id, payload.persona_id)
      const prior = s.batches[k]
      const pausedAt: MemoryBatchPausedAtDto = {
        session_index: payload.paused_at_session_index,
        session_id: payload.paused_at_session_id,
        reason: payload.reason,
        user_message: payload.user_message,
        detail: payload.detail,
        at: new Date().toISOString(),
      }
      const base: MemoryBatchEntry = prior ?? {
        import_id: payload.import_id,
        persona_id: payload.persona_id,
        state: 'paused',
        target_count: payload.total,
        conversations_imported: 0,
        permanent_failures: 0,
        session_ids: [],
        paused_at: pausedAt,
        total_entries_created: 0,
        created_at: '',
        updated_at: '',
        current_session_index: null,
        current_session_title: null,
      }
      return {
        batches: {
          ...s.batches,
          [k]: {
            ...base,
            state: 'paused',
            target_count: payload.total,
            paused_at: pausedAt,
          },
        },
      }
    }),

  handleDoneEvent: (payload) =>
    set((s) => {
      const k = keyOf(payload.import_id, payload.persona_id)
      const prior = s.batches[k]
      const base: MemoryBatchEntry = prior ?? {
        import_id: payload.import_id,
        persona_id: payload.persona_id,
        state: 'done',
        target_count: payload.total,
        conversations_imported: payload.total,
        permanent_failures: 0,
        session_ids: [],
        paused_at: null,
        total_entries_created: payload.total_entries_created,
        created_at: '',
        updated_at: '',
        current_session_index: null,
        current_session_title: null,
      }
      // "Done" events are reused by the discard path; the resulting
      // ``state`` is preserved on the server but the WS event itself
      // doesn't carry it. We keep the prior server state if it was
      // already "discarded"; otherwise fall through to "done".
      const nextState =
        prior?.state === 'discarded' ? 'discarded' : 'done'
      return {
        batches: {
          ...s.batches,
          [k]: {
            ...base,
            state: nextState,
            target_count: payload.total,
            total_entries_created: payload.total_entries_created,
            paused_at: null,
          },
        },
      }
    }),

  rehydrateForPersona: async (importId, personaId) => {
    try {
      const batch = await chatGptImportApi.getMemoryBatch(importId, personaId)
      if (batch === null) {
        // No batch row — drop any stale entry we may have.
        get().removeBatch(importId, personaId)
        return
      }
      get().setBatch(batch)
    } catch {
      // Silent failure: the persona-detail page should not blow up if
      // the rehydrate fails; the user can retry by reopening the tab.
    }
  },

  reset: () => set({ batches: {} }),
}))

// --- Selectors -------------------------------------------------------------

export function selectBatchByImportAndPersona(
  importId: string,
  personaId: string,
) {
  return (state: MemoryBatchState): MemoryBatchEntry | undefined =>
    state.batches[keyOf(importId, personaId)]
}

export function selectActiveBatchesForPersona(personaId: string) {
  return (state: MemoryBatchState): MemoryBatchEntry[] =>
    Object.values(state.batches).filter(
      (b) =>
        b.persona_id === personaId &&
        (b.state === 'running' || b.state === 'paused'),
    )
}
