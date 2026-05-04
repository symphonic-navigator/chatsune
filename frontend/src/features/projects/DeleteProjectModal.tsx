// DeleteProjectModal — spec §9. Single-modal pattern with a safe
// default and an explicit checkbox for the destructive variant.
//
// Layout:
//
//   Delete project "<title>"
//   ─────────────────────────
//
//   After deletion, this project will be removed.
//   Its 14 chats will return to your global history.
//
//   [ ] Also delete all data permanently
//       14 chats · 8 uploads · 23 artefacts · 6 images
//       This cannot be undone.
//
//                              [Cancel]   [Delete project]
//
// Behaviour: on mount we fetch ``GET /api/projects/{id}?include_usage=true``
// to render counts. The submit button label and style change when the
// purge checkbox flips on; the API call goes to
// ``projectsApi.delete(id, purgeData)``. After success the modal closes
// — the project store reconciles via the ``PROJECT_DELETED`` WS event,
// no follow-up GET needed.

import { useEffect, useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { useNotificationStore } from '../../core/store/notificationStore'
import { projectsApi } from './projectsApi'
import type { ProjectUsageDto } from './types'

export interface DeleteProjectModalProps {
  isOpen: boolean
  /** ID of the project to delete. */
  projectId: string
  /** Title surfaced in the heading — passed in to avoid a second store lookup. */
  projectTitle: string
  onClose: () => void
}

export function DeleteProjectModal({
  isOpen,
  projectId,
  projectTitle,
  onClose,
}: DeleteProjectModalProps) {
  const addNotification = useNotificationStore((s) => s.addNotification)

  const [usage, setUsage] = useState<ProjectUsageDto | null>(null)
  const [usageError, setUsageError] = useState(false)
  const [purgeData, setPurgeData] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Reset modal state every time it (re-)opens so a previous run
  // doesn't leak into the next session.
  useEffect(() => {
    if (!isOpen) return
    setUsage(null)
    setUsageError(false)
    setPurgeData(false)
    setSubmitting(false)

    let cancelled = false
    projectsApi
      .get(projectId, true)
      .then((res) => {
        if (cancelled) return
        setUsage(res.usage ?? null)
      })
      .catch(() => {
        if (cancelled) return
        // We still let the user proceed with the delete — the counts
        // are an informational nicety, not a precondition.
        setUsageError(true)
      })
    return () => {
      cancelled = true
    }
  }, [isOpen, projectId])

  async function handleSubmit() {
    if (submitting) return
    setSubmitting(true)
    try {
      await projectsApi.delete(projectId, purgeData)
      onClose()
    } catch {
      addNotification({
        level: 'error',
        title: 'Delete failed',
        message: 'Could not delete the project. Please try again.',
      })
      setSubmitting(false)
    }
  }

  const chatCount = usage?.chat_count ?? 0
  const submitLabel = purgeData ? 'Delete project + all data' : 'Delete project'

  return (
    <Sheet
      isOpen={isOpen}
      onClose={submitting ? () => {} : onClose}
      size="md"
      ariaLabel={`Delete project ${projectTitle}`}
      className="border border-white/8 bg-elevated shadow-2xl"
    >
      <div className="flex flex-col" data-testid="delete-project-modal">
        {/* Header */}
        <div className="border-b border-white/6 px-5 py-4">
          <h2 className="text-[14px] font-semibold text-white/90">
            Delete project "{projectTitle}"
          </h2>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-4 overflow-y-auto px-5 py-4">
          <p className="text-[13px] text-white/75">
            After deletion, this project will be removed.{' '}
            {usage ? (
              <span data-testid="delete-project-safe-summary">
                {chatCount === 1
                  ? 'Its 1 chat will return to your global history.'
                  : `Its ${chatCount} chats will return to your global history.`}
              </span>
            ) : usageError ? (
              <span className="text-white/50" data-testid="delete-project-usage-error">
                (Usage counts unavailable.)
              </span>
            ) : (
              <span className="text-white/50">Loading usage counts…</span>
            )}
          </p>

          <label className="flex cursor-pointer items-start gap-3 rounded-md border border-white/8 bg-white/3 p-3 transition-colors hover:bg-white/5">
            <input
              type="checkbox"
              checked={purgeData}
              onChange={(e) => setPurgeData(e.target.checked)}
              disabled={submitting}
              data-testid="delete-project-purge-toggle"
              className="mt-0.5 h-3.5 w-3.5 cursor-pointer"
            />
            <div className="flex flex-1 flex-col gap-1">
              <span className="text-[12px] font-medium text-white/85">
                Also delete all data permanently
              </span>
              {usage && (
                <span
                  className="font-mono text-[11px] text-white/55"
                  data-testid="delete-project-purge-counts"
                >
                  {usage.chat_count} chat{usage.chat_count === 1 ? '' : 's'} ·{' '}
                  {usage.upload_count} upload
                  {usage.upload_count === 1 ? '' : 's'} ·{' '}
                  {usage.artefact_count} artefact
                  {usage.artefact_count === 1 ? '' : 's'} ·{' '}
                  {usage.image_count} image
                  {usage.image_count === 1 ? '' : 's'}
                </span>
              )}
              <span className="text-[11px] text-red-300/80">
                This cannot be undone.
              </span>
            </div>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-white/6 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            data-testid="delete-project-cancel"
            className="rounded border border-white/8 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/60 transition-colors hover:border-white/15 hover:text-white/80 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting}
            data-testid="delete-project-submit"
            className={[
              'rounded px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-40',
              purgeData
                ? 'border border-red-500/45 bg-red-500/15 text-red-300 hover:bg-red-500/25'
                : 'border border-white/15 bg-white/8 text-white/85 hover:bg-white/12',
            ].join(' ')}
          >
            {submitting ? 'Deleting…' : submitLabel}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
