import type { NarratorMode, SpeechSegment } from '../types'
import { splitSentences } from './sentenceSplitter'

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

// A segment has speakable content iff it contains at least one Unicode letter
// or digit. Punctuation- or emoji-only segments (e.g. the "😄" produced when
// a sentence boundary cuts before a decorative emoji) are rejected by TTS
// providers after their own sanitisation, so filtering them at the source
// avoids needless 400s and keeps the synth chain healthy.
function hasSpeakableContent(text: string): boolean {
  return /[\p{L}\p{N}]/u.test(text)
}

export function parseForSpeech(text: string, mode: NarratorMode): SpeechSegment[] {
  const cleaned = preprocess(text, mode)
  if (!cleaned) return []
  if (mode === 'off') {
    return splitSentences(cleaned)
      .filter(hasSpeakableContent)
      .map((s) => ({ type: 'voice' as const, text: s }))
  }
  const coarse = splitSegments(cleaned, mode)
  const result: SpeechSegment[] = []
  for (const seg of coarse) {
    for (const expanded of expandToSentences(seg)) {
      if (hasSpeakableContent(expanded.text)) result.push(expanded)
    }
  }
  return result
}
