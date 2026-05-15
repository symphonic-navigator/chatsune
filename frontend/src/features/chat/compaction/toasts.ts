import { useNotificationStore } from '../../../core/store/notificationStore'
import type { CompactionCheckpoint } from '../../../core/api/chat'

/**
 * Render-only payload shapes for ``chat.compaction.completed`` /
 * ``chat.compaction.failed`` events. Mirrors the relevant fields of the
 * matching ``ChatCompactionCompletedEvent`` / ``ChatCompactionFailedEvent``
 * Pydantic models in ``shared/events/chat.py``; we accept narrow shapes
 * rather than the full event so call sites can pass already-narrowed
 * payload subsets without a cast.
 */
export interface CompactionCompletedPayload {
  checkpoint: CompactionCheckpoint
  tokens_saved: number
  truncated_message_count?: number
}

export interface CompactionFailedPayload {
  user_message: string
  recoverable: boolean
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${Math.round(n / 1000)}k`
  return String(n)
}

/**
 * Success toast — auto-dismisses after ~4 s. When the compaction
 * truncated the oldest source messages (briefing prompt itself
 * overflowed the budget), the toast appends a single-sentence note
 * about how many were dropped. See §5.5 of the design spec.
 */
export function showCompactionSuccess(event: CompactionCompletedPayload): void {
  const truncated = event.truncated_message_count ?? 0
  let message = `Saved ${formatTokens(event.tokens_saved)} tokens.`
  if (truncated > 0) {
    message += ` Note: the ${truncated} oldest message${truncated === 1 ? '' : 's'} didn't fit into the briefing.`
  }
  useNotificationStore.getState().addNotification({
    level: 'success',
    title: '✨ Compacted',
    message,
    duration: 4000,
  })
}

/**
 * Failure toast — auto-dismisses after ~8 s. When the failure is
 * marked ``recoverable``, an inline Retry action is attached that fires
 * ``onRetry``; otherwise no action is provided. See §5.5 of the design
 * spec.
 */
export function showCompactionFailure(
  event: CompactionFailedPayload,
  onRetry: () => void,
): void {
  useNotificationStore.getState().addNotification({
    level: 'error',
    title: 'Compaction failed',
    message: event.user_message,
    duration: 8000,
    action: event.recoverable ? { label: 'Retry', onClick: onRetry } : undefined,
  })
}
