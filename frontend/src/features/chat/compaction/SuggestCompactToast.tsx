interface Props {
  /** Context fill ratio in 0..1 (used to render the percentage label). */
  fillPct: number
  /** Fires when the user accepts the suggestion. */
  onCompact: () => void
  /** Fires when the user dismisses the toast — "Later". */
  onLater: () => void
}

/**
 * One-off suggest toast shown when the conversation crosses 60 % context
 * fill for the first time. Built as an inline overlay rather than going
 * through ``useNotificationStore`` because that store's notification
 * shape supports only a single action button; the Compact / Later pair
 * is intrinsic to the suggest-toast UX (§5.3 of the design spec).
 *
 * Styled to match the neighbouring sparkly button: dark surface, amber
 * accent on the primary action, thin border. Anchored to the bottom of
 * the chat viewport with a small horizontal centre offset; the parent
 * is responsible for hard-suppressing this in continuous-voice mode (see
 * ``useSuggestToast``).
 */
export function SuggestCompactToast({ fillPct, onCompact, onLater }: Props) {
  const pct = Math.round(fillPct * 100)
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-24 left-1/2 -translate-x-1/2 z-40 w-[min(22rem,calc(100vw-2rem))] rounded-md border border-amber-400/30 bg-[#0b0a08]/95 backdrop-blur-sm shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2.5"
    >
      <p className="text-[12px] text-white/85 font-mono leading-snug">
        <span aria-hidden>{'✨ '}</span>
        Conversation is at {pct}% context. Compact now?
      </p>
      <div className="mt-2 flex gap-2 justify-end">
        <button
          type="button"
          onClick={onLater}
          className="rounded border border-white/15 bg-white/3 px-2 py-1 text-[12px] text-white/55 hover:bg-white/6 transition-colors"
        >
          Later
        </button>
        <button
          type="button"
          onClick={onCompact}
          className="rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-[12px] text-amber-200 hover:bg-amber-400/15 transition-colors"
        >
          Compact
        </button>
      </div>
    </div>
  )
}
