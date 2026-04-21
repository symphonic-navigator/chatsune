import { describe, expect, it } from 'vitest'
import { splitSentences, splitSentencesWithWrapScope } from '../sentenceSplitter'

describe('splitSentences', () => {
  it('returns a single sentence unchanged', () => {
    expect(splitSentences('Hello there my dear friend.')).toEqual([
      'Hello there my dear friend.',
    ])
  })

  it('returns empty array for empty input', () => {
    expect(splitSentences('')).toEqual([])
  })

  it('splits on sentence end followed by whitespace and an uppercase letter', () => {
    expect(splitSentences('Hi there my dear friend! How are you doing today my friend?')).toEqual([
      'Hi there my dear friend!',
      'How are you doing today my friend?',
    ])
  })

  it('splits on German umlaut-starting sentences', () => {
    expect(splitSentences('Hallo und guten Morgen zusammen. Über den Berg und weit hinaus.')).toEqual([
      'Hallo und guten Morgen zusammen.',
      'Über den Berg und weit hinaus.',
    ])
  })

  it('does not split inside decimal numbers', () => {
    expect(splitSentences('It is 3.14 metres long.')).toEqual(['It is 3.14 metres long.'])
  })

  it('treats line breaks as hard boundaries', () => {
    expect(
      splitSentences(
        'First line is nice and long\nSecond line is also long enough\nThird line is also sufficiently long',
      ),
    ).toEqual([
      'First line is nice and long',
      'Second line is also long enough',
      'Third line is also sufficiently long',
    ])
  })

  it('combines line splits and sentence splits', () => {
    // Each sentence is sized past its respective threshold (20 for first,
    // 30 for followers) so all four stay separate.
    const input =
      'One long opening sentence here today. Two is also a bit longer now indeed.\nThree stays on its own perfectly too. Four wraps up our entire tale here.'
    expect(splitSentences(input)).toEqual([
      'One long opening sentence here today.',
      'Two is also a bit longer now indeed.',
      'Three stays on its own perfectly too.',
      'Four wraps up our entire tale here.',
    ])
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
    expect(
      splitSentences('No punctuation here at all\nAlso no punctuation on the second line'),
    ).toEqual([
      'No punctuation here at all',
      'Also no punctuation on the second line',
    ])
  })

  it('trims whitespace around produced sentences', () => {
    expect(
      splitSentences('  Hello there my dear everyone.   World is very large today indeed.  '),
    ).toEqual([
      'Hello there my dear everyone.',
      'World is very large today indeed.',
    ])
  })

  it('filters empty fragments from repeated whitespace and blank lines', () => {
    expect(
      splitSentences('\n\nOne long opening sentence here.\n\n\nTwo and it is also longer now.\n'),
    ).toEqual(['One long opening sentence here.', 'Two and it is also longer now.'])
  })

  it('splits before an emoji following punctuation with whitespace', () => {
    expect(splitSentences('That is absolutely great today! 😀 Let us all go for a walk now.')).toEqual([
      'That is absolutely great today!',
      '😀 Let us all go for a walk now.',
    ])
  })

  it('splits directly before an emoji that follows punctuation with no whitespace', () => {
    expect(splitSentences('That is absolutely great today!😀 Let us all go for a walk now.')).toEqual([
      'That is absolutely great today!',
      '😀 Let us all go for a walk now.',
    ])
  })
})

describe('splitSentences — length guard (Guard 1)', () => {
  it('merges a too-short first sentence (< 20) with the next one', () => {
    // "First one." is 10 chars effective — below the 20-char first-sentence
    // threshold. It must be merged with the following sentence so nothing
    // emits a tiny stand-alone chunk.
    expect(splitSentences('First one. Second sentence here is long enough.')).toEqual([
      'First one. Second sentence here is long enough.',
    ])
  })

  it('keeps a long-enough first sentence (>= 20) stand-alone', () => {
    expect(splitSentences('Hi there my dear friend! How are you doing today my friend?')).toEqual([
      'Hi there my dear friend!',
      'How are you doing today my friend?',
    ])
  })

  it('merges a too-short follow-up sentence (< 30) with the next one', () => {
    // First sentence is long enough (>= 20). Second is short (10 chars) and
    // must be merged with the third.
    const input =
      'This first sentence is plenty long. Short one. Then a much longer closing sentence arrives here.'
    expect(splitSentences(input)).toEqual([
      'This first sentence is plenty long.',
      'Short one. Then a much longer closing sentence arrives here.',
    ])
  })

  it('merges a too-short last sentence with the previous one', () => {
    // The last sentence "Ja." is way below 30 — must merge backwards into
    // the previous long sentence.
    const input = 'This is a nice and long opening sentence here. Ja.'
    expect(splitSentences(input)).toEqual([
      'This is a nice and long opening sentence here. Ja.',
    ])
  })

  it('measures effective length, not raw length, when deciding to merge', () => {
    // "[chuckle] [nod]" is raw 15 chars but effectively "[nod]" (5 chars,
    // since only [chuckle] is a canonical inline tag). Below the 20-char
    // first-sentence threshold → must merge with the next sentence.
    // Use a line-break boundary to mirror the real-world LLM output.
    const input = '[chuckle] [nod]\nVerstanden — alles klar so weit bei mir.'
    expect(splitSentences(input)).toEqual([
      '[chuckle] [nod] Verstanden — alles klar so weit bei mir.',
    ])
  })
})

describe('splitSentencesWithWrapScope', () => {
  it('leaves unwrapped text alone', () => {
    expect(
      splitSentencesWithWrapScope(
        'Hi there my friend, how are you? How has your entire day been going today?',
      ),
    ).toEqual([
      'Hi there my friend, how are you?',
      'How has your entire day been going today?',
    ])
  })

  it('re-wraps a wrap that spans two sentences', () => {
    // Both sentences must be long enough past the wrap-tag effective-length
    // check so they stay separate.
    expect(
      splitSentencesWithWrapScope(
        '<whisper>First sentence here is long enough. Second sentence is also plenty long.</whisper>',
      ),
    ).toEqual([
      '<whisper>First sentence here is long enough.</whisper>',
      '<whisper>Second sentence is also plenty long.</whisper>',
    ])
  })

  it('handles wraps that close before sentence boundary', () => {
    expect(
      splitSentencesWithWrapScope(
        'This is <emphasis>important stuff</emphasis> right here. Next sentence is also long enough.',
      ),
    ).toEqual([
      'This is <emphasis>important stuff</emphasis> right here.',
      'Next sentence is also long enough.',
    ])
  })

  it('closes an unterminated wrap on the final sentence', () => {
    expect(splitSentencesWithWrapScope('<whisper>Only one sentence but it is long enough.')).toEqual([
      '<whisper>Only one sentence but it is long enough.</whisper>',
    ])
  })
})
