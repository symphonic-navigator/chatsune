import { describe, expect, it } from 'vitest'
import { parseForSpeech } from '../pipeline/audioParser'

describe('parseForSpeech', () => {
  describe("mode 'off'", () => {
    it('treats everything as a single voice segment', () => {
      expect(parseForSpeech('Hello, how are you?', 'off')).toEqual([{ type: 'voice', text: 'Hello, how are you?' }])
    })
    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', 'off')).toEqual([])
    })
  })

  describe("mode 'play' (dialogue spoken, narration narrated)", () => {
    it('splits quoted dialogue from narration', () => {
      const result = parseForSpeech('*walks over* "Hello there!" *waves*', 'play')
      expect(result).toEqual([
        { type: 'narration', text: 'walks over' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'narration', text: 'waves' },
      ])
    })
    it('treats unmarked text as narration', () => {
      expect(parseForSpeech('She looked away quietly.', 'play')).toEqual([
        { type: 'narration', text: 'She looked away quietly.' },
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
    it('swaps the roles: prose and actions become narration, quotes become voice', () => {
      const result = parseForSpeech('*walks over* "Hello there!" *waves*', 'narrate')
      expect(result).toEqual([
        { type: 'narration', text: '*walks over*' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'narration', text: '*waves*' },
      ])
    })
    it('treats unmarked text as narration', () => {
      expect(parseForSpeech('She looked away quietly.', 'narrate')).toEqual([
        { type: 'narration', text: 'She looked away quietly.' },
      ])
    })
    it('keeps consecutive dialogue segments as voice', () => {
      expect(parseForSpeech('"Hi!" "How are you?"', 'narrate')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
      ])
    })
    it('emits narration between quotes', () => {
      expect(parseForSpeech('"Hi!" he said. "Bye!"', 'narrate')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'narration', text: 'he said.' },
        { type: 'voice', text: 'Bye!' },
      ])
    })
  })

  describe('pre-processing (mode-agnostic)', () => {
    it('strips code blocks', () => {
      expect(parseForSpeech('Here is some code:\n```js\nconsole.log("hi")\n```\nDone.', 'off')).toEqual([
        { type: 'voice', text: 'Here is some code:\nDone.' },
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
        { type: 'voice', text: 'Section Title\nSome text.' },
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
    it('strips list markers', () => {
      expect(parseForSpeech('- First item\n- Second item\n1. Numbered', 'off')).toEqual([
        { type: 'voice', text: 'First item\nSecond item\nNumbered' },
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
