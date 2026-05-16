/* genericErrorHandler.ts — bridges the generic ``Topics.ERROR`` WS event
 * (shared/events/system.py :: ErrorEvent) to a user-visible toast via the
 * notification store. Registered once at app startup via
 * registerGenericErrorHandler().
 *
 * Rationale: stream- and feature-specific errors flow through their own
 * handlers (chat.stream.error, knowledge.document.embed_failed, etc.).
 * The catch-all ``error`` topic is for backend-emitted errors that have
 * no feature-specific subscriber — without this bridge they were
 * silently dropped on the client.
 */
import type { BaseEvent, ErrorEventPayload } from '../types/events'
import { Topics } from '../types/events'
import { eventBus } from './eventBus'
import { useNotificationStore } from '../store/notificationStore'

function handleGenericError(event: BaseEvent): void {
  const payload = event.payload as unknown as Partial<ErrorEventPayload>
  const userMessage = typeof payload?.user_message === 'string'
    ? payload.user_message
    : 'An unexpected error occurred.'
  const recoverable = Boolean(payload?.recoverable)
  useNotificationStore.getState().addNotification({
    level: 'error',
    title: recoverable ? 'Something went wrong' : 'Error',
    message: userMessage,
  })
}

export function registerGenericErrorHandler(): () => void {
  return eventBus.on(Topics.ERROR, handleGenericError)
}
