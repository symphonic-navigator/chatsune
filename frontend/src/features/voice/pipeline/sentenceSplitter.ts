import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'
import { effectiveLength } from './effectiveLength'

// Per-sentence length guard applied by the batch splitter after the raw
// split. The first sentence must clear 20 effective characters, every
// follow-up sentence 30. Sentences below threshold are merged with the
// next one (or, for the final sentence, with the previous one).
const FIRST_SENTENCE_MIN = 20
const FOLLOWUP_SENTENCE_MIN = 30

// Normalise the Unicode ellipsis (U+2026) to three ASCII dots so subsequent
// sentence-boundary logic sees a canonical form.
function normaliseEllipses(text: string): string {
  return text.replace(/…/g, '...')
}

// Split after sentence-ending punctuation in two shapes:
//   (a) whitespace followed by an uppercase letter or an emoji/pictograph
//   (b) an emoji/pictograph directly (no whitespace) — e.g. "Great!😀 Next"
// The match consumes only the whitespace gap in (a) and is zero-width in (b),
// so the terminal punctuation stays attached to the preceding sentence.
const SENTENCE_BOUNDARY = /(?<![.][.])(?<=[.!?])(?:\s+(?=[A-ZÄÖÜ]|\p{Extended_Pictographic})|(?=\p{Extended_Pictographic}))/u

function splitLine(line: string): string[] {
  const parts = line.split(SENTENCE_BOUNDARY)
  const out: string[] = []
  for (const p of parts) {
    const trimmed = p.trim()
    if (trimmed) out.push(trimmed)
  }
  return out
}

// Merge under-threshold sentences forwards (with the next) until they reach
// the minimum effective length. A final short sentence is merged backwards
// into its predecessor. Returns a new array; does not mutate `sentences`.
function applyLengthGuard(sentences: string[]): string[] {
  if (sentences.length === 0) return sentences
  const merged: string[] = []
  let pending: string | null = null
  for (let i = 0; i < sentences.length; i++) {
    const current: string = pending !== null ? `${pending} ${sentences[i]}` : sentences[i]
    const threshold = merged.length === 0 ? FIRST_SENTENCE_MIN : FOLLOWUP_SENTENCE_MIN
    if (effectiveLength(current) >= threshold) {
      merged.push(current)
      pending = null
    } else {
      pending = current
    }
  }
  if (pending !== null) {
    // Tail below threshold: merge backwards into the last accepted sentence,
    // or emit on its own if there is no predecessor.
    if (merged.length > 0) {
      merged[merged.length - 1] = `${merged[merged.length - 1]} ${pending}`
    } else {
      merged.push(pending)
    }
  }
  return merged
}

export function splitSentences(text: string): string[] {
  const normalised = normaliseEllipses(text)
  const lines = normalised.split('\n')
  const raw: string[] = []
  for (const line of lines) {
    for (const sentence of splitLine(line)) {
      raw.push(sentence)
    }
  }
  return applyLengthGuard(raw)
}

// Wrap-aware counterpart of `splitSentences`. Each emitted sentence carries
// the wrap scope that was active at its start, and closes any opens that
// remained open at its end. Interior markers inside a sentence are preserved
// verbatim; `wrapSegmentWithActiveStack` adds only boundary scope.
//
// The length guard is applied against the merged text (before scope wrap)
// so that the scope reconstruction operates on the final sentence shapes.
export function splitSentencesWithWrapScope(text: string): string[] {
  const bare = splitSentences(text)
  const out: string[] = []
  let entering: string[] = []
  for (const sentence of bare) {
    const leaving = scanSegment(sentence, entering)
    out.push(wrapSegmentWithActiveStack(sentence, entering, leaving))
    entering = leaving
  }
  return out
}
