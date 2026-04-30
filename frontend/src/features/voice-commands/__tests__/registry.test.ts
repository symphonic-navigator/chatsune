import { describe, it, expect, beforeEach } from 'vitest'
import {
  registerCommand,
  unregisterCommand,
  lookupCommand,
  hasCommand,
  _resetRegistry,
} from '../registry'
import type { CommandSpec } from '../types'

function makeSpec(overrides: Partial<CommandSpec> = {}): CommandSpec {
  return {
    trigger: 'foo',
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: async () => ({
      level: 'info',
      spokenText: '',
      displayText: '',
    }),
    ...overrides,
  }
}

describe('registry', () => {
  beforeEach(() => {
    _resetRegistry()
  })

  it('registers and looks up a command', () => {
    const spec = makeSpec()
    registerCommand(spec)
    expect(lookupCommand('foo')).toBe(spec)
    expect(hasCommand('foo')).toBe(true)
  })

  it('throws on collision with both source labels in the message', () => {
    const a = makeSpec({ source: 'core' })
    const b = makeSpec({ source: 'integration:hue' })
    registerCommand(a)
    expect(() => registerCommand(b)).toThrow(/already registered/)
    expect(() => registerCommand(b)).toThrow(/core/)
    expect(() => registerCommand(b)).toThrow(/integration:hue/)
  })

  it('unregister removes the command', () => {
    registerCommand(makeSpec())
    unregisterCommand('foo')
    expect(lookupCommand('foo')).toBeUndefined()
    expect(hasCommand('foo')).toBe(false)
  })

  it('unregister on unknown trigger is a no-op', () => {
    expect(() => unregisterCommand('does-not-exist')).not.toThrow()
  })

  it('hasCommand returns false for unknown triggers', () => {
    expect(hasCommand('nope')).toBe(false)
  })
})
