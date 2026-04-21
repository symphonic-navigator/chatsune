import {
  INLINE_TAG_PATTERN,
  WRAPPING_OPEN_PATTERN,
  WRAPPING_CLOSE_PATTERN,
} from '../expressionTags'

// Return the trimmed length of `text` after removing all canonical wrapping
// and inline expression-tag markers. Tags carry no spoken content, so a
// "sentence" that is only tags (e.g. "[chuckle] [nod]") must not count as
// speakable when sizing chunks for the TTS splitter.
export function effectiveLength(text: string): number {
  const stripped = text
    .replace(new RegExp(INLINE_TAG_PATTERN.source, 'g'), '')
    .replace(new RegExp(WRAPPING_OPEN_PATTERN.source, 'g'), '')
    .replace(new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g'), '')
  return stripped.trim().length
}
