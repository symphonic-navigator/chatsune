/**
 * Normalise a raw STT result into a token array suitable for command matching.
 *
 * Pipeline:
 *   1. lowercase
 *   2. replace punctuation characters with spaces
 *   3. trim outer whitespace, split on whitespace, drop empty tokens
 *   4. greedily strip leading filler tokens (one at a time, until a non-filler is hit)
 *
 * Returns an empty array if normalisation leaves nothing — caller should
 * treat this as a no-match (no trigger possible).
 */

export const LEADING_FILLERS: ReadonlySet<string> = new Set([
  'uh',
  'um',
  'uhm',
  'hey',
  'ok',
  'okay',
  'äh',
  'ähm',
  'also',
  'naja',
])

const PUNCTUATION_PATTERN = /[.,;:!?…„"'']/gu

export function normalise(text: string): string[] {
  const lowered = text.toLowerCase()
  const stripped = lowered.replace(PUNCTUATION_PATTERN, ' ')
  const tokens = stripped.trim().split(/\s+/).filter(Boolean)
  let i = 0
  while (i < tokens.length && LEADING_FILLERS.has(tokens[i])) i += 1
  return tokens.slice(i)
}
