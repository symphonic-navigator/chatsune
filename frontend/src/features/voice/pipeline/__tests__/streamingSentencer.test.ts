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
      expect(s.push('Hello world and everyone! ')).toEqual([])
      expect(s.push('Another')).toEqual([
        { type: 'voice', text: 'Hello world and everyone!' },
      ])
    })

    it('emits on a hard line break', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('No punctuation here at all\n')).toEqual([
        { type: 'voice', text: 'No punctuation here at all' },
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
      s.push('Something which is long enough to count as a sentence.')
      s.reset()
      expect(s.flush()).toEqual([])
    })

    it('emits multiple sentences across successive pushes', () => {
      const s = createStreamingSentencer('off')
      // Each sentence is sized past its respective threshold so we still
      // verify cut-per-sentence behaviour.
      const first = s.push('First one is a long enough sentence. ')
      expect(first).toEqual([])
      const second = s.push('Second one is another long enough sentence. ')
      expect(second).toEqual([
        { type: 'voice', text: 'First one is a long enough sentence.' },
      ])
      const third = s.push('Third o')
      expect(third).toEqual([
        { type: 'voice', text: 'Second one is another long enough sentence.' },
      ])
      expect(s.flush()).toEqual([{ type: 'voice', text: 'Third o' }])
    })
  })

  describe('safe-prefix invariants', () => {
    it('does not emit while a fenced code block is open', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Before everything happens here. ```\ncode. ')).toEqual([])
      // After we close the fence, the "Before..." sentence becomes safe
      // once the next uppercase starter arrives.
      expect(s.push('```\nAfter it all is done and said. More content')).toEqual([
        { type: 'voice', text: 'Before everything happens here.' },
        { type: 'voice', text: 'After it all is done and said.' },
      ])
    })

    it('does not emit while an inline-tick span is open on the same line', () => {
      const s = createStreamingSentencer('off')
      // `.` inside the unclosed inline-tick span must not trigger a cut.
      expect(s.push('Use the following command `npm. ')).toEqual([])
      // After the backtick closes and a proper uppercase sentence start
      // appears, the whole prefix commits (inline code is stripped).
      expect(s.push('install`. Then run it nicely and long enough now please')).toEqual([
        { type: 'voice', text: 'Use the following command .' },
      ])
    })

    it('does not emit while an OOC marker is open', () => {
      // Unclosed OOC is never safe to cut inside.
      const s = createStreamingSentencer('off')
      expect(s.push('A nice long story begins here. ((aside note ')).toEqual([])
      expect(s.push('stays open for a while')).toEqual([])
      // Closing the OOC and then a proper sentence-starting uppercase unlocks
      // a single combined chunk (OOC is stripped by parseForSpeech).
      const emitted = s.push(')) Then comes the much longer follow-up. Next stuff')
      expect(emitted).toEqual([
        { type: 'voice', text: 'A nice long story begins here.' },
        { type: 'voice', text: 'Then comes the much longer follow-up.' },
      ])
    })

    it("mode 'narrate' does not cut inside an open double-quote", () => {
      const s = createStreamingSentencer('narrate')
      // Opening quote means we cannot commit at the "." inside the quote.
      expect(s.push('She said loudly and clearly "Hello everyone here today. ')).toEqual([])
      // Until the quote closes, the scanner stays unsafe.
      expect(s.push('Goodbye to all of you now my friends. ')).toEqual([])
      // Close the quote, add a terminal sentence and sentence-starting
      // uppercase follow-up. Only then can the whole chunk commit via
      // parseForSpeech.
      expect(s.push('" she added quietly afterwards today. Next stuff comes')).toEqual([
        { type: 'narration', text: 'She said loudly and clearly' },
        { type: 'voice', text: 'Hello everyone here today.' },
        { type: 'voice', text: 'Goodbye to all of you now my friends.' },
        { type: 'narration', text: 'she added quietly afterwards today.' },
      ])
    })

    it("mode 'play' does not cut inside an open asterisk pair", () => {
      const s = createStreamingSentencer('play')
      // Asterisks must be balanced before we commit anything post-asterisk.
      expect(s.push('Before everything happens here. *walks. ')).toEqual([])
      expect(s.push('smiles* After it all ends right now')).toEqual([])
      // preprocess strips `*walks. smiles*` to `walks. smiles` before
      // segmentation; the resulting plain prose is a single narration segment
      // because none of the internal periods are followed by an uppercase word.
      expect(s.push('. Next')).toEqual([
        {
          type: 'narration',
          text: 'Before everything happens here. walks. smiles After it all ends right now.',
        },
      ])
    })

    it("mode 'off' ignores asterisks (no balance requirement)", () => {
      const s = createStreamingSentencer('off')
      // Asterisks are stripped as markdown bold inside parseForSpeech when
      // paired, but unpaired asterisks don't block the cut.
      expect(s.push('One thing leads to another here. Two')).toEqual([
        { type: 'voice', text: 'One thing leads to another here.' },
      ])
    })

    it('apostrophes inside words do not open a single-quote span', () => {
      const s = createStreamingSentencer('narrate')
      // "it's" and "don't" contain an apostrophe that must NOT be treated as
      // an opening quote — otherwise the safe-cut would never trigger.
      expect(s.push("It's absolutely fine by me here. ")).toEqual([])
      expect(s.push('Next up comes more')).toEqual([
        { type: 'narration', text: "It's absolutely fine by me here." },
      ])
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
      s.push('Only one long opening sentence here. ')
      // Commits "Only one..." and "Second is another..." via "T" start.
      s.push('Second is another long enough sentence. Third')
      s.flush()
      expect(s.flush()).toEqual([])
    })
  })

  describe('ellipsis handling', () => {
    it('does not commit on any dot inside a "..." run', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Ich dachte... ')).toEqual([])
      expect(s.push('vielleicht... ')).toEqual([])
      expect(s.push('ja. Next')).toEqual([
        { type: 'voice', text: 'Ich dachte... vielleicht... ja.' },
      ])
    })

    it('commits past an ellipsis once a real sentence terminator follows', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Warte... noch einen kurzen Moment mal. ')).toEqual([])
      expect(s.push('Next')).toEqual([
        { type: 'voice', text: 'Warte... noch einen kurzen Moment mal.' },
      ])
    })
  })

  describe('emoji boundary handling', () => {
    it('commits a sentence when an emoji follows punctuation with whitespace', () => {
      const s = createStreamingSentencer('off')
      // Emoji past the whitespace run is a valid sentence-start marker and
      // unlocks the cut at the punctuation immediately.
      expect(s.push('That is really absolutely great! 😀 Let')).toEqual([
        { type: 'voice', text: 'That is really absolutely great!' },
      ])
    })

    it('commits a sentence when an emoji directly follows punctuation (no space)', () => {
      const s = createStreamingSentencer('off')
      // Emoji right after "!" is a valid cut point without any whitespace,
      // matching LLM decoration patterns like "Great!😀".
      expect(s.push('That is really absolutely great!😀 Let')).toEqual([
        { type: 'voice', text: 'That is really absolutely great!' },
      ])
    })

    it('drops emoji-only segments on flush', () => {
      const s = createStreamingSentencer('off')
      // End-of-stream case: "Hello everyone here today!" commits on the
      // emoji cut, leaving "😄" as the buffer tail. flush must not emit a
      // speech-less segment — TTS providers sanitise them to empty and
      // reject the request.
      expect(s.push('Hello everyone here today!😄')).toEqual([
        { type: 'voice', text: 'Hello everyone here today!' },
      ])
      expect(s.flush()).toEqual([])
    })
  })
})

