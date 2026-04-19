# TTS Text Preprocessing Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frontend voice pipeline preserve ellipses, strip residual markdown and quote decoration, and drop emojis before handing text to the TTS provider.

**Architecture:** All changes live in `frontend/src/features/voice/pipeline/`. `preprocess` in `audioParser.ts` gains a narrator-mode parameter and additional replace-rules. `sentenceSplitter.ts` stops collapsing ellipses and gains a negative lookbehind in its boundary regex. `streamingSentencer.ts` refuses to cut on the second-or-later dot of a run. Existing ellipsis-normalisation tests are updated to the new contract; new tests lock in the markdown-strip and emoji-strip behaviour.

**Tech Stack:** TypeScript, Vite, Vitest, `pnpm`.

**Spec:** `devdocs/superpowers/specs/2026-04-19-tts-text-preprocessing-hardening-design.md`

---

## File Structure

| File | Role |
| --- | --- |
| `frontend/src/features/voice/pipeline/audioParser.ts` | `preprocess` gains `mode` param; strip rules for `*…*`, `_…_`, quotes (off-only), emojis. |
| `frontend/src/features/voice/pipeline/sentenceSplitter.ts` | `normaliseEllipses` keeps `...`; `SENTENCE_BOUNDARY` refuses the third dot of an ellipsis. |
| `frontend/src/features/voice/pipeline/streamingSentencer.ts` | `findSafeCutPoint` rejects `.` preceded by `.`. |
| `frontend/src/features/voice/__tests__/audioParser.test.ts` | Update ellipsis tests; add markdown-strip, quote-strip, emoji-strip tests. |
| `frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts` | Update ellipsis tests. |
| `frontend/src/features/voice/pipeline/__tests__/streamingSentencer.test.ts` | Add test: streaming does not cut inside `...`. |

Working directory for all test runs: `frontend/`. Run via `pnpm exec vitest run <path>` for a single file.

---

## Task 1: Preserve ellipses end-to-end

**Files:**
- Modify: `frontend/src/features/voice/__tests__/audioParser.test.ts:66-77`
- Modify: `frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts:37-54`
- Modify: `frontend/src/features/voice/pipeline/__tests__/streamingSentencer.test.ts` (append new describe block)
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts:17-18`
- Modify: `frontend/src/features/voice/pipeline/sentenceSplitter.ts:3-5, 12`
- Modify: `frontend/src/features/voice/pipeline/streamingSentencer.ts:92`

- [ ] **Step 1.1: Update `sentenceSplitter.test.ts` ellipsis tests to new contract**

Replace the existing three ellipsis tests (lines 37–54) with:

```ts
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
```

- [ ] **Step 1.2: Update `audioParser.test.ts` ellipsis tests to new contract**

Replace the `describe('ellipsis normalisation', ...)` block at lines 66–77 with:

```ts
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
```

- [ ] **Step 1.3: Append an ellipsis-streaming test to `streamingSentencer.test.ts`**

Before the closing `})` of the outermost `describe('createStreamingSentencer', ...)`, append:

```ts
  describe('ellipsis handling', () => {
    it('does not commit on any dot inside a "..." run', () => {
      const s = createStreamingSentencer('off')
      // The third dot of "..." used to be a committable boundary because the
      // old code collapsed "..." to ".". With ellipses preserved, the entire
      // prefix stays buffered until a real sentence-ending context appears.
      expect(s.push('Ich dachte... ')).toEqual([])
      expect(s.push('vielleicht... ')).toEqual([])
      expect(s.push('ja. Next')).toEqual([
        { type: 'voice', text: 'Ich dachte... vielleicht... ja.' },
      ])
    })

    it('commits past an ellipsis once a real sentence terminator follows', () => {
      const s = createStreamingSentencer('off')
      expect(s.push('Warte... kurz mal. ')).toEqual([])
      expect(s.push('Next')).toEqual([
        { type: 'voice', text: 'Warte... kurz mal.' },
      ])
    })
  })
