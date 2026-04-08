import { create } from 'zustand'
import type { JournalEntryDto, MemoryBodyDto, MemoryBodyVersionDto, MemoryContextDto } from '../api/memory'

interface MemoryState {
  uncommittedEntries: Record<string, JournalEntryDto[]>
  committedEntries: Record<string, JournalEntryDto[]>
  memoryBody: Record<string, MemoryBodyDto | null>
  bodyVersions: Record<string, MemoryBodyVersionDto[]>
  context: Record<string, MemoryContextDto | null>
  isDreaming: Record<string, boolean>
  isExtracting: Record<string, boolean>
  toastCounter: Record<string, number>

  setUncommittedEntries: (personaId: string, entries: JournalEntryDto[]) => void
  setCommittedEntries: (personaId: string, entries: JournalEntryDto[]) => void
  setMemoryBody: (personaId: string, body: MemoryBodyDto | null) => void
  setBodyVersions: (personaId: string, versions: MemoryBodyVersionDto[]) => void
  setContext: (personaId: string, context: MemoryContextDto | null) => void
  setDreaming: (personaId: string, dreaming: boolean) => void
  setExtracting: (personaId: string, extracting: boolean) => void
  addEntry: (personaId: string, entry: JournalEntryDto) => void
  updateEntry: (personaId: string, entry: JournalEntryDto) => void
  removeEntry: (personaId: string, entryId: string) => void
  commitEntry: (personaId: string, entry: JournalEntryDto) => void
  autoCommitEntry: (personaId: string, entry: JournalEntryDto) => void
  resetToastCounter: (personaId: string) => void
  incrementToastCounter: (personaId: string) => void
}

export const useMemoryStore = create<MemoryState>((set, _get) => ({
  uncommittedEntries: {},
  committedEntries: {},
  memoryBody: {},
  bodyVersions: {},
  context: {},
  isDreaming: {},
  isExtracting: {},
  toastCounter: {},

  setUncommittedEntries: (personaId, entries) =>
    set((s) => ({ uncommittedEntries: { ...s.uncommittedEntries, [personaId]: entries } })),

  setCommittedEntries: (personaId, entries) =>
    set((s) => ({ committedEntries: { ...s.committedEntries, [personaId]: entries } })),

  setMemoryBody: (personaId, body) =>
    set((s) => ({ memoryBody: { ...s.memoryBody, [personaId]: body } })),

  setBodyVersions: (personaId, versions) =>
    set((s) => ({ bodyVersions: { ...s.bodyVersions, [personaId]: versions } })),

  setContext: (personaId, context) =>
    set((s) => ({ context: { ...s.context, [personaId]: context } })),

  setDreaming: (personaId, dreaming) =>
    set((s) => ({ isDreaming: { ...s.isDreaming, [personaId]: dreaming } })),

  setExtracting: (personaId, extracting) =>
    set((s) => ({ isExtracting: { ...s.isExtracting, [personaId]: extracting } })),

  addEntry: (personaId, entry) =>
    set((s) => {
      const current = s.uncommittedEntries[personaId] ?? []
      const counter = (s.toastCounter[personaId] ?? 0) + 1
      return {
        uncommittedEntries: { ...s.uncommittedEntries, [personaId]: [...current, entry] },
        toastCounter: { ...s.toastCounter, [personaId]: counter },
      }
    }),

  updateEntry: (personaId, entry) =>
    set((s) => {
      const uncommitted = s.uncommittedEntries[personaId] ?? []
      const committed = s.committedEntries[personaId] ?? []
      const inUncommitted = uncommitted.some((e) => e.id === entry.id)
      if (inUncommitted) {
        return {
          uncommittedEntries: {
            ...s.uncommittedEntries,
            [personaId]: uncommitted.map((e) => (e.id === entry.id ? entry : e)),
          },
        }
      }
      return {
        committedEntries: {
          ...s.committedEntries,
          [personaId]: committed.map((e) => (e.id === entry.id ? entry : e)),
        },
      }
    }),

  removeEntry: (personaId, entryId) =>
    set((s) => ({
      uncommittedEntries: {
        ...s.uncommittedEntries,
        [personaId]: (s.uncommittedEntries[personaId] ?? []).filter((e) => e.id !== entryId),
      },
      committedEntries: {
        ...s.committedEntries,
        [personaId]: (s.committedEntries[personaId] ?? []).filter((e) => e.id !== entryId),
      },
      toastCounter: { ...s.toastCounter, [personaId]: 0 },
    })),

  commitEntry: (personaId, entry) =>
    set((s) => {
      const committed = entry.state === 'committed'
        ? entry
        : { ...entry, state: 'committed' as const }
      return {
        uncommittedEntries: {
          ...s.uncommittedEntries,
          [personaId]: (s.uncommittedEntries[personaId] ?? []).filter((e) => e.id !== entry.id),
        },
        committedEntries: {
          ...s.committedEntries,
          [personaId]: [
            ...(s.committedEntries[personaId] ?? []).filter((e) => e.id !== entry.id),
            committed,
          ],
        },
        toastCounter: { ...s.toastCounter, [personaId]: 0 },
      }
    }),

  autoCommitEntry: (personaId, entry) =>
    set((s) => {
      const committed = entry.state === 'committed'
        ? entry
        : { ...entry, state: 'committed' as const }
      return {
        uncommittedEntries: {
          ...s.uncommittedEntries,
          [personaId]: (s.uncommittedEntries[personaId] ?? []).filter((e) => e.id !== entry.id),
        },
        committedEntries: {
          ...s.committedEntries,
          [personaId]: [
            ...(s.committedEntries[personaId] ?? []).filter((e) => e.id !== entry.id),
            committed,
          ],
        },
        // No toastCounter reset for auto-commit
      }
    }),

  resetToastCounter: (personaId) =>
    set((s) => ({ toastCounter: { ...s.toastCounter, [personaId]: 0 } })),

  incrementToastCounter: (personaId) =>
    set((s) => ({
      toastCounter: { ...s.toastCounter, [personaId]: (s.toastCounter[personaId] ?? 0) + 1 },
    })),
}))

