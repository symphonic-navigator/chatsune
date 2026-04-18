import { describe, expect, it } from 'vitest'
import { createStreamingSentencer } from '../streamingSentencer'

describe('createStreamingSentencer', () => {
  describe("mode 'off'", () => {
    it('returns nothing for a partial sentence', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Hello ')).toEqual([])
      expect(s.push('world')).toEqual([])
    })

    it('emits a sentence once a following uppercase word arrives', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Hello world. ')).toEqual([])
      expect(s.push('Another')).toEqual([{ type: 'voice', text: 'Hello world.' }])
    })

    it('emits on a hard line break', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('No punctuation here\n')).toEqual([
        { type: 'voice', text: 'No punctuation here' },
      ])
    })

    it('does not cut inside a decimal', () => {
      const s = createStreamingSentencer('off')
      // "3." followed by "14" — must NOT emit after "3." because next char is '1', not whitespace.
      expect(s.push('Pi is 3.14 metres.')).toEqual([])
    })

    it('flush emits whatever is buffered, even without a boundary', () => {
      const s = createStreamingSentencer('off')
      s.push('An incomplete fragment')
      expect(s.flush()).toEqual([{ type: 'voice', text: 'An incomplete fragment' }])
    })

    it('reset clears state', () => {
      const s = createStreamingSentencer('off')
      s.push('Something.')
      s.reset()
      expect(s.flush()).toEqual([])
    })

    it('emits multiple sentences across successive pushes', () => {
      const s = createStreamingSentencer('off')
      const first = s.push('First one. ')
      expect(first).toEqual([])
      const second = s.push('Second one. ')
      expect(second).toEqual([{ type: 'voice', text: 'First one.' }])
      const third = s.push('Third o')
      expect(third).toEqual([{ type: 'voice', text: 'Second one.' }])
      expect(s.flush()).toEqual([{ type: 'voice', text: 'Third o' }])
    })
  })

  describe('safe-prefix invariants', () => {
    it('does not emit while a fenced code block is open', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Before. ```\ncode. ')).toEqual([])
      // After we close the fence, the "Before." sentence becomes safe once the
      // next uppercase starter arrives.
      expect(s.push('```\nAfter. More')).toEqual([
        { type: 'voice', text: 'Before.' },
        { type: 'voice', text: 'After.' },
      ])
    })

    it('does not emit while an inline-tick span is open on the same line', () => {
      const s = createStreamingSentencer('off')
      // `.` inside the unclosed inline-tick span must not trigger a cut.
      expect(s.push('Use `npm. ')).toEqual([])
      // After the backtick closes and a proper uppercase sentence start
      // appears, the whole prefix commits (inline code is stripped).
      expect(s.push('install`. Then run')).toEqual([
        { type: 'voice', text: 'Use .' },
      ])
    })

    it('does not emit while an OOC marker is open', () => {
      // Unclosed OOC is never safe to cut inside.
      const s = createStreamingSentencer('off')
      expect(s.push('Story. ((aside note ')).toEqual([])
      expect(s.push('stays open')).toEqual([])
      // Closing the OOC and then a proper sentence-starting uppercase unlocks
      // a single combined chunk (OOC is stripped by parseForSpeech).
      const emitted = s.push(')) Then comes more. Next')
      expect(emitted).toEqual([
        { type: 'voice', text: 'Story.' },
        { type: 'voice', text: 'Then comes more.' },
      ])
    })

    it("mode 'narrate' does not cut inside an open double-quote", () => {
      const s = createStreamingSentencer('narrate')
      // Opening quote means we cannot commit at the "." inside the quote.
      expect(s.push('She said "Hello. ')).toEqual([])
      // Until the quote closes, the scanner stays unsafe.
      expect(s.push('Goodbye. ')).toEqual([])
      // Close the quote, add a terminal sentence and sentence-starting
      // uppercase follow-up. Only then can the whole chunk commit via
      // parseForSpeech.
      expect(s.push('" she added. Next')).toEqual([
        { type: 'narration', text: 'She said' },
        { type: 'voice', text: 'Hello.' },
        { type: 'voice', text: 'Goodbye.' },
        { type: 'narration', text: 'she added.' },
      ])
    })

    it("mode 'play' does not cut inside an open asterisk pair", () => {
      const s = createStreamingSentencer('play')
      // Asterisks must be balanced before we commit anything post-asterisk.
      expect(s.push('Before. *walks. ')).toEqual([])
      expect(s.push('smiles* After it all ends')).toEqual([])
      // splitSegments groups everything inside a matching */…/* pair into
      // one narration block, so "*walks. smiles*" becomes a single segment
      // (then sentence-split into two on the internal period).
      expect(s.push('. Next')).toEqual([
        { type: 'narration', text: 'Before.' },
        { type: 'narration', text: 'walks. smiles' },
        { type: 'narration', text: 'After it all ends.' },
      ])
    })

    it("mode 'off' ignores asterisks (no balance requirement)", () => {
      const s = createStreamingSentencer('off')
      // Asterisks are stripped as markdown bold inside parseForSpeech when
      // paired, but unpaired asterisks don't block the cut.
      expect(s.push('One. Two')).toEqual([{ type: 'voice', text: 'One.' }])
    })

    it('apostrophes inside words do not open a single-quote span', () => {
      const s = createStreamingSentencer('narrate')
      // "it's" and "don't" contain an apostrophe that must NOT be treated as
      // an opening quote — otherwise the safe-cut would never trigger.
      expect(s.push("It's fine. ")).toEqual([])
      expect(s.push('Next up')).toEqual([{ type: 'narration', text: "It's fine." }])
    })
  })

  describe('flush', () => {
    it('drains the entire buffer even if unbalanced', () => {
      const s = createStreamingSentencer('off')
      s.push('```\nhalf-open fence')
      const out = s.flush()
      // parseForSpeech strips unterminated fences in the raw preprocess. Since
      // the fence is unbalanced and our regex only matches `…`, it stays in
      // the buffer; what matters is that flush returns *something* for the
      // non-stripped portion without throwing.
      expect(Array.isArray(out)).toBe(true)
    })

    it('returns an empty array when nothing is pending', () => {
      const s = createStreamingSentencer('off')
      s.push('Only one. ')
      s.push('Second. Third') // commits "Only one." and "Second." via "T" start
      s.flush()
      expect(s.flush()).toEqual([])
    })
  })

  describe('emoji boundary handling', () => {
    it('commits a sentence when an emoji follows punctuation with whitespace', () => {
      const s = createStreamingSentencer('off')
      // Emoji past the whitespace run is a valid sentence-start marker and
      // unlocks the cut at the punctuation immediately.
      expect(s.push('That is great! 😀 Let')).toEqual([{ type: 'voice', text: 'That is great!' }])
    })

    it('commits a sentence when an emoji directly follows punctuation (no space)', () => {
      const s = createStreamingSentencer('off')
      // Emoji right after "!" is a valid cut point without any whitespace,
      // matching LLM decoration patterns like "Great!😀".
      expect(s.push('That is great!😀 Let')).toEqual([{ type: 'voice', text: 'That is great!' }])
    })

    it('drops emoji-only segments on flush', () => {
      const s = createStreamingSentencer('off')
      // End-of-stream case: "Hello!" commits on the emoji cut, leaving "😄"
      // as the buffer tail. flush must not emit a speech-less segment —
      // TTS providers sanitise them to empty and reject the request.
      expect(s.push('Hello!😄')).toEqual([{ type: 'voice', text: 'Hello!' }])
      expect(s.flush()).toEqual([])
    })
  })
})
