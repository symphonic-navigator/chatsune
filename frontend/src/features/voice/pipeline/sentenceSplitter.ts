import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'

// Normalise the Unicode ellipsis (U+2026) to three ASCII dots so subsequent
// sentence-boundary logic sees a canonical form.
function normaliseEllipses(text: string): string {
  return text.replace(/\u2026/g, '...')
}

// Split after sentence-ending punctuation in two shapes:
//   (a) whitespace followed by an uppercase letter or an emoji/pictograph
//   (b) an emoji/pictograph directly (no whitespace) — e.g. "Great!😀 Next"
// The match consumes only the whitespace gap in (a) and is zero-width in (b),
// so the terminal punctuation stays attached to the preceding sentence.
const SENTENCE_BOUNDARY = /(?<![.][.])(?<=[.!?])(?:\s+(?=[A-Z\u00C4\u00D6\u00DC]|\p{Extended_Pictographic})|(?=\p{Extended_Pictographic}))/u

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

// Wrap-aware counterpart of `splitSentences`. Each emitted sentence carries
// the wrap scope that was active at its start, and closes any opens that
// remained open at its end. Interior markers inside a sentence are preserved
// verbatim; `wrapSegmentWithActiveStack` adds only boundary scope.
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
