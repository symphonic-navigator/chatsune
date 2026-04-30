import { describe, it, expect, beforeEach } from 'vitest'
import { match } from '../matcher'
import { registerCommand, _resetRegistry } from '../registry'
import type { CommandSpec } from '../types'

function makeSpec(trigger: string): CommandSpec {
  return {
    trigger,
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: async () => ({ level: 'info', spokenText: '', displayText: '' }),
  }
}

describe('match', () => {
  beforeEach(() => {
    _resetRegistry()
    registerCommand(makeSpec('companion'))
    registerCommand(makeSpec('debug'))
  })

  it('returns null for an empty token list', () => {
    expect(match([])).toBeNull()
  })

  it('returns null when first token is not a registered trigger', () => {
    expect(match(['unknown', 'foo'])).toBeNull()
  })

  it('returns trigger and joined body when first token matches', () => {
    expect(match(['companion', 'off'])).toEqual({
      trigger: 'companion',
      body: 'off',
    })
  })

  it('returns empty body when only the trigger word is present', () => {
    expect(match(['companion'])).toEqual({ trigger: 'companion', body: '' })
  })

  it('does NOT match a longer token that starts with the trigger', () => {
    expect(match(['companionship', 'is', 'great'])).toBeNull()
  })

  it('joins all body tokens with a single space', () => {
    expect(match(['companion', 'is', 'a', 'good', 'word'])).toEqual({
      trigger: 'companion',
      body: 'is a good word',
    })
  })

  it('matches the debug trigger', () => {
    expect(match(['debug', 'ping'])).toEqual({ trigger: 'debug', body: 'ping' })
  })
})
