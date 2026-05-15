import type { CompactionCheckpoint } from '../../../core/api/chat'

interface Props {
  checkpoint: CompactionCheckpoint
  onOpen: () => void
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${Math.round(n / 1000)}k`
  return String(n)
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/**
 * Horizontal divider with a centred pill marking a compaction
 * checkpoint in the chat timeline. Click opens the snapshot drawer.
 *
 * Styled to match the neighbouring sparkly button vocabulary: a tiny
 * mono pill with a 1px border, dark surface, amber accent. The
 * horizontal rules use the chat's existing low-contrast border colour
 * so the marker reads as a quiet separator rather than a banner. See
 * ``devdocs/specs/2026-05-15-compact-and-continue-design.md`` §5.4.
 */
export function CompactedMarkerPill({ checkpoint, onOpen }: Props) {
  return (
    <div className="my-4 flex items-center" role="separator" aria-label="Compaction checkpoint">
      <hr className="flex-1 border-t border-white/10" />
      <button
        type="button"
        onClick={onOpen}
        className="mx-3 rounded-full border border-amber-400/25 bg-amber-400/5 px-3 py-0.5 font-mono text-[11px] text-amber-200/90 hover:bg-amber-400/10 transition-colors"
        title="Open compaction snapshot"
      >
        <span aria-hidden>{'✨ '}</span>
        Compacted · {formatTime(checkpoint.created_at)} ·{' '}
        {formatTokens(checkpoint.tokens_before)} → {formatTokens(checkpoint.tokens_after)} tokens
      </button>
      <hr className="flex-1 border-t border-white/10" />
    </div>
  )
}
