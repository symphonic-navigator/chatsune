/* secretsEventHandler.ts — bridges integration.secrets.* WSS events to the
 * secrets store. Registered once at app startup via registerSecretsEventHandler().
 * Events are emitted flat (no payload wrapper) per the backend convention.
 */

import type { BaseEvent } from '../../core/types/events'
import { eventBus } from '../../core/websocket/eventBus'
import { useSecretsStore } from './secretsStore'

interface SecretsHydratedEvent extends BaseEvent {
  type: 'integration.secrets.hydrated'
  integration_id: string
  secrets: Record<string, string>
}

interface SecretsClearedEvent extends BaseEvent {
  type: 'integration.secrets.cleared'
  integration_id: string
}

function handleIntegrationSecretsHydrated(event: BaseEvent): void {
  // TEMP TRACING — remove after hydrate-event bug is found
  console.log('[secretsEventHandler] hydrated received:', event)
  const e = event as SecretsHydratedEvent
  console.log('[secretsEventHandler] hydrated → integration_id:', e.integration_id, 'secrets keys:', Object.keys(e.secrets ?? {}))
  useSecretsStore.getState().setSecrets(e.integration_id, e.secrets)
}

function handleIntegrationSecretsCleared(event: BaseEvent): void {
  // TEMP TRACING — remove after hydrate-event bug is found
  console.log('[secretsEventHandler] cleared received:', event)
  const e = event as SecretsClearedEvent
  useSecretsStore.getState().clearSecrets(e.integration_id)
}

export function registerSecretsEventHandler(): () => void {
  const unsubHydrated = eventBus.on('integration.secrets.hydrated', handleIntegrationSecretsHydrated)
  const unsubCleared = eventBus.on('integration.secrets.cleared', handleIntegrationSecretsCleared)
  return () => {
    unsubHydrated()
    unsubCleared()
  }
}
