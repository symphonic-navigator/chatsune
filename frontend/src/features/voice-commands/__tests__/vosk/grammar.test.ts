import { describe, expect, it } from 'vitest'
import { VOSK_GRAMMAR, ACCEPT_TEXTS } from '../../vosk/grammar'

describe('VOSK_GRAMMAR', () => {
  it('contains the accept set', () => {
    expect(VOSK_GRAMMAR).toContain('companion on')
    expect(VOSK_GRAMMAR).toContain('companion status')
  })

  it('does NOT contain "companion off" (deliberately excluded — see spec Decision #10)', () => {
    expect(VOSK_GRAMMAR).not.toContain('companion off')
  })

  it('contains the [unk] garbage model token', () => {
    expect(VOSK_GRAMMAR).toContain('[unk]')
  })

  it('has every standalone phonetic distractor also as <word> on and <word> status', () => {
    const standaloneDistractors = ['campaign', 'champion', 'company', 'compass', 'common', 'complete', 'complain']
    for (const word of standaloneDistractors) {
      expect(VOSK_GRAMMAR, `standalone ${word}`).toContain(word)
      expect(VOSK_GRAMMAR, `${word} on`).toContain(`${word} on`)
      expect(VOSK_GRAMMAR, `${word} status`).toContain(`${word} status`)
    }
  })

  it('exposes ACCEPT_TEXTS containing only the wake/status phrases', () => {
    expect(ACCEPT_TEXTS.has('companion on')).toBe(true)
    expect(ACCEPT_TEXTS.has('companion status')).toBe(true)
    expect(ACCEPT_TEXTS.size).toBe(2)
  })
})
