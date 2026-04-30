import { describe, it, expect } from 'vitest'
import { executeTag } from '../tags'

describe('screen_effect executeTag', () => {
  it('dispatches rising_emojis to the effect builder', () => {
    const result = executeTag('rising_emojis', ['💖', '🤘'], {})
    expect(result.pillContent).toBe('✨ rising_emojis 💖🤘')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      effect: 'rising_emojis',
      emojis: ['💖', '🤘'],
    })
  })

  it('lower-cases the command before dispatching', () => {
    const result = executeTag('Rising_Emojis', ['💖'], {})
    expect(result.pillContent).toBe('✨ rising_emojis 💖')
  })

  it('returns an "unknown" pill for an unrecognised command', () => {
    const result = executeTag('cartwheel', [], {})
    expect(result.pillContent).toBe('screen_effect: unknown "cartwheel"')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      error: 'unknown_effect',
      command: 'cartwheel',
    })
    expect(result.sideEffect).toBeUndefined()
  })

  it('does not throw on empty args for a known command', () => {
    const result = executeTag('rising_emojis', [], {})
    expect(result.pillContent).toBe('✨ rising_emojis (no emojis)')
  })
})
