/**
 * pluginLifecycle.ts — Orchestrates plugin activate/deactivate callbacks.
 *
 * A plugin becomes active when:
 *   1. Its config is enabled (configs[id].enabled === true)
 *   2. AND either the integration has no secret fields, OR secrets are hydrated
 *      (secretsStore.hasSecrets(id) === true)
 *
 * Note: the `secret` attribute on config fields is not currently included in
 * IntegrationConfigFieldDto — it will always evaluate as false until the DTO
 * is extended. For Lovense (no secret fields) this is correct. When Mistral
 * (which has an API key) is added, the DTO will need a `secret: bool` field.
 */
import { useIntegrationsStore } from './store'
import { useSecretsStore } from './secretsStore'
import { getPlugin } from './registry'

type PluginState = 'inactive' | 'active'
const pluginStates = new Map<string, PluginState>()

/** FOR TESTING ONLY — resets tracked plugin states. Do not call in production. */
export function _resetPluginStates(): void {
  pluginStates.clear()
}

function shouldBeActive(integrationId: string): boolean {
  const { definitions, configs } = useIntegrationsStore.getState()

  const cfg = configs[integrationId]
  if (!cfg?.enabled) return false

  // definitions is an array — find by id
  const defn = definitions.find((d) => d.id === integrationId)
  // Cast to any: the `secret` field exists in the backend registry but is not
  // currently propagated via IntegrationConfigFieldDto. Gracefully returns false
  // (i.e. no secrets required) until the DTO is extended.
  const hasSecretFields = (defn?.config_fields ?? []).some((f: any) => f.secret === true)

  if (hasSecretFields && !useSecretsStore.getState().hasSecrets(integrationId)) {
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
