import { useEffect, useId } from 'react'

export interface EditResendDialogProps {
  isOpen: boolean
  /** Triggered when the user picks "Replace response" — runs the existing
   *  in-place edit flow (truncate-and-resend on the same session). */
  onReplace: () => void
  /** Triggered when the user picks "New branch" — opens the
   *  ``BranchNameDialog`` and proceeds with the branch flow. */
  onBranch: () => void
  onClose: () => void
}

/**
 * Case-1 prompt shown when the user edits the LAST user message and saves
 * the change: pick between rewriting the response in-place or forking the
 * conversation into a new branch. See
 * ``devdocs/specs/2026-05-17-branching-design.md`` §6.2.
 *
 * Earlier-message edits (case 2) skip this dialog and go directly to the
 * ``BranchNameDialog``.
 */
export function EditResendDialog({
  isOpen,
  onReplace,
  onBranch,
  onClose,
}: EditResendDialogProps) {
  const titleId = useId()

  useEffect(() => {
    if (!isOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="presentation"
    >
      <button
        type="button"
        aria-label="Close dialog"
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="edit-resend-dialog"
        className="relative z-10 mx-4 w-full max-w-md rounded-xl border border-white/10 bg-[#13101e] p-5 shadow-2xl"
      >
        <h2
          id={titleId}
          className="mb-2 font-mono text-[13px] font-semibold text-white/85"
        >
          Replace response or new branch?
        </h2>
        <p className="mb-4 text-[12px] leading-relaxed text-white/55">
          You can replace the existing response with a new one, or create a
          new branch instead in which the old response is preserved.
        </p>
        <div className="flex flex-col gap-2">
          <button
            type="button"
            data-testid="edit-resend-replace"
            onClick={onReplace}
            className="w-full rounded bg-white/12 px-3 py-2 text-left text-[12px] font-semibold text-white/85 transition-colors hover:bg-white/18"
          >
            Replace response
          </button>
          <button
            type="button"
            data-testid="edit-resend-branch"
            onClick={onBranch}
            className="w-full rounded bg-white/12 px-3 py-2 text-left text-[12px] font-semibold text-white/85 transition-colors hover:bg-white/18"
          >
            New branch
          </button>
          <button
            type="button"
            data-testid="edit-resend-cancel"
            onClick={onClose}
            className="mt-1 self-end rounded px-3 py-1.5 text-[12px] text-white/55 transition-colors hover:bg-white/5 hover:text-white/80"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
