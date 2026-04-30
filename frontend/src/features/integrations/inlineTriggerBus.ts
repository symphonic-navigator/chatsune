import { eventBus } from '../../core/websocket/eventBus'
import { Topics } from '../../core/types/events'
import type { IntegrationInlineTrigger } from './types'

/**
 * Wrap an `IntegrationInlineTrigger` in the standard `BaseEvent` envelope
 * and emit it on the shared frontend event bus. Used by ResponseTagBuffer's
 * immediate-emit path (live LLM stream + read-aloud) and by playbackChild's
 * sentence-synced path so all three call sites end up with structurally
 * identical bus events.
 *
 * `correlationId` defaults to the trigger's own field when set, then falls
 * back to a `frontend-trigger-…` placeholder so the envelope is never
 * empty. Sequence is `'0'` because client-emitted events do not participate
 * in the backend event-store ordering.
 */
export function emitInlineTrigger(
  trigger: IntegrationInlineTrigger,
  fallbackCorrelationId?: string,
): void {
  eventBus.emit({
    id: `inline-trig-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: Topics.INTEGRATION_INLINE_TRIGGER,
    sequence: '0',
    scope: 'frontend',
    correlation_id:
      trigger.correlation_id || fallbackCorrelationId || `frontend-trigger-${Date.now()}`,
    timestamp: trigger.timestamp,
    payload: { ...trigger },
  })
}