describe('createStreamingSentencer — length guard (Guard 1)', () => {
  it('does not cut a first sentence below 20 effective characters', () => {
    const s = createStreamingSentencer('off')
    // "Short one." → 10 chars, below the first-sentence threshold.
    // Even with a proper uppercase starter following, no emit yet.
    expect(s.push('Short one. Then more arrives here')).toEqual([])
  })

  it('emits the first sentence once it clears 20 effective characters', () => {
    const s = createStreamingSentencer('off')
    // Sentence is 24 chars effective — above the 20-char first-sentence
    // threshold. Cut lands on the following uppercase starter.
    const out = s.push('Hi there my dear friend! Next stuff follows')
    expect(out).toEqual([{ type: 'voice', text: 'Hi there my dear friend!' }])
  })

  it('does not emit a too-short follow-up sentence as its own chunk', () => {
    const s = createStreamingSentencer('off')
    // First push: a 24-char sentence is past the first-sentence threshold
    // so it can commit once an uppercase starter arrives.
    expect(s.push('Hi there my dear friend! ')).toEqual([])
    // Second push: the first sentence commits, and "Short." (6 chars) —
    // the follow-up — is swallowed into the same chunk by the batch merge
    // rather than leaving the sentencer as a standalone tiny TTS request.
    const out = s.push('Short. Another fragment follows')
    expect(out.length).toBe(1)
    // Whatever final shape the merge produced, "Short." must not appear as
    // its own speech segment.
    expect(out.every((seg) => seg.text !== 'Short.')).toBe(true)
  })

  it('emits a follow-up once it clears 30 effective characters', () => {
    const s = createStreamingSentencer('off')
    // First push: no uppercase starter yet → buffered.
    expect(s.push('Hi there my dear friend! ')).toEqual([])
    // Second push: "This second sentence is plenty long." is 36 effective
    // chars, past the 30 threshold, and the uppercase "Next" unlocks the
    // boundary of both the first and second sentences.
    const out = s.push('This second sentence is plenty long. Next')
    expect(out).toEqual([
      { type: 'voice', text: 'Hi there my dear friend!' },
      { type: 'voice', text: 'This second sentence is plenty long.' },
    ])
  })

  it('merges a tag-only chunk with the next sentence (the bug)', () => {
    // The canonical regression case from the spec. An LLM-emitted
    // "[chuckle] [nod]\n<soft>…</soft>" must not produce a tag-only
    // chunk — Guard 1 forces the tags to stay attached to the next sentence.
    const s = createStreamingSentencer('off', true)
    const out1 = s.push(
      '[chuckle] [nod]\n<soft>Verstanden, STT Test Marathon laeuft weiter schon.</soft> ',
    )
    expect(out1).toEqual([])
    const out2 = s.push(
      '<emphasis>Kein laengerer Problemfall hier!</emphasis> Weiterer langer Fuelltext hier.',
    )
    // After the second push we expect the first speech segment to carry
    // both the tag prefix and the <soft> sentence content.
    expect(out2.length).toBeGreaterThan(0)
    const firstText = out2[0].text
    expect(firstText).toContain('[chuckle]')
    expect(firstText).toContain('Verstanden')
  })
})

