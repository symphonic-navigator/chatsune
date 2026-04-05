import { create } from "zustand"
import type { StorageFileDto, AttachmentRefDto } from "../api/storage"

export interface PendingAttachment {
  localId: string
  file: File
  status: "uploading" | "done" | "error"
  fileId: string | null
  dto: StorageFileDto | null
  localPreviewUrl: string | null
  error: string | null
}

interface UploadState {
  pendingAttachments: PendingAttachment[]
  addPending: (attachment: PendingAttachment) => void
  updatePending: (localId: string, updates: Partial<PendingAttachment>) => void
  removePending: (localId: string) => void
  clearPending: () => void
}

export const useUploadStore = create<UploadState>((set) => ({
  pendingAttachments: [],

  addPending: (attachment) =>
    set((s) => ({ pendingAttachments: [...s.pendingAttachments, attachment] })),

  updatePending: (localId, updates) =>
    set((s) => ({
      pendingAttachments: s.pendingAttachments.map((a) =>
        a.localId === localId ? { ...a, ...updates } : a,
      ),
    })),

  removePending: (localId) =>
    set((s) => {
      const att = s.pendingAttachments.find((a) => a.localId === localId)
      if (att?.localPreviewUrl) URL.revokeObjectURL(att.localPreviewUrl)
      return { pendingAttachments: s.pendingAttachments.filter((a) => a.localId !== localId) }
    }),

  clearPending: () =>
    set((s) => {
      s.pendingAttachments.forEach((a) => {
        if (a.localPreviewUrl) URL.revokeObjectURL(a.localPreviewUrl)
      })
      return { pendingAttachments: [] }
    }),
}))

export function toAttachmentRefs(attachments: PendingAttachment[]): AttachmentRefDto[] {
  return attachments
    .filter(
      (a): a is PendingAttachment & { dto: StorageFileDto } =>
        a.status === "done" && a.dto !== null,
    )
    .map((a) => ({
      file_id: a.dto.id,
      display_name: a.dto.display_name,
      media_type: a.dto.media_type,
      size_bytes: a.dto.size_bytes,
      thumbnail_b64: a.dto.thumbnail_b64,
      text_preview: a.dto.text_preview,
    }))
}
