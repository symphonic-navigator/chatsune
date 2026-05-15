import { useMemo } from 'react'

/**
 * Visibility states for the sparkly compact button. Mirrors the table in
 * ``devdocs/specs/2026-05-15-compact-and-continue-design.md`` §5.1.
 *
 * - ``hidden_too_short`` — conversation is shorter than the minimum-size
 *   precondition (≤ 12 messages or ≤ 4000 tokens). Button is not rendered
 *   in the top-bar at all.
 * - ``overflow_only`` — context fill is below 30 %; minimum-size precondition
 *   is met but compaction would be premature. Button stays hidden from the
 *   top-bar and ``canTrigger`` is false.
 * - ``subtle`` — 30–75 %: visible in the top-bar, no animation. Below 60 %
 *   the suggest-toast does not fire; the button is the only entry-point.
 * - ``sparkle`` — 75–90 %: visible in the top-bar with a pulse animation.
 * - ``warning`` — > 90 %: visible with an orange tint; compaction may fail
 *   due to source-too-large, so the tooltip recommends switching models.
 */
export type CompactButtonVisibility =
  | 'hidden_too_short'
  | 'overflow_only'
  | 'subtle'
  | 'sparkle'
  | 'warning'

export interface CompactionState {
  visibility: CompactButtonVisibility
  tooltip: string
  showSparkle: boolean
  /** True when the 75 % threshold has been crossed; Phase 9 reads this to decide whether to surface the modal hint toast. */
  showModalHint: boolean
  /** True when the user is allowed to trigger compaction right now. */
  canTrigger: boolean
}

interface UseCompactionStateInput {
  /** Total number of messages in the active session's transcript. */
  totalMessages: number
  /** Total token usage for the active session (``contextUsedTokens``). */
  totalTokens: number
  /** Context fill ratio in the range 0..1 (``contextFillPercentage``). */
  fillPercentage: number
}

/**
 * Pure derivation of the sparkly compact button's visibility / tooltip /
 * trigger-availability from the active session's metrics. Implemented as
 * a hook (rather than a free function) so the result reference is stable
 * across renders that don't change the inputs — the button component
 * mounts in the chat top-bar and re-renders on every streaming delta.
 *
 * The hook takes primitives rather than a full ChatSessionDto: the
 * relevant context-window metrics live in ``useChatStore`` (not on the
 * persisted session DTO), and the message count is most cheaply derived
 * from the active transcript at the call site. This keeps the hook a
 * pure function of its inputs and trivially unit-testable.
 */
export function useCompactionState(input: UseCompactionStateInput): CompactionState {
  const { totalMessages, totalTokens, fillPercentage } = input
  return useMemo(() => {
    // Minimum-size precondition — §5.1: total_messages > 12 AND
    // total_tokens > 4000. Below this, the button is hidden from the
    // top-bar entirely. The settings overflow shows a greyed-out entry
    // with the same tooltip, but that path lives outside this hook.
    const minSize = totalMessages > 12 && totalTokens > 4000
    if (!minSize) {
      return {
        visibility: 'hidden_too_short',
        tooltip: 'Conversation too short to compact yet',
        showSparkle: false,
        showModalHint: false,
        canTrigger: false,
      }
    }

    if (fillPercentage < 0.30) {
      return {
        visibility: 'overflow_only',
        tooltip: 'Compact this conversation',
        showSparkle: false,
        showModalHint: false,
        canTrigger: false,
      }
    }
    if (fillPercentage < 0.75) {
      return {
        visibility: 'subtle',
        tooltip: 'Compact this conversation?',
        showSparkle: false,
        showModalHint: false,
        canTrigger: true,
      }
    }
    if (fillPercentage < 0.90) {
      return {
        visibility: 'sparkle',
        tooltip: 'Context is filling up — compact soon',
        showSparkle: true,
        showModalHint: true,
        canTrigger: true,
      }
    }
    return {
      visibility: 'warning',
      tooltip: 'Compaction may fail — consider switching to a larger model',
      showSparkle: true,
      showModalHint: true,
      canTrigger: true,
    }
  }, [totalMessages, totalTokens, fillPercentage])
}