describe('createStreamingSentencer — no-space guard (Guard 2)', () => {
  it('does not cut at an abbreviation when no whitespace has appeared yet', () => {
    const s = createStreamingSentencer('off')
    // "z.B." is an abbreviation. The "." at position 3 has an uppercase
    // letter following ("B"), but no whitespace has appeared in the
    // segment since the start → Guard 2 blocks the cut there.
    // Later, a genuine sentence end ("erzaehlen.") followed by a new
    // sentence-starter does emit, confirming we only blocked the abbrev.
    const out = s.push(
      'z.B. Gerne moechte ich dir etwas Wichtiges erzaehlen. Naechste Stufe kommt',
    )
    expect(out).toEqual([
      { type: 'voice', text: 'z.B. Gerne moechte ich dir etwas Wichtiges erzaehlen.' },
    ])
  })

  it('still cuts on a newline inside an abbreviation-like prefix (newlines ignore Guard 2)', () => {
    const s = createStreamingSentencer('off')
    // Newline is always a boundary regardless of Guard 2. Guard 1 still
    // applies — so a pure "z.B." (4 chars, below 20) stays buffered.
    expect(s.push('z.B.\nirgendwas kurzes')).toEqual([])
  })
})

describe('createStreamingSentencer — flush bypasses guards (Guard 3)', () => {
  it('flush emits a short trailing sentence below the threshold', () => {
    const s = createStreamingSentencer('off')
    s.push('Kurz.')
    expect(s.flush()).toEqual([{ type: 'voice', text: 'Kurz.' }])
  })

  it('flush emits the tail even if the last committed chunk was empty', () => {
    const s = createStreamingSentencer('off')
    // Below-threshold sentence stays buffered on push.
    expect(s.push('Ja.')).toEqual([])
    // Flush sends it regardless.
    expect(s.flush()).toEqual([{ type: 'voice', text: 'Ja.' }])
  })
})

