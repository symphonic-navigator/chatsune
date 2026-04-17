/* secretsEventHandler.ts — bridges integration.secrets.* WSS events to the
 * secrets store. Registered once at app startup via registerSecretsEventHandler().
 * The WSS transport wraps every event in an envelope with a `payload` field;
 * the flat fields declared on the backend Pydantic class land inside that payload.
 */

import type { BaseEvent } from '../../core/types/events'
import { eventBus } from '../../core/websocket/eventBus'
import { useSecretsStore } from './secretsStore'

interface SecretsHydratedPayload {
  integration_id: string
  secrets: Record<string, string>
}

interface SecretsClearedPayload {
  integration_id: string
}

function handleIntegrationSecretsHydrated(event: BaseEvent): void {
  const payload = event.payload as unknown as SecretsHydratedPayload
  if (!payload?.integration_id || !payload.secrets) return
  useSecretsStore.getState().setSecrets(payload.integration_id, payload.secrets)
}

function handleIntegrationSecretsCleared(event: BaseEvent): void {
  const payload = event.payload as unknown as SecretsClearedPayload
  if (!payload?.integration_id) return
  useSecretsStore.getState().clearSecrets(payload.integration_id)
}

export function registerSecretsEventHandler(): () => void {
  const unsubHydrated = eventBus.on('integration.secrets.hydrated', handleIntegrationSecretsHydrated)
  const unsubCleared = eventBus.on('integration.secrets.cleared', handleIntegrationSecretsCleared)
  return () => {
    unsubHydrated()
    unsubCleared()
  }
}
