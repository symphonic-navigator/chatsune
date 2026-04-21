/**
 * pluginLifecycle.ts — Orchestrates plugin activate/deactivate callbacks.
 *
 * A plugin becomes active when:
 *   1. Its config is effectively enabled (configs[id].effective_enabled === true).
 *      This is the authoritative "is this integration usable" flag — for
 *      integrations linked to a Premium Provider Account (xai_voice,
 *      mistral_voice) the raw `enabled` field is meaningless; see
 *      backend/modules/integrations/_handlers.py:list_user_configs.
 *   2. AND either the integration has no secret fields, OR secrets are hydrated
 *      (secretsStore.hasSecrets(id) === true)
 */
import { useIntegrationsStore } from './store'
import { useSecretsStore } from './secretsStore'
import { getPlugin } from './registry'
import type { IntegrationConfigField } from './types'

type PluginState = 'inactive' | 'active'
const pluginStates = new Map<string, PluginState>()

/** FOR TESTING ONLY — resets tracked plugin states. Do not call in production. */
export function _resetPluginStates(): void {
  pluginStates.clear()
}

function shouldBeActive(integrationId: string): boolean {
  const { definitions, configs } = useIntegrationsStore.getState()

  const cfg = configs[integrationId]
  if (!cfg?.effective_enabled) return false

  // definitions is an array — find by id
  const defn = definitions.find((d) => d.id === integrationId)
  const hasSecretFields = (defn?.config_fields ?? []).some((f: IntegrationConfigField) => Boolean(f.secret))

  // Backend-proxied integrations (hydrate_secrets === false) keep their
  // API key on the server; no hydration event will ever arrive in the
  // browser, so we must not gate activation on secret presence.
  const requiresHydration = hasSecretFields && defn?.hydrate_secrets !== false
  if (requiresHydration && !useSecretsStore.getState().hasSecrets(integrationId)) {
    return false
  }
  return true
}

function reconcileOne(integrationId: string): void {
  const plugin = getPlugin(integrationId)
  if (!plugin) return

  const desired: PluginState = shouldBeActive(integrationId) ? 'active' : 'inactive'
  const current = pluginStates.get(integrationId) ?? 'inactive'
  if (desired === current) return

  if (desired === 'active') {
    plugin.onActivate?.()
  } else {
    plugin.onDeactivate?.()
  }
  pluginStates.set(integrationId, desired)
}

function reconcileAll(): void {
  const { definitions } = useIntegrationsStore.getState()
  for (const defn of definitions) {
    reconcileOne(defn.id)
  }
}

/**
 * Initialise the plugin lifecycle orchestrator. Call once at app start.
 * Returns a cleanup function that unsubscribes both store listeners.
 */
export function initPluginLifecycle(): () => void {
  const unsubIntegrations = useIntegrationsStore.subscribe(reconcileAll)
  const unsubSecrets = useSecretsStore.subscribe(reconcileAll)
  reconcileAll()
  return () => {
    unsubIntegrations()
    unsubSecrets()
  }
}
