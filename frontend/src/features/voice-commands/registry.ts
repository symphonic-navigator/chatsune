import type { CommandSpec } from './types'

const registry = new Map<string, CommandSpec>()

export function registerCommand(spec: CommandSpec): void {
  const existing = registry.get(spec.trigger)
  if (existing) {
    throw new Error(
      `Voice command trigger '${spec.trigger}' already registered ` +
        `(existing source: ${existing.source}, attempted source: ${spec.source}).`,
    )
  }
  registry.set(spec.trigger, spec)
}

export function unregisterCommand(trigger: string): void {
  registry.delete(trigger)
}

export function lookupCommand(trigger: string): CommandSpec | undefined {
  return registry.get(trigger)
}

export function hasCommand(trigger: string): boolean {
  return registry.has(trigger)
}

/** FOR TESTING ONLY — resets the singleton registry. Do not call in production code. */
export function _resetRegistry(): void {
  registry.clear()
}
