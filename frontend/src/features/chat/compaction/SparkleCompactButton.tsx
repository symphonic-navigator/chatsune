import { useCompactionState } from './useCompactionState'

interface Props {
  /** Total number of messages in the active session's transcript. */
  totalMessages: number
  /** Total token usage for the active session (``contextUsedTokens``). */
  totalTokens: number
  /** Context fill ratio in the range 0..1 (``contextFillPercentage``). */
  fillPercentage: number
  /** True while a compaction job is in flight (from ``chatStore.compactionLoading``). */
  isLoading: boolean
  /** Fired when the user clicks the button — opens the confirm card. */
  onClick: () => void
}

/**
 * Top-bar action that surfaces the Compact-and-Continue trigger as the
 * context window fills up. Visibility / animation / tooltip are driven
 * entirely by ``useCompactionState``; this component only renders. See
 * ``devdocs/specs/2026-05-15-compact-and-continue-design.md`` §5.1.
 *
 * Styling matches the neighbouring ``ContextStatusPill``: a small
 * rounded-full pill with a 1px border and ``font-mono text-[11px]``
 * label. The sparkle emoji is the glyph; ``animate-pulse`` is applied
 * when the state crosses the 75 % threshold.
 */
export function SparkleCompactButton({
  totalMessages,
  totalTokens,
  fillPercentage,
  isLoading,
  onClick,
}: Props) {
  const state = useCompactionState({ totalMessages, totalTokens, fillPercentage })

  // States ``hidden_too_short`` / ``overflow_only`` are not rendered in
  // the top-bar — the overflow menu surfaces them separately (Phase 2).
  if (state.visibility === 'hidden_too_short' || state.visibility === 'overflow_only') {
    return null
  }

  const baseCls =
    'flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px] transition-colors'
  const borderCls =
    state.visibility === 'warning'
      ? 'border-orange-500/30 bg-orange-500/5 text-orange-300 hover:bg-orange-500/10'
      : state.visibility === 'sparkle'
        ? 'border-amber-400/25 bg-amber-400/5 text-amber-300 hover:bg-amber-400/10'
        : 'border-white/10 bg-white/3 text-white/55 hover:bg-white/6'
  const sparkleCls = state.showSparkle ? 'animate-pulse' : ''
  const disabledCls = isLoading || !state.canTrigger ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isLoading || !state.canTrigger}
      title={state.tooltip}
      className={`${baseCls} ${borderCls} ${sparkleCls} ${disabledCls}`}
      aria-label="Compact conversation"
    >
      {isLoading ? (
        <>
          <span aria-hidden>{'✨'}</span>
          <span>Compacting…</span>
        </>
      ) : (
        <span aria-hidden>{'✨'}</span>
      )}
    </button>
  )
}
