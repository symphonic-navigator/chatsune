import { describe, it, expect } from 'vitest'
import { risingEmojis, parseEmojis } from '../effects/risingEmojis'

describe('parseEmojis', () => {
  it('returns space-separated emojis as-is', () => {
    expect(parseEmojis(['💖', '🤘', '🔥'])).toEqual(['💖', '🤘', '🔥'])
  })

  it('splits a concatenated emoji string into graphemes', () => {
    expect(parseEmojis(['💖🤘🔥'])).toEqual(['💖', '🤘', '🔥'])
  })

  it('dedupes across all args', () => {
    expect(parseEmojis(['💖', '💖🤘'])).toEqual(['💖', '🤘'])
  })

  it('keeps ZWJ sequences intact', () => {
    expect(parseEmojis(['👨‍👩‍👧'])).toEqual(['👨‍👩‍👧'])
  })

  it('keeps skin-tone modifiers intact', () => {
    expect(parseEmojis(['👋🏽'])).toEqual(['👋🏽'])
  })

  it('returns an empty array for no args', () => {
    expect(parseEmojis([])).toEqual([])
  })

  it('caps the result at 5 distinct emojis', () => {
    expect(parseEmojis(['💖🤘🔥💪🎉🌈'])).toHaveLength(5)
  })

  it('ignores whitespace graphemes', () => {
    expect(parseEmojis(['  💖  '])).toEqual(['💖'])
  })
})

describe('risingEmojis', () => {
  it('returns a pill with icon + command + emojis for valid args', () => {
    const result = risingEmojis(['💖', '🤘', '🔥'])
    expect(result.pillContent).toBe('✨ rising_emojis 💖🤘🔥')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      effect: 'rising_emojis',
      emojis: ['💖', '🤘', '🔥'],
    })
    expect(result.sideEffect).toBeUndefined()
  })

  it('falls back to a sparkle when no emojis are given', () => {
    const result = risingEmojis([])
    expect(result.pillContent).toBe('✨ rising_emojis (no emojis)')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      effect: 'rising_emojis',
      emojis: ['✨'],
    })
  })

  it('caps payload emojis at MAX_EMOJIS', () => {
    const result = risingEmojis(['💖🤘🔥💪🎉🌈'])
    const payload = result.effectPayload as { emojis: string[] }
    expect(payload.emojis).toHaveLength(5)
  })
})
