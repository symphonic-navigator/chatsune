import { describe, it, expect } from 'vitest'
import {
  INLINE_TAGS,
  WRAPPING_TAGS,
  INLINE_TAG_PATTERN,
  WRAPPING_OPEN_PATTERN,
  WRAPPING_CLOSE_PATTERN,
  ANY_TAG_PATTERN,
  isKnownWrappingTag,
} from '../expressionTags'

describe('expressionTags constants', () => {
  it('INLINE_TAGS covers the xAI inline vocabulary', () => {
    expect(new Set(INLINE_TAGS)).toEqual(
      new Set([
        'pause', 'long-pause', 'hum-tune',
        'laugh', 'chuckle', 'giggle', 'cry',
        'tsk', 'tongue-click', 'lip-smack',
        'breath', 'inhale', 'exhale', 'sigh',
      ]),
    )
  })

  it('WRAPPING_TAGS covers the xAI wrapping vocabulary', () => {
    expect(new Set(WRAPPING_TAGS)).toEqual(
      new Set([
        'soft', 'whisper', 'loud', 'build-intensity', 'decrease-intensity',
        'higher-pitch', 'lower-pitch', 'slow', 'fast',
        'sing-song', 'singing', 'laugh-speak', 'emphasis',
      ]),
    )
  })
})

describe('INLINE_TAG_PATTERN', () => {
  it('matches a canonical inline tag', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('hello [laugh] world'.match(re)).toEqual(['[laugh]'])
  })

  it('does not match an unknown bracketed token', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('see [1] in the footnote'.match(re)).toBeNull()
  })
})

describe('WRAPPING_OPEN_PATTERN / WRAPPING_CLOSE_PATTERN', () => {
  it('match open and close markers of canonical wraps', () => {
    const open = new RegExp(WRAPPING_OPEN_PATTERN.source, 'g')
    const close = new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g')
    expect('<whisper>hi</whisper>'.match(open)).toEqual(['<whisper>'])
    expect('<whisper>hi</whisper>'.match(close)).toEqual(['</whisper>'])
  })

  it('does not match unknown markers', () => {
    const open = new RegExp(WRAPPING_OPEN_PATTERN.source, 'g')
    expect('<br> line break'.match(open)).toBeNull()
  })
})

describe('ANY_TAG_PATTERN', () => {
  it('matches all three tag shapes in one pass', () => {
    const re = new RegExp(ANY_TAG_PATTERN.source, 'g')
    const input = '<whisper>a [laugh] b</whisper>'
    const matches = [...input.matchAll(re)].map((m) => m[0])
    expect(matches).toEqual(['<whisper>', '[laugh]', '</whisper>'])
  })
})

describe('isKnownWrappingTag', () => {
  it('returns true for canonical names', () => {
    expect(isKnownWrappingTag('whisper')).toBe(true)
    expect(isKnownWrappingTag('emphasis')).toBe(true)
  })

  it('returns false for unknown names', () => {
    expect(isKnownWrappingTag('foo')).toBe(false)
    expect(isKnownWrappingTag('br')).toBe(false)
  })
})

describe('INLINE_TAG_PATTERN — qualifier-tolerant', () => {
  it('matches plain canonical tags', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('hi [laugh] there'.match(re)).toEqual(['[laugh]'])
  })

  it('matches a qualifier before the canonical tag', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('she let out a [soft laugh] and smiled'.match(re)).toEqual(['[soft laugh]'])
  })

  it('matches a qualifier after the canonical tag', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('he [exhale sharply] and stepped forward'.match(re)).toEqual(['[exhale sharply]'])
  })

  it('matches multi-word qualifier', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('[very soft laugh]'.match(re)).toEqual(['[very soft laugh]'])
  })

  it('matches hyphenated canonical tags', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('[long-pause] and then [hum-tune]'.match(re)).toEqual(['[long-pause]', '[hum-tune]'])
  })

  it('matches hyphenated canonical tags with a qualifier', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('[dramatic long-pause]'.match(re)).toEqual(['[dramatic long-pause]'])
  })

  it('does not match suffix-extended words (laughter, laughing)', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('the [laughter] of friends'.match(re)).toBeNull()
    expect('[laughing]'.match(re)).toBeNull()
  })

  it('does not match unknown bracketed tokens', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('see [1] and [note]'.match(re)).toBeNull()
  })

  it('matches multiple inline tags in prose', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('[soft laugh] then [breath] then [exhale sharply]'.match(re)).toEqual([
      '[soft laugh]', '[breath]', '[exhale sharply]',
    ])
  })
})
