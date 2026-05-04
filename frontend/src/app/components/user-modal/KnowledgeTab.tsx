import { useEffect, useRef, useState } from 'react'
import { knowledgeApi } from '../../../core/api/knowledge'
import { ApiError } from '../../../core/api/client'
import { DeletionReportSheet } from '../../../core/components/DeletionReportSheet'
import { useKnowledgeStore } from '../../../core/store/knowledgeStore'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { triggerBlobDownload } from '../../../core/utils/download'
import { KissMarkIcon } from '../../../core/components/symbols'
import type { DeletionReportDto } from '../../../core/types/deletion'
import type { KnowledgeDocumentDto, KnowledgeLibraryDto, RefreshFrequency } from '../../../core/types/knowledge'
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
  } = useKnowledgeStore()

  const { isSanitised } = useSanitisedMode()

  const [libraryModal, setLibraryModal] = useState<LibraryModalState>({ mode: 'none' })
  const [documentModal, setDocumentModal] = useState<DocumentModalState>({ mode: 'none' })
  const [loadingDoc, setLoadingDoc] = useState<string | null>(null)
  const [exportingLibraryId, setExportingLibraryId] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [deletionReport, setDeletionReport] = useState<DeletionReportDto | null>(null)
  const importInputRef = useRef<HTMLInputElement>(null)
  const addNotification = useNotificationStore((s) => s.addNotification)

  async function handleExportLibrary(library: KnowledgeLibraryDto) {
    if (exportingLibraryId) return
    setExportingLibraryId(library.id)
    try {
      const { blob, filename } = await knowledgeApi.exportLibrary(library.id)
      triggerBlobDownload({ blob, filename })
      addNotification({
        level: 'success',
        title: 'Library exported',
        message: `${library.name} downloaded as ${filename}.`,
      })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to export library.'
      addNotification({
        level: 'error',
        title: 'Export failed',
        message,
      })
    } finally {
      setExportingLibraryId(null)
    }
  }

  async function handleImportFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null
    event.target.value = ''
    if (!file) return

    setImporting(true)
    try {
      const created = await knowledgeApi.importLibrary(file)
      addNotification({
        level: 'success',
        title: 'Library imported',
        message: `${created.name} has been imported.`,
      })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to import library.'
      addNotification({
        level: 'error',
        title: 'Import failed',
        message,
      })
    } finally {
      setImporting(false)
    }
  }

  useEffect(() => {
    fetchLibraries()
  }, [fetchLibraries])

  const visibleLibraries = isSanitised
    ? libraries.filter((l) => !l.nsfw)
    : libraries

  async function handleSaveLibrary(data: { name: string; description: string; nsfw: boolean; default_refresh: RefreshFrequency }) {
    if (libraryModal.mode === 'create') {
      await knowledgeApi.createLibrary(data)
    } else if (libraryModal.mode === 'edit') {
      await knowledgeApi.updateLibrary(libraryModal.library.id, data)
    }
  }

  async function handleDeleteLibrary() {
    if (libraryModal.mode !== 'edit') return
    const library = libraryModal.library
    const report = await knowledgeApi.deleteLibrary(library.id)
    setDeletionReport(report)
    addNotification({
      level: report.success ? 'success' : 'warning',
      title: report.success ? 'Library deleted' : 'Library deletion partially failed',
      message: report.success
        ? `${library.name} has been permanently deleted.`
        : `${library.name} could not be fully removed — see the report for details.`,
    })
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

  async function handleSaveDocument(data: { title: string; content: string; media_type: 'text/markdown' | 'text/plain'; trigger_phrases: string[]; refresh: RefreshFrequency | null }) {
    if (documentModal.mode === 'create') {
      await knowledgeApi.createDocument(documentModal.libraryId, data)
      fetchLibraries()
    } else if (documentModal.mode === 'edit') {
      await knowledgeApi.updateDocument(documentModal.libraryId, documentModal.doc.id, data)
    }
  }

  async function handleDeleteDocument() {
    if (documentModal.mode !== 'edit') return
    await knowledgeApi.deleteDocument(documentModal.libraryId, documentModal.doc.id)
    fetchLibraries()
  }

  async function handleRetryEmbedding(libraryId: string, docId: string) {
    useKnowledgeStore.getState().onDocumentEmbeddingStatus(docId, 'processing')
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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => importInputRef.current?.click()}
            disabled={importing}
            className="rounded border border-white/15 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/65 transition-colors hover:border-white/30 hover:text-white/85 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            title="Import a library archive"
          >
            {importing ? 'Importing…' : '⇪ Import'}
          </button>
          <button
            type="button"
            onClick={() => setLibraryModal({ mode: 'create' })}
            className="rounded border border-gold/30 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors hover:bg-gold/10 hover:border-gold/40 cursor-pointer"
          >
            + New Library
          </button>
        </div>
      </div>

      <input
        ref={importInputRef}
        type="file"
        accept=".tar.gz,.gz,application/gzip"
        className="hidden"
        onChange={handleImportFile}
      />

      {/* Library list */}
      <div className="flex-1 overflow-y-auto">
        {visibleLibraries.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-16">
            <p className="text-[12px] font-mono text-white/60">No libraries yet</p>
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
                    <span className="flex-shrink-0" title="NSFW">
                      <KissMarkIcon style={{ fontSize: '12px' }} />
                    </span>
                  )}
                  {hasFailed && (
                    <span className="flex-shrink-0 text-[12px]" title="Some documents have failed embeddings">⚠</span>
                  )}
                </button>

                {/* Export button */}
                <button
                  type="button"
                  onClick={() => handleExportLibrary(library)}
                  disabled={exportingLibraryId === library.id}
                  aria-label={`Export library ${library.name}`}
                  className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 flex-shrink-0 rounded border border-white/8 px-1.5 py-0.5 text-[10px] font-mono text-white/60 transition-all hover:border-white/20 hover:text-white/80 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
                  title="Export library"
                >
                  {exportingLibraryId === library.id ? '…' : '⇩'}
                </button>

                {/* Edit button */}
                <button
                  type="button"
                  onClick={() => setLibraryModal({ mode: 'edit', library })}
                  aria-label={`Edit library ${library.name}`}
                  className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 flex-shrink-0 rounded border border-white/8 px-1.5 py-0.5 text-[10px] font-mono text-white/60 transition-all hover:border-white/20 hover:text-white/80 cursor-pointer"
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
                default_refresh: libraryModal.library.default_refresh,
              }
            : undefined}
          onSave={handleSaveLibrary}
          onDelete={libraryModal.mode === 'edit' ? handleDeleteLibrary : undefined}
          onClose={() => setLibraryModal({ mode: 'none' })}
        />
      )}

      {/* Document editor modal */}
      {documentModal.mode !== 'none' && (() => {
        const docLibrary = libraries.find((l) => l.id === documentModal.libraryId)
        const libraryDefaultRefresh = docLibrary?.default_refresh ?? 'standard'
        return (
          <DocumentEditorModal
            libraryId={documentModal.libraryId}
            libraryDefaultRefresh={libraryDefaultRefresh}
            initial={documentModal.mode === 'edit'
              ? {
                  title: documentModal.doc.title,
                  content: documentModal.doc.content,
                  media_type: documentModal.doc.media_type,
                  trigger_phrases: documentModal.doc.trigger_phrases,
                  refresh: documentModal.doc.refresh,
                }
              : undefined}
            onSave={handleSaveDocument}
            onDelete={documentModal.mode === 'edit' ? handleDeleteDocument : undefined}
            onClose={() => setDocumentModal({ mode: 'none' })}
          />
        )
      })()}

      {/* Cascade-delete report — shown after the editor modal closes. */}
      <DeletionReportSheet
        report={deletionReport}
        onClose={() => setDeletionReport(null)}
      />
    </div>
  )
}
