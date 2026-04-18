import { describe, expect, it } from 'vitest'
import { decideSttOutcome } from '../bargeDecision'

describe('decideSttOutcome', () => {
  it('returns "resume" when the transcript is empty and bargeId is still current', () => {
    expect(decideSttOutcome({ transcript: '', sttBargeId: 3, currentBargeId: 3 }))
      .toBe('resume')
  })

  it('returns "resume" when the transcript is only whitespace', () => {
    expect(decideSttOutcome({ transcript: '   \n ', sttBargeId: 1, currentBargeId: 1 }))
      .toBe('resume')
  })

  it('returns "confirm" when the transcript is non-empty and bargeId matches', () => {
    expect(decideSttOutcome({ transcript: 'hello', sttBargeId: 2, currentBargeId: 2 }))
      .toBe('confirm')
  })

  it('returns "stale" when a newer barge has started, regardless of transcript', () => {
    expect(decideSttOutcome({ transcript: 'hello', sttBargeId: 1, currentBargeId: 2 }))
      .toBe('stale')
    expect(decideSttOutcome({ transcript: '', sttBargeId: 1, currentBargeId: 2 }))
      .toBe('stale')
  })

  it('returns "stale" when sttBargeId is ahead of currentBargeId', () => {
    expect(decideSttOutcome({ transcript: 'hi', sttBargeId: 5, currentBargeId: 3 }))
      .toBe('stale')
  })

  it('returns "confirm" when transcript has surrounding whitespace but is not empty', () => {
    expect(decideSttOutcome({ transcript: '  hello  ', sttBargeId: 1, currentBargeId: 1 }))
      .toBe('confirm')
  })
})
