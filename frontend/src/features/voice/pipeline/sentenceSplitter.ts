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