describe('createStreamingSentencer — expressive markup', () => {
  it('re-wraps a <whisper> that spans a sentence boundary', () => {
    const s = createStreamingSentencer('off', true)
    const out1 = s.push('<whisper>Ich verrate dir ein Geheimnis. Die Klingonen ')
    expect(out1).toEqual([
      { type: 'voice', text: '<whisper>Ich verrate dir ein Geheimnis.</whisper>' },
    ])
    const out2 = s.push('planen einen Angriff.</whisper> Dann ')
    expect(out2).toEqual([
      { type: 'voice', text: '<whisper> Die Klingonen planen einen Angriff.</whisper>' },
    ])
  })

  it('re-wraps nested wraps across a cut', () => {
    const s = createStreamingSentencer('off', true)
    // "Das ist wichtig fuer uns." is 25 effective chars (>= 20).
    const out1 = s.push('<soft><emphasis>Das ist wichtig fuer uns.</emphasis> Nicht so ')
    expect(out1).toEqual([
      { type: 'voice', text: '<soft><emphasis>Das ist wichtig fuer uns.</emphasis></soft>' },
    ])
    // "Nicht so wichtig jetzt im Moment." is 33 effective chars (>= 30).
    const out2 = s.push('wichtig jetzt im Moment.</soft> Danach folgt weiterer Text ')
    expect(out2).toEqual([
      { type: 'voice', text: '<soft> Nicht so wichtig jetzt im Moment.</soft>' },
    ])
  })

  it('treats unknown tags as plain text', () => {
    const s = createStreamingSentencer('off', true)
    // "<foo>hi there everyone.</foo>" is >= 20 effective chars — both foo
    // tags are unknown so they count towards raw and effective length.
    const out = s.push('<foo>hi there everyone.</foo> Next up we have more ')
    expect(out).toEqual([{ type: 'voice', text: '<foo>hi there everyone.</foo>' }])
  })

  it('flush closes an unterminated open on emit so TTS sees balanced input', () => {
    const s = createStreamingSentencer('off', true)
    s.push('<whisper>ich sage noch nichts')   // no sentence-end → buffered
    const out = s.flush()
    expect(out).toEqual([{ type: 'voice', text: '<whisper>ich sage noch nichts</whisper>' }])
  })

  it('strips expression tags and emits plain text when flag is false (default)', () => {
    // flag=false activates tag-stripping in preprocess; no wrap-stack rewrapping.
    // The tags are removed and only the inner text is spoken.
    const s = createStreamingSentencer('off')
    // Raw "<whisper>hello there my friend.</whisper>" → stripped body is
    // "hello there my friend." (22 chars, >= 20).
    const out = s.push('<whisper>hello there my friend.</whisper> Next up more ')
    expect(out).toEqual([{ type: 'voice', text: 'hello there my friend.' }])
  })
})