```

- [ ] **Step 1.4: Run the three affected test files and confirm they fail**

Run from `frontend/`:
```bash
pnpm exec vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts src/features/voice/__tests__/audioParser.test.ts src/features/voice/pipeline/__tests__/streamingSentencer.test.ts
```

Expected: the three updated tests in `sentenceSplitter.test.ts`, the three updated tests in `audioParser.test.ts`, and the two new tests in `streamingSentencer.test.ts` fail. The remaining tests still pass.

- [ ] **Step 1.5: Update `preprocess` in `audioParser.ts` to stop collapsing ellipses**

Replace lines 17–18:
```ts
  s = s.replace(/\.{2,}/g, '.')                   // collapse '..', '...', '....'
  s = s.replace(/\u2026/g, '.')                   // collapse Unicode ellipsis
```
with:
```ts
  s = s.replace(/\u2026/g, '...')                 // normalise Unicode ellipsis to three dots
```

- [ ] **Step 1.6: Update `normaliseEllipses` and `SENTENCE_BOUNDARY` in `sentenceSplitter.ts`**

Replace the `normaliseEllipses` function body:
```ts
function normaliseEllipses(text: string): string {
  return text.replace(/\.{2,}/g, '.').replace(/\u2026/g, '.')
}
```
with:
```ts
function normaliseEllipses(text: string): string {
  return text.replace(/\u2026/g, '...')
}
```

Replace the `SENTENCE_BOUNDARY` definition (line 12):
```ts
const SENTENCE_BOUNDARY = /(?<=[.!?])(?:\s+(?=[A-Z\u00C4\u00D6\u00DC]|\p{Extended_Pictographic})|(?=\p{Extended_Pictographic}))/u
```
with:
```ts
const SENTENCE_BOUNDARY = /(?<![.][.])(?<=[.!?])(?:\s+(?=[A-Z\u00C4\u00D6\u00DC]|\p{Extended_Pictographic})|(?=\p{Extended_Pictographic}))/u
```

The negative lookbehind `(?<![.][.])` rejects the boundary candidate when the two preceding characters are both `.` — i.e. the third-or-later dot of a run — while leaving `.!` / `.?` / first two dots of `...` untouched.

- [ ] **Step 1.7: Update `findSafeCutPoint` in `streamingSentencer.ts` to skip `.` after `.`**

Locate the `SENTENCE_END.test(ch)` branch (currently starting at line 92). Right after that `if` opens, insert as the first statement inside the branch:

```ts
      if (ch === '.' && text[i - 1] === '.') continue
```

The final snippet of the branch should read:
```ts
    if (i >= start && SENTENCE_END.test(ch)) {
      if (ch === '.' && text[i - 1] === '.') continue
      const allBalanced = ...
      // ...rest unchanged
    }
```

- [ ] **Step 1.8: Re-run the three test files and confirm they pass**

```bash
pnpm exec vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts src/features/voice/__tests__/audioParser.test.ts src/features/voice/pipeline/__tests__/streamingSentencer.test.ts
```

Expected: all tests pass.

- [ ] **Step 1.9: Run the full frontend suite to catch regressions**

```bash
pnpm exec vitest run
```

Expected: all tests pass. If any pre-existing test relying on collapsed ellipses fails, update its expectation to the new contract (preserved `...`) — this is the intended behaviour change.

- [ ] **Step 1.10: Commit**

```bash
git add frontend/src/features/voice
git commit -m "Preserve ellipses in TTS preprocessing"
```

---

## Task 2: Strip residual markdown and quote decoration

**Files:**
- Modify: `frontend/src/features/voice/__tests__/audioParser.test.ts` (add tests, update narrate test at lines 47–55)
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts` (threaded `mode` into `preprocess`, new replace rules)

