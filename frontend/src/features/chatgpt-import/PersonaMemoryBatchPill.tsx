/**
 * Inline status pill for a persona's active ChatGPT-import memory batch.
 *
 * Renders nothing when no batch is in ``running`` or ``paused`` state for
 * the persona — the pill is optional content, not a permanently-visible
 * widget. (Differs from ``feedback_disabled_over_hidden`` because there
 * is no equivalent "no batch in progress" affordance; the pill belongs to
 * the batch's existence, not to a control.)
 *
 * Style mirrors the voice-tag / integration-pill convention in
 * ``index.css``: small monospace, low-key bg/fg, slight vertical-align.
 * The whole pill is a button — click navigates to the ChatGPT-import
 * tab so the user can resume / discard from there.
 *
 * When multiple imports share a persona (rare), the first active one is
 * shown — the user can step through them by opening the tab.
 */
import { useMemoryBatchStore, selectFirstActiveBatchForPersona } from '../../core/store/memoryBatchStore'

interface Props {
  personaId: string
  onOpenImportTab: () => void
}

export function PersonaMemoryBatchPill({ personaId, onOpenImportTab }: Props) {
  const batch = useMemoryBatchStore(selectFirstActiveBatchForPersona(personaId))
  if (!batch) return null
  const total = batch.target_count
  const current =
    batch.state === 'paused' && batch.paused_at
      ? Math.max(0, batch.paused_at.session_index - 1)
      : Math.max(0, (batch.current_session_index ?? 0) - 1)
  const paused = batch.state === 'paused'

  return (
    <button
      type="button"
      onClick={onOpenImportTab}
      className="inline-flex items-center gap-1 rounded text-[10px] font-mono px-1.5 py-0.5 transition-colors"
      style={{
        background: paused
          ? 'rgba(245, 158, 11, 0.16)'
          : 'rgba(255, 255, 255, 0.08)',
        color: paused ? 'rgba(252, 211, 77, 0.95)' : 'rgba(255, 255, 255, 0.65)',
        verticalAlign: '0.05em',
      }}
      title={
        paused
          ? 'Imported-conversation memory extraction paused — click to resolve'
          : 'Imported-conversation memory extraction in progress'
      }
      aria-label={
        paused
          ? `Memory batch paused at ${current} of ${total}`
          : `Memory batch in progress: ${current} of ${total}`
      }
    >
      <span>memory: {current} / {total}</span>
      {paused && <span aria-hidden>⏸</span>}
    </button>
  )
}
