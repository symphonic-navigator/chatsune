import { describe, it, expect } from 'vitest'
import { normalise } from '../normaliser'

describe('normalise', () => {
  it('returns [] for empty string', () => {
    expect(normalise('')).toEqual([])
  })

  it('returns [] for whitespace-only string', () => {
    expect(normalise('   \t\n  ')).toEqual([])
  })

  it('lowercases and tokenises plain text', () => {
    expect(normalise('Companion off')).toEqual(['companion', 'off'])
  })

  it('strips trailing punctuation', () => {
    expect(normalise('Companion off.')).toEqual(['companion', 'off'])
  })

  it('strips inline punctuation', () => {
    expect(normalise('Companion, off.')).toEqual(['companion', 'off'])
  })

  it('collapses multiple internal spaces', () => {
    expect(normalise('  companion    off  ')).toEqual(['companion', 'off'])
  })

  it('strips a single leading filler', () => {
    expect(normalise('hey companion off')).toEqual(['companion', 'off'])
  })

  it('strips multiple leading fillers greedily', () => {
    expect(normalise('uh um hey companion off')).toEqual(['companion', 'off'])
  })

  it('preserves filler tokens that are not at the start', () => {
    expect(normalise('companion uh off')).toEqual(['companion', 'uh', 'off'])
  })

  it('returns [] when all tokens are fillers', () => {
    expect(normalise('uh um')).toEqual([])
  })

  it('strips German fillers (äh, ähm, also, naja)', () => {
    expect(normalise('äh companion off')).toEqual(['companion', 'off'])
    expect(normalise('ähm companion')).toEqual(['companion'])
    expect(normalise('also naja companion')).toEqual(['companion'])
  })

  it('strips Unicode punctuation (German quotes, ellipsis)', () => {
    expect(normalise('Companion „off…')).toEqual(['companion', 'off'])
  })

  it('handles a body that is just the trigger word', () => {
    expect(normalise('Debug')).toEqual(['debug'])
  })
})
