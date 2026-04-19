import { describe, expect, it } from 'vitest'
import { splitSentences } from '../sentenceSplitter'

describe('splitSentences', () => {
  it('returns a single sentence unchanged', () => {
    expect(splitSentences('Hello there.')).toEqual(['Hello there.'])
  })

  it('returns empty array for empty input', () => {
    expect(splitSentences('')).toEqual([])
  })

  it('splits on sentence end followed by whitespace and an uppercase letter', () => {
    expect(splitSentences('Hi! How are you?')).toEqual(['Hi!', 'How are you?'])
  })

  it('splits on German umlaut-starting sentences', () => {
    expect(splitSentences('Hallo. Über den Berg.')).toEqual(['Hallo.', 'Über den Berg.'])
  })

  it('does not split inside decimal numbers', () => {
    expect(splitSentences('It is 3.14 metres long.')).toEqual(['It is 3.14 metres long.'])
  })

  it('treats line breaks as hard boundaries', () => {
    expect(splitSentences('First line\nSecond line\nThird line')).toEqual([
      'First line',
      'Second line',
      'Third line',
    ])
  })

  it('combines line splits and sentence splits', () => {
    expect(splitSentences('One. Two.\nThree. Four.')).toEqual(['One.', 'Two.', 'Three.', 'Four.'])
  })

  it('keeps a three-dot ellipsis intact and does not split inside it', () => {
    expect(splitSentences('Ich dachte... vielleicht sollte ich...')).toEqual([
      'Ich dachte... vielleicht sollte ich...',
    ])
  })

  it('normalises Unicode ellipsis to three dots and keeps it intact', () => {
    expect(splitSentences('Ich dachte\u2026 vielleicht\u2026')).toEqual([
      'Ich dachte... vielleicht...',
    ])
  })

  it('does not split after an ellipsis even when an uppercase word follows', () => {
    expect(splitSentences('Ich weiss nicht... Aber egal.')).toEqual([
      'Ich weiss nicht... Aber egal.',
    ])
  })

  it('ends-of-line act as soft terminators without requiring punctuation', () => {
    expect(splitSentences('No punctuation here\nAlso none here')).toEqual([
      'No punctuation here',
      'Also none here',
    ])
  })

  it('trims whitespace around produced sentences', () => {
    expect(splitSentences('  Hello.   World.  ')).toEqual(['Hello.', 'World.'])
  })

  it('filters empty fragments from repeated whitespace and blank lines', () => {
    expect(splitSentences('\n\nOne.\n\n\nTwo.\n')).toEqual(['One.', 'Two.'])
  })

  it('splits before an emoji following punctuation with whitespace', () => {
    expect(splitSentences('That is great! 😀 Let us go.')).toEqual([
      'That is great!',
      '😀 Let us go.',
    ])
  })

  it('splits directly before an emoji that follows punctuation with no whitespace', () => {
    expect(splitSentences('That is great!😀 Let us go.')).toEqual([
      'That is great!',
      '😀 Let us go.',
    ])
  })
})
