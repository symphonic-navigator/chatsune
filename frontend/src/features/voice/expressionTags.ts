// Canonical xAI voice expression tag vocabulary.
//
// This file is one half of a two-file source of truth; the other half
// is `backend/modules/integrations/_voice_expression_tags.py`. Any
// change here must be mirrored there. See the "xAI Voice Expression
// Tags" note in CLAUDE.md.

export const INLINE_TAGS = [
  'pause', 'long-pause', 'hum-tune',
  'laugh', 'chuckle', 'giggle', 'cry',
  'tsk', 'tongue-click', 'lip-smack',
  'breath', 'inhale', 'exhale', 'sigh',
] as const

export const WRAPPING_TAGS = [
  'soft', 'whisper', 'loud', 'build-intensity', 'decrease-intensity',
  'higher-pitch', 'lower-pitch', 'slow', 'fast',
  'sing-song', 'singing', 'laugh-speak', 'emphasis',
] as const

export type InlineTag = (typeof INLINE_TAGS)[number]
export type WrappingTag = (typeof WRAPPING_TAGS)[number]

const WRAPPING_SET: ReadonlySet<string> = new Set(WRAPPING_TAGS)

export function isKnownWrappingTag(name: string): name is WrappingTag {
  return WRAPPING_SET.has(name)
}

// Regex sources are plain (no flags). Construct new RegExp at each call site
// that needs /g, /i etc., so stateful `lastIndex` cannot leak between uses.
const inlineAlternation = INLINE_TAGS.map(escapeForRegex).join('|')
const wrappingAlternation = WRAPPING_TAGS.map(escapeForRegex).join('|')

export const INLINE_TAG_PATTERN = new RegExp(`\\[(?:${inlineAlternation})\\]`)
export const WRAPPING_OPEN_PATTERN = new RegExp(`<(?:${wrappingAlternation})>`)
export const WRAPPING_CLOSE_PATTERN = new RegExp(`</(?:${wrappingAlternation})>`)
export const ANY_TAG_PATTERN = new RegExp(
  `${INLINE_TAG_PATTERN.source}|${WRAPPING_CLOSE_PATTERN.source}|${WRAPPING_OPEN_PATTERN.source}`,
)

function escapeForRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
