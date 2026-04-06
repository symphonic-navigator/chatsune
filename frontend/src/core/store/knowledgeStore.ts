import { create } from 'zustand'
import { knowledgeApi } from '../api/knowledge'
import type { KnowledgeDocumentDto, KnowledgeLibraryDto } from '../types/knowledge'

interface KnowledgeState {
  libraries: KnowledgeLibraryDto[]
  libraryDocuments: Record<string, KnowledgeDocumentDto[]>
  expandedLibraryIds: Set<string>
  isLoading: boolean

  // Actions
  fetchLibraries: () => Promise<void>
  fetchDocuments: (libraryId: string) => Promise<void>
  toggleExpanded: (libraryId: string) => void

  // Event-driven updates (called from WS event handlers)
  onLibraryCreated: (library: KnowledgeLibraryDto) => void
  onLibraryUpdated: (library: KnowledgeLibraryDto) => void
  onLibraryDeleted: (libraryId: string) => void
  onDocumentCreated: (document: KnowledgeDocumentDto) => void
  onDocumentUpdated: (document: KnowledgeDocumentDto) => void
  onDocumentDeleted: (libraryId: string, documentId: string) => void
  onDocumentEmbeddingStatus: (documentId: string, status: string, error?: string | null) => void
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  libraries: [],
  libraryDocuments: {},
  expandedLibraryIds: new Set(),
  isLoading: false,

  fetchLibraries: async () => {
    set({ isLoading: true })
    try {
      const libraries = await knowledgeApi.listLibraries()
      set({ libraries, isLoading: false })
    } catch {
      set({ isLoading: false })
    }
  },

  fetchDocuments: async (libraryId: string) => {
    try {
      const docs = await knowledgeApi.listDocuments(libraryId)
      set((s) => ({
        libraryDocuments: { ...s.libraryDocuments, [libraryId]: docs },
      }))
    } catch {
      // ignore
    }
  },

  toggleExpanded: (libraryId: string) => {
    const { expandedLibraryIds, libraryDocuments, fetchDocuments } = get()
    const next = new Set(expandedLibraryIds)
    if (next.has(libraryId)) {
      next.delete(libraryId)
    } else {
      next.add(libraryId)
      if (!libraryDocuments[libraryId]) {
        fetchDocuments(libraryId)
      }
    }
    set({ expandedLibraryIds: next })
  },

  onLibraryCreated: (library) =>
    set((s) => ({ libraries: [...s.libraries, library] })),

  onLibraryUpdated: (library) =>
    set((s) => ({
      libraries: s.libraries.map((l) => (l.id === library.id ? library : l)),
    })),

  onLibraryDeleted: (libraryId) =>
    set((s) => {
      const { [libraryId]: _, ...rest } = s.libraryDocuments
      const next = new Set(s.expandedLibraryIds)
      next.delete(libraryId)
      return {
        libraries: s.libraries.filter((l) => l.id !== libraryId),
        libraryDocuments: rest,
        expandedLibraryIds: next,
      }
    }),

  onDocumentCreated: (document) =>
    set((s) => {
      const existing = s.libraryDocuments[document.library_id] ?? []
      return {
        libraryDocuments: {
          ...s.libraryDocuments,
          [document.library_id]: [...existing, document],
        },
      }
    }),

  onDocumentUpdated: (document) =>
    set((s) => {
      const existing = s.libraryDocuments[document.library_id] ?? []
      return {
        libraryDocuments: {
          ...s.libraryDocuments,
          [document.library_id]: existing.map((d) =>
            d.id === document.id ? document : d,
          ),
        },
      }
    }),

  onDocumentDeleted: (libraryId, documentId) =>
    set((s) => {
      const existing = s.libraryDocuments[libraryId] ?? []
      return {
        libraryDocuments: {
          ...s.libraryDocuments,
          [libraryId]: existing.filter((d) => d.id !== documentId),
        },
      }
    }),

  onDocumentEmbeddingStatus: (documentId, status, error) =>
    set((s) => {
      const updated = { ...s.libraryDocuments }
      for (const libId of Object.keys(updated)) {
        updated[libId] = updated[libId].map((d) =>
          d.id === documentId
            ? { ...d, embedding_status: status as KnowledgeDocumentDto['embedding_status'], embedding_error: error ?? null }
            : d,
        )
      }
      return { libraryDocuments: updated }
    }),
}))
