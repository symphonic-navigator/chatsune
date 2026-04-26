import { useCallback } from 'react'
import { useUploadStore, toAttachmentRefs, type PendingAttachment } from '../../core/store/uploadStore'
import { uploadFile } from '../../core/api/storage'
import type { AttachmentRefDto } from '../../core/api/storage'
import type { GeneratedImageSummaryDto } from '../../core/api/images'

export function useAttachments(personaId?: string) {
  const pendingAttachments = useUploadStore((s) => s.pendingAttachments)
  const addPending = useUploadStore((s) => s.addPending)
  const updatePending = useUploadStore((s) => s.updatePending)
  const removePending = useUploadStore((s) => s.removePending)
  const clearPending = useUploadStore((s) => s.clearPending)

  const addFile = useCallback(
    async (file: File) => {
      // Dedupe check: same name + size already pending
      const existing = useUploadStore.getState().pendingAttachments
      if (existing.some((a) => a.file.name === file.name && a.file.size === file.size)) return

      const localId = `pending-${crypto.randomUUID()}`
      const localPreviewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : null

      const pending: PendingAttachment = {
        localId,
        file,
        status: 'uploading',
        fileId: null,
        dto: null,
        localPreviewUrl,
        error: null,
      }
      addPending(pending)

      try {
        const dto = await uploadFile(file, personaId)
        updatePending(localId, { status: 'done', fileId: dto.id, dto })
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Upload failed'
        updatePending(localId, { status: 'error', error: message })
      }
    },
    [personaId, addPending, updatePending],
  )

  const addExistingFile = useCallback(
    (dto: import('../../core/api/storage').StorageFileDto) => {
      // Add an already-uploaded file as a pending attachment (from upload browser)
      const existing = useUploadStore.getState().pendingAttachments
      if (existing.some((a) => a.fileId === dto.id)) return

      const localId = `existing-${crypto.randomUUID()}`
      addPending({
        localId,
        file: new File([], dto.display_name), // placeholder
        status: 'done',
        fileId: dto.id,
        dto,
        localPreviewUrl: null,
        error: null,
      })
    },
    [addPending],
  )

  const addGeneratedImage = useCallback(
    (image: GeneratedImageSummaryDto) => {
      // Skip if already queued (e.g. double-click on a tile).
      const existing = useUploadStore.getState().pendingAttachments
      if (existing.some((a) => a.fileId === image.id)) return

      const localId = `generated-${crypto.randomUUID()}`
      addPending({
        localId,
        // Placeholder File so the type check in AttachmentStrip resolves to an image.
        file: new File([], image.prompt.slice(0, 40) || 'generated-image', { type: 'image/jpeg' }),
        status: 'done',
        fileId: image.id,
        dto: null,
        localPreviewUrl: image.thumb_url,
        error: null,
      })
    },
    [addPending],
  )

  const hasPending = pendingAttachments.some((a) => a.status === 'uploading')
  const hasErrors = pendingAttachments.some((a) => a.status === 'error')
  const hasAttachments = pendingAttachments.length > 0

  const getAttachmentIds = useCallback((): string[] => {
    return pendingAttachments
      .filter((a) => a.status === 'done' && a.fileId)
      .map((a) => a.fileId!)
  }, [pendingAttachments])

  const getAttachmentRefs = useCallback((): AttachmentRefDto[] => {
    return toAttachmentRefs(pendingAttachments)
  }, [pendingAttachments])

  return {
    pendingAttachments,
    addFile,
    addExistingFile,
    addGeneratedImage,
    removeAttachment: removePending,
    clearAttachments: clearPending,
    hasPending,
    hasErrors,
    hasAttachments,
    getAttachmentIds,
    getAttachmentRefs,
  }
}
