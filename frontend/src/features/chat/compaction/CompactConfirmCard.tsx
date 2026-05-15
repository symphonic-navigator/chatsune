interface Props {
  /** Current token usage for the active session. */
  contextUsed: number
  /** Maximum context window size for the active model. */
  contextMax: number
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Inline confirmation card shown after the user clicks the
 * SparkleCompactButton. Mirrors §5.2 of the design spec:
 *
 *   - "{used} / {max} tokens, {pct}%"
 *   - "After compact: ~{est} tokens" (heuristic: 5–10 % of source plus tail)
 *   - "The last 6 turns stay verbatim; everything before is condensed
 *     into a briefing."
 *   - Compact (primary) / Cancel buttons
 *
 * Styled to match the chat top-bar's tooltip vocabulary: dark surface,
 * thin border, mono labels. Width is fixed at 18rem so it slides
 * neatly under the trigger button without reflowing on mobile.
 */
export function CompactConfirmCard({ contextUsed, contextMax, onConfirm, onCancel }: Props) {
  const fillPct = contextMax > 0 ? Math.round((contextUsed / contextMax) * 100) : 0
  // Heuristic: roughly 8 % of source, floor at 500 tokens. Matches the
  // backend's ``estimated_tokens_after`` calc inside the started event so
  // the UI doesn't surface a wildly different number.
  const estimatedAfter = Math.max(500, Math.round(contextUsed * 0.08))

  return (
    <div
      role="dialog"
      aria-label="Compact this conversation"
      className="w-72 rounded-md border border-white/15 bg-[#0b0a08] lg:bg-[#0b0a08]/95 lg:backdrop-blur-sm shadow-sm lg:shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2.5 text-[12px] text-white/70 font-mono leading-relaxed"
    >
      <div className="text-white/85">
        {contextUsed.toLocaleString()} / {contextMax.toLocaleString()} tokens, {fillPct}%
      </div>
      <div className="text-white/55">
        After compact: ~{estimatedAfter.toLocaleString()} tokens
      </div>
      <p className="mt-2 text-white/60 font-sans text-[12px] leading-snug">
        The last 6 turns stay verbatim; everything before is condensed into a briefing.
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onConfirm}
          className="flex-1 rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-[12px] text-amber-200 hover:bg-amber-400/15 transition-colors"
        >
          Compact
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 rounded border border-white/15 bg-white/3 px-2 py-1 text-[12px] text-white/55 hover:bg-white/6 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
