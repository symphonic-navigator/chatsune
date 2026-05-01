import { describe, it, expect } from 'vitest'
import { ACCEPT_TEXTS, VOSK_GRAMMAR } from '../../vosk/grammar'

describe('VOSK_GRAMMAR / ACCEPT_TEXTS', () => {
  it('accept set contains exactly the five voice phrases', () => {
    expect([...ACCEPT_TEXTS].sort()).toEqual([
      'voice continue',
      'voice on',
      'voice resume',
      'voice state',
      'voice status',
    ])
  })

  it('grammar contains the [unk] garbage path', () => {
    expect(VOSK_GRAMMAR).toContain('[unk]')
  })

  it('grammar contains every accept phrase', () => {
    for (const phrase of ACCEPT_TEXTS) {
      expect(VOSK_GRAMMAR).toContain(phrase)
    }
  })

  it('every standalone distractor also appears with each subcommand', () => {
    const subs = ['on', 'continue', 'resume', 'status', 'state'] as const
    const distractors = ['noise', 'choice', 'boys', 'poise', 'vice', 'rice'] as const
    for (const d of distractors) {
      expect(VOSK_GRAMMAR).toContain(d)
      for (const s of subs) {
        expect(VOSK_GRAMMAR).toContain(`${d} ${s}`)
      }
    }
  })

  it('voice itself appears as a standalone distractor (drop, do not collapse)', () => {
    expect(VOSK_GRAMMAR).toContain('voice')
  })
})
