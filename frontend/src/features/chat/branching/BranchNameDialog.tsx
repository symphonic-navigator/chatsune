import { useEffect, useId, useRef, useState } from 'react'
import type { ChatSessionDto } from '../../../core/api/chat'

/**
 * Compute the default branch name as ``${parentTitle} (Variante ${n})`` where
 * ``n`` is one greater than the highest variant index seen on any sibling
 * session whose title matches ``${parentTitle} (Variante <number>)``.
 *
 * Best-effort only: the system does not enforce unique titles. Concurrent
 * branch creation from two tabs may produce the same variant index — that's
 * a cosmetic collision the user can fix by renaming.
 *
 * Exported for unit testing.
 */
export function computeDefaultBranchName(
  parentTitle: string,
  allSessions: readonly Pick<ChatSessionDto, 'title'>[],
): string {
  const prefix = `${parentTitle} (Variante `
  let maxIdx = 0
  for (const session of allSessions) {
    const t = session.title
    if (!t || !t.startsWith(prefix)) continue
    const rest = t.slice(prefix.length)
    const closeIdx = rest.indexOf(')')
    if (closeIdx === -1) continue
    const numStr = rest.slice(0, closeIdx).trim()
    const num = Number.parseInt(numStr, 10)
    if (Number.isFinite(num) && num > maxIdx) maxIdx = num
  }
  return `${parentTitle} (Variante ${maxIdx + 1})`
}

export interface BranchNameDialogProps {
  isOpen: boolean
  /** Parent session title — used to seed the default name. ``null`` falls
   *  back to the literal "Chat" so the input is never empty. */
  parentTitle: string | null
  /** All sessions visible to the user — scanned for sibling variant indices.
   *  See ``computeDefaultBranchName``. */
  allSessions: readonly Pick<ChatSessionDto, 'title'>[]
  /** Fired with the trimmed name when the user confirms. The handler may
   *  return a promise; while it is pending the dialog renders a loader
   *  in place of the body and disables interaction (the Escape / overlay
   *  dismissal still works so a hung request can be aborted). */
  onConfirm: (name: string) => void | Promise<void>
  onClose: () => void
}

/**
 * Modal dialog for naming a new branch. See
 * ``devdocs/specs/2026-05-17-branching-design.md`` §6.3.
 *
 * Behaviour:
 *   - Pre-fills the input with ``${parentTitle} (Variante ${nextIdx})``.
 *   - Escape and overlay click dismiss without creating a branch.
 *   - Primary action disabled while the trimmed input is empty.
 *   - On confirm, the body is replaced by a "Branch wird erstellt..." loader
 *     while the parent handler is in flight. The dialog stays mounted so the
 *     loader can be cancelled by Escape or by the parent dismissing it.
 */
export function BranchNameDialog({
  isOpen,
  parentTitle,
  allSessions,
  onConfirm,
  onClose,
}: BranchNameDialogProps) {
  const effectiveParentTitle = parentTitle?.trim() || 'Chat'
  const titleId = useId()
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Reset state when the dialog opens. We deliberately recompute the
  // default name on each open: the sidebar may have gained or lost
  // sibling variants since the previous opening.
  useEffect(() => {
    if (!isOpen) return
    setName(computeDefaultBranchName(effectiveParentTitle, allSessions))
    setSubmitting(false)
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (!el) return
      el.focus()
      el.select()
    })
  }, [isOpen, effectiveParentTitle, allSessions])

  // Escape closes the dialog. Mirrors ``BookmarkModal`` / ``Sheet``'s
  // behaviour but inlined here so the dialog stays standalone (no body
  // scroll lock — the parent chat view stays scrollable per the spec).
  useEffect(() => {
    if (!isOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const trimmed = name.trim()
  const canConfirm = trimmed.length > 0 && !submitting

  async function handleConfirm() {
    if (!canConfirm) return
    setSubmitting(true)
    try {
      await onConfirm(trimmed)
    } finally {
      // The parent owns dismissal — on success it usually closes the
      // dialog itself. We still reset ``submitting`` so a failure path
      // that re-opens the same dialog presents an actionable state.
      setSubmitting(false)
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleConfirm()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="presentation"
    >
      <button
        type="button"
        aria-label="Dialog schließen"
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="branch-name-dialog"
        className="relative z-10 mx-4 w-full max-w-md rounded-xl border border-white/10 bg-[#13101e] p-5 shadow-2xl"
      >
        <h2
          id={titleId}
          className="mb-3 font-mono text-[13px] font-semibold text-white/85"
        >
          Neuen Branch erstellen
        </h2>
        {submitting ? (
          <div
            data-testid="branch-name-dialog-loader"
            className="flex flex-col items-center gap-3 py-8 text-[12px] text-white/60"
          >
            <svg
              className="animate-spin"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
            <span>Branch wird erstellt...</span>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <label
              htmlFor={inputId}
              className="font-mono text-[11px] uppercase tracking-wider text-white/55"
            >
              Name
            </label>
            <input
              ref={inputRef}
              id={inputId}
              data-testid="branch-name-input"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-[13px] text-white/90 placeholder:text-white/25 outline-none transition-colors focus:border-white/20"
            />
            <div className="mt-2 flex justify-end gap-2">
              <button
                type="button"
                data-testid="branch-name-cancel"
                onClick={onClose}
                className="rounded px-3 py-1.5 text-[12px] text-white/55 transition-colors hover:bg-white/5 hover:text-white/80"
              >
                Abbrechen
              </button>
              <button
                type="button"
                data-testid="branch-name-confirm"
                onClick={handleConfirm}
                disabled={!canConfirm}
                className="rounded bg-white/12 px-3 py-1.5 text-[12px] font-semibold text-white/85 transition-colors hover:bg-white/18 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Branch erstellen
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
