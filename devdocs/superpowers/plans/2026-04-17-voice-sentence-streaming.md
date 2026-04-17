# Voice Sentence Streaming & Configurable Playback Gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split each speech segment into individual sentences, give the audio queue a `closeStream()` signal so `onFinished` waits for late-arriving chunks, and insert a user-configurable gap between chunks stored on the TTS integration config.

**Architecture:**
- Pure-function sentence splitter fed by the existing parser.
- A new `config_field` on the `mistral_voice` integration (not a persona field) with preset gap values served as a `select`.
- Small refactor of `audioPlayback` to carry a `streamClosed` flag and an inter-chunk delay.
- `ReadAloudButton` reads the gap from the user-scoped integration config and calls `closeStream()` after the last `enqueue`.

**Tech Stack:** React 19 + Vite + TypeScript + vitest (frontend); Python 3.12 + FastAPI + Pydantic v2 + pytest (backend).

Spec: `devdocs/superpowers/specs/2026-04-17-voice-sentence-streaming-design.md`.

---

## File Structure

**Created:**
- `frontend/src/features/voice/pipeline/sentenceSplitter.ts` — pure helper, one responsibility: split a string into sentences using the three-stage heuristic.
- `frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts` — unit tests.
- `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts` — unit tests for the new `closeStream` semantics and gap timer.

**Modified:**
- `frontend/src/features/voice/pipeline/audioParser.ts` — apply `splitSentences` to every emitted segment text; move ellipsis normalisation up into `preprocess`.
- `frontend/src/features/voice/__tests__/audioParser.test.ts` — cases reflect sentence-level output.
- `frontend/src/features/voice/infrastructure/audioPlayback.ts` — add `streamClosed` flag, `closeStream()` method, `gapMs` callback option, pending-gap timer handling in `stopAll`.
- `frontend/src/features/voice/components/ReadAloudButton.tsx` — resolve `gapMs` from the active TTS user-config, thread it through `setCallbacks`, call `closeStream()` after enqueues.
- `backend/modules/integrations/_registry.py` — add `playback_gap_ms` to the `mistral_voice` `config_fields`.
- `tests/modules/integrations/test_registry_capabilities.py` — assert the new field shape.

---

## Task 1: Sentence splitter module

