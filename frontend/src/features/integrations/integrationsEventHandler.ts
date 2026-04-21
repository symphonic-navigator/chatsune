/* integrationsEventHandler.ts — bridges provider-account and integration-config
 * WSS events to a full reload of the integrations store. Registered once at
 * app startup via registerIntegrationsEventHandler().
 *
 * Rationale: `effective_enabled` on voice integrations (xai_voice, mistral_voice
 * etc.) is derived server-side from premium provider account state. When that
 * state changes, the frontend must re-fetch integration configs so the TTS/STT
 * dropdowns reflect the new eligibility without a hard reload.
 *
 * We deliberately re-list rather than patch from payloads so the canonical
 * server view wins (handles concurrent edits and ordering anomalies). The
 * store's `load()` has an internal `loading` guard, so overlapping triggers
 * (e.g. upserted + tested in quick succession) coalesce naturally.
 */

import { Topics } from '../../core/types/events'
import { eventBus } from '../../core/websocket/eventBus'
import { useIntegrationsStore } from './store'

function reloadIntegrations(): void {
  void useIntegrationsStore.getState().load()
}

export function registerIntegrationsEventHandler(): () => void {
  const topics = [
    Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED,
    Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED,
    Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED,
    Topics.INTEGRATION_CONFIG_UPDATED,
  ] as const
  const unsubs = topics.map((t) => eventBus.on(t, reloadIntegrations))
  return () => {
    for (const unsub of unsubs) unsub()
  }
}
