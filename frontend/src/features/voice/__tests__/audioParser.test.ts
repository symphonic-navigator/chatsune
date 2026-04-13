import { describe, expect, it } from 'vitest'
import { parseForSpeech } from '../pipeline/audioParser'

describe('parseForSpeech', () => {
  describe('roleplay mode', () => {
    it('splits quoted dialogue from narration', () => {
      const result = parseForSpeech('*walks over* "Hello there!" *waves*', true)
      expect(result).toEqual([
        { type: 'narration', text: 'walks over' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'narration', text: 'waves' },
      ])
    })
    it('treats unmarked text as narration', () => {
      const result = parseForSpeech('She looked away quietly.', true)
      expect(result).toEqual([{ type: 'narration', text: 'She looked away quietly.' }])
    })
    it('handles consecutive dialogue segments', () => {
      const result = parseForSpeech('"Hi!" "How are you?"', true)
      expect(result).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
      ])
    })
  })
  describe('non-roleplay mode', () => {
    it('treats everything as voice', () => {
      expect(parseForSpeech('Hello, how are you?', false)).toEqual([{ type: 'voice', text: 'Hello, how are you?' }])
    })
  })
  describe('pre-processing', () => {
    it('strips code blocks', () => {
      const input = 'Here is some code:\n```js\nconsole.log("hi")\n```\nDone.'
      expect(parseForSpeech(input, false)).toEqual([{ type: 'voice', text: 'Here is some code:\nDone.' }])
    })
    it('strips inline code', () => {
      expect(parseForSpeech('Use the `console.log` function.', false)).toEqual([{ type: 'voice', text: 'Use the  function.' }])
    })
    it('strips OOC markers', () => {
      expect(parseForSpeech('"Hello!" (( this is OOC )) *smiles*', true)).toEqual([
        { type: 'voice', text: 'Hello!' },
        { type: 'narration', text: 'smiles' },
      ])
    })
    it('strips markdown bold and italic', () => {
      expect(parseForSpeech('This is **bold** and __also bold__.', false)).toEqual([{ type: 'voice', text: 'This is bold and also bold.' }])
    })
    it('strips markdown headings', () => {
      expect(parseForSpeech('## Section Title\nSome text.', false)).toEqual([{ type: 'voice', text: 'Section Title\nSome text.' }])
    })
    it('strips markdown links', () => {
      expect(parseForSpeech('Click [here](https://example.com) now.', false)).toEqual([{ type: 'voice', text: 'Click here now.' }])
    })
    it('strips URLs', () => {
      expect(parseForSpeech('Visit https://example.com for details.', false)).toEqual([{ type: 'voice', text: 'Visit  for details.' }])
    })
    it('strips list markers', () => {
      expect(parseForSpeech('- First item\n- Second item\n1. Numbered', false)).toEqual([{ type: 'voice', text: 'First item\nSecond item\nNumbered' }])
    })
    it('returns empty array for empty input', () => { expect(parseForSpeech('', false)).toEqual([]) })
    it('returns empty array for code-only input', () => { expect(parseForSpeech('```js\ncode\n```', false)).toEqual([]) })
  })
})
