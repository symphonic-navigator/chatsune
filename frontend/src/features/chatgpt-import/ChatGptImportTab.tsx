/**
 * Persona-overlay tab — turns a ChatGPT export bundle into native sessions.
 *
 * State machine:
 *   - no active import  → show ``UploadEmptyState``
 *   - status=parsing    → show ``ParseProgressBanner`` (live event-driven count)
 *   - status=failed     → show ``ParseProgressBanner`` in failure variant
 *   - status=ready      → show ``ConversationList`` with multi-select + import
 *
 * The active import is per-user (not per-persona). The list, however, is
 * scoped to the current persona id for the "imported into this persona"
 * badge logic.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  chatGptImportApi,
  type ConversationItemDto,
} from '../../core/api/chatGptImportApi'
import { ApiError } from '../../core/api/client'
import { personasApi } from '../../core/api/personas'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'
import { useMemoryBatchStore } from '../../core/store/memoryBatchStore'
import { useNotificationStore } from '../../core/store/notificationStore'

import { ConversationList } from './ConversationList'
import { MemoryBatchProgressPanel } from './MemoryBatchProgressPanel'
import { ParseProgressBanner } from './ParseProgressBanner'
import { ReplaceUploadDialog } from './ReplaceUploadDialog'
import { UploadEmptyState } from './UploadEmptyState'
import { useChatGptImportEvents } from './useChatGptImportEvents'

interface Props {
  personaId: string
  personaName: string
}

export function ChatGptImportTab({ personaId, personaName }: Props) {
  const activeImport = useChatGptImportStore((s) => s.activeImport)
  const conversations = useChatGptImportStore((s) => s.conversations)
  const parseProgress = useChatGptImportStore((s) => s.parseProgress)
  const setActiveImport = useChatGptImportStore((s) => s.setActiveImport)
  const setConversations = useChatGptImportStore((s) => s.setConversations)
  const setImportingIds = useChatGptImportStore((s) => s.setImportingIds)
  const clearSelection = useChatGptImportStore((s) => s.clearSelection)
  const titleSearch = useChatGptImportStore((s) => s.titleSearch)
  const sort = useChatGptImportStore((s) => s.sort)

  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [replaceDialogFile, setReplaceDialogFile] = useState<File | null>(null)
  const [personaNames, setPersonaNames] = useState<Record<string, string>>({})

  useChatGptImportEvents()

  // One-shot persona-names map for badge rendering.
  useEffect(() => {
    let cancelled = false
    personasApi.list().then((list) => {
      if (cancelled) return
      const map: Record<string, string> = {}
      list.forEach((p) => {
        map[p.id] = p.name
      })
      setPersonaNames(map)
    }).catch(() => {
      // Falls back to whatever persona_name the event payload carried.
    })
    return () => {
      cancelled = true
    }
  }, [])

  // Initial fetch of the active import (if any).
  useEffect(() => {
    chatGptImportApi
      .getActiveImport()
      .then((imp) => setActiveImport(imp))
      .catch(() => setActiveImport(null))
  }, [setActiveImport])

  // Rehydrate the memory-batch state from the server whenever the
  // import + persona pair changes. Idempotent; collapses to no-op when
  // no batch exists for the pair.
  useEffect(() => {
    if (!activeImport) return
    void useMemoryBatchStore
      .getState()
      .rehydrateForPersona(activeImport.import_id, personaId)
  }, [activeImport, personaId])

  // Reload conversations whenever filters or the active import change.
  useEffect(() => {
    if (!activeImport || activeImport.status !== 'ready') {
      setConversations([])
      return
    }
    chatGptImportApi
      .listConversations(activeImport.import_id, { titleSearch, sort })
      .then(setConversations)
      .catch((err) => {
        console.error('Failed to list ChatGPT-import conversations', err)
      })
  }, [activeImport, titleSearch, sort, setConversations])

  const performUpload = useCallback(
    async (file: File, replace: boolean) => {
      setIsUploading(true)
      setUploadProgress(0)
      try {
        const res = await chatGptImportApi.uploadFile(file, {
          replace,
          onProgress: (loaded) => setUploadProgress(loaded),
        })
        const imp = await chatGptImportApi.getActiveImport()
        setActiveImport(imp)
        if (res.duplicate && imp) {
          const convs = await chatGptImportApi.listConversations(imp.import_id)
          setConversations(convs)
          useNotificationStore.getState().addNotification({
            level: 'info',
            title: 'Same file already uploaded',
            message: 'Using the existing parsed copy.',
          })
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setReplaceDialogFile(file)
        } else {
          console.error(err)
          useNotificationStore.getState().addNotification({
            level: 'error',
            title: 'Upload failed',
            message: err instanceof Error ? err.message : 'Unknown error',
          })
        }
      } finally {
        setIsUploading(false)
        setUploadProgress(null)
      }
    },
    [setActiveImport, setConversations],
  )

  const onFileSelected = useCallback(
    (file: File) => performUpload(file, false),
    [performUpload],
  )

  const onReplaceConfirm = useCallback(() => {
    if (replaceDialogFile) {
      const file = replaceDialogFile
      setReplaceDialogFile(null)
      void performUpload(file, true)
    }
  }, [replaceDialogFile, performUpload])

  const onConfirmImport = useCallback(
    async (convs: ConversationItemDto[]) => {
      if (!activeImport) return
      const ids = convs.map((c) => c.chatgpt_conversation_id)
      setImportingIds(new Set(ids))
      clearSelection()
      try {
        await chatGptImportApi.triggerImport(activeImport.import_id, {
          persona_id: personaId,
          chatgpt_conversation_ids: ids,
        })
        useNotificationStore.getState().addNotification({
          level: 'info',
          title: `Importing ${ids.length} conversation${ids.length === 1 ? '' : 's'}`,
          message: 'Sessions will appear in the persona history when ready.',
        })
      } catch (err) {
        console.error(err)
        useNotificationStore.getState().addNotification({
          level: 'error',
          title: 'Import failed',
          message: err instanceof Error ? err.message : 'Unknown error',
        })
        setImportingIds(new Set())
      }
    },
    [activeImport, personaId, setImportingIds, clearSelection],
  )

  const onDelete = useCallback(async () => {
    if (!activeImport) return
    if (!window.confirm('Delete this upload? Already-imported sessions are kept.')) {
      return
    }
    try {
      await chatGptImportApi.deleteImport(activeImport.import_id)
    } catch (err) {
      console.error(err)
    }
    setActiveImport(null)
  }, [activeImport, setActiveImport])

  const formattedExpiry = useMemo(() => {
    if (!activeImport) return ''
    try {
      return new Date(activeImport.expires_at).toLocaleDateString()
    } catch {
      return ''
    }
  }, [activeImport])

  // --- States --------------------------------------------------------

  if (!activeImport) {
    return (
      <>
        <UploadEmptyState
          onFileSelected={onFileSelected}
          isUploading={isUploading}
          uploadProgress={uploadProgress}
        />
        <ReplaceUploadDialog
          isOpen={replaceDialogFile !== null}
          currentFilename=""
          currentConversationCount={0}
          onCancel={() => setReplaceDialogFile(null)}
          onConfirm={onReplaceConfirm}
        />
      </>
    )
  }

  if (activeImport.status === 'parsing') {
    return (
      <div className="p-4">
        <ParseProgressBanner
          conversationsIndexed={parseProgress?.conversationsIndexed ?? 0}
        />
        <button
          type="button"
          onClick={onDelete}
          className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded text-red-300"
        >
          Cancel and delete
        </button>
      </div>
    )
  }

  if (activeImport.status === 'failed') {
    return (
      <div className="p-4">
        <ParseProgressBanner
          conversationsIndexed={0}
          failed={{ errorMessage: activeImport.error_message ?? 'Unknown error' }}
          onRestart={onDelete}
        />
      </div>
    )
  }

  return (
    <div className="p-4 pb-0">
      <div
        id="chatgpt-import-memory-batch-panel"
        data-import-id={activeImport.import_id}
        data-persona-id={personaId}
      >
        <MemoryBatchProgressPanel
          importId={activeImport.import_id}
          personaId={personaId}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-white/5 rounded mb-4 text-sm">
        <span className="text-white/70">
          <code className="font-mono">{activeImport.filename}</code> ·{' '}
          {activeImport.conversation_count} conversations
          {activeImport.skipped_count > 0 && (
            <span className="text-amber-300">
              {' '}
              · {activeImport.skipped_count} skipped
            </span>
          )}
          {' '}
          · expires {formattedExpiry}
        </span>
        <button
          type="button"
          onClick={onDelete}
          className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded text-red-300"
        >
          Delete upload
        </button>
      </div>
      <ConversationList
        conversations={conversations}
        currentPersonaId={personaId}
        currentPersonaName={personaName}
        personaNames={personaNames}
        onConfirmImport={onConfirmImport}
      />
      <ReplaceUploadDialog
        isOpen={replaceDialogFile !== null}
        currentFilename={activeImport.filename}
        currentConversationCount={activeImport.conversation_count}
        onCancel={() => setReplaceDialogFile(null)}
        onConfirm={onReplaceConfirm}
      />
    </div>
  )
}