- [ ] **Step 2.1: Update the narrate-mode test at `audioParser.test.ts:47-55` to expect stripped asterisks**

Replace lines 47–55 with:
```ts
  describe("mode 'narrate' (narration narrated, only dialogue spoken)", () => {
    it('strips decorative asterisks in narration and sentence-splits inside quotes', () => {
      const result = parseForSpeech('*walks over* "Hello there! How are you?" *waves*', 'narrate')
      expect(result).toEqual([
        { type: 'narration', text: 'walks over' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'voice', text: 'How are you?' },
        { type: 'narration', text: 'waves' },
      ])
    })
```

(The next `it('sentence-splits narration between quotes', ...)` block stays unchanged.)

- [ ] **Step 2.2: Add markdown-strip and quote-strip tests to `audioParser.test.ts`**

Append a new describe block at the top level of the outer `describe('parseForSpeech', ...)`, before its closing `})`:

```ts
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
```

- [ ] **Step 2.3: Run the affected test file and confirm the new tests fail**

```bash
pnpm exec vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: the new `markdown and quote decoration stripping` tests fail, and the updated narrate test fails. All other tests pass.

- [ ] **Step 2.4: Update `preprocess` in `audioParser.ts` to accept `mode` and add strip rules**

Change the `preprocess` signature and body:
```ts
function preprocess(text: string): string {
  let s = text
  s = s.replace(/```[\s\S]*?```/g, '')           // fenced code blocks
  s = s.replace(/`[^`]+`/g, '')                   // inline code
  s = s.replace(/\(\([\s\S]*?\)\)/g, '')          // OOC markers
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')   // markdown links
  s = s.replace(/https?:\/\/\S+/g, '')            // standalone URLs
  s = s.replace(/^#{1,6}\s+/gm, '')               // headings
  s = s.replace(/\*\*(.+?)\*\*/g, '$1')           // bold
  s = s.replace(/__(.+?)__/g, '$1')               // underline bold
  s = s.replace(/^[-*+]\s+/gm, '')                // unordered list markers
  s = s.replace(/^\d+\.\s+/gm, '')                // ordered list markers
  s = s.replace(/^>\s?/gm, '')                    // blockquotes
  s = s.replace(/\u2026/g, '...')                 // normalise Unicode ellipsis to three dots
  s = s.replace(/\n{2,}/g, '\n')                  // collapse blank lines
  return s.trim()
}
```

to:
```ts
function preprocess(text: string, mode: NarratorMode): string {
  let s = text
  s = s.replace(/```[\s\S]*?```/g, '')           // fenced code blocks
  s = s.replace(/`[^`]+`/g, '')                   // inline code
  s = s.replace(/\(\([\s\S]*?\)\)/g, '')          // OOC markers
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')   // markdown links
  s = s.replace(/https?:\/\/\S+/g, '')            // standalone URLs
  s = s.replace(/^#{1,6}\s+/gm, '')               // headings
  s = s.replace(/\*\*(.+?)\*\*/g, '$1')           // bold
  s = s.replace(/__(.+?)__/g, '$1')               // underline bold
  s = s.replace(/\*([^*\n]+)\*/g, '$1')           // single asterisk italics
  s = s.replace(/_([^_\n]+)_/g, '$1')             // single underscore italics
  if (mode === 'off') {
    s = s.replace(/"([^"\n]+)"/g, '$1')                       // straight double quotes
    s = s.replace(/\u201c([^\u201d\n]+)\u201d/g, '$1')        // curly double quotes
  }
  s = s.replace(/^[-*+]\s+/gm, '')                // unordered list markers
  s = s.replace(/^\d+\.\s+/gm, '')                // ordered list markers
  s = s.replace(/^>\s?/gm, '')                    // blockquotes
  s = s.replace(/\u2026/g, '...')                 // normalise Unicode ellipsis to three dots
  s = s.replace(/\n{2,}/g, '\n')                  // collapse blank lines
  return s.trim()
}
```

Update the sole call site in `parseForSpeech`:
```ts
export function parseForSpeech(text: string, mode: NarratorMode): SpeechSegment[] {
  const cleaned = preprocess(text, mode)
  // ...rest unchanged
}
```

- [ ] **Step 2.5: Re-run the test file and confirm everything passes**

```bash
pnpm exec vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: all tests pass.

