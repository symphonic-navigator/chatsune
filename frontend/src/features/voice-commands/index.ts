/**
 * Public API of the voice-commands module.
 *
 * External callers (App bootstrap, useConversationMode, pluginLifecycle)
 * import from this file. Internal files (registry, dispatcher, matcher,
 * normaliser, responseChannel, handlers/*) are private — do not import
 * them directly from outside this module.
 */

import { registerCommand } from './registry'
import { debugCommand } from './handlers/debug'

export { tryDispatchCommand } from './dispatcher'
export { registerCommand, unregisterCommand } from './registry'
export type { CommandSpec, CommandResponse, DispatchResult } from './types'

/**
 * Register all core built-in voice commands. Call once at app bootstrap,
 * after auth gate. Idempotency is the caller's responsibility — calling
 * this twice will throw on collision (which is intentional: a double-init
 * is a real bug).
 */
export function registerCoreBuiltins(): void {
  registerCommand(debugCommand)
}
