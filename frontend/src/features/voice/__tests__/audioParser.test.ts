import { describe, expect, it } from 'vitest'
import { parseForSpeech } from '../pipeline/audioParser'

describe('parseForSpeech', () => {
  describe("mode 'off'", () => {
    it('splits a single-sentence input into one voice segment', () => {
      expect(parseForSpeech('Hello, how are you?', 'off')).toEqual([
        { type: 'voice', text: 'Hello, how are you?' },
      ])
    })
    it('splits multi-sentence input into one voice segment per sentence', () => {
      // Each sentence must clear its threshold (20 for first, 30 for
      // followers) to stay separate under the length guard.
      expect(
        parseForSpeech(
          'Hi there my dearest friend! How are you doing today so far? I am doing absolutely fine thank you.',
          'off',
        ),
      ).toEqual([
        { type: 'voice', text: 'Hi there my dearest friend!' },
        { type: 'voice', text: 'How are you doing today so far?' },
        { type: 'voice', text: 'I am doing absolutely fine thank you.' },
      ])
    })
    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', 'off')).toEqual([])
    })
  })

  describe("mode 'play' (dialogue spoken, narration narrated)", () => {
    it('splits dialogue and narration, then splits each by sentence', () => {
      const result = parseForSpeech(
        '*walks over slowly* "Hello there my dear friend! How are you doing today so far?" *waves back*',
        'play',
      )
      expect(result).toEqual([
        { type: 'narration', text: 'walks over slowly' },
        { type: 'voice', text: 'Hello there my dear friend!' },
        { type: 'voice', text: 'How are you doing today so far?' },
        { type: 'narration', text: 'waves back' },
      ])
    })
    it('treats unmarked text as narration and sentence-splits it', () => {
      expect(
        parseForSpeech(
          'She looked away quietly just then. He did too without saying anything.',
          'play',
        ),
      ).toEqual([
        { type: 'narration', text: 'She looked away quietly just then.' },
        { type: 'narration', text: 'He did too without saying anything.' },
      ])
    })
    it('handles consecutive dialogue segments', () => {
      expect(parseForSpeech('"Hi!" "How are you?"', 'play')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
      ])
    })
  })

  describe("mode 'narrate' (narration narrated, only dialogue spoken)", () => {
    it('strips decorative asterisks in narration and sentence-splits inside quotes', () => {
      const result = parseForSpeech(
        '*walks over slowly* "Hello there my dear friend! How are you doing today so far?" *waves back*',
        'narrate',
      )
      expect(result).toEqual([
        { type: 'narration', text: 'walks over slowly' },
        { type: 'voice', text: 'Hello there my dear friend!' },
        { type: 'voice', text: 'How are you doing today so far?' },
        { type: 'narration', text: 'waves back' },
      ])
    })
    it('sentence-splits narration between quotes', () => {
      expect(parseForSpeech('"Hi!" He said. "Bye!"', 'narrate')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'narration', text: 'He said.' },
        { type: 'voice', text: 'Bye!' },
      ])
    })
  })

  describe('ellipsis preservation', () => {
    it('keeps a three-dot ellipsis verbatim and treats the surrounding text as one sentence', () => {
      expect(parseForSpeech('Ich dachte... vielleicht...', 'off')).toEqual([
        { type: 'voice', text: 'Ich dachte... vielleicht...' },
      ])
    })
    it('normalises Unicode ellipsis to three dots and keeps it intact', () => {
      expect(parseForSpeech('Ich dachte\u2026 vielleicht\u2026', 'off')).toEqual([
        { type: 'voice', text: 'Ich dachte... vielleicht...' },
      ])
    })
    it('does not split at an ellipsis even when an uppercase word follows', () => {
      expect(parseForSpeech('Ich weiss nicht... Aber egal.', 'off')).toEqual([
        { type: 'voice', text: 'Ich weiss nicht... Aber egal.' },
      ])
    })
  })

  describe('list handling via line breaks', () => {
    it('splits bulleted lists item-by-item', () => {
      // Each item must clear its length threshold so the splitter does not
      // merge them back together.
      const result = parseForSpeech(
        '- First item is long enough to stand alone\n- Second item is also long enough to stand alone\n- Third item is likewise long enough to stand alone',
        'off',
      )
      expect(result).toEqual([
        { type: 'voice', text: 'First item is long enough to stand alone' },
        { type: 'voice', text: 'Second item is also long enough to stand alone' },
        { type: 'voice', text: 'Third item is likewise long enough to stand alone' },
      ])
    })
    it('splits numbered lists item-by-item', () => {
      const result = parseForSpeech(
        '1. Alpha is a long enough list item here\n2. Bravo is another long enough list item here',
        'off',
      )
      expect(result).toEqual([
        { type: 'voice', text: 'Alpha is a long enough list item here' },
        { type: 'voice', text: 'Bravo is another long enough list item here' },
      ])
    })
  })

  describe('pre-processing (mode-agnostic)', () => {
    it('strips code blocks', () => {
      expect(
        parseForSpeech(
          'Here is some code for you today:\n```js\nconsole.log("hi")\n```\nAnd that concludes everything nicely.',
          'off',
        ),
      ).toEqual([
        { type: 'voice', text: 'Here is some code for you today:' },
        { type: 'voice', text: 'And that concludes everything nicely.' },
      ])
    })
    it('strips inline code', () => {
      expect(parseForSpeech('Use the `console.log` function.', 'off')).toEqual([
        { type: 'voice', text: 'Use the  function.' },
      ])
    })
    it('strips OOC markers', () => {
      expect(parseForSpeech('"Hello!" (( this is OOC )) *smiles*', 'play')).toEqual([
        { type: 'voice', text: 'Hello!' },
        { type: 'narration', text: 'smiles' },
      ])
    })
    it('strips markdown bold and italic', () => {
      expect(parseForSpeech('This is **bold** and __also bold__.', 'off')).toEqual([
        { type: 'voice', text: 'This is bold and also bold.' },
      ])
    })
    it('strips markdown headings', () => {
      expect(
        parseForSpeech(
          '## Section Title For Today\nSome substantive text goes into this section.',
          'off',
        ),
      ).toEqual([
        { type: 'voice', text: 'Section Title For Today' },
        { type: 'voice', text: 'Some substantive text goes into this section.' },
      ])
    })
    it('strips markdown links', () => {
      expect(parseForSpeech('Click [here](https://example.com) now.', 'off')).toEqual([
        { type: 'voice', text: 'Click here now.' },
      ])
    })
    it('strips URLs', () => {
      expect(parseForSpeech('Visit https://example.com for details.', 'off')).toEqual([
        { type: 'voice', text: 'Visit  for details.' },
      ])
    })
    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', 'off')).toEqual([])
    })
    it('returns empty array for code-only input', () => {
      expect(parseForSpeech('```js\ncode\n```', 'off')).toEqual([])
    })
  })

  describe('emoji stripping', () => {
    it('removes a trailing standalone emoji', () => {
      expect(parseForSpeech('Hi there 😀', 'off')).toEqual([
        { type: 'voice', text: 'Hi there' },
      ])
    })
    it('removes inline emojis in the middle of a sentence', () => {
      expect(parseForSpeech('I love 🍕 pizza.', 'off')).toEqual([
        { type: 'voice', text: 'I love  pizza.' },
      ])
    })
    it('removes regional-indicator flag pairs', () => {
      expect(parseForSpeech('Hallo aus \u{1F1E9}\u{1F1EA}!', 'off')).toEqual([
        { type: 'voice', text: 'Hallo aus !' },
      ])
    })
    it('removes ZWJ-joined emoji sequences', () => {
      // Family emoji (man + ZWJ + woman + ZWJ + girl + ZWJ + boy).
      expect(parseForSpeech('Family: \u{1F468}\u200D\u{1F469}\u200D\u{1F467}\u200D\u{1F466} here', 'off')).toEqual([
        { type: 'voice', text: 'Family:  here' },
      ])
    })
    it('removes skin-tone-modified emojis', () => {
      expect(parseForSpeech('Wave \u{1F44B}\u{1F3FD} hello', 'off')).toEqual([
        { type: 'voice', text: 'Wave  hello' },
      ])
    })
    it('removes emojis in narrate-mode voice segments', () => {
      expect(parseForSpeech('"Hi 😀 there"', 'narrate')).toEqual([
        { type: 'voice', text: 'Hi  there' },
      ])
    })
    it('preserves legal and commercial symbols that are not decorative emojis', () => {
      expect(parseForSpeech('Widget\u2122 and Logo\u00AE \u00A9 2026.', 'off')).toEqual([
        { type: 'voice', text: 'Widget\u2122 and Logo\u00AE \u00A9 2026.' },
      ])
    })
  })

  describe('markdown and quote decoration stripping', () => {
    describe("mode 'off'", () => {
      it('strips single asterisks, keeping the inner content', () => {
        expect(parseForSpeech('She *whispered* softly.', 'off')).toEqual([
          { type: 'voice', text: 'She whispered softly.' },
        ])
      })
      it('strips single underscores, keeping the inner content', () => {
        expect(parseForSpeech('This is _emphasised_ text.', 'off')).toEqual([
          { type: 'voice', text: 'This is emphasised text.' },
        ])
      })
      it('strips straight double quotes, keeping the inner content', () => {
        expect(parseForSpeech('He said "hello" to me.', 'off')).toEqual([
          { type: 'voice', text: 'He said hello to me.' },
        ])
      })
      it('strips curly double quotes, keeping the inner content', () => {
        expect(parseForSpeech('He said \u201chello\u201d to me.', 'off')).toEqual([
          { type: 'voice', text: 'He said hello to me.' },
        ])
      })
    })

    describe("mode 'play'", () => {
      it('strips single underscores from narration', () => {
        expect(parseForSpeech('Then _slowly_ she turned.', 'play')).toEqual([
          { type: 'narration', text: 'Then slowly she turned.' },
        ])
      })
      it('keeps the play-mode voice/narration split when asterisks are stripped pre-segmentation', () => {
        // `*he smiled*` becomes implicit narration (no marker needed) because
        // in play mode everything outside quotes is narration anyway.
        expect(parseForSpeech('"Hello" *he smiled*', 'play')).toEqual([
          { type: 'voice', text: 'Hello' },
          { type: 'narration', text: 'he smiled' },
        ])
      })
    })

    describe("mode 'narrate'", () => {
      it('strips single asterisks from narration', () => {
        expect(parseForSpeech('*walks over* "Hi" *waves*', 'narrate')).toEqual([
          { type: 'narration', text: 'walks over' },
          { type: 'voice', text: 'Hi' },
          { type: 'narration', text: 'waves' },
        ])
      })
      it('preserves straight quotes as voice-segment markers', () => {
        expect(parseForSpeech('He said "hello" quietly.', 'narrate')).toEqual([
          { type: 'narration', text: 'He said' },
          { type: 'voice', text: 'hello' },
          { type: 'narration', text: 'quietly.' },
        ])
      })
    })
  })
})