- [ ] **Step 2.6: Run the full frontend suite**

```bash
pnpm exec vitest run
```

Expected: all tests pass.

- [ ] **Step 2.7: Commit**

```bash
git add frontend/src/features/voice
git commit -m "Strip single markdown italics and off-mode quotes from TTS text"
```

---

## Task 3: Strip emojis

**Files:**
- Modify: `frontend/src/features/voice/__tests__/audioParser.test.ts` (new describe block)
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts` (emoji strip in `preprocess`)

- [ ] **Step 3.1: Add emoji-strip tests to `audioParser.test.ts`**

Append a new describe block inside `describe('parseForSpeech', ...)` before its closing `})`:

```ts
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
  })
```

- [ ] **Step 3.2: Run the test file and confirm the new tests fail**

```bash
pnpm exec vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: the new `emoji stripping` tests fail. Existing tests still pass.

- [ ] **Step 3.3: Add emoji-strip rules to `preprocess` in `audioParser.ts`**

Inside the `preprocess` function, immediately before the `s = s.replace(/\n{2,}/g, '\n')` line, add:

```ts
  s = s.replace(/\p{Extended_Pictographic}/gu, '')          // emojis / pictographs
  s = s.replace(/\p{Regional_Indicator}/gu, '')             // flag-emoji regional indicators
  s = s.replace(/[\uFE0F\u200D]/g, '')                      // orphaned variation selectors / ZWJ
```

- [ ] **Step 3.4: Re-run the test file and confirm the new tests pass**

```bash
pnpm exec vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: all tests pass.

- [ ] **Step 3.5: Run the full frontend suite**

```bash
pnpm exec vitest run
```

Expected: all tests pass, including the existing emoji-boundary tests in `streamingSentencer.test.ts`. Those tests remain valid because the streaming sentencer still detects emojis in the raw buffer for cut-point purposes; the final `parseForSpeech` call on the committed chunk strips them before returning.

- [ ] **Step 3.6: Commit**

```bash
git add frontend/src/features/voice
git commit -m "Strip emojis from TTS text"
```

---

## Task 4: Build verification and merge

- [ ] **Step 4.1: Run a typecheck build**

From `frontend/`:
```bash
pnpm run build
```

Expected: a clean build with no TypeScript errors. If `preprocess`'s new `mode` argument is missing from an unlisted call site, fix it.

- [ ] **Step 4.2: Run the full frontend test suite one more time**

```bash
pnpm exec vitest run
```

Expected: all tests pass.

- [ ] **Step 4.3: Merge to master per project convention**

Per CLAUDE.md "Please always merge to master after implementation". Verify branch state with `git status`, then perform the project's standard merge workflow (fast-forward merge into `master`).

---

## Self-review notes (already applied inline)

- Spec coverage: Task 1 covers ellipse preservation (spec Change 1). Task 2 covers markdown / quote stripping (spec Change 2). Task 3 covers emoji stripping (spec Change 3). Task 4 covers build verification and merge.
- Placeholder scan: no TBDs, no "similar to above" references; every code snippet is complete.
- Type consistency: `preprocess(text, mode)` signature is used consistently across Task 2 changes and the updated `parseForSpeech` call site. `NarratorMode` is already imported at the top of `audioParser.ts`.
- Test-update callouts: the existing ellipsis tests in `sentenceSplitter.test.ts` and `audioParser.test.ts`, and the narrate-mode test in `audioParser.test.ts:47-55`, are rewritten rather than appended because the new contract contradicts the old assertions.
