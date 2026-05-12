/**
 * Banner-style panel rendering the live memory-batch state for a given
 * ChatGPT import + persona.
 *
 * Reads from ``useMemoryBatchStore``. Renders ``null`` when no batch row
 * exists or when the batch is in a terminal-and-acknowledged state
 * (``discarded``). For ``done`` the panel shows a one-shot success
 * summary so the user sees their work completed.
 *
 * Layout follows the spec §6.1:
 *  - running  → progress bar + currently-processing title
 *  - paused   → reason + Resume / Discard (with force-budget variant
 *               when the pause reason is ``budget_exhausted``)
 *  - done     → "N / N extracted, M memories created"
 *
 * Style aligns with ``ParseProgressBanner`` (rounded card, coloured
 * accent border) — user-facing surface, so the opulent prototype style
 * applies rather than Catppuccin admin colours.
 */
import { useState } from 'react'

import { chatGptImportApi } from '../../core/api/chatGptImportApi'
import {
  selectBatchByImportAndPersona,
  useMemoryBatchStore,
} from '../../core/store/memoryBatchStore'

interface Props {
  importId: string
  personaId: string
}

function reasonHeadline(reason: string, userMessage: string): string {
  if (reason === 'budget_exhausted') return 'Daily budget exhausted'
  if (reason === 'provider_unavailable') return 'Provider not reachable'
  return userMessage || 'Memory extraction paused'
}

export function MemoryBatchProgressPanel({ importId, personaId }: Props) {
  const batch = useMemoryBatchStore(
    selectBatchByImportAndPersona(importId, personaId),
  )
  const setBatch = useMemoryBatchStore((s) => s.setBatch)
  const [busy, setBusy] = useState(false)
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)

  if (!batch) return null
  if (batch.state === 'discarded' || batch.state === 'pending') return null

  const total = batch.target_count

  const handleResume = async (forceBudget: boolean) => {
    if (busy) return
    setBusy(true)
    try {
      const next = await chatGptImportApi.resumeMemoryBatch(
        importId,
        personaId,
        forceBudget,
      )
      setBatch(next)
    } catch (err) {
      console.error('Failed to resume memory batch', err)
    } finally {
      setBusy(false)
    }
  }

  const handleDiscard = async () => {
    if (busy) return
    setBusy(true)
    try {
      const next = await chatGptImportApi.discardMemoryBatch(
        importId,
        personaId,
      )
      setBatch(next)
    } catch (err) {
      console.error('Failed to discard memory batch', err)
    } finally {
      setBusy(false)
      setConfirmingDiscard(false)
    }
  }

  // --- Running -----------------------------------------------------------

  if (batch.state === 'running') {
    const currentIndex = batch.current_session_index ?? 0
    const percent = total > 0
      ? Math.max(0, Math.min(100, Math.round(((currentIndex - 1) / total) * 100)))
      : 0
    return (
      <div className="bg-indigo-900/30 border border-indigo-700 rounded-lg p-4 mb-4">
        <div className="flex items-baseline justify-between gap-3 mb-2">
          <span className="text-indigo-100 text-sm">
            Memory extraction:{' '}
            <strong>
              {Math.max(0, currentIndex - 1)} / {total}
            </strong>
          </span>
          <span className="text-indigo-200/70 text-xs font-mono">
            {percent}%
          </span>
        </div>
        <div
          className="h-1.5 w-full rounded-full overflow-hidden bg-indigo-900/50"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-indigo-400 transition-all duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
        {batch.current_session_title && (
          <p className="text-indigo-200/80 text-xs mt-2">
            Currently processing:{' '}
            <span className="text-indigo-100">
              “{batch.current_session_title}”
            </span>
          </p>
        )}
      </div>
    )
  }

  // --- Paused ------------------------------------------------------------

  if (batch.state === 'paused' && batch.paused_at) {
    const at = batch.paused_at
    const headline = reasonHeadline(at.reason, at.user_message)
    const isBudget = at.reason === 'budget_exhausted'
    // For budget_exhausted, "Resume tomorrow" is a deliberate no-op
    // (spec §6.1): the user closes the dialog and re-opens later when
    // the daily budget has reset. We collapse the paused banner from
    // view via a local dismissed flag so they aren't nagged.
    const handleResumeTomorrow = () => {
      // No-op: leave the batch as-is. The user can reopen the tab
      // tomorrow to find the paused panel and try a normal Resume.
    }
    return (
      <div className="bg-amber-900/30 border border-amber-700 rounded-lg p-4 mb-4">
        <p className="text-amber-100 text-sm">
          Memory extraction paused at{' '}
          <strong>
            {at.session_index} / {total}
          </strong>
        </p>
        <p className="text-amber-200/80 text-xs mt-1">Reason: {headline}</p>
        {at.user_message && at.user_message !== headline && (
          <p className="text-amber-200/60 text-xs mt-1">{at.user_message}</p>
        )}

        <div className="flex flex-wrap items-center gap-2 mt-3">
          {isBudget ? (
            <>
              <button
                type="button"
                onClick={handleResumeTomorrow}
                disabled={busy}
                className="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 text-amber-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title="Defer until the daily budget resets"
              >
                Resume tomorrow
              </button>
              <button
                type="button"
                onClick={() => handleResume(true)}
                disabled={busy}
                className="px-3 py-1.5 rounded text-xs bg-amber-500/20 hover:bg-amber-500/30 text-amber-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title="Continue immediately and exceed the daily budget"
              >
                Resume now — exceed budget
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => handleResume(false)}
              disabled={busy}
              className="px-3 py-1.5 rounded text-xs bg-amber-500/20 hover:bg-amber-500/30 text-amber-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Resume
            </button>
          )}
          <button
            type="button"
            onClick={() => setConfirmingDiscard(true)}
            disabled={busy}
            className="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 text-red-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Discard remaining
          </button>
        </div>

        {confirmingDiscard && (
          <div className="mt-3 p-3 rounded bg-black/30 border border-white/10">
            <p className="text-white/80 text-xs">
              Discard the remaining {Math.max(0, total - at.session_index + 1)}{' '}
              conversation
              {Math.max(0, total - at.session_index + 1) === 1 ? '' : 's'}? The
              memories already extracted will stay.
            </p>
            <div className="flex items-center gap-2 mt-2">
              <button
                type="button"
                onClick={handleDiscard}
                disabled={busy}
                className="px-3 py-1.5 rounded text-xs bg-red-500/20 hover:bg-red-500/30 text-red-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Yes, discard
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDiscard(false)}
                disabled={busy}
                className="px-3 py-1.5 rounded text-xs bg-white/5 hover:bg-white/10 text-white/70 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  // --- Done --------------------------------------------------------------

  if (batch.state === 'done') {
    return (
      <div className="bg-emerald-900/30 border border-emerald-700 rounded-lg p-4 mb-4 flex items-center justify-between gap-3">
        <p className="text-emerald-100 text-sm">
          <span aria-hidden className="mr-1">
            ✓
          </span>
          Memory extraction complete:{' '}
          <strong>
            {total} / {total}
          </strong>{' '}
          — {batch.total_entries_created} memor
          {batch.total_entries_created === 1 ? 'y' : 'ies'} created
        </p>
      </div>
    )
  }

  return null
}
