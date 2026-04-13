import type { SpeechSegment } from '../types'

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
  s = s.replace(/\n{2,}/g, '\n')                  // collapse multiple blank lines left by removed blocks
  return s.trim()
}

function parseRoleplay(text: string): SpeechSegment[] {
  const segments: SpeechSegment[] = []
  const pattern = /"([^"]+)"|\u201c([^\u201d]+)\u201d|\*([^*]+)\*/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      const unmarked = text.slice(lastIndex, match.index).trim()
      if (unmarked) segments.push({ type: 'narration', text: unmarked })
    }
    if (match[1] !== undefined) segments.push({ type: 'voice', text: match[1] })
    else if (match[2] !== undefined) segments.push({ type: 'voice', text: match[2] })
    else if (match[3] !== undefined) segments.push({ type: 'narration', text: match[3] })
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex).trim()
    if (trailing) segments.push({ type: 'narration', text: trailing })
  }
  return segments
}

export function parseForSpeech(text: string, roleplay: boolean): SpeechSegment[] {
  const cleaned = preprocess(text)
  if (!cleaned) return []
  if (!roleplay) return [{ type: 'voice', text: cleaned }]
  return parseRoleplay(cleaned)
}
