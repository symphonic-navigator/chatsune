import { useEffect, useState } from 'react'
import { knowledgeApi } from '../../../core/api/knowledge'
import { useKnowledgeStore } from '../../../core/store/knowledgeStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import type { KnowledgeDocumentDto, KnowledgeLibraryDto } from '../../../core/types/knowledge'
import { DocumentEditorModal } from './DocumentEditorModal'
import { LibraryEditorModal } from './LibraryEditorModal'

type LibraryModalState =
  | { mode: 'none' }
  | { mode: 'create' }
  | { mode: 'edit'; library: KnowledgeLibraryDto }

type DocumentModalState =
  | { mode: 'none' }
  | { mode: 'create'; libraryId: string }
  | { mode: 'edit'; libraryId: string; doc: KnowledgeDocumentDto & { content: string } }

function EmbeddingDot({ status, onClick }: { status: KnowledgeDocumentDto['embedding_status']; onClick?: () => void }) {
  const base = 'inline-block h-2 w-2 rounded-full flex-shrink-0'
  if (status === 'completed') {
    return <span className={`${base} bg-live`} title="Embedded" />
  }
  if (status === 'processing') {
    return <span className={`${base} bg-yellow-500 animate-pulse`} title="Processing..." />
  }
  if (status === 'failed') {
    return (
      <button
        type="button"
        onClick={onClick}
        title="Embedding failed — click to retry"
        className={`${base} bg-red-400 cursor-pointer hover:bg-red-300 transition-colors`}
      />
    )
  }
  // pending
  return <span className={`${base} bg-white/20`} title="Pending" />
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function KnowledgeTab() {
  const {
    libraries,
    libraryDocuments,
    expandedLibraryIds,
    isLoading,
    fetchLibraries,
    fetchDocuments,
    toggleExpanded,
    onLibraryCreated,
    onLibraryUpdated,
    onLibraryDeleted,
    onDocumentCreated,
    onDocumentUpdated,
    onDocumentDeleted,
  } = useKnowledgeStore()

  const { isSanitised } = useSanitisedMode()

  const [libraryModal, setLibraryModal] = useState<LibraryModalState>({ mode: 'none' })
  const [documentModal, setDocumentModal] = useState<DocumentModalState>({ mode: 'none' })
  const [loadingDoc, setLoadingDoc] = useState<string | null>(null)

  useEffect(() => {
    fetchLibraries()
  }, [fetchLibraries])

  const visibleLibraries = isSanitised
    ? libraries.filter((l) => !l.nsfw)
    : libraries

  async function handleSaveLibrary(data: { name: string; description: string; nsfw: boolean }) {
    if (libraryModal.mode === 'create') {
      const created = await knowledgeApi.createLibrary(data)
      onLibraryCreated(created)
    } else if (libraryModal.mode === 'edit') {
      const updated = await knowledgeApi.updateLibrary(libraryModal.library.id, data)
      onLibraryUpdated(updated)
    }
  }

  async function handleDeleteLibrary() {
    if (libraryModal.mode !== 'edit') return
    await knowledgeApi.deleteLibrary(libraryModal.library.id)
    onLibraryDeleted(libraryModal.library.id)
  }

  async function handleOpenDocument(libraryId: string, doc: KnowledgeDocumentDto) {
    setLoadingDoc(doc.id)
    try {
      const detail = await knowledgeApi.getDocument(libraryId, doc.id)
      setDocumentModal({ mode: 'edit', libraryId, doc: detail })
    } finally {
      setLoadingDoc(null)
    }
  }

  async function handleSaveDocument(data: { title: string; content: string; media_type: 'text/markdown' | 'text/plain' }) {
    if (documentModal.mode === 'create') {
      const created = await knowledgeApi.createDocument(documentModal.libraryId, data)
      onDocumentCreated(created)
      // Refresh library list to update document_count
      fetchLibraries()
    } else if (documentModal.mode === 'edit') {
      const updated = await knowledgeApi.updateDocument(documentModal.libraryId, documentModal.doc.id, data)
      onDocumentUpdated(updated)
    }
  }

  async function handleDeleteDocument() {
    if (documentModal.mode !== 'edit') return
    await knowledgeApi.deleteDocument(documentModal.libraryId, documentModal.doc.id)
    onDocumentDeleted(documentModal.libraryId, documentModal.doc.id)
    fetchLibraries()
  }

  async function handleRetryEmbedding(libraryId: string, docId: string) {
    await knowledgeApi.retryEmbedding(libraryId, docId)
  }

  function handleExpandLibrary(libraryId: string) {
    toggleExpanded(libraryId)
    if (!expandedLibraryIds.has(libraryId)) {
      fetchDocuments(libraryId)
    }
  }

  if (isLoading && libraries.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/6 px-4 py-3">
        <span className="text-[11px] font-mono uppercase tracking-wider text-white/40">
          Your Libraries
        </span>
        <button
          type="button"
          onClick={() => setLibraryModal({ mode: 'create' })}
          className="rounded border border-gold/30 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors hover:bg-gold/10 hover:border-gold/40 cursor-pointer"
        >
          + New Library
        </button>
      </div>

      {/* Library list */}
      <div className="flex-1 overflow-y-auto">
        {visibleLibraries.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-16">
            <p className="text-[12px] font-mono text-white/25">No libraries yet</p>
            <button
              type="button"
              onClick={() => setLibraryModal({ mode: 'create' })}
              className="text-[11px] font-mono text-gold/60 underline underline-offset-2 hover:text-gold cursor-pointer"
            >
              Create your first library
            </button>
          </div>
        )}

        {visibleLibraries.map((library) => {
          const isExpanded = expandedLibraryIds.has(library.id)
          const docs = libraryDocuments[library.id] ?? []
          const hasFailed = docs.some((d) => d.embedding_status === 'failed')

          return (
            <div key={library.id} className="border-b border-white/6">
              {/* Library row */}
              <div className="flex items-center gap-2 px-4 py-2.5 hover:bg-white/[0.02] transition-colors group">
                {/* Expand toggle */}
                <button
                  type="button"
                  onClick={() => handleExpandLibrary(library.id)}
                  className="flex flex-1 items-center gap-2 min-w-0 cursor-pointer text-left"
                >
                  <span className={`text-[10px] font-mono text-white/30 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                    ▶
                  </span>
                  <span className="flex-1 truncate text-[13px] text-white/75">
                    {library.name}
                  </span>
                  <span className="text-[10px] font-mono text-white/30 flex-shrink-0">
                    {library.document_count} doc{library.document_count !== 1 ? 's' : ''}
                  </span>
                  {library.nsfw && (
                    <span className="flex-shrink-0 text-[12px]" title="NSFW">💋</span>
                  )}
                  {hasFailed && (
                    <span className="flex-shrink-0 text-[12px]" title="Some documents have failed embeddings">⚠</span>
                  )}
                </button>

                {/* Edit button */}
                <button
                  type="button"
                  onClick={() => setLibraryModal({ mode: 'edit', library })}
                  className="opacity-0 group-hover:opacity-100 flex-shrink-0 rounded border border-white/8 px-1.5 py-0.5 text-[10px] font-mono text-white/40 transition-all hover:border-white/20 hover:text-white/60 cursor-pointer"
                  title="Edit library"
                >
                  ✎
                </button>
              </div>

              {/* Documents */}
              {isExpanded && (
                <div className="bg-white/[0.01] pb-1">
                  {docs.length === 0 && (
                    <p className="px-8 py-2 text-[11px] font-mono text-white/20">No documents</p>
                  )}

                  {docs.map((doc) => (
                    <div
                      key={doc.id}
                      className="flex items-center gap-2 px-8 py-1.5 hover:bg-white/[0.03] transition-colors group/doc"
                    >
                      <EmbeddingDot
                        status={doc.embedding_status}
                        onClick={() => handleRetryEmbedding(library.id, doc.id)}
                      />
                      <button
                        type="button"
                        onClick={() => handleOpenDocument(library.id, doc)}
                        disabled={loadingDoc === doc.id}
                        className="flex-1 truncate text-left text-[12px] text-white/65 hover:text-white/85 transition-colors cursor-pointer disabled:cursor-wait"
                      >
                        {doc.title}
                      </button>
                      <span className="flex-shrink-0 text-[10px] font-mono text-white/25">
                        {formatBytes(doc.size_bytes)}
                      </span>
                      {loadingDoc === doc.id && (
                        <span className="h-2.5 w-2.5 animate-spin rounded-full border border-gold/30 border-t-gold flex-shrink-0" />
                      )}
                    </div>
                  ))}

                  {/* Add document button */}
                  <button
                    type="button"
                    onClick={() => setDocumentModal({ mode: 'create', libraryId: library.id })}
                    className="mx-6 mt-1 mb-1 flex w-[calc(100%-3rem)] items-center justify-center rounded-lg border border-dashed border-white/8 py-1.5 text-[10px] font-mono uppercase tracking-wider text-white/25 transition-colors hover:border-white/20 hover:text-white/40 cursor-pointer"
                  >
                    + Add Document
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Library editor modal */}
      {libraryModal.mode !== 'none' && (
        <LibraryEditorModal
          initial={libraryModal.mode === 'edit'
            ? {
                name: libraryModal.library.name,
                description: libraryModal.library.description ?? '',
                nsfw: libraryModal.library.nsfw,
              }
            : undefined}
          onSave={handleSaveLibrary}
          onDelete={libraryModal.mode === 'edit' ? handleDeleteLibrary : undefined}
          onClose={() => setLibraryModal({ mode: 'none' })}
        />
      )}

      {/* Document editor modal */}
      {documentModal.mode !== 'none' && (
        <DocumentEditorModal
          libraryId={documentModal.libraryId}
          initial={documentModal.mode === 'edit'
            ? {
                title: documentModal.doc.title,
                content: documentModal.doc.content,
                media_type: documentModal.doc.media_type,
              }
            : undefined}
          onSave={handleSaveDocument}
          onDelete={documentModal.mode === 'edit' ? handleDeleteDocument : undefined}
          onClose={() => setDocumentModal({ mode: 'none' })}
        />
      )}
    </div>
  )
}
