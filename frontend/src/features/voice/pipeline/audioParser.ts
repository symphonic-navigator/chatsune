import type { NarratorMode, SpeechSegment } from '../types'
import { splitSentences } from './sentenceSplitter'
import { INLINE_TAG_PATTERN, WRAPPING_OPEN_PATTERN, WRAPPING_CLOSE_PATTERN } from '../expressionTags'
import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'

function preprocess(text: string, mode: NarratorMode, supportsExpressiveMarkup: boolean): string {
  let s = text
  if (!supportsExpressiveMarkup) {
    s = s.replace(new RegExp(INLINE_TAG_PATTERN.source, 'g'), '')
    s = s.replace(new RegExp(WRAPPING_OPEN_PATTERN.source, 'g'), '')
    s = s.replace(new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g'), '')
  }
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
  s = s.replace(/[\p{Emoji_Presentation}\p{Emoji_Modifier}]/gu, '')             // default-presentation emojis + skin-tone modifiers
  s = s.replace(/\p{Regional_Indicator}/gu, '')             // flag-emoji regional indicators
  s = s.replace(/[\uFE0F\u200D]/g, '')                      // orphan variation selectors / ZWJ
  s = s.replace(/\n{2,}/g, '\n')                  // collapse blank lines
  return s.trim()
}

// Split text into voice (quoted) and narration (everything else). Asterisk
// and underscore italics are stripped upstream in `preprocess`, so this stage
// only needs to recognise quote-delimited voice spans.
// When supportsExpressiveMarkup is true, wrap markers (e.g. <whisper>…</whisper>)
// that straddle a quote boundary are re-applied to each sub-segment so that
// scope is preserved correctly across narration↔voice transitions.
function splitSegments(
  text: string,
  supportsExpressiveMarkup: boolean = false,
): Array<{ type: 'voice' | 'narration'; text: string }> {
  const segments: Array<{ type: 'voice' | 'narration'; text: string }> = []
  const pattern = /"([^"]+)"|\u201c([^\u201d]+)\u201d/g
  let lastIndex = 0
  let wrapStack: string[] = []
  for (const match of text.matchAll(pattern)) {
    const idx = match.index as number
    if (idx > lastIndex) {
      const unmarked = text.slice(lastIndex, idx).trim()
      if (unmarked) {
        pushSegment(segments, 'narration', unmarked, wrapStack, supportsExpressiveMarkup)
        wrapStack = scanSegment(unmarked, wrapStack)
      }
    }
    const voiceText = match[1] ?? match[2] ?? ''
    if (voiceText) {
      pushSegment(segments, 'voice', voiceText, wrapStack, supportsExpressiveMarkup)
      wrapStack = scanSegment(voiceText, wrapStack)
    }
    lastIndex = idx + match[0].length
  }
  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex).trim()
    if (trailing) {
      pushSegment(segments, 'narration', trailing, wrapStack, supportsExpressiveMarkup)
    }
  }
  return segments
}

function pushSegment(
  out: Array<{ type: 'voice' | 'narration'; text: string }>,
  type: 'voice' | 'narration',
  rawText: string,
  enteringStack: readonly string[],
  supportsExpressiveMarkup: boolean,
): void {
  if (!supportsExpressiveMarkup) {
    out.push({ type, text: rawText })
    return
  }
  const leaving = scanSegment(rawText, enteringStack)
  // Keep the raw text (including any interior markers from the LLM) and let
  // wrapSegmentWithActiveStack add opens/closes at the edges only. Stripping
  // and re-emitting would discard interior close tags on the last sub-segment.
  const wrapped = wrapSegmentWithActiveStack(rawText, enteringStack, leaving)
  out.push({ type, text: wrapped })
}

// Expand a coarse segment into one-per-sentence segments of the same type.
function expandToSentences(segment: { type: 'voice' | 'narration'; text: string }): SpeechSegment[] {
  const sentences = splitSentences(segment.text)
  return sentences.map((text) => ({ type: segment.type, text }))
}

// A segment has speakable content iff it contains at least one Unicode letter
// or digit. Punctuation- or emoji-only segments (e.g. the "😄" produced when
// a sentence boundary cuts before a decorative emoji) are rejected by TTS
// providers after their own sanitisation, so filtering them at the source
// avoids needless 400s and keeps the synth chain healthy.
function hasSpeakableContent(text: string): boolean {
  return /[\p{L}\p{N}]/u.test(text)
}

export function parseForSpeech(
  text: string,
  mode: NarratorMode,
  supportsExpressiveMarkup: boolean = false,
): SpeechSegment[] {
  const cleaned = preprocess(text, mode, supportsExpressiveMarkup)
  if (!cleaned) return []
  if (mode === 'off') {
    return splitSentences(cleaned)
      .filter(hasSpeakableContent)
      .map((s) => ({ type: 'voice' as const, text: s }))
  }
  const coarse = splitSegments(cleaned, supportsExpressiveMarkup)
  const result: SpeechSegment[] = []
  for (const seg of coarse) {
    for (const expanded of expandToSentences(seg)) {
      if (hasSpeakableContent(expanded.text)) result.push(expanded)
    }
  }
  return result
}
