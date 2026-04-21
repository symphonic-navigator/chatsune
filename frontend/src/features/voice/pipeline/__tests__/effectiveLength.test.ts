import { describe, expect, it } from 'vitest'
import { effectiveLength } from '../effectiveLength'

describe('effectiveLength', () => {
  it('returns the trimmed length for plain text', () => {
    expect(effectiveLength('Hello world.')).toBe('Hello world.'.length)
  })

  it('trims surrounding whitespace before measuring', () => {
    expect(effectiveLength('  Hi.  ')).toBe('Hi.'.length)
  })

  it('returns 0 for empty or whitespace-only strings', () => {
    expect(effectiveLength('')).toBe(0)
    expect(effectiveLength('   ')).toBe(0)
    expect(effectiveLength('\n\t')).toBe(0)
  })

  it('ignores wrapping open tags', () => {
    const raw = '<whisper>Secret.</whisper>'
    // effective text is "Secret." → 7 characters
    expect(effectiveLength(raw)).toBe('Secret.'.length)
  })

  it('ignores multiple wrap tags', () => {
    const raw = '<soft><emphasis>Wichtig.</emphasis></soft>'
    expect(effectiveLength(raw)).toBe('Wichtig.'.length)
  })

  it('ignores inline tags', () => {
    const raw = '[chuckle] [nod]'
    // Only [chuckle] is a known canonical inline tag; [nod] is unknown
    // and therefore counts as speakable text. After stripping known tags
    // and trimming, the remainder is "[nod]" → 5 characters.
    expect(effectiveLength(raw)).toBe('[nod]'.length)
  })

  it('ignores a known inline tag but keeps surrounding words', () => {
    const raw = 'Hello [chuckle] there.'
    // After stripping "[chuckle]" and collapsing adjacent spaces, the
    // effective text is "Hello  there." (double space is fine — we only
    // count characters after trim, interior whitespace stays).
    const stripped = 'Hello  there.'
    expect(effectiveLength(raw)).toBe(stripped.length)
  })

  it('handles mixed wrap and inline tags', () => {
    const raw = '<soft>[inhale] Okay.</soft>'
    // After stripping tags: " Okay." then trim → "Okay." (5 chars)
    expect(effectiveLength(raw)).toBe('Okay.'.length)
  })
})
