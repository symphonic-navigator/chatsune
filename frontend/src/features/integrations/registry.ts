import type { IntegrationPlugin } from './types'

const plugins = new Map<string, IntegrationPlugin>()

export function registerPlugin(plugin: IntegrationPlugin): void {
  if (plugins.has(plugin.id)) {
    console.warn(`Integration plugin '${plugin.id}' already registered`)
    return
  }
  plugins.set(plugin.id, plugin)
}

export function getPlugin(id: string): IntegrationPlugin | undefined {
  return plugins.get(id)
}

export function getAllPlugins(): Map<string, IntegrationPlugin> {
  return plugins
}

/** FOR TESTING ONLY — clears all registered plugins. Do not call in production. */
export function _resetPluginRegistry(): void {
  plugins.clear()
}