**Files:**
- Create: `/home/chris/workspace/chatsune/frontend/src/features/voice/pipeline/sentenceSplitter.ts`
- Create: `/home/chris/workspace/chatsune/frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `/home/chris/workspace/chatsune/frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`:

```ts
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

  it('normalises doubled-up full stops to a single period (no split inside)', () => {
    expect(splitSentences('Ich dachte... vielleicht sollte ich...')).toEqual([
      'Ich dachte. vielleicht sollte ich.',
    ])
  })

  it('normalises typographic Unicode ellipsis', () => {
    expect(splitSentences('Ich dachte\u2026 vielleicht\u2026')).toEqual([
      'Ich dachte. vielleicht.',
    ])
  })

  it('splits after an ellipsis that is followed by an uppercase word', () => {
    expect(splitSentences('Ich weiss nicht... Aber egal.')).toEqual([
      'Ich weiss nicht.',
      'Aber egal.',
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
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the splitter**

Create `/home/chris/workspace/chatsune/frontend/src/features/voice/pipeline/sentenceSplitter.ts`:

```ts
// Normalise typed and typographic ellipses to a single period. Applied first
// so subsequent sentence-boundary logic sees a canonical form.
function normaliseEllipses(text: string): string {
  return text.replace(/\.{2,}/g, '.').replace(/\u2026/g, '.')
}

// Split one line at sentence-ending punctuation followed by whitespace and an
// uppercase letter. The lookbehind/lookahead matches only the whitespace gap,
// so the terminal punctuation stays attached to the preceding sentence.
const SENTENCE_BOUNDARY = /(?<=[.!?])\s+(?=[A-Z\u00C4\u00D6\u00DC])/

function splitLine(line: string): string[] {
  const parts = line.split(SENTENCE_BOUNDARY)
  const out: string[] = []
  for (const p of parts) {
    const trimmed = p.trim()
    if (trimmed) out.push(trimmed)
  }
  return out
}

export function splitSentences(text: string): string[] {
  const normalised = normaliseEllipses(text)
  const lines = normalised.split('\n')
  const out: string[] = []
  for (const line of lines) {
    for (const sentence of splitLine(line)) {
      out.push(sentence)
    }
  }
  return out
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/pipeline/sentenceSplitter.ts frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts && git commit -m "Add sentenceSplitter with line-break and sentence-boundary heuristic"
```

---

## Task 2: Parser integration

**Files:**
- Modify: `/home/chris/workspace/chatsune/frontend/src/features/voice/pipeline/audioParser.ts`
- Modify: `/home/chris/workspace/chatsune/frontend/src/features/voice/__tests__/audioParser.test.ts`

- [ ] **Step 1: Update the parser tests to expect sentence-level output**

Replace the contents of `/home/chris/workspace/chatsune/frontend/src/features/voice/__tests__/audioParser.test.ts` with:

```ts
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
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/__tests__/audioParser.test.ts`
Expected: many failures, because current parser returns one segment per quoted/narration chunk (no sentence split) and does not normalise ellipses.

- [ ] **Step 3: Update the parser**

Replace the contents of `/home/chris/workspace/chatsune/frontend/src/features/voice/pipeline/audioParser.ts` with:

```ts
import type { NarratorMode, SpeechSegment } from '../types'
import { splitSentences } from './sentenceSplitter'

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
  s = s.replace(/\.{2,}/g, '.')                   // collapse '..', '...', '....'
  s = s.replace(/\u2026/g, '.')                   // collapse Unicode ellipsis
  s = s.replace(/\n{2,}/g, '\n')                  // collapse blank lines
  return s.trim()
}

// Pattern for the 'play' and 'narrate' mode splits. In 'play' mode: "..." and
// smart-quote variants become voice, *...* becomes narration, else narration.
// In 'narrate' mode: "..." / smart-quote variants become voice, everything
// else (including *...*) stays as narration verbatim.
function splitSegments(text: string, mode: 'play' | 'narrate'): Array<{ type: 'voice' | 'narration'; text: string }> {
  const segments: Array<{ type: 'voice' | 'narration'; text: string }> = []
  const pattern = mode === 'play'
    ? /"([^"]+)"|\u201c([^\u201d]+)\u201d|\*([^*]+)\*/g
    : /"([^"]+)"|\u201c([^\u201d]+)\u201d/g
  let lastIndex = 0
  for (const match of text.matchAll(pattern)) {
    const idx = match.index as number
    if (idx > lastIndex) {
      const unmarked = text.slice(lastIndex, idx).trim()
      if (unmarked) segments.push({ type: 'narration', text: unmarked })
    }
    if (match[1] !== undefined) segments.push({ type: 'voice', text: match[1] })
    else if (match[2] !== undefined) segments.push({ type: 'voice', text: match[2] })
    else if (match[3] !== undefined) segments.push({ type: 'narration', text: match[3] })
    lastIndex = idx + match[0].length
  }
  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex).trim()
    if (trailing) segments.push({ type: 'narration', text: trailing })
  }
  return segments
}

// Expand a coarse segment into one-per-sentence segments of the same type.
function expandToSentences(segment: { type: 'voice' | 'narration'; text: string }): SpeechSegment[] {
  const sentences = splitSentences(segment.text)
  return sentences.map((text) => ({ type: segment.type, text }))
}

export function parseForSpeech(text: string, mode: NarratorMode): SpeechSegment[] {
  const cleaned = preprocess(text)
  if (!cleaned) return []
  if (mode === 'off') {
    return splitSentences(cleaned).map((s) => ({ type: 'voice' as const, text: s }))
  }
  const coarse = splitSegments(cleaned, mode)
  const result: SpeechSegment[] = []
  for (const seg of coarse) {
    for (const expanded of expandToSentences(seg)) {
      result.push(expanded)
    }
  }
  return result
}
```

- [ ] **Step 4: Run parser tests — expect pass**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/__tests__/audioParser.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Run the splitter tests again to confirm no regression**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`
Expected: PASS.

- [ ] **Step 6: Typecheck**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b --noEmit`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/pipeline/audioParser.ts frontend/src/features/voice/__tests__/audioParser.test.ts && git commit -m "Parser: emit one segment per sentence; normalise ellipses in preprocess"
```

---

## Task 3: Backend — `playback_gap_ms` config field on `mistral_voice`

**Files:**
- Modify: `/home/chris/workspace/chatsune/backend/modules/integrations/_registry.py`
- Modify: `/home/chris/workspace/chatsune/tests/modules/integrations/test_registry_capabilities.py`

- [ ] **Step 1: Extend the test**

Append to `/home/chris/workspace/chatsune/tests/modules/integrations/test_registry_capabilities.py`:

```python
def test_mistral_voice_has_playback_gap_field():
    defn = get("mistral_voice")
    field = next(f for f in defn.config_fields if f["key"] == "playback_gap_ms")
    assert field["field_type"] == "select"
    assert field["required"] is False
    expected_values = {"0", "50", "100", "200", "300", "500"}
    actual_values = {o["value"] for o in field["options"]}
    assert actual_values == expected_values
```

- [ ] **Step 2: Run test — expect failure**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/modules/integrations/test_registry_capabilities.py::test_mistral_voice_has_playback_gap_field -v`
Expected: FAIL — `StopIteration`.

- [ ] **Step 3: Extend the registry entry**

In `/home/chris/workspace/chatsune/backend/modules/integrations/_registry.py`, find the `config_fields` block for the `mistral_voice` integration (the list containing the `api_key` entry). Append the new field so the full list becomes:

```python
        config_fields=[
            {
                "key": "api_key",
                "label": "Mistral API Key",
                "field_type": "password",
                "secret": True,
                "required": True,
                "description": "Your personal Mistral AI API key. Encrypted at rest, delivered in memory to your browser.",
            },
            {
                "key": "playback_gap_ms",
                "label": "Pause between chunks",
                "field_type": "select",
                "required": False,
                "description": "Gap inserted between sentences and speaker switches. Mistral TTS produces crisp boundaries — a small pause sounds more natural.",
                "options": [
                    {"value": "0", "label": "0 ms"},
                    {"value": "50", "label": "50 ms"},
                    {"value": "100", "label": "100 ms (default)"},
                    {"value": "200", "label": "200 ms"},
                    {"value": "300", "label": "300 ms"},
                    {"value": "500", "label": "500 ms"},
                ],
            },
        ],
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/modules/integrations/test_registry_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune && git add backend/modules/integrations/_registry.py tests/modules/integrations/test_registry_capabilities.py && git commit -m "Add playback_gap_ms config_field to mistral_voice integration"
```

---

## Task 4: `audioPlayback` — `streamClosed` flag and gap timer

**Files:**
- Create: `/home/chris/workspace/chatsune/frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`
- Modify: `/home/chris/workspace/chatsune/frontend/src/features/voice/infrastructure/audioPlayback.ts`

Note: this task mocks `AudioContext` in the test environment because jsdom/happy-dom do not implement Web Audio. The tests exercise queue semantics and timer behaviour rather than actual audio.

- [ ] **Step 1: Write the failing tests**

Create `/home/chris/workspace/chatsune/frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SpeechSegment } from '../../types'

// We import the module under test lazily so mocks are set up first.
let audioPlayback: typeof import('../audioPlayback').audioPlayback

// Minimal AudioContext stub: createBuffer/createBufferSource return objects
// whose onended callback can be triggered manually to simulate playback end.
class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  start = vi.fn()
  stop = vi.fn()
  connect = vi.fn()
}

let sources: FakeSource[] = []

class FakeAudioContext {
  state = 'running'
  destination = {}
  createBuffer() { return { getChannelData: () => ({ set: vi.fn() }) } }
  createBufferSource() {
    const s = new FakeSource()
    sources.push(s)
    return s
  }
  resume() { this.state = 'running'; return Promise.resolve() }
  close() { this.state = 'closed'; return Promise.resolve() }
}

const SEGMENT: SpeechSegment = { type: 'voice', text: 'x' }

beforeEach(async () => {
  vi.useFakeTimers()
  sources = []
  // @ts-expect-error — injecting global stub for test
  globalThis.AudioContext = FakeAudioContext
  const mod = await import('../audioPlayback')
  audioPlayback = mod.audioPlayback
  audioPlayback.dispose() // reset state between tests
})

afterEach(() => {
  vi.useRealTimers()
})

function finishPlayback(index = 0): void {
  const s = sources[index]
  if (s && s.onended) s.onended()
}

describe('audioPlayback — streamClosed semantics', () => {
  it('does not fire onFinished when the queue drains while streamClosed is false', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    const audio = new Float32Array(10)
    audioPlayback.enqueue(audio, SEGMENT)
    finishPlayback(0) // first segment ends, queue now empty
    expect(onFinished).not.toHaveBeenCalled()
  })

  it('fires onFinished when closeStream is called after the queue drains', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(0)
    audioPlayback.closeStream()
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('fires onFinished when closeStream is called before the last segment ends', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.closeStream()
    expect(onFinished).not.toHaveBeenCalled()
    finishPlayback(0)
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('stopAll resets streamClosed so a new session can start', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.closeStream()
    finishPlayback(0)
    expect(onFinished).toHaveBeenCalledTimes(1)

    // New session: closeStream from a prior run should not persist
    audioPlayback.stopAll()
    const onFinished2 = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: onFinished2 })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(1)
    expect(onFinished2).not.toHaveBeenCalled()
  })
})

describe('audioPlayback — gap timer', () => {
  it('waits gapMs before starting the next segment', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 200, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // first segment playing
    finishPlayback(0)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // still waiting
    vi.advanceTimersByTime(199)
    expect(onSegmentStart).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1)
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
  })

  it('calls the next segment immediately when gapMs is 0', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 0, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(0)
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
  })

  it('stopAll cancels a pending gap timer', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 500, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(0)
    audioPlayback.stopAll()
    vi.advanceTimersByTime(1000)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // second segment never started
  })
})
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`
Expected: FAIL — `closeStream` does not exist, `gapMs` option is unknown, existing `onFinished` fires too eagerly.

- [ ] **Step 3: Update `audioPlayback`**

Replace the contents of `/home/chris/workspace/chatsune/frontend/src/features/voice/infrastructure/audioPlayback.ts` with:

```ts
import type { SpeechSegment } from '../types'

interface QueueEntry { audio: Float32Array; segment: SpeechSegment }

export interface AudioPlaybackCallbacks {
  gapMs?: number
  onSegmentStart: (segment: SpeechSegment) => void
  onFinished: () => void
}

class AudioPlaybackImpl {
  private queue: QueueEntry[] = []
  private ctx: AudioContext | null = null
  private currentSource: AudioBufferSourceNode | null = null
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false
  private streamClosed = false
  private pendingGapTimer: ReturnType<typeof setTimeout> | null = null

  setCallbacks(callbacks: AudioPlaybackCallbacks): void { this.callbacks = callbacks }

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null) this.playNext()
  }

  closeStream(): void {
    this.streamClosed = true
    if (!this.playing && this.queue.length === 0 && this.pendingGapTimer === null) {
      this.callbacks?.onFinished()
    }
  }

  stopAll(): void {
    this.queue = []
    this.streamClosed = false
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource) {
      this.currentSource.onended = null // prevent stale onended → playNext → onFinished
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.playing = false
  }

  skipCurrent(): void {
    if (this.currentSource) {
      // Keep onended intact — it schedules the next segment.
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
  }

  private scheduleNext(): void {
    const gap = this.callbacks?.gapMs ?? 0
    if (gap > 0) {
      this.pendingGapTimer = setTimeout(() => {
        this.pendingGapTimer = null
        this.playNext()
      }, gap)
    } else {
      this.playNext()
    }
  }

  private async playNext(): Promise<void> {
    const entry = this.queue.shift()
    if (!entry) {
      this.playing = false
      if (this.streamClosed) this.callbacks?.onFinished()
      return
    }

    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)

    try {
      if (!this.ctx || this.ctx.state === 'closed') {
        this.ctx = new AudioContext({ sampleRate: 24_000 })
      }
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume()
      }

      const buffer = this.ctx.createBuffer(1, entry.audio.length, 24_000)
      buffer.getChannelData(0).set(entry.audio)

      const source = this.ctx.createBufferSource()
      source.buffer = buffer
      source.connect(this.ctx.destination)
      this.currentSource = source

      source.onended = () => {
        this.currentSource = null
        this.scheduleNext()
      }

      source.start()
    } catch (err) {
      console.error('[AudioPlayback] Failed to play segment:', err)
      this.currentSource = null
      this.scheduleNext()
    }
  }

  isPlaying(): boolean { return this.playing }

  dispose(): void {
    this.stopAll()
    if (this.ctx && this.ctx.state !== 'closed') {
      this.ctx.close()
    }
    this.ctx = null
    this.callbacks = null
  }
}

export const audioPlayback = new AudioPlaybackImpl()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b --noEmit`
Expected: clean in `audioPlayback.ts`; `ReadAloudButton.tsx` may have an error about `closeStream` not being called yet — that is addressed in Task 5.

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/infrastructure/audioPlayback.ts frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts && git commit -m "audioPlayback: add streamClosed flag and inter-chunk gap timer"
```

---

## Task 5: `ReadAloudButton` — gap lookup and stream closure

**Files:**
- Modify: `/home/chris/workspace/chatsune/frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Add the gap helper inside the file**

Open `/home/chris/workspace/chatsune/frontend/src/features/voice/components/ReadAloudButton.tsx`. Near the other module-level helpers (above `runReadAloud`), add:

```ts
function resolveGapMs(integrationCfg: Record<string, unknown> | undefined): number {
  const raw = integrationCfg?.playback_gap_ms
  if (typeof raw === 'string') {
    const n = Number.parseInt(raw, 10)
    if (Number.isFinite(n) && n >= 0) return n
  }
  if (typeof raw === 'number' && Number.isFinite(raw) && raw >= 0) return raw
  return 100
}
```

- [ ] **Step 2: Thread `gapMs` through `runReadAloud` and call `closeStream`**

Still in `ReadAloudButton.tsx`, replace the existing `runReadAloud` function with:

```ts
async function runReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
  gapMs: number,
): Promise<void> {
  const tts = ttsRegistry.active()
  if (!tts?.isReady()) { setActiveReader(null, 'idle'); return }

  const cacheKey = readAloudCacheKey(messageId, primary.id, narratorVoiceId, mode)

  audioPlayback.setCallbacks({
    gapMs,
    onSegmentStart: () => { if (activeMessageId === messageId) setActiveReader(messageId, 'playing') },
    onFinished: () => { if (activeMessageId === messageId) setActiveReader(null, 'idle') },
  })

  const cached = cacheGet(cacheKey)
  if (cached) {
    setActiveReader(messageId, 'playing')
    for (const { audio, segment } of cached.segments) {
      audioPlayback.enqueue(audio, segment)
    }
    audioPlayback.closeStream()
    return
  }

  const parsed = parseForSpeech(content, mode)
  if (parsed.length === 0) { setActiveReader(null, 'idle'); return }

  setActiveReader(messageId, 'synthesising')

  try {
    const results: CachedAudio['segments'] = []
    for (const segment of parsed) {
      if (activeMessageId !== messageId) return // cancelled
      const voice = segment.type === 'voice' ? primary : narrator
      const audio = await tts.synthesise(segment.text, voice)
      if (activeMessageId !== messageId) return
      results.push({ audio, segment })
      audioPlayback.enqueue(audio, segment)
    }
    cachePut(cacheKey, { segments: results })
    audioPlayback.closeStream()
  } catch (err) {
    if (activeMessageId !== messageId) return
    console.error('[ReadAloud] TTS synthesis failed:', err)
    setActiveReader(null, 'idle')
    const isAuthError = err instanceof Error && (err.message.includes('401') || err.message.includes('Unauthorized'))
    useNotificationStore.getState().addNotification({
      level: 'error',
      title: 'Read aloud failed',
      message: isAuthError
        ? "Couldn't read reply aloud — check your Mistral API key."
        : "Couldn't read reply aloud — check the console for details.",
    })
  }
}
```

- [ ] **Step 3: Update `triggerReadAloud` to accept and forward `gapMs`**

Replace the existing `triggerReadAloud` export with:

```ts
export async function triggerReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
  gapMs: number,
): Promise<void> {
  audioPlayback.stopAll()
  setActiveReader(messageId, 'synthesising')
  await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, mode, gapMs)
}
```

- [ ] **Step 4: Update the button's `handleClick` to resolve `gapMs` from the user's TTS integration config**

Locate the `handleClick` callback inside `ReadAloudButton`. Right after the `integrationCfg` / `narratorVoiceId` lookups, add the gap resolution:

```ts
  const integrationUserConfig = activeTTS ? configs?.[activeTTS.id]?.config : undefined
  const gapMs = resolveGapMs(integrationUserConfig)
```

Then change the final call inside `handleClick` to pass `gapMs`:

```ts
    await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, resolvedMode, gapMs)
```

Add `gapMs` to the `useCallback` dependency array:

```ts
  }, [messageId, content, dialogueVoice, narratorVoice, resolvedMode, isActive, state, voiceId, narratorVoiceId, gapMs])
```

- [ ] **Step 5: Update `ChatView.tsx` auto-read to pass `gapMs`**

In `/home/chris/workspace/chatsune/frontend/src/features/chat/ChatView.tsx`, inside the auto-read `useEffect` (the block that calls `triggerReadAloud`), resolve the gap just like the button does. Locate the current `triggerReadAloud` call — it looks like:

```tsx
      void triggerReadAloud(lastAssistant.id, lastAssistant.content, voice, narratorVoice, narratorVoiceId, narratorMode)
```

Add — directly above that line, inside the same block — the gap lookup:

```tsx
      const gapRaw = ttsDefn ? (intConfigs?.[ttsDefn.id]?.config?.playback_gap_ms) : undefined
      const gapMs = typeof gapRaw === 'string'
        ? (Number.parseInt(gapRaw, 10) >= 0 ? Number.parseInt(gapRaw, 10) : 100)
        : (typeof gapRaw === 'number' && gapRaw >= 0 ? gapRaw : 100)
```

Then update the call itself:

```tsx
      void triggerReadAloud(lastAssistant.id, lastAssistant.content, voice, narratorVoice, narratorVoiceId, narratorMode, gapMs)
```

- [ ] **Step 6: Update `PersonaVoiceConfig` preview callers to not break on the new option**

The preview path in `PersonaVoiceConfig.tsx` calls `audioPlayback.setCallbacks({ onSegmentStart, onFinished })` without `gapMs`. That's fine — `gapMs` is optional and defaults to 0 when omitted (one segment per preview anyway). Verify no code change is required here:

```bash
cd /home/chris/workspace/chatsune && grep -n "setCallbacks" frontend/src/features/voice/components/PersonaVoiceConfig.tsx
```

Expected: a single match with no `gapMs` key. No action needed.

- [ ] **Step 7: Typecheck**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b --noEmit`
Expected: clean.

- [ ] **Step 8: Build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: build passes (PWA precache warning unrelated to this feature is acceptable).

- [ ] **Step 9: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/components/ReadAloudButton.tsx frontend/src/features/chat/ChatView.tsx && git commit -m "Thread playback gap from integration config through read-aloud pipeline"
```

---

## Task 6: Full verification

**Files:** None (verification task).

- [ ] **Step 1: Backend tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/modules/integrations tests/modules/persona -v`
Expected: PASS.

- [ ] **Step 2: Frontend unit tests**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice`
Expected: PASS (parser, splitter, cache key, audioPlayback, all green).

- [ ] **Step 3: Typecheck + build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b --noEmit && pnpm run build`
Expected: PASS.

- [ ] **Step 4: Manual verification (user runs in dev env)**

Run through each scenario. If any fails, file the symptom and fix before merging.

- **Default gap (100 ms), long quoted block with multiple sentences:** time-to-first-audio is visibly shorter than before (first sentence starts playing while later ones synthesise). Between sentences there is a short, natural-feeling pause.
- **Default gap, roleplay mode with narrator voice switch:** the handoff between speakers now has a clean pause, no jarring cut.
- **Gap set to 0 ms in the integration config:** playback feels nearly identical to before this feature — still sentence-split under the hood, but no audible pauses.
- **Gap set to 500 ms:** deliberate, theatrical pacing; Stop button reacts immediately (pending gap timer is cancelled).
- **Markdown bullet list in auto-read:** each list item plays as its own chunk.
- **Ellipsis-heavy message (e.g. "Ich dachte... vielleicht... ja."):** plays fluidly as one sentence, no spurious splits.
- **Empty-looking message (only code fence or only `...`):** nothing plays, no errors, UI resets cleanly.
- **Stop mid-stream, during synthesis:** synthesis loop exits, queue drains, no lingering audio.
- **Stop mid-stream, during playback:** playback halts, no further chunks start.
- **Integration-config form shows the new select:** user can pick a gap and save; change is applied to the next read-aloud without a page reload.

- [ ] **Step 5: Final commit (if any touchup required)**

If Step 4 required a fix, commit with a descriptive message. Otherwise no commit is needed.

---

## Post-Implementation

- Merge the feature branch back into `master` (CLAUDE.md default).
- No follow-up spec planned — this closes the sentence-streaming loop that was deferred from the first voice polish round.
