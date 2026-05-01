/**
 * Public API of the voice-commands module.
 *
 * External callers (App bootstrap, useConversationMode, pluginLifecycle)
 * import from this file. Internal files (registry, dispatcher, matcher,
 * normaliser, responseChannel, handlers/*) are private — do not import
 * them directly from outside this module.
 */

import { registerCommand, unregisterCommand } from './registry'
import { debugCommand } from './handlers/debug'
import { companionCommand } from './handlers/companion'

export { tryDispatchCommand } from './dispatcher'
export { registerCommand, unregisterCommand } from './registry'
export type { CommandSpec, CommandResponse, DispatchResult, CueKind } from './types'
export { useVoiceLifecycleStore } from './voiceLifecycleStore'
export type { VoiceLifecycle } from './voiceLifecycleStore'
export { vosk } from './vosk/recogniser'

/**
 * Register all core built-in voice commands. Call once at app bootstrap,
 * after auth gate. Idempotency is the caller's responsibility — calling
 * this twice will throw on collision (which is intentional: a double-init
 * is a real bug).
 */
export function registerCoreBuiltins(): void {
  registerCommand(debugCommand)
  registerCommand(companionCommand)
}

/**
 * Unregister all core built-ins. Call from the cleanup of the same effect
 * that registers them — this keeps the bootstrap symmetric and prevents
 * StrictMode's dev-only double-invoke from throwing on re-register.
 */
export function unregisterCoreBuiltins(): void {
  unregisterCommand(debugCommand.trigger)
  unregisterCommand(companionCommand.trigger)
}