describe('parseForSpeech — expressive markup stripping', () => {
  it('strips inline tags when capability is absent', () => {
    const out = parseForSpeech('Hi [laugh] there.', 'off', false)
    expect(out).toEqual([{ type: 'voice', text: 'Hi  there.' }])
  })

  it('strips wrapping markers but keeps their content when capability is absent', () => {
    const out = parseForSpeech('I <whisper>whisper</whisper> quietly.', 'off', false)
    expect(out).toEqual([{ type: 'voice', text: 'I whisper quietly.' }])
  })

  it('keeps tags intact when capability is present', () => {
    const out = parseForSpeech('Hi [laugh] there.', 'off', true)
    expect(out).toEqual([{ type: 'voice', text: 'Hi [laugh] there.' }])
  })

  it('default (no third argument) behaves as capability absent', () => {
    const out = parseForSpeech('Hi [laugh] there.', 'off')
    expect(out).toEqual([{ type: 'voice', text: 'Hi  there.' }])
  })
})

describe('splitSegments — wrap-aware', () => {
  it('propagates a wrap that straddles a dialogue quote in narrate mode', () => {
    const out = parseForSpeech(
      '<whisper>Er sagte "hallo welt" gestern.</whisper>',
      'narrate',
      true,
    )
    expect(out).toEqual([
      { type: 'narration', text: '<whisper>Er sagte</whisper>' },
      { type: 'voice', text: '<whisper>hallo welt</whisper>' },
      { type: 'narration', text: '<whisper>gestern.</whisper>' },
    ])
  })

  it('keeps an inside-quote wrap local to the dialogue voice', () => {
    const out = parseForSpeech(
      'Er sagte "<whisper>hallo</whisper>" und ging.',
      'narrate',
      true,
    )
    expect(out).toEqual([
      { type: 'narration', text: 'Er sagte' },
      { type: 'voice', text: '<whisper>hallo</whisper>' },
      { type: 'narration', text: 'und ging.' },
    ])
  })

  it('behaves identically to today when expressive markup is off', () => {
    const out = parseForSpeech(
      'Er sagte "hallo welt" gestern.',
      'narrate',
      false,
    )
    expect(out).toEqual([
      { type: 'narration', text: 'Er sagte' },
      { type: 'voice', text: 'hallo welt' },
      { type: 'narration', text: 'gestern.' },
    ])
  })
})
