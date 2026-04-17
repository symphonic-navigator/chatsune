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
      expect(parseForSpeech('Hi! How are you? I am fine.', 'off')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
        { type: 'voice', text: 'I am fine.' },
      ])
    })
    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', 'off')).toEqual([])
    })
  })

  describe("mode 'play' (dialogue spoken, narration narrated)", () => {
    it('splits dialogue and narration, then splits each by sentence', () => {
      const result = parseForSpeech('*walks over* "Hello there! How are you?" *waves*', 'play')
      expect(result).toEqual([
        { type: 'narration', text: 'walks over' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'voice', text: 'How are you?' },
        { type: 'narration', text: 'waves' },
      ])
    })
    it('treats unmarked text as narration and sentence-splits it', () => {
      expect(parseForSpeech('She looked away. He did too.', 'play')).toEqual([
        { type: 'narration', text: 'She looked away.' },
        { type: 'narration', text: 'He did too.' },
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
    it('swaps roles and sentence-splits inside quotes', () => {
      const result = parseForSpeech('*walks over* "Hello there! How are you?" *waves*', 'narrate')
      expect(result).toEqual([
        { type: 'narration', text: '*walks over*' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'voice', text: 'How are you?' },
        { type: 'narration', text: '*waves*' },
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

  describe('ellipsis normalisation', () => {
    it("collapses '...' and does not split mid-thought", () => {
      expect(parseForSpeech('Ich dachte... vielleicht...', 'off')).toEqual([
        { type: 'voice', text: 'Ich dachte. vielleicht.' },
      ])
    })
    it('collapses Unicode ellipsis', () => {
      expect(parseForSpeech('Ich dachte\u2026 vielleicht\u2026', 'off')).toEqual([
        { type: 'voice', text: 'Ich dachte. vielleicht.' },
      ])
    })
  })

  describe('list handling via line breaks', () => {
    it('splits bulleted lists item-by-item', () => {
      const result = parseForSpeech('- First item\n- Second item\n- Third item', 'off')
      expect(result).toEqual([
        { type: 'voice', text: 'First item' },
        { type: 'voice', text: 'Second item' },
        { type: 'voice', text: 'Third item' },
      ])
    })
    it('splits numbered lists item-by-item', () => {
      const result = parseForSpeech('1. Alpha\n2. Bravo', 'off')
      expect(result).toEqual([
        { type: 'voice', text: 'Alpha' },
        { type: 'voice', text: 'Bravo' },
      ])
    })
  })

  describe('pre-processing (mode-agnostic)', () => {
    it('strips code blocks', () => {
      expect(parseForSpeech('Here is some code:\n```js\nconsole.log("hi")\n```\nDone.', 'off')).toEqual([
        { type: 'voice', text: 'Here is some code:' },
        { type: 'voice', text: 'Done.' },
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
      expect(parseForSpeech('## Section Title\nSome text.', 'off')).toEqual([
        { type: 'voice', text: 'Section Title' },
        { type: 'voice', text: 'Some text.' },
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
})
