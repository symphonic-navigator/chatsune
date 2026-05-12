/**
 * Zustand store for the ChatGPT-import persona-overlay tab.
 *
 * Holds the currently active import (per user, at most one), the parsed
 * conversation list for that import, multi-select state, filter state,
 * and a per-conversation "importing" flag used to dim rows while their
 * per-conversation job is in flight.
 */
import { create } from 'zustand'

import type {
  ConversationItemDto,
  ImportDto,
} from '../api/chatGptImportApi'

export type StatusFilter =
  | 'all'
  | 'not_in_this_persona'
  | 'not_in_any_persona'
  | 'in_other_persona'

export type SortOption = 'create_time_desc' | 'create_time_asc' | 'title_asc'

interface ChatGptImportState {
  activeImport: ImportDto | null
  conversations: ConversationItemDto[]
  parseProgress: { conversationsIndexed: number } | null
  selectedConversationIds: Set<string>
  importingConversationIds: Set<string>
  titleSearch: string
  sort: SortOption
  statusFilter: StatusFilter

  setActiveImport: (imp: ImportDto | null) => void
  setConversations: (convs: ConversationItemDto[]) => void
  setParseProgress: (p: { conversationsIndexed: number } | null) => void

  toggleSelected: (id: string) => void
  selectMany: (ids: string[]) => void
  clearSelection: () => void
  setImportingIds: (ids: Set<string>) => void
  markConversationImported: (
    convId: string,
    info: {
      persona_id: string
      persona_name: string
      session_id: string
      imported_at: string
    },
  ) => void
  markConversationImportFailed: (convId: string) => void

  setTitleSearch: (s: string) => void
  setSort: (s: SortOption) => void
  setStatusFilter: (s: StatusFilter) => void

  reset: () => void
}

export const useChatGptImportStore = create<ChatGptImportState>((set) => ({
  activeImport: null,
  conversations: [],
  parseProgress: null,
  selectedConversationIds: new Set<string>(),
  importingConversationIds: new Set<string>(),
  titleSearch: '',
  sort: 'create_time_desc',
  statusFilter: 'all',

  setActiveImport: (imp) =>
    set((s) =>
      imp === null
        ? {
            activeImport: null,
            conversations: [],
            parseProgress: null,
            selectedConversationIds: new Set<string>(),
            importingConversationIds: new Set<string>(),
          }
        : { ...s, activeImport: imp },
    ),
  setConversations: (convs) => set({ conversations: convs }),
  setParseProgress: (p) => set({ parseProgress: p }),

  toggleSelected: (id) =>
    set((s) => {
      const next = new Set(s.selectedConversationIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedConversationIds: next }
    }),

  selectMany: (ids) =>
    set((s) => {
      const next = new Set(s.selectedConversationIds)
      ids.forEach((i) => next.add(i))
      return { selectedConversationIds: next }
    }),

  clearSelection: () => set({ selectedConversationIds: new Set<string>() }),

  setImportingIds: (ids) => set({ importingConversationIds: ids }),

  markConversationImported: (convId, info) =>
    set((s) => {
      const nextImporting = new Set(s.importingConversationIds)
      nextImporting.delete(convId)
      return {
        importingConversationIds: nextImporting,
        conversations: s.conversations.map((c) =>
          c.chatgpt_conversation_id === convId
            ? { ...c, imports: [...c.imports, info] }
            : c,
        ),
      }
    }),

  markConversationImportFailed: (convId) =>
    set((s) => {
      const next = new Set(s.importingConversationIds)
      next.delete(convId)
      return { importingConversationIds: next }
    }),

  setTitleSearch: (titleSearch) => set({ titleSearch }),
  setSort: (sort) => set({ sort }),
  setStatusFilter: (statusFilter) => set({ statusFilter }),

  reset: () =>
    set({
      activeImport: null,
      conversations: [],
      parseProgress: null,
      selectedConversationIds: new Set<string>(),
      importingConversationIds: new Set<string>(),
      titleSearch: '',
      sort: 'create_time_desc',
      statusFilter: 'all',
    }),
}))
